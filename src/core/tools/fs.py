"""Filesystem tools — view, create, str_replace, grep, list_dir, delete."""

import difflib
import fnmatch
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote


def _diff_stats(old: str, new: str) -> str:
    lines = list(difflib.unified_diff(old.splitlines(), new.splitlines(), n=0))
    added = sum(1 for l in lines if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in lines if l.startswith("-") and not l.startswith("---"))
    return f"+{added}/-{removed} lines"

from core.ai_client.models import Tool
from core.text import text_stats
from core.tools.ctx import READ_CTX, WORKDIR, log_call

_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
_MIN_TARGETED_READ_LINES = 30
_READ_MAX_OUTPUT_TOKENS = 8_000
PROTECTED_PATH_PARTS = frozenset({".git", ".worktrees", ".venv", "node_modules", "__pycache__"})
PROTECTED_PATH_FILES = frozenset({".agent.db", ".librarian.db"})


def _rel(path: str) -> Path:
    # Decode URL encoding (%2e%2e%2f → ../) and normalise Unicode (NFD → NFC)
    # before resolving — prevents traversal attacks via encoding tricks.
    sanitised = unicodedata.normalize("NFC", unquote(path))
    p = Path(sanitised)
    base = WORKDIR.get()
    resolved = (p if p.is_absolute() else base / p).resolve()
    if not str(resolved).startswith(str(base.resolve())):
        raise ValueError(f"Path outside workdir: {path}")
    return resolved


def _check_write(p: Path) -> str | None:
    """Return a FATAL error string if p is a protected runtime path."""
    rel = p.resolve().relative_to(WORKDIR.get().resolve())
    if any(part in PROTECTED_PATH_PARTS for part in rel.parts) or rel.name in PROTECTED_PATH_FILES:
        return f"FATAL: writing to '{rel}' is not allowed — protected runtime path"
    return None


def _resolve_file(path: str, *, must_exist: bool = True) -> Path | str:
    """Resolve a path that must point to a file (not a dir). Returns Path or error string."""
    try:
        p = _rel(path)
    except ValueError as e:
        return f"FATAL: {e}"
    if must_exist and not p.exists():
        return f"FATAL: file not found: {path}"
    if p.exists() and p.is_dir():
        return f"RETRYABLE: {path!r} is a directory, not a file — pass a file path"
    return p


def _truncate_middle_tokens(text: str, max_tokens: int) -> tuple[str, bool]:
    if text_stats(text)["tokens"] <= max_tokens:
        return text, False

    marker = f"\n[read_file truncated to {max_tokens} tokens; request explicit line ranges for omitted content]\n"
    budget = max(0, max_tokens - text_stats(marker)["tokens"])
    if budget <= 0:
        return marker.strip(), True

    keep_chars = max(1, budget * 4)
    half = keep_chars // 2
    out = text[:half] + marker + text[-half:]
    while text_stats(out)["tokens"] > max_tokens and half > 1:
        half = int(half * 0.8)
        out = text[:half] + marker + text[-half:]
    return out, True


async def read_file(
    path: str,
    start_line: int | None = None,
    end_line: int | None = None,
) -> str:
    p = _resolve_file(path)
    if isinstance(p, str):
        log_call("read_file", {"path": path}, p)
        return p

    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    total = len(lines)

    if start_line is not None or end_line is not None:
        requested_lo = max(0, (start_line or 1) - 1)
        requested_hi = min(total, end_line or total)
        lo = requested_lo
        hi = requested_hi
        expanded = False
        if total >= _MIN_TARGETED_READ_LINES and hi > lo and hi - lo < _MIN_TARGETED_READ_LINES:
            hi = min(total, lo + _MIN_TARGETED_READ_LINES)
            if hi - lo < _MIN_TARGETED_READ_LINES:
                lo = max(0, hi - _MIN_TARGETED_READ_LINES)
            expanded = lo != requested_lo or hi != requested_hi
        body = "".join(lines[lo:hi])
        header = f"[{path} · lines {lo+1}-{hi} of {total}]\n"
        if expanded:
            header += (
                f"[read_file expanded requested lines {requested_lo+1}-{requested_hi} "
                f"to {lo+1}-{hi}; minimum targeted read is {_MIN_TARGETED_READ_LINES} lines]\n"
            )
        suffix = f" (lines {lo+1}–{hi} of {total})"
    else:
        body, truncated = _truncate_middle_tokens("".join(lines), _READ_MAX_OUTPUT_TOKENS)
        header = f"[{path} · {total} lines]\n"
        if truncated:
            header += (
                f"[read_file truncated full-file output to {_READ_MAX_OUTPUT_TOKENS} tokens; "
                "use start_line/end_line for exact omitted content]\n"
            )
        suffix = ""
        lo = hi = None
        expanded = False

    reads = READ_CTX.get(None)
    if reads is not None:
        reads.add(str(p))
    s = text_stats(body)
    log_call(
        "read_file",
        {
            "path": path,
            "start_line": start_line,
            "end_line": end_line,
            "served_start_line": lo + 1 if lo is not None else None,
            "served_end_line": hi,
            "expanded": expanded,
        },
        f"OK: {s['words']} words / {s['tokens']} tokens{suffix}",
    )
    return header + body


