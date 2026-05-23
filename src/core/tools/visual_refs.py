"""Tools for loading existing website images as visual references."""

from __future__ import annotations

import mimetypes
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote, urlsplit

from core.ai_client.models import ImageContent, Tool
from core.images import shrink
from core.log import Category
from core.log import log as _log
from core.tools.ctx import REPO_ROOT, WORKDIR, queue_multimodal

_IMG_RE = re.compile(r"<img\b[^>]*\bsrc\s*=\s*(['\"])(?P<src>.*?)\1", re.IGNORECASE | re.DOTALL)
_CSS_URL_RE = re.compile(r"url\(\s*(['\"]?)(?P<src>[^)'\"\s]+)\1\s*\)", re.IGNORECASE)
_REMOTE_PREFIXES = ("http://", "https://", "data:", "mailto:", "javascript:", "tel:", "ftp://", "slack://", "#")
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@dataclass(frozen=True)
class _Candidate:
    label: str
    html_path: str
    src: str
    context: str = ""
    local_path: Path | None = None
    branch_ref: str | None = None
    branch_path: str | None = None


def _clean_src(src: str) -> str:
    split = urlsplit(src.strip())
    return unquote(split.path)


def _mime_for(path: str) -> str | None:
    mime = mimetypes.guess_type(path)[0]
    return mime if mime and mime.startswith("image/") else None


def _safe_child(parent: Path, rel: str) -> Path | None:
    try:
        path = (parent / rel).resolve()
        path.relative_to(parent.resolve())
        return path
    except ValueError:
        return None


def _docs_image_path(path: str) -> str | None:
    if path.strip().lower().startswith(_REMOTE_PREFIXES):
        return None
    clean = _clean_src(path)
    if clean.startswith("/one/images/"):
        clean = f"docs/images/{clean.removeprefix('/one/images/')}"
    elif clean.startswith("/docs/images/"):
        clean = clean.removeprefix("/")
    elif clean.startswith("images/"):
        clean = f"docs/{clean}"
    elif not clean.startswith("docs/images/"):
        return None
    rel = Path(clean)
    if rel.is_absolute() or ".." in rel.parts or rel.suffix.lower() not in _IMAGE_SUFFIXES:
        return None
    return rel.as_posix()


def _extract_sources(html: str) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for match in [*_IMG_RE.finditer(html), *_CSS_URL_RE.finditer(html)]:
        src = match.group("src").strip()
        if not src or src in seen:
            continue
        seen.add(src)
        out.append(src)
    return out


def _resolve_local(src: str, html_file: Path, workdir: Path) -> Path | None:
    if src.strip().lower().startswith(_REMOTE_PREFIXES):
        return None
    clean = _clean_src(src)
    if not clean:
        return None
    candidates: list[Path | None] = []
    if clean.startswith("/one/images/"):
        candidates.append(_safe_child(workdir / "docs" / "images", clean.removeprefix("/one/images/")))
    elif clean.startswith("/images/"):
        candidates.append(_safe_child(workdir / "generated" / "images", clean.removeprefix("/images/")))
    elif clean.startswith("/"):
        candidates.append(_safe_child(workdir / "docs", clean.removeprefix("/")))
        candidates.append(_safe_child(workdir, clean.removeprefix("/")))
    else:
        candidates.append(_safe_child(html_file.parent, clean))
        candidates.append(_safe_child(workdir / "docs", clean))
    for path in candidates:
        if path and path.is_file() and path.suffix.lower() in _IMAGE_SUFFIXES:
            return path
    return None


def _git_show(ref: str, path: str) -> bytes | None:
    try:
        return subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "show", f"{ref}:{path}"],
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return None


def _git_common_dir(cwd: Path) -> Path | None:
    try:
        raw = subprocess.check_output(
            ["git", "-C", str(cwd), "rev-parse", "--git-common-dir"],
            stderr=subprocess.DEVNULL,
        ).decode("utf-8", "replace").strip()
    except subprocess.CalledProcessError:
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = cwd / path
    return path.resolve()


def _workdir_belongs_to_repo(workdir: Path) -> bool:
    workdir_common = _git_common_dir(workdir)
    repo_common = _git_common_dir(REPO_ROOT)
    return workdir_common is not None and repo_common is not None and workdir_common == repo_common


def _image_content(data: bytes) -> ImageContent | None:
    try:
        resized = shrink(data)
    except Exception:
        return None
    return ImageContent(mime=resized.mime, data=resized.data)


def _branch_docs_listing(ref: str) -> list[str]:
    try:
        listing = subprocess.check_output(
            ["git", "-C", str(REPO_ROOT), "ls-tree", "-r", "--name-only", ref, "docs"],
            stderr=subprocess.DEVNULL,
        ).decode("utf-8", "replace")
    except subprocess.CalledProcessError:
        return []
    return [path for path in listing.splitlines() if path.startswith("docs/")]


