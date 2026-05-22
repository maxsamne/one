"""FastAPI gateway — receives tasks, runs manager, returns results."""

import asyncio
import contextlib
import json
import mimetypes
import re
import subprocess
import time
import traceback
from pathlib import Path
from typing import AsyncIterator

from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from core.agents import workdir_registry
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from core.agents import graders as graders_mod
from core.agents import manager, skills
from core.agents.task_ctx import EXA_CALL_LOG, PR_URL_CTX, TASK_CTX, TASK_GRADERS_CTX, TASK_IMAGES_CTX, TASK_SKILLS_CTX, TASK_USAGE_LOG, TIER_CTX, TaskContext, new_task_id
from core import presets as presets_mod
from core.ai_client import AiClient, EmbeddingModel, ImageContent, ModelProvider, create_client, create_embedding_client
from core.ai_client.fallback_client import is_unavailable
from core.events import publish, subscribe, unsubscribe
from core.gateway.tasks import TaskRecord, TaskStatus, get, list_all, register
from core.log import Category, recent, task_id_exists, task_parent_id, tasks_history, tasks_insert, tasks_mark_orphaned_cancelled, tasks_update
from core.log import log as _log
from core.log import stat_inc
from core.scheduler import runner as scheduler_runner
from core.scheduler import store as scheduler_store
from core.text import text_stats
from core.ai_client.tiers import TierClients, load_tier
from core.tools.librarian import LIBRARIAN_CTX, LibrarianAgent
from core.tools.todo import clear_all_stale


@contextlib.asynccontextmanager
async def _lifespan(app: FastAPI):
    clear_all_stale()
    n = tasks_mark_orphaned_cancelled()
    if n:
        _log(Category.GATEWAY, "orphaned tasks swept", count=n)
    scheduler_runner.start(_fire_schedule)
    try:
        yield
    finally:
        await scheduler_runner.stop()


app = FastAPI(lifespan=_lifespan)

# Tier clients are created on demand and cached by tier name.
_tier_cache: dict[str, TierClients] = {}

def _get_tier(name: str) -> TierClients:
    if name not in _tier_cache:
        _tier_cache[name] = load_tier(name)
    return _tier_cache[name]

_ollama = create_client(ModelProvider.OLLAMA)
_embedder = create_embedding_client(EmbeddingModel.QWEN, dimensions=768)

_lib_nano   = create_client(ModelProvider.OPENAI, model_name="gpt-5.4-nano")
_lib_gemini = create_client(ModelProvider.GEMINI, model_name="gemini-3.5-flash")
_helper_mini = create_client(ModelProvider.OPENAI, model_name="gpt-5.4-mini")

_LIBRARIANS: dict[str, LibrarianAgent] = {
    "ultra_cheap": LibrarianAgent(embedding_client=_embedder, ai_client=_ollama,      dimensions=768),
    "cheap":       LibrarianAgent(embedding_client=_embedder, ai_client=_lib_nano,    dimensions=768),
    "default":     LibrarianAgent(embedding_client=_embedder, ai_client=_lib_nano,    dimensions=768),
    "pro":         LibrarianAgent(embedding_client=_embedder, ai_client=_lib_gemini,  dimensions=768),
}


# --- Request / response models ---

class TaskRequest(BaseModel):
    task: str
    tier: str = "ultra_cheap"
    # Skills the user explicitly attached (paths from GET /skills). Empty = no pre-loaded
    # skills; coder uses the always-injected skills index + load_skill tool.
    skills: list[str] = []
    # Graders the user explicitly attached (paths from GET /graders). Each becomes a
    # GraderHook the coder runs before declaring done. Empty = only universal linters.
    graders: list[str] = []
    # Images attached to the task. Each entry is a data URI:
    # "data:image/png;base64,iVBORw0KGgo..." — UI converts dropped files client-side.
    images: list[str] = []
    # Optional follow-up: when set, the new task seeds its coder loop with the
    # parent task's persisted transcript (full message history). Auto-compaction
    # keeps token cost bounded.
    parent_task_id: str | None = None
    # null = let the manager auto-classify (default). "conversational" / "persistent" force the mode.
    mode: str | None = None