async def write_file(path: str, content: str) -> str:
    p = _resolve_file(path, must_exist=False)
    if isinstance(p, str):
        log_call("write_file", {"path": path}, p)
        return p
    if err := _check_write(p):
        log_call("write_file", {"path": path}, err)
        return err
    if len(content.encode()) > _MAX_BYTES:
        result = "FATAL: content exceeds 10 MB limit"
        log_call("write_file", {"path": path}, result)
        return result
    existed = p.exists()
    old = p.read_text(encoding="utf-8") if existed else ""
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    verb = "Updated" if existed else "Created"
    result = f"{verb}: {path} ({_diff_stats(old, content)})"
    log_call("write_file", {"path": path}, result)
    return result


async def edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    args = {"path": path, "replace_all": replace_all}
    p = _resolve_file(path)
    if isinstance(p, str):
        log_call("edit_file", args, p)
        return p
    if err := _check_write(p):
        log_call("edit_file", args, err)
        return err
    reads = READ_CTX.get(None)
    if reads is not None and str(p) not in reads:
        result = f"RETRYABLE: must call read_file(\"{path}\") before editing"
        log_call("edit_file", args, result)
        return result
    if old_string == new_string:
        result = "FATAL: old_string and new_string are identical — no edit needed"
        log_call("edit_file", args, result)
        return result
    content = p.read_text(encoding="utf-8")
    if old_string not in content:
        result = f"RETRYABLE: old_string not found in {path} — call view to get the exact current text"
        log_call("edit_file", args, result)
        return result
    updated = content.replace(old_string, new_string) if replace_all else content.replace(old_string, new_string, 1)
    if len(updated.encode()) > _MAX_BYTES:
        result = "FATAL: result exceeds 10 MB limit"
        log_call("edit_file", args, result)
        return result
    p.write_text(updated, encoding="utf-8")
    count = content.count(old_string)
    replaced = count if replace_all else 1
    result = f"Edited: {path} ({replaced} replacement{'s' if replaced > 1 else ''}, {_diff_stats(content, updated)})"
    log_call("edit_file", args, result)
    return result


async def list_dir(path: str = ".") -> str:
    try:
        p = _rel(path)
    except ValueError as e:
        result = f"FATAL: {e}"
        log_call("list_dir", {"path": path}, result)
        return result
    if not p.exists():
        result = f"FATAL: directory not found: {path}"
        log_call("list_dir", {"path": path}, result)
        return result
    entries = sorted(p.iterdir(), key=lambda e: (e.is_file(), e.name))
    lines = [f"{'d' if e.is_dir() else 'f'}  {e.name}" for e in entries]
    result = "\n".join(lines) or "(empty)"
    log_call("list_dir", {"path": path}, f"OK: {len(entries)} entries")
    return result


async def delete_file(path: str) -> str:
    p = _resolve_file(path)
    if isinstance(p, str):
        log_call("delete_file", {"path": path}, p)
        return p
    if err := _check_write(p):
        log_call("delete_file", {"path": path}, err)
        return err
    p.unlink()
    result = f"Deleted: {path}"
    log_call("delete_file", {"path": path}, result)
    return result


_GREP_SKIP_DIRS = {".git", ".worktrees", "node_modules", ".venv", "__pycache__", "generated", ".agent.db", ".librarian.db"}
_GREP_MAX_FILES = 1_000
_GREP_MAX_BYTES = 512_000
_GREP_DEFAULT_FILE_RESULTS = 100
_GREP_DEFAULT_COUNT_RESULTS = 100
_GREP_DEFAULT_CONTENT_RESULTS = 30
_GREP_MAX_FILE_RESULTS = 300
_GREP_MAX_COUNT_RESULTS = 300
_GREP_MAX_CONTENT_RESULTS = 100
_GREP_CONTEXT_LINES = 3
_GREP_OUTPUT_MODES = frozenset({"files", "content", "count"})


