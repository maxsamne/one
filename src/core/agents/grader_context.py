"""Deterministic changed-file context for grader and inspector prompts."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from core.tools.ctx import TOOL_LOG, WORKDIR

CHANGE_CONTEXT_MAX_BYTES = 120_000
TOUCHED_FILE_LIMIT = 8
TOUCHED_FILE_MAX_BYTES = 20_000


@dataclass
class ChangeContext:
    text: str
    source: str
    changed_files: list[str] = field(default_factory=list)
    truncated: bool = False
    omitted_files: int = 0


async def _git(*args: str, workdir: Path) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=str(workdir),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    return proc.returncode, out.decode(errors="replace")


def _truncate_bytes(text: str, limit: int) -> tuple[str, bool]:
    if len(text.encode("utf-8")) <= limit:
        return text, False
    truncated = text.encode("utf-8")[:limit].decode("utf-8", errors="ignore")
    return truncated + "\n... [truncated]", True


async def _git_changed_files(workdir: Path, base: str | None) -> list[str]:
    paths: list[str] = []
    specs: list[tuple[str, ...]] = []
    if base:
        specs.append(("--name-only", "--diff-filter=ACMR", f"{base}..HEAD"))
    specs.append(("--name-only", "--diff-filter=ACMR", "HEAD"))
    for spec in specs:
        rc, out = await _git("diff", *spec, workdir=workdir)
        if rc != 0:
            continue
        for line in out.splitlines():
            rel = line.strip()
            if rel and rel not in paths:
                paths.append(rel)
    return paths


def _touched_paths() -> list[str]:
    paths: list[str] = []
    for entry in TOOL_LOG.get([]):
        if entry.get("tool") not in {"write_file", "edit_file"}:
            continue
        path = entry.get("args", {}).get("path")
        if isinstance(path, str) and path not in paths:
            paths.append(path)
    return paths


async def changed_files_for_grader(workdir: Path | None = None) -> list[str]:
    from core.agents.task_ctx import GRADER_DIFF_BASE_CTX

    root = workdir or WORKDIR.get()
    files = await _git_changed_files(root, GRADER_DIFF_BASE_CTX.get())
    return files or _touched_paths()


async def changed_files_tool() -> str:
    files = await changed_files_for_grader()
    return json.dumps({"changed_files": files}, indent=2)


async def _git_diff_context(workdir: Path) -> ChangeContext | None:
    from core.agents.task_ctx import GRADER_DIFF_BASE_CTX

    diffs: list[str] = []
    base = GRADER_DIFF_BASE_CTX.get()
    if base:
        rc, diff = await _git("diff", "--find-renames", "--diff-filter=ACMR", f"{base}..HEAD", workdir=workdir)
        if rc == 0 and diff.strip():
            diffs.append(diff)

    rc, diff = await _git("diff", "--find-renames", "--diff-filter=ACMR", "HEAD", workdir=workdir)
    if rc == 0 and diff.strip():
        diffs.append(diff)
    if not diffs:
        return None

    body, truncated = _truncate_bytes("\n".join(diffs), CHANGE_CONTEXT_MAX_BYTES)
    return ChangeContext(
        text="```diff\n" + body + "\n```",
        source="git_diff",
        changed_files=await _git_changed_files(workdir, base),
        truncated=truncated,
    )


def _safe_touched_file(workdir: Path, rel: str) -> Path | None:
    candidate = workdir / rel
    try:
        root = workdir.resolve()
        resolved = candidate.resolve(strict=True)
    except (FileNotFoundError, OSError):
        return None
    if not (resolved == root or root in resolved.parents):
        return None
    return resolved if resolved.is_file() else None


def _touched_file_context(workdir: Path) -> ChangeContext | None:
    paths = _touched_paths()
    blocks: list[str] = []
    truncated_any = False
    for rel in paths[:TOUCHED_FILE_LIMIT]:
        path = _safe_touched_file(workdir, rel)
        if path is None:
            continue
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        body, truncated = _truncate_bytes(content, TOUCHED_FILE_MAX_BYTES)
        truncated_any = truncated_any or truncated
        blocks.append(f"### `{rel}`\n\n```\n{body}\n```")
    if not blocks:
        return None
    return ChangeContext(
        text="\n\n".join(blocks),
        source="touched_files",
        changed_files=paths,
        truncated=truncated_any or len(paths) > TOUCHED_FILE_LIMIT,
        omitted_files=max(0, len(paths) - TOUCHED_FILE_LIMIT),
    )


async def collect_change_context() -> ChangeContext | None:
    workdir = WORKDIR.get()
    if git_context := await _git_diff_context(workdir):
        return git_context
    return _touched_file_context(workdir)