class TaskSubmitted(BaseModel):
    task_id: str
    status: str = "queued"


class TaskResponse(BaseModel):
    task_id: str
    prompt: str
    status: str
    submitted_at: float
    started_at: float | None
    finished_at: float | None
    elapsed_s: float | None
    result: str | None
    error: str | None
    pr_url: str | None
    schedule_id: str | None = None
    parent_task_id: str | None = None
    tier: str | None = None
    skills: list[str] = []
    graders: list[str] = []
    mode_override: str | None = None


# --- Background runner ---

async def _run(record: TaskRecord) -> None:
    from core.ai_client.costs import cost_usd, format_cost
    record.status = "running"
    record.started_at = time.time()
    task_token = TASK_CTX.set(TaskContext(task_id=record.task_id, prompt=record.prompt))
    tier_token = TIER_CTX.set(record.tier)
    skills_token = TASK_SKILLS_CTX.set(record.skills)
    graders_token = TASK_GRADERS_CTX.set(record.graders)
    images_token = TASK_IMAGES_CTX.set(record.images)
    lib_token = LIBRARIAN_CTX.set(_LIBRARIANS.get(record.tier, _LIBRARIANS["ultra_cheap"]))
    exa_log: list[str] = []
    exa_token = EXA_CALL_LOG.set(exa_log)
    usage_log: list[tuple[str, int, int, int]] = []
    usage_token = TASK_USAGE_LOG.set(usage_log)
    pr_token = PR_URL_CTX.set(None)
    tier = _get_tier(record.tier)
    _log(Category.GATEWAY, "task started", task=record.prompt[:120], tier=record.tier)
    stat_inc("gateway.tasks")
    tasks_update(record.task_id, status="running", started_at=record.started_at)
    active_tier = tier
    parent_id = record.parent_task_id
    mode_override = record.mode_override
    try:
        try:
            result = await manager.run(record.prompt, clients={"default": tier.coder},
                                        orchestrator=tier.manager, parent_task_id=parent_id,
                                        mode_override=mode_override)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            if tier.fallback and is_unavailable(e):
                _log(Category.GATEWAY, "primary unavailable, falling back", error=str(e)[:120])
                active_tier = tier.fallback
                result = await manager.run(record.prompt, clients={"default": active_tier.coder},
                                            orchestrator=active_tier.manager, parent_task_id=parent_id,
                                            mode_override=mode_override)
            else:
                raise
        record.result = result
        record.pr_url = PR_URL_CTX.get()
        record.status = "done"
    except asyncio.CancelledError:
        record.status = "cancelled"
        raise
    except Exception as e:
        record.error = str(e)
        record.status = "failed"
        _log(Category.GATEWAY, "task failed", error=str(e), traceback=traceback.format_exc())
    finally:
        record.finished_at = time.time()
        LIBRARIAN_CTX.reset(lib_token)
        TIER_CTX.reset(tier_token)
        TASK_SKILLS_CTX.reset(skills_token)
        TASK_GRADERS_CTX.reset(graders_token)
        TASK_IMAGES_CTX.reset(images_token)
        TASK_CTX.reset(task_token)
        EXA_CALL_LOG.reset(exa_token)
        TASK_USAGE_LOG.reset(usage_token)
        PR_URL_CTX.reset(pr_token)
        elapsed = round(record.finished_at - (record.started_at or record.finished_at), 2)
        ts = text_stats(record.result or "")
        total_in = sum(inp for _, inp, _, _ in usage_log)
        total_out = sum(out for _, _, out, _ in usage_log)
        usd = sum(cost_usd(model, inp, out, cached) for model, inp, out, cached in usage_log) + len(exa_log) * 0.007
        _log(Category.GATEWAY, "task complete", status=record.status, elapsed_s=elapsed,
             tokens_in=total_in, tokens_out=total_out, cost=format_cost(usd), **ts)
        tasks_update(
            record.task_id,
            status=record.status,
            finished_at=record.finished_at,
            elapsed_s=elapsed,
            tokens_out=ts.get("tokens"),
            words_out=ts.get("words"),
            error=record.error,
            result=record.result,
            pr_url=record.pr_url,
        )
        # Sentinel: wake up any SSE consumers waiting on this task.
        publish(record.task_id, {"type": "done", "status": record.status,
                                  "tokens_in": total_in, "tokens_out": total_out, "cost": format_cost(usd)})


