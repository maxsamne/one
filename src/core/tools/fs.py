"""Filesystem tools — view, create, str_replace, grep, list_dir, delete."""

import difflib
import re
import unicodedata
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
_MIN_TARGETED_READ_LINES = 50
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
        body = "".join(lines)
        header = f"[{path} · {total} lines]\n"
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
_GREP_MAX_FILES = 500
_GREP_MAX_BYTES = 512_000


async def grep_file(path: str, pattern: str, context_lines: int = 2) -> str:
    args = {"path": path, "pattern": pattern}
    try:
        rx = re.compile(pattern)
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

    if target.is_dir():
        files: list[Path] = []
        for f in target.rglob("*"):
            if not f.is_file():
                continue
            if any(part in _GREP_SKIP_DIRS for part in f.relative_to(target).parts):
                continue
            try:
                if f.stat().st_size > _GREP_MAX_BYTES:
                    continue
            except OSError:
                continue
            files.append(f)
            if len(files) >= _GREP_MAX_FILES:
                break
        per_file: list[str] = []
        total = 0
        for f in files:
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            file_matches = [
                f"{i+1}: {line}" for i, line in enumerate(text.splitlines()) if rx.search(line)
            ]
            if file_matches:
                rel = f.relative_to(target)
                per_file.append(f"{rel}:\n" + "\n".join(file_matches[:20]))
                total += len(file_matches)
        if not per_file:
            result = f"No matches for '{pattern}' under {path or '.'}"
            log_call("grep_file", args, result)
            return result
        result = f"Matches under {path or '.'} ({total} total):\n\n" + "\n\n".join(per_file)
        log_call("grep_file", args, f"OK: {total} match(es) across {len(per_file)} file(s)")
        return result

    lines = target.read_text(encoding="utf-8").splitlines()
    matches: list[str] = []
    for i, line in enumerate(lines):
        if rx.search(line):
            start = max(0, i - context_lines)
            end = min(len(lines), i + context_lines + 1)
            block = "\n".join(f"{j+1}: {lines[j]}" for j in range(start, end))
            matches.append(block)
    if not matches:
        result = f"No matches for '{pattern}' in {path}"
        log_call("grep_file", args, result)
        return result
    result = f"Matches in {path}:\n\n" + "\n---\n".join(matches)
    log_call("grep_file", args, f"OK: {len(matches)} match(es)")
    return result


# --- Tool definitions ---

READ_FILE = Tool(
    name="read_file",
    description=(
        "Read a file's contents. Optionally specify start_line and end_line (1-based) "
        "to read only a range — useful for large files. Very small bounded ranges may "
        "be expanded to provide enough surrounding context. Must be called before edit_file."
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
        "Search for a regex pattern. If path is a file, returns matches with context. "
        "If path is a directory (or empty for repo root), recursively greps text files under it "
        "and returns up to 20 matches per file. Skips .git, node_modules, .venv, etc. "
        "Use read_file first if you intend to edit — grep alone does not satisfy the read requirement."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path":          {"type": "string",  "description": "File or directory path. Empty string = repo root."},
            "pattern":       {"type": "string",  "description": "Regex pattern to search for"},
            "context_lines": {"type": "integer", "description": "Lines of context around each match (file mode only, default 2)"},
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