@dataclass
class _GrepFileResult:
    path: Path
    lines: list[str]
    matches: list[int]
    score: int


def _grep_matches_glob(rel: Path, glob: str | None) -> bool:
    if not glob:
        return True
    s = rel.as_posix()
    return fnmatch.fnmatch(s, glob) or (glob.startswith("**/") and fnmatch.fnmatch(s, glob[3:]))


def _grep_path_score(rel: Path, pattern: str, *, fixed_string: bool) -> int:
    path = rel.as_posix().lower()
    name = rel.name.lower()
    raw_terms = re.split(r"[^A-Za-z0-9_.-]+", pattern)
    if fixed_string:
        raw_terms.append(pattern)
    terms = [t.lower() for t in raw_terms if len(t.strip()) >= 2]
    if not terms:
        return 0
    if any(t in name for t in terms):
        return 2
    if any(t in path for t in terms):
        return 1
    return 0


def _grep_page_label(noun: str, offset: int, shown: int, total: int) -> str:
    if shown == 0:
        return f"No {noun} at offset {offset}; total {total}."
    return f"Showing {noun} {offset + 1}-{offset + shown} of {total}."


def _grep_default_max_results(output_mode: str) -> int:
    if output_mode == "content":
        return _GREP_DEFAULT_CONTENT_RESULTS
    if output_mode == "count":
        return _GREP_DEFAULT_COUNT_RESULTS
    return _GREP_DEFAULT_FILE_RESULTS


def _grep_max_results_limit(output_mode: str) -> int:
    if output_mode == "content":
        return _GREP_MAX_CONTENT_RESULTS
    if output_mode == "count":
        return _GREP_MAX_COUNT_RESULTS
    return _GREP_MAX_FILE_RESULTS