# --- Endpoints ---

_DATA_URI_RE = __import__("re").compile(r"^data:(?P<mime>image/(?:png|jpeg|jpg|webp|gif));base64,(?P<b64>.+)$")
_VALID_IMAGE_MIMES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}
_MAX_IMAGES = 8
_MAX_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB per image


def _parse_data_uri(uri: str) -> ImageContent:
    import base64 as _b64
    from core.images import shrink
    m = _DATA_URI_RE.match(uri.strip())
    if not m:
        raise ValueError(f"image must be a data URI of form 'data:image/<png|jpeg|webp|gif>;base64,...'")
    mime = m.group("mime")
    if mime == "image/jpg":  # normalize
        mime = "image/jpeg"
    try:
        data = _b64.b64decode(m.group("b64"), validate=True)
    except Exception as e:
        raise ValueError(f"invalid base64 in image: {e}")
    if len(data) > _MAX_IMAGE_BYTES:
        raise ValueError(f"image exceeds {_MAX_IMAGE_BYTES // (1024*1024)} MB")
    resized = shrink(data)
    _log(Category.GATEWAY, "image upload",
         original_px=f"{resized.original_size[0]}x{resized.original_size[1]}",
         new_px=f"{resized.new_size[0]}x{resized.new_size[1]}",
         original_kb=resized.original_bytes // 1024,
         new_kb=resized.new_bytes // 1024)
    return ImageContent(mime=resized.mime, data=resized.data)


def _valid_skill_paths() -> set[str]:
    return {s.path for s in skills.discover()}


def _valid_grader_paths() -> set[str]:
    return graders_mod.valid_paths()


def _spawn_task(
    *,
    prompt: str,
    tier: str,
    skills_paths: list[str],
    graders_paths: list[str],
    images: list[ImageContent],
    schedule_id: str | None = None,
    parent_task_id: str | None = None,
    mode_override: str | None = None,
) -> TaskRecord:
    """Create + register + start a TaskRecord. Shared by HTTP submit and scheduler fires."""
    # 8-hex-char task IDs collide at ~50% by 65k tasks. Regenerate on collision —
    # checks both the in-memory registry and the persistent DB. Bail after a
    # bounded number of attempts so a misconfigured DB can't hang the request.
    for _ in range(8):
        task_id = new_task_id()
        if get(task_id) is None and not task_id_exists(task_id):
            break
    else:
        raise HTTPException(status_code=503, detail="could not allocate a unique task id")
    record = TaskRecord(
        task_id=task_id, prompt=prompt, tier=tier,
        skills=list(skills_paths), graders=list(graders_paths), images=images,
        schedule_id=schedule_id, parent_task_id=parent_task_id,
        mode_override=mode_override,
    )
    register(record)
    tasks_insert(task_id, prompt, record.submitted_at,
                 schedule_id=schedule_id, parent_task_id=parent_task_id, tier=tier,
                 skills=list(skills_paths), graders=list(graders_paths),
                 mode_override=mode_override)
    record._task = asyncio.create_task(_run(record), name=task_id)
    return record


async def _fire_schedule(sched: scheduler_store.Schedule) -> str:
    """Scheduler callback — turns a Schedule into a running task. Returns the new task_id."""
    record = _spawn_task(
        prompt=sched.prompt, tier=sched.tier,
        skills_paths=sched.skills, graders_paths=sched.graders, images=[],
        schedule_id=sched.id,
        mode_override=sched.mode,
    )
    return record.task_id


def _validate_parent(parent_task_id: str | None) -> None:
    if parent_task_id is None:
        return
    from core.log import transcript_load
    if get(parent_task_id) is None and transcript_load(parent_task_id) is None:
        raise HTTPException(status_code=400, detail=f"parent_task_id {parent_task_id!r} not found")


@app.post("/task", response_model=TaskSubmitted, status_code=202)
async def submit_task(req: TaskRequest) -> TaskSubmitted:
    if not req.task.strip():
        raise HTTPException(status_code=400, detail="task cannot be empty")
    try:
        _get_tier(req.tier)  # validate tier name early
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    valid_paths = _valid_skill_paths()
    bad = [p for p in req.skills if p not in valid_paths]
    if bad:
        raise HTTPException(status_code=400, detail=f"unknown skill path(s): {bad}")

    valid_graders = _valid_grader_paths()
    bad_g = [p for p in req.graders if p not in valid_graders]
    if bad_g:
        raise HTTPException(status_code=400, detail=f"unknown grader path(s): {bad_g}")

    if len(req.images) > _MAX_IMAGES:
        raise HTTPException(status_code=400, detail=f"max {_MAX_IMAGES} images per task")
    try:
        images = [_parse_data_uri(u) for u in req.images]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    _validate_parent(req.parent_task_id)

    if req.mode is not None and req.mode not in _VALID_MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {sorted(_VALID_MODES)} or null")

    record = _spawn_task(
        prompt=req.task, tier=req.tier, skills_paths=list(req.skills),
        graders_paths=list(req.graders),
        images=images, parent_task_id=req.parent_task_id,
        mode_override=req.mode,
    )
    return TaskSubmitted(task_id=record.task_id)


class SkillSummary(BaseModel):
    path: str
    summary: str
    keywords: list[str]
    domain: str


@app.get("/skills", response_model=list[SkillSummary])
async def list_skills() -> list[SkillSummary]:
    """Skill catalog for UI autocomplete + suggestion. Includes keywords for fuzzy match."""
    return [
        SkillSummary(path=s.path, summary=s.summary, keywords=sorted(s.keywords), domain=s.domain)
        for s in skills.discover()
    ]


@app.get("/skills/suggest", response_model=list[SkillSummary])
async def suggest_skills(q: str) -> list[SkillSummary]:
    """UI hint endpoint — given the user's in-progress task text, return skills whose
    keywords match. UI surfaces these as 'do you want to add X?' chips."""
    return [
        SkillSummary(path=s.path, summary=s.summary, keywords=sorted(s.keywords), domain=s.domain)
        for s in skills.suggest_for(q)
    ]


class CriterionSummary(BaseModel):
    name: str
    description: str
    weight: int


class GraderSummary(BaseModel):
    path: str
    summary: str
    domain: str
    judge: str
    criteria: list[CriterionSummary]
    suggested_for_skills: list[str]


def _grader_to_summary(g: graders_mod.GraderEntry) -> GraderSummary:
    return GraderSummary(
        path=g.path, summary=g.summary, domain=g.domain,
        judge=f"{g.judge_provider.value}:{g.judge_model}",
        criteria=[CriterionSummary(name=c.name, description=c.description, weight=c.weight) for c in g.criteria],
        suggested_for_skills=sorted(g.suggested_for_skills),
    )


@app.get("/graders", response_model=list[GraderSummary])
async def list_graders() -> list[GraderSummary]:
    """Grader catalog for UI autocomplete + chip rendering."""
    return [_grader_to_summary(g) for g in graders_mod.discover()]


@app.get("/graders/suggest", response_model=list[GraderSummary])
async def suggest_graders(skills: str = "") -> list[GraderSummary]:
    """Given a comma-separated list of skill paths, return graders that declare any
    of those skills as suggested. UI calls this when the user attaches a skill chip."""
    if not skills.strip():
        return []
    skill_paths = [p.strip() for p in skills.split(",") if p.strip()]
    return [_grader_to_summary(g) for g in graders_mod.suggest_for_skills(skill_paths)]


class PresetSummary(BaseModel):
    name: str
    description: str
    tier: str
    skills: list[str]
    graders: list[str]


@app.get("/presets", response_model=list[PresetSummary])
async def list_presets() -> list[PresetSummary]:
    """Project presets — convenience bundles of (tier, skills, graders) the UI
    hydrates the composer from. User can override any field before submitting."""
    return [
        PresetSummary(
            name=p.name, description=p.description, tier=p.tier,
            skills=list(p.skills), graders=list(p.graders),
        )
        for p in presets_mod.discover()
    ]


@app.get("/tasks", response_model=list[TaskResponse])
async def list_tasks(status: TaskStatus | None = None) -> list[TaskResponse]:
    return [TaskResponse(**r.to_dict()) for r in list_all(status=status)]


class TaskHistoryItem(BaseModel):
    task_id: str
    prompt: str
    status: str
    submitted_at: float
    finished_at: float | None
    elapsed_s: float | None
    parent_task_id: str | None
    schedule_id: str | None
    result: str | None = None
    tier: str | None = None
    skills: list[str] = []
    graders: list[str] = []
    mode_override: str | None = None
    pr_url: str | None = None


@app.get("/tasks/history", response_model=list[TaskHistoryItem])
async def list_task_history(status: str = "done", limit: int = 20) -> list[TaskHistoryItem]:
    """Persisted task history from SQLite — survives gateway restarts. Used by the
    @-picker so follow-ups can reach back to conversations from prior sessions."""
    return [TaskHistoryItem(**row) for row in tasks_history(status=status or None, limit=limit)]


@app.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str) -> TaskResponse:
    record = get(task_id)
    if not record:
        raise HTTPException(status_code=404, detail="task not found")
    return TaskResponse(**record.to_dict())