def _branch_docs_html(ref: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for path in _branch_docs_listing(ref):
        if not path.endswith(".html"):
            continue
        data = _git_show(ref, path)
        if data is not None:
            out.append((path, data.decode("utf-8", "replace")))
    return out


def _resolve_branch(src: str, html_path: str, ref: str) -> tuple[str, bytes] | None:
    if src.strip().lower().startswith(_REMOTE_PREFIXES):
        return None
    clean = _clean_src(src)
    if not clean:
        return None
    candidates: list[str] = []
    if clean.startswith("/one/images/"):
        candidates.append(f"docs/images/{clean.removeprefix('/one/images/')}")
    elif clean.startswith("/"):
        candidates.append(f"docs/{clean.removeprefix('/')}")
        candidates.append(clean.removeprefix("/"))
    else:
        html_dir = str(Path(html_path).parent)
        candidates.append(str(Path(html_dir) / clean))
        candidates.append(f"docs/{clean}")
    for path in candidates:
        if Path(path).suffix.lower() not in _IMAGE_SUFFIXES or ".." in Path(path).parts:
            continue
        data = _git_show(ref, path)
        if data is not None:
            return path, data
    return None


def _explicit_local_candidate(path: str, workdir: Path) -> _Candidate | None:
    docs_path = _docs_image_path(path)
    if not docs_path:
        return None
    local_path = _safe_child(workdir, docs_path)
    if not local_path or not local_path.is_file():
        return None
    return _Candidate(local_path.name, "explicit path", path, context=path, local_path=local_path)


def _explicit_branch_candidate(path: str, task_id: str) -> _Candidate | None:
    if not _TASK_ID_RE.fullmatch(task_id):
        return None
    return _explicit_ref_candidate(path, f"task/{task_id}")


def _explicit_ref_candidate(path: str, ref: str) -> _Candidate | None:
    docs_path = _docs_image_path(path)
    if not docs_path:
        return None
    if _git_show(ref, docs_path) is None:
        return None
    return _Candidate(Path(docs_path).name, "explicit path", path, context=path, branch_ref=ref, branch_path=docs_path)


def _explicit_canonical_candidate(path: str, workdir: Path) -> _Candidate | None:
    if not _workdir_belongs_to_repo(workdir):
        return None
    for ref in ("origin/main", "main"):
        candidate = _explicit_ref_candidate(path, ref)
        if candidate:
            return candidate
    return None


def _local_candidates() -> list[_Candidate]:
    workdir = WORKDIR.get()
    docs = workdir / "docs"
    if not docs.is_dir():
        return []
    out: list[_Candidate] = []
    for html_file in sorted(docs.glob("*.html")):
        try:
            html = html_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for src in _extract_sources(html):
            path = _resolve_local(src, html_file, workdir)
            if path:
                out.append(_Candidate(path.name, str(html_file.relative_to(workdir)), src, context=html, local_path=path))
    images_dir = docs / "images"
    if images_dir.is_dir():
        for image_file in sorted(images_dir.rglob("*")):
            if not image_file.is_file() or image_file.suffix.lower() not in _IMAGE_SUFFIXES:
                continue
            rel = image_file.relative_to(workdir).as_posix()
            out.append(_Candidate(image_file.name, "docs/images", rel, context=rel, local_path=image_file))
    return out


def _branch_candidates(task_id: str) -> list[_Candidate]:
    if not _TASK_ID_RE.fullmatch(task_id):
        return []
    ref = f"task/{task_id}"
    return _branch_ref_candidates(ref)


def _branch_ref_candidates(ref: str) -> list[_Candidate]:
    out: list[_Candidate] = []
    for html_path, html in _branch_docs_html(ref):
        for src in _extract_sources(html):
            resolved = _resolve_branch(src, html_path, ref)
            if not resolved:
                continue
            branch_path, _ = resolved
            out.append(_Candidate(Path(branch_path).name, html_path, src, context=html, branch_ref=ref, branch_path=branch_path))
    for path in _branch_docs_listing(ref):
        rel = Path(path)
        if not path.startswith("docs/images/") or rel.suffix.lower() not in _IMAGE_SUFFIXES:
            continue
        out.append(_Candidate(rel.name, "docs/images", path, context=path, branch_ref=ref, branch_path=path))
    return out


def _canonical_branch_candidates(workdir: Path) -> list[_Candidate]:
    if not _workdir_belongs_to_repo(workdir):
        return []
    out: list[_Candidate] = []
    seen_paths: set[str] = set()
    for ref in ("origin/main", "main"):
        for candidate in _branch_ref_candidates(ref):
            key = candidate.branch_path or candidate.src
            if key in seen_paths:
                continue
            seen_paths.add(key)
            out.append(candidate)
    return out


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.lower())).strip()


def _query_terms(query: str | None) -> list[str]:
    if not query:
        return []
    return [term for term in re.findall(r"[a-z0-9]+", query.lower()) if len(term) > 1]


def _score_candidate(candidate: _Candidate, query: str) -> int:
    terms = _query_terms(query)
    if not terms:
        return 0
    phrase = _norm_text(query)
    path_text = _norm_text(
        " ".join(
            [
                candidate.label,
                candidate.html_path,
                candidate.src,
                str(candidate.local_path or ""),
                candidate.branch_path or "",
            ]
        )
    )
    context_text = _norm_text(candidate.context)
    score = 0
    if phrase and phrase in path_text:
        score += 100
    if phrase and phrase in context_text:
        score += 40
    for left, right in zip(terms, terms[1:], strict=False):
        pair = f"{left} {right}"
        if pair in path_text:
            score += 30
        if pair in context_text:
            score += 10
    for term in terms:
        if term in path_text:
            score += 10
        if term in context_text:
            score += 3
    return score