async def grep_file(
    path: str,
    pattern: str,
    output_mode: str = "files",
    max_results: int | None = None,
    offset: int = 0,
    fixed_string: bool = False,
    glob: str | None = None,
) -> str:
    if output_mode not in _GREP_OUTPUT_MODES:
        result = f"FATAL: invalid output_mode {output_mode!r}; use one of: content, count, files"
        log_call("grep_file", {"path": path, "pattern": pattern, "output_mode": output_mode}, result)
        return result
    max_results = _grep_default_max_results(output_mode) if max_results is None else max_results
    max_results = max(1, min(max_results, _grep_max_results_limit(output_mode)))
    offset = max(0, offset)
    args = {
        "path": path,
        "pattern": pattern,
        "output_mode": output_mode,
        "max_results": max_results,
        "offset": offset,
        "fixed_string": fixed_string,
        "glob": glob or "",
    }
    try:
        rx = re.compile(re.escape(pattern) if fixed_string else pattern)
    except re.error as e:
        result = f"FATAL: invalid pattern: {e}"
        log_call("grep_file", args, result)
        return result

    try:
        target = _rel(path)
    except ValueError as e:
        log_call("grep_file", args, f"FATAL: {e}")
        return f"FATAL: {e}"
    if not target.exists():
        msg = f"FATAL: path not found: {path}"
        log_call("grep_file", args, msg)
        return msg

    base = target if target.is_dir() else WORKDIR.get().resolve()
    candidates: list[Path]
    hit_candidate_cap = False
    if target.is_dir():
        candidates = []
        for f in target.rglob("*"):
            if not f.is_file():
                continue
            if any(part in _GREP_SKIP_DIRS for part in f.relative_to(target).parts):
                continue
            if not _grep_matches_glob(f.relative_to(target), glob):
                continue
            try:
                if f.stat().st_size > _GREP_MAX_BYTES:
                    continue
            except OSError:
                continue
            candidates.append(f)
            if len(candidates) >= _GREP_MAX_FILES:
                hit_candidate_cap = True
                break
    else:
        try:
            rel = target.relative_to(base)
        except ValueError:
            rel = Path(target.name)
        if not _grep_matches_glob(rel, glob):
            result = f"No matches for '{pattern}' in {path} matching glob {glob!r}"
            log_call("grep_file", args, result)
            return result
        candidates = [target]

    file_results: list[_GrepFileResult] = []
    total_matches = 0
    for f in candidates:
        try:
            lines = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        match_indexes = [i for i, line in enumerate(lines) if rx.search(line)]
        if not match_indexes:
            continue
        try:
            rel = f.relative_to(base)
        except ValueError:
            rel = Path(f.name)
        total_matches += len(match_indexes)
        file_results.append(_GrepFileResult(
            path=rel,
            lines=lines,
            matches=match_indexes,
            score=_grep_path_score(rel, pattern, fixed_string=fixed_string),
        ))

    if not file_results:
        scope = f"{path or '.'}" + (f" matching glob {glob!r}" if glob else "")
        result = f"No matches for '{pattern}' under {scope}"
        log_call("grep_file", args, result)
        return result

    file_results.sort(
        key=lambda r: (
            -r.score,
            -len(r.matches),
            r.path.as_posix(),
        )
    )

    scope = path or "."
    if glob:
        scope += f" (glob {glob!r})"
    scan_note = ""
    if hit_candidate_cap:
        scan_note = (
            f"\n[grep_file scanned first {_GREP_MAX_FILES} candidate files under {scope}; "
            "files beyond that were not searched. Narrow path/glob to search a smaller set if needed.]"
        )

    if output_mode == "files":
        rows = [r.path.as_posix() for r in file_results]
        page = rows[offset:offset + max_results]
        shown_end = offset + len(page)
        more = shown_end < len(rows)
        header = (
            f"Found {total_matches} match(es) across {len(rows)} file(s) under {scope}. "
            f"{_grep_page_label('files', offset, len(page), len(rows))}"
        )
        hint = ""
        if more:
            hint = (
                f"\nIf these include what you need, you can inspect them if desired with output_mode='content' or read_file. "
                f"If not, continue with offset={shown_end}, or narrow path/glob/pattern."
            )
        result = header + scan_note + hint + "\n\n" + "\n".join(page)
        log_call("grep_file", args, f"OK: {total_matches} match(es) across {len(rows)} file(s)")
        return result

    if output_mode == "count":
        rows = [f"{r.path.as_posix()}: {len(r.matches)}" for r in file_results]
        page = rows[offset:offset + max_results]
        shown_end = offset + len(page)
        more = shown_end < len(rows)
        header = (
            f"Found {total_matches} match(es) across {len(rows)} file(s) under {scope}. "
            f"{_grep_page_label('files', offset, len(page), len(rows))}"
        )
        hint = ""
        if more:
            hint = (
                f"\nIf these include what you need, you can inspect them if desired with output_mode='content' or read_file. "
                f"If not, continue with offset={shown_end}, or narrow path/glob/pattern."
            )
        result = header + scan_note + hint + "\n\n" + "\n".join(page)
        log_call("grep_file", args, f"OK: {total_matches} match(es) across {len(rows)} file(s)")
        return result

    blocks: list[tuple[str, str, int]] = []
    for r in file_results:
        rel = r.path.as_posix()
        lines = r.lines
        ranges: list[list[int]] = []
        for idx in r.matches:
            start = max(0, idx - _GREP_CONTEXT_LINES)
            end = min(len(lines), idx + _GREP_CONTEXT_LINES + 1)
            if ranges and start <= ranges[-1][1]:
                ranges[-1][1] = max(ranges[-1][1], end)
                ranges[-1][2] += 1
            else:
                ranges.append([start, end, 1])
        for start, end, match_count in ranges:
            body = "\n".join(f"{j+1}: {lines[j]}" for j in range(start, end))
            blocks.append((rel, body, match_count))

    page_blocks = blocks[offset:offset + max_results]
    shown_end = offset + len(page_blocks)
    more = shown_end < len(blocks)
    header = (
        f"Found {total_matches} match(es) across {len(file_results)} file(s) under {scope}. "
        f"{_grep_page_label('context blocks', offset, len(page_blocks), len(blocks))} "
        f"Each block includes up to {_GREP_CONTEXT_LINES} line(s) before and after a match."
    )
    hint = ""
    if more:
        hint = (
            f"\nIf these include what you need, you can inspect more if desired with read_file on the relevant path/line range. "
            f"If not, continue with offset={shown_end}, or narrow path/glob/pattern."
        )
    rendered = [
        f"{rel} ({match_count} match{'es' if match_count != 1 else ''} in block):\n{body}"
        for rel, body, match_count in page_blocks
    ]
    result = header + scan_note + hint + "\n\n" + "\n---\n".join(rendered)
    log_call("grep_file", args, f"OK: {total_matches} match(es) across {len(file_results)} file(s)")
    return result


# --- Tool definitions ---