@app.delete("/tasks/{task_id}", status_code=204)
async def cancel_task(task_id: str) -> None:
    record = get(task_id)
    if not record:
        raise HTTPException(status_code=404, detail="task not found")
    if record.status not in ("queued", "running"):
        raise HTTPException(status_code=409, detail=f"task is already {record.status}")
    if record._task:
        record._task.cancel()


@app.get("/tasks/{task_id}/events")
async def stream_events(task_id: str, request: Request) -> EventSourceResponse:
    record = get(task_id)
    if not record:
        raise HTTPException(status_code=404, detail="task not found")

    async def _generate() -> AsyncIterator[dict]:
        # Backfill events that already happened before the client connected (chronological).
        for event in recent(task_id=task_id, n=500):
            yield {"data": json.dumps(event)}

        # If already finished, synthesise the done sentinel so the client can close cleanly.
        if record.status not in ("running", "queued"):
            yield {"data": json.dumps({"type": "done", "status": record.status})}
            return

        q = subscribe(task_id)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=20.0)
                except asyncio.TimeoutError:
                    yield {"event": "keepalive", "data": ""}
                    continue
                if event.get("type") == "done":
                    yield {"data": json.dumps(event)}
                    return
                yield {"data": json.dumps(event)}
        finally:
            unsubscribe(task_id, q)

    return EventSourceResponse(_generate())


