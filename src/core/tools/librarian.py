"""Librarian — persistent search cache with hybrid BM25 + vector scoring and recency decay."""

import asyncio
import logging
import re
import sqlite3
import struct
import time
from collections.abc import Callable, Coroutine
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import numpy as np
import sqlite_vec
from pydantic import BaseModel

from core.ai_client.interface import AiClient, EmbeddingClient
from core.debug import trace as _dtrace
from core.log import Category
from core.log import log as _log
from core.log import stat_inc

logger = logging.getLogger(__name__)

LIBRARIAN_CTX: ContextVar["LibrarianAgent | None"] = ContextVar("librarian", default=None)

_DB_PATH = Path(__file__).parents[3] / ".agent.db"
_TOP_K = 8
_SCORE_THRESHOLD = 0.55
_MAX_CHARS = 120_000
_SECS_PER_MONTH = 30 * 24 * 3600


def _pack(v: np.ndarray) -> bytes:
    return struct.pack(f"{len(v)}f", *v.tolist())


class _CheckResult(BaseModel):
    summary: str
    further_search_required: bool


class LibrarianAgent:
    _INSTRUCTIONS = (
        "You are a research librarian. Given pre-retrieved search results and a new query, "
        "determine whether the library already contains the information needed to answer the query.\n\n"
        "Each entry is labelled with how long ago it was retrieved (e.g. '0.3h old', '2 days old'). "
        "Use the age together with the nature of the query to judge whether the cached result is still fresh enough.\n\n"
        "Rules:\n"
        "- Set further_search_required=false if the query can be directly and completely answered from the library.\n"
        "- Set further_search_required=true if the library is missing the specific detail, coverage is only partial, "
        "or the cached result is too old given how time-sensitive the topic is.\n"
        "- Always return a summary of any relevant information found — even if further_search_required=true."
    )

    def __init__(
        self,
        embedding_client: EmbeddingClient,
        ai_client: AiClient,
        db_path: Path = _DB_PATH,
        dimensions: int = 768,
    ) -> None:
        self._embedder = embedding_client
        self._ai = ai_client
        self._dimensions = dimensions
        self._lock = asyncio.Lock()
        self.searches_made: int = 0
        self.searches_saved: int = 0
        self._db = self._init_db(db_path)

    def _init_db(self, path: Path) -> sqlite3.Connection:
        conn = sqlite3.connect(str(path), check_same_thread=False)
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.executescript(f"""
            CREATE TABLE IF NOT EXISTS lib_entries (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                query      TEXT    NOT NULL,
                result     TEXT    NOT NULL,
                created_at REAL    NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS lib_entries_fts USING fts5(
                query, result,
                content='lib_entries', content_rowid='id'
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS lib_vec_entries USING vec0(
                embedding float[{self._dimensions}]
            );
            CREATE TRIGGER IF NOT EXISTS lib_entries_ai AFTER INSERT ON lib_entries BEGIN
                INSERT INTO lib_entries_fts(rowid, query, result)
                VALUES (new.id, new.query, new.result);
            END;
        """)
        conn.commit()
        return conn

    async def route(
        self, query: str, raw_search: Callable[[str], Coroutine[Any, Any, str]]
    ) -> str:
        _dtrace("librarian.route", query=query)
        async with self._lock:
            q_vec = await self._embed(query)
            candidates = self._retrieve(query, q_vec)
            _dtrace("librarian.candidates", count=len(candidates), scores=[round(c["score"], 3) for c in candidates])

            check = None
            if candidates:
                check = await self._check(query, candidates)
                _dtrace("librarian.check", further_search=check.further_search_required, summary=check.summary[:120] if check.summary else None)
                if not check.further_search_required:
                    _log(Category.LIBRARIAN, "cache hit", query=query[:80], score=round(candidates[0]["score"], 3))
                    stat_inc("librarian.cache_hits")
                    self.searches_saved += 1
                    return check.summary

            _log(Category.LIBRARIAN, "cache miss", query=query[:80])
            stat_inc("librarian.cache_misses")
            self.searches_made += 1
            result = await raw_search(query)
            _dtrace("librarian.exa_result", chars=len(result), preview=result[:200])
            self._store(query, result, q_vec)

            if check and check.summary:
                return f"Fresh search:\n{result}\n\nOther relevant information:\n{check.summary}"
            return result

    def _retrieve(self, query: str, q_vec: np.ndarray) -> list[dict[str, Any]]:
        vec_rows = self._db.execute(
            """
            SELECT e.id, e.query, e.result, e.created_at, v.distance
            FROM lib_vec_entries v
            JOIN lib_entries e ON e.id = v.rowid
            WHERE v.embedding MATCH ? AND k = ?
            ORDER BY v.distance
            """,
            [_pack(q_vec), _TOP_K],
        ).fetchall()

        if not vec_rows:
            return []

        ids = [r[0] for r in vec_rows]
        # L2 distance on normalised vectors → cosine sim: 1 - d²/2
        cosine_scores = {r[0]: max(0.0, 1.0 - r[4] ** 2 / 2) for r in vec_rows}
        created_ats = {r[0]: r[3] for r in vec_rows}
        texts = {r[0]: {"query": r[1], "result": r[2]} for r in vec_rows}

        # BM25 from FTS5 (negate: bm25() returns negative scores).
        # Strip FTS5 special syntax (colons, operators) to avoid OperationalError.
        fts_query = re.sub(r"[^\w\s]", " ", query).strip() or "x"
        _dtrace("librarian.fts", raw=query, sanitized=fts_query)
        placeholders = ",".join("?" * len(ids))
        fts_rows = self._db.execute(
            f"""
            SELECT e.id, -bm25(lib_entries_fts) AS score
            FROM lib_entries_fts
            JOIN lib_entries e ON e.id = lib_entries_fts.rowid
            WHERE lib_entries_fts MATCH ? AND e.id IN ({placeholders})
            """,
            [fts_query, *ids],
        ).fetchall()
        bm25_raw = {r[0]: r[1] for r in fts_rows}
        max_bm25 = max(bm25_raw.values(), default=1.0) or 1.0
        bm25_scores = {k: v / max_bm25 for k, v in bm25_raw.items()}

        now = time.time()
        results = []
        for eid in ids:
            cosine = cosine_scores.get(eid, 0.0)
            bm25 = bm25_scores.get(eid, 0.0)
            hybrid = 0.7 * cosine + 0.3 * bm25

            age_secs = now - created_ats[eid]
            months_old = age_secs / _SECS_PER_MONTH
            decay = 0.5 ** (months_old / 3)

            score = hybrid * decay
            if score >= _SCORE_THRESHOLD:
                results.append({**texts[eid], "score": score, "age_hours": age_secs / 3600})

        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    async def _check(self, query: str, entries: list[dict[str, Any]]) -> _CheckResult:
        lines, total = [], 0
        for i, e in enumerate(entries):
            age_h = e.get("age_hours", 0.0)
            age_label = f"{age_h:.1f}h old" if age_h < 24 else f"{round(age_h / 24)} days old"
            chunk = f"[{i + 1}] (retrieved {age_label}) Query: {e['query']}\nResult: {e['result']}"
            if total + len(chunk) > _MAX_CHARS:
                break
            lines.append(chunk)
            total += len(chunk)

        prompt = f"Query: {query}\n\nRelevant library entries:\n" + "\n\n".join(lines)
        try:
            return await self._ai.complete(
                prompt,
                response_model=_CheckResult,
                thinking=None,
                instructions=self._INSTRUCTIONS,
            )
        except Exception as e:
            logger.warning("[librarian] check failed, falling back to search: %s", e)
            return _CheckResult(summary="", further_search_required=True)

    def _store(self, query: str, result: str, vec: np.ndarray) -> None:
        cur = self._db.execute(
            "INSERT INTO lib_entries (query, result, created_at) VALUES (?, ?, ?)",
            [query, result, time.time()],
        )
        self._db.execute(
            "INSERT INTO lib_vec_entries (rowid, embedding) VALUES (?, ?)",
            [cur.lastrowid, _pack(vec)],
        )
        self._db.commit()

    async def _embed(self, text: str) -> np.ndarray:
        vecs = await self._embedder.embed(text)
        v = np.array(vecs[0][: self._dimensions])
        return v / np.linalg.norm(v)