READ_FILE = Tool(
    name="read_file",
    description=(
        "Read a file's contents. Optionally specify start_line and end_line (1-based) "
        "to read only a range — useful for large files. Very small bounded ranges may "
        "be expanded to provide enough surrounding context. Full-file reads are capped "
        "with head/tail truncation; request explicit ranges for omitted content. "
        "Must be called before edit_file."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path":       {"type": "string",  "description": "Relative file path, e.g. 'src/core/tools/fs.py' (use 'path', not 'file_path')"},
            "start_line": {"type": "integer", "description": "First line to read (1-based, inclusive)"},
            "end_line":   {"type": "integer", "description": "Last line to read (1-based, inclusive)"},
        },
        "required": ["path"],
    },
    fn=read_file,
    is_read_only=True,
    is_concurrency_safe=True,
)

WRITE_FILE = Tool(
    name="write_file",
    description=(
        "Write full content to a file, creating parent directories as needed. "
        "Use for new files or complete rewrites. For targeted edits use edit_file."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path":    {"type": "string", "description": "File path (use 'path', not 'file_path')"},
            "content": {"type": "string", "description": "Full file content"},
        },
        "required": ["path", "content"],
    },
    fn=write_file,
)

EDIT_FILE = Tool(
    name="edit_file",
    description=(
        "Replace an exact string in a file. Requires read_file to have been called first. "
        "old_string must match exactly — including whitespace and indentation. "
        "Fails if not found. Use replace_all=true to replace every occurrence."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path":        {"type": "string",  "description": "Relative file path, e.g. 'src/core/tools/fs.py' (use 'path', not 'file_path')"},
            "old_string":  {"type": "string",  "description": "Exact text to replace (must match literally, including whitespace)"},
            "new_string":  {"type": "string",  "description": "Replacement text"},
            "replace_all": {"type": "boolean", "description": "Replace all occurrences (default false)"},
        },
        "required": ["path", "old_string", "new_string"],
    },
    fn=edit_file,
)

GREP_FILE = Tool(
    name="grep_file",
    description=(
        "Search for a regex pattern in a file or directory. Empty path = repo root. "
        "Defaults to output_mode='files' so broad searches return matching paths first. "
        "Use output_mode='content' to return line-numbered matches with 3 lines before/after, "
        "or output_mode='count' to return per-file match counts. Results are ranked by path/name "
        "relevance, match count, then stable path order. If a response says more results exist, "
        "use offset to continue or narrow with path/glob/pattern. Use fixed_string=true for literal "
        "text such as URLs, endpoint paths, filenames, or strings containing regex punctuation. "
        "Use glob to filter files under path, e.g. '**/*.py', 'docs/**/*.html'. "
        "Use read_file first if you intend to edit — grep alone does not satisfy the read requirement."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path":        {"type": "string",  "description": "File or directory path. Empty string = repo root."},
            "pattern":     {"type": "string",  "description": "Regex pattern to search for, or literal text when fixed_string=true"},
            "output_mode": {"type": "string",  "enum": ["files", "content", "count"], "description": "files = matching paths only (default); content = line-numbered matches with 3 lines before/after; count = per-file match counts"},
            "max_results": {"type": "integer", "description": "Maximum files/count rows/context blocks to return in this page. Usually omit it: defaults are files=100, count=100, content=30. Clamped by mode: files/count up to 300, content up to 100."},
            "offset":      {"type": "integer", "description": "Zero-based result offset for continuing a truncated result page"},
            "fixed_string": {"type": "boolean", "description": "Treat pattern as literal text instead of regex (default false)"},
            "glob":        {"type": "string",  "description": "Optional file filter under path, e.g. '**/*.py', 'docs/**/*.html', '*.md'"},
        },
        "required": ["path", "pattern"],
    },
    fn=grep_file,
    is_read_only=True,
    is_concurrency_safe=True,
)

LIST_DIR = Tool(
    name="list_dir",
    description="List files and directories at a path. Defaults to repo root.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Directory path, e.g. 'src/core/tools'. Empty or omit = repo root."}},
        "required": [],
    },
    fn=list_dir,
    is_read_only=True,
    is_concurrency_safe=True,
)

DELETE_FILE = Tool(
    name="delete_file",
    description="Delete a file.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Relative file path to delete (use 'path', not 'file_path')"}},
        "required": ["path"],
    },
    fn=delete_file,
)

FS_TOOLS = [READ_FILE, WRITE_FILE, EDIT_FILE, GREP_FILE, LIST_DIR, DELETE_FILE]