# --- Schedules ---

_VALID_MODES = {"conversational", "persistent"}


class ScheduleCreate(BaseModel):
    cron: str
    prompt: str
    tier: str = "ultra_cheap"
    skills: list[str] = []
    graders: list[str] = []
    enabled: bool = True
    mode: str | None = None  # null = auto-classify; "conversational" / "persistent" = force


class ScheduleUpdate(BaseModel):
    cron: str | None = None
    prompt: str | None = None
    tier: str | None = None
    skills: list[str] | None = None
    graders: list[str] | None = None
    enabled: bool | None = None
    mode: str | None = None


class ScheduleResponse(BaseModel):
    id: str
    cron: str
    prompt: str
    tier: str
    skills: list[str]
    graders: list[str]
    enabled: bool
    created_at: float
    last_run_at: float | None
    next_run_at: float | None
    mode: str | None


def _schedule_to_response(s: scheduler_store.Schedule) -> ScheduleResponse:
    try:
        nxt = scheduler_runner.next_fire_at(s) if s.enabled else None
    except Exception:
        nxt = None
    return ScheduleResponse(
        id=s.id, cron=s.cron, prompt=s.prompt, tier=s.tier,
        skills=s.skills, graders=s.graders,
        enabled=s.enabled, created_at=s.created_at, last_run_at=s.last_run_at,
        next_run_at=nxt, mode=s.mode,
    )