def _rank_candidates(candidates: list[_Candidate], query: str | None) -> list[_Candidate]:
    if not query:
        return candidates
    scored = [(idx, _score_candidate(candidate, query), candidate) for idx, candidate in enumerate(candidates)]
    return [candidate for idx, score, candidate in sorted(scored, key=lambda item: (-item[1], item[0])) if score > 0]


async def load_website_image_refs(
    max_images: int = 4,
    from_task_id: str | None = None,
    query: str | None = None,
    paths: list[str] | None = None,
) -> str:
    """Load existing website/article images into the next model call as visual references."""
    if max_images < 1 or max_images > 8:
        return "FATAL: max_images must be between 1 and 8"
    workdir = WORKDIR.get()
    requested_paths = [path for path in paths or [] if path.strip()]
    candidates: list[_Candidate] = []
    for path in requested_paths:
        candidate = _explicit_local_candidate(path, workdir)
        if not candidate and from_task_id:
            candidate = _explicit_branch_candidate(path, from_task_id)
        if not candidate:
            candidate = _explicit_canonical_candidate(path, workdir)
        if candidate:
            candidates.append(candidate)

    pool = _local_candidates()
    if from_task_id:
        pool.extend(_branch_candidates(from_task_id))
    if query:
        pool.extend(_canonical_branch_candidates(workdir))

    if query:
        candidates.extend(_rank_candidates(pool, query))
    elif not requested_paths:
        candidates.extend(pool)

    images: list[ImageContent] = []
    lines: list[str] = []
    seen: set[tuple[str, str]] = set()
    for candidate in candidates:
        key = (candidate.branch_ref or "local", str(candidate.local_path or candidate.branch_path))
        if key in seen:
            continue
        seen.add(key)
        if candidate.local_path:
            if not _mime_for(candidate.local_path.name):
                continue
            data = candidate.local_path.read_bytes()
            label = str(candidate.local_path.relative_to(WORKDIR.get()))
        elif candidate.branch_ref and candidate.branch_path:
            has_image_mime = _mime_for(candidate.branch_path) is not None
            data = _git_show(candidate.branch_ref, candidate.branch_path)
            if not has_image_mime or data is None:
                continue
            label = f"{candidate.branch_ref}:{candidate.branch_path}"
        else:
            continue
        image = _image_content(data)
        if image is None:
            continue
        images.append(image)
        lines.append(f"- {label} referenced by {candidate.html_path} as `{candidate.src}`")
        if len(images) >= max_images:
            break

    if not images:
        _log(
            Category.TOOL,
            "load_website_image_refs",
            count=0,
            from_task_id=from_task_id or "",
            query=query or "",
            paths=requested_paths,
        )
        if query:
            return f"No matching website image references found for query `{query}`."
        if requested_paths:
            return "No matching website image references found for the requested path(s)."
        return "No website image references found in docs/*.html."
    queue_multimodal(images)
    _log(
        Category.TOOL,
        "load_website_image_refs",
        count=len(images),
        from_task_id=from_task_id or "",
        query=query or "",
        paths=requested_paths,
        refs=lines,
    )
    return (
        f"Loaded {len(images)} website image reference(s) into the next model call. "
        "Use them to match the existing article/site visual language before generating or revising images.\n"
        + "\n".join(lines)
    )


LOAD_WEBSITE_IMAGE_REFS_TOOL = Tool(
    name="load_website_image_refs",
    description=(
        "Load existing website/article images as visual references for the next model call. "
        "Use this only when a task asks to match an existing site/article visual style, create a new article "
        "cover in the same family, or critique whether a generated image fits the website. It deterministically "
        "loads exact `paths` first, or ranks local and canonical-main `docs/*.html` image references by a "
        "text `query` when provided. "
        "It resolves paths like `/one/images/foo.png` to `docs/images/foo.png`, and can optionally fall back to "
        "`task/<from_task_id>` for prior task branches. There is no LLM inside this tool. The loaded images are "
        "attached once to the next provider iteration; they are not permanently added to every turn."
    ),
    parameters={
        "type": "object",
        "properties": {
            "max_images": {
                "type": "integer",
                "description": "Maximum reference images to load. Default 4; must be 1-8.",
            },
            "from_task_id": {
                "type": "string",
                "description": "Optional prior task id to load docs images from branch task/<id> if local docs do not include enough references.",
            },
            "query": {
                "type": "string",
                "description": "Optional deterministic text query such as `Silicon Sociology cover image style`; only matching image refs are loaded.",
            },
            "paths": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional exact image paths to load first, such as `docs/images/hero.png` or `/one/images/hero.png`.",
            },
        },
    },
    fn=load_website_image_refs,
    is_read_only=True,
    is_concurrency_safe=False,
)