def _validate_schedule_inputs(*, cron: str | None, tier: str | None,
                               skills_paths: list[str] | None,
                               graders_paths: list[str] | None = None,
                               mode: str | None = None) -> None:
    if cron is not None:
        try:
            scheduler_store.validate_cron(cron)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    if tier is not None:
        try:
            _get_tier(tier)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    if skills_paths:
        valid = _valid_skill_paths()
        bad = [p for p in skills_paths if p not in valid]
        if bad:
            raise HTTPException(status_code=400, detail=f"unknown skill path(s): {bad}")
    if graders_paths:
        valid_g = _valid_grader_paths()
        bad_g = [p for p in graders_paths if p not in valid_g]
        if bad_g:
            raise HTTPException(status_code=400, detail=f"unknown grader path(s): {bad_g}")
    if mode is not None and mode not in _VALID_MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of {sorted(_VALID_MODES)} or null")


_CRON_NL_INSTRUCTIONS = (
    "Translate the user's natural-language schedule into a 5-field cron expression "
    "(minute hour day-of-month month day-of-week). Output ONLY the cron expression — "
    "no quotes, no markdown, no explanation. The scheduler interprets the cron in the "
    "user's local timezone (Europe/Stockholm), so just output their stated wall-clock "
    "time directly — no timezone conversion needed. Use the 'now' line for relative "
    "phrasing like \"in an hour\". If the description is ambiguous, pick the most likely "
    "interpretation. If you cannot translate it, output exactly: INVALID"
)


def _now_context_block() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    local = datetime.now(ZoneInfo("Europe/Stockholm"))
    return f"now (local, Europe/Stockholm): {local.strftime('%Y-%m-%d %H:%M %A')}"


class CronFromNlRequest(BaseModel):
    text: str


class CronFromNlResponse(BaseModel):
    cron: str


@app.post("/cron-from-nl", response_model=CronFromNlResponse)
async def cron_from_nl(req: CronFromNlRequest) -> CronFromNlResponse:
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="text cannot be empty")
    user_msg = f"{_now_context_block()}\n\nrequest: {req.text.strip()}"
    try:
        raw = await _helper_mini.complete(user_msg, instructions=_CRON_NL_INSTRUCTIONS)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"LLM call failed: {e}")
    cron = (raw or "").strip().strip("`").strip()
    if cron.upper() == "INVALID" or not cron:
        raise HTTPException(status_code=422, detail="could not interpret schedule")
    try:
        scheduler_store.validate_cron(cron)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"model returned {cron!r}, not valid cron: {e}")
    return CronFromNlResponse(cron=cron)


@app.get("/schedules", response_model=list[ScheduleResponse])
async def list_schedules() -> list[ScheduleResponse]:
    return [_schedule_to_response(s) for s in scheduler_store.list_all()]


@app.post("/schedules", response_model=ScheduleResponse, status_code=201)
async def create_schedule(req: ScheduleCreate) -> ScheduleResponse:
    if not req.prompt.strip():
        raise HTTPException(status_code=400, detail="prompt cannot be empty")
    _validate_schedule_inputs(cron=req.cron, tier=req.tier, skills_paths=req.skills,
                               graders_paths=req.graders, mode=req.mode)
    sched = scheduler_store.create(
        cron=req.cron, prompt=req.prompt, tier=req.tier,
        skills=req.skills, graders=req.graders,
        enabled=req.enabled, mode=req.mode,
    )
    return _schedule_to_response(sched)


@app.patch("/schedules/{sched_id}", response_model=ScheduleResponse)
async def update_schedule(sched_id: str, req: ScheduleUpdate) -> ScheduleResponse:
    if scheduler_store.get(sched_id) is None:
        raise HTTPException(status_code=404, detail="schedule not found")
    fields = req.model_dump(exclude_unset=True)
    _validate_schedule_inputs(
        cron=fields.get("cron"),
        tier=fields.get("tier"),
        skills_paths=fields.get("skills"),
        graders_paths=fields.get("graders"),
        mode=fields.get("mode"),
    )
    if "prompt" in fields and not fields["prompt"].strip():
        raise HTTPException(status_code=400, detail="prompt cannot be empty")
    sched = scheduler_store.update(sched_id, **fields)
    assert sched is not None
    return _schedule_to_response(sched)


@app.delete("/schedules/{sched_id}", status_code=204)
async def delete_schedule(sched_id: str) -> None:
    if not scheduler_store.delete(sched_id):
        raise HTTPException(status_code=404, detail="schedule not found")


@app.get("/health")
async def health() -> dict[str, str]:
    active = sum(1 for r in list_all() if r.status in ("queued", "running"))
    return {"status": "ok", "active_tasks": str(active)}


_REPO_ROOT = Path(__file__).resolve().parents[3]
_ARTIFACTS_DIR = _REPO_ROOT / "generated" / "artifacts"


class ArtifactRequest(BaseModel):
    task_id: str
    content: str
    slug: str | None = None


class ArtifactResponse(BaseModel):
    url: str
    path: str


_SLUG_RE = re.compile(r"[^a-z0-9-]+")
_TASK_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

# Inject before </head> so the standalone /artifacts/ view doesn't show a
# split background when the body has max-width / min-height / a gradient.
# Strategy:
# 1. CSS pre-paints html with var(--bg) or warm-cream fallback (no flash).
# 2. On load, copy the body's full computed background (color + image +
#    gradient + size + repeat) onto the html element so the same paint
#    extends past the body box. We skip translucent solid colors (alpha < 0.99)
#    to avoid the double-blend "two-tone" split, but always copy gradients.
_HTML_BG_FIX = (
    '<style>html{background:var(--bg,#f4f0eb);}body{margin:0;}</style>'
    '<script>addEventListener("load",function(){'
    'var s=getComputedStyle(document.body);'
    'var img=s.backgroundImage||"none";'
    'var col=s.backgroundColor||"";'
    'var h=document.documentElement.style;'
    'if(img&&img!=="none"){'
      'h.backgroundImage=img;'
      'h.backgroundSize=s.backgroundSize;'
      'h.backgroundRepeat=s.backgroundRepeat;'
      'h.backgroundPosition=s.backgroundPosition;'
      'h.backgroundAttachment="fixed";'
    '}'
    'var m=col.match(/^rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)(?:,\\s*([\\d.]+))?\\)$/);'
    'var a=m&&m[4]!==undefined?parseFloat(m[4]):1;'
    'if(m&&a>=0.99){h.backgroundColor=col;}'
    '});</script>'
)


def _inject_html_bg_fix(html: str) -> str:
    if "</head>" in html:
        return html.replace("</head>", _HTML_BG_FIX + "</head>", 1)
    if "<body" in html:  # no </head>, inject before <body>
        return html.replace("<body", _HTML_BG_FIX + "<body", 1)
    return _HTML_BG_FIX + html


@app.post("/artifacts", response_model=ArtifactResponse)
async def save_artifact(req: ArtifactRequest) -> ArtifactResponse:
    if not req.content.strip():
        raise HTTPException(status_code=400, detail="content cannot be empty")
    slug = (req.slug or "artifact").lower().strip().replace(" ", "-")
    slug = _SLUG_RE.sub("", slug)[:40] or "artifact"
    _ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    # Allow multiple artifacts per task — index by sequential number.
    n = 1
    while True:
        filename = f"{req.task_id[:8]}-{n}-{slug}.html"
        path = _ARTIFACTS_DIR / filename
        if not path.exists():
            break
        n += 1
    path.write_text(_inject_html_bg_fix(req.content), encoding="utf-8")
    _log(Category.GATEWAY, "artifact saved", filename=filename, bytes=len(req.content))
    return ArtifactResponse(url=f"/artifacts/{filename}", path=str(path.relative_to(_REPO_ROOT)))


_IMAGES_DIR = _REPO_ROOT / "generated" / "images"


def _safe_child(parent: Path, child: Path) -> Path | None:
    try:
        resolved = child.resolve(strict=True)
    except FileNotFoundError:
        return None
    parent_resolved = parent.resolve()
    if parent_resolved in resolved.parents or resolved.parent == parent_resolved:
        return resolved
    return None


@app.get("/images/{task_id}/{filename}")
async def _serve_image(task_id: str, filename: str):
    # Per-task generated images live in the running coder's worktree (registered
    # by the manager at dispatch). Fall back to REPO_ROOT for completed/cleaned-up
    # tasks. Path traversal blocked by validating against the resolved parent.
    candidates: list[Path] = []
    live = workdir_registry.get(task_id)
    if live:
        candidates.append(live / "generated" / "images" / task_id / filename)
    candidates.append(_IMAGES_DIR / task_id / filename)
    for p in candidates:
        resolved = _safe_child(p.parent, p)
        if resolved:
            return FileResponse(resolved)
    raise HTTPException(status_code=404, detail="image not found")


@app.get("/artifact-docs/{task_id}/images/{filename:path}")
async def _serve_artifact_docs_image(task_id: str, filename: str):
    """Serve committed docs images for local artifact previews.

    GitHub Pages pages correctly use `/one/images/...`, but the local gateway
    does not host the site at `/one/`. The UI rewrites only preview copies to
    this task-scoped route so docs HTML can remain deployment-correct.
    """
    if not _TASK_ID_RE.fullmatch(task_id):
        raise HTTPException(status_code=404, detail="image not found")
    rel = Path(filename)
    if rel.is_absolute() or ".." in rel.parts or not filename:
        raise HTTPException(status_code=404, detail="image not found")

    live = workdir_registry.get(task_id)
    candidates = []
    if live:
        candidates.append(live / "docs" / "images" / rel)

    for p in candidates:
        resolved = _safe_child(p.parent, p)
        if resolved:
            return FileResponse(resolved)

    git_path = f"docs/images/{filename}"
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    refs = [task_id]
    parent_id = task_parent_id(task_id)
    if parent_id and parent_id not in refs:
        refs.append(parent_id)
    for ref_task_id in refs:
        try:
            proc = subprocess.run(
                ["git", "-C", str(_REPO_ROOT), "show", f"task/{ref_task_id}:{git_path}"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            proc = None
        if proc and proc.returncode == 0:
            return Response(content=proc.stdout, media_type=media_type)

    repo_path = _REPO_ROOT / "docs" / "images" / rel
    resolved = _safe_child(repo_path.parent, repo_path)
    if resolved:
        return FileResponse(resolved)

    raise HTTPException(status_code=404, detail="image not found")


_STATIC = Path(__file__).resolve().parent / "static"
if _STATIC.is_dir():
    _ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    _IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    app.mount("/artifacts", StaticFiles(directory=str(_ARTIFACTS_DIR), html=True), name="artifacts")
    app.mount("/", StaticFiles(directory=str(_STATIC), html=True), name="ui")

    # Disable browser caching of UI files so JS/CSS edits show up on next reload
    # without needing a hard-refresh. Negligible perf cost for a local dev tool.
    @app.middleware("http")
    async def _no_cache_static(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path == "/" or path.endswith((".js", ".css", ".html")):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response
