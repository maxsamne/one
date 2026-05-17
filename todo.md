# Todo

## Phase 1 — Plumbing
- [ ] Install Tailscale on Mac Mini and iPhone
- [ ] FastAPI server on Mac Mini: task inbox, queue, results endpoint
- [ ] SwiftUI iOS app: text input, task list, result viewer (talks to FastAPI over Tailscale)

## Phase 2 — Orchestrator
- [x] Tool implementations: `fs.py`, `shell.py`, `git.py`
- [x] Manager agent: keyword detection, skill loading, model tier from hints
- [x] FastAPI gateway: POST /task, GET /health, AI_PROVIDER env var
- [ ] Skills auto-detection: expand keyword map as new skills are added

## Phase 3 — Specialist agents
- [ ] Coder agent: file tools + skills context
- [ ] Researcher agent: Exa + librarian
- [ ] Reviewer agent: reads diffs, flags issues
- [ ] Git agent: branch per task, commit cadence, conflict resolution

## Phase 4 — Polish
- [ ] Streaming results back to iOS app (WebSocket or SSE)
- [ ] Task history + status in iOS app
- [ ] Nicer iOS UI

## Backlog — for future Claude sessions

### Per-provider structured task results
Right now `manager._dispatch` returns a single string with provider sections labelled
`## <provider>  [<merge_status>]`. Replace with structured per-provider records so the
iOS app can render them cleanly and the gateway can expose token/time stats per provider.

- New return type from `coder.run`: `CoderResult(text, tokens, elapsed_s, tool_calls)`.
- Manager aggregates `dict[provider, CoderResult]` plus the overall merge_status map.
- Gateway `TaskResponse` becomes `{task_id, results: dict[provider, ...], merges: dict[provider, status]}`.
- Existing single-string callers (chat.py) need an updated rendering helper.

### Auto-push final branch after merge
After `worktree.merge` succeeds, optionally `git push origin task/<task_id>` so the
branch shows up on the remote without manual intervention. Gate behind a flag in
`manager.run` (default off for local dev). Push happens under the existing `git:repo`
lock so concurrent task pushes serialise.

### Persistence for in-flight tasks across restarts
Once `/tasks` endpoints land (see CLAUDE.md "Live task tracking"), persist the
`TaskRecord` registry to SQLite (`.agent_tasks.db`). On startup, mark any
`status="running"` records as `failed` with reason "server restart" — their asyncio
tasks are gone and worktrees may be stale.

### Cleanup of stale worktrees on startup
If a previous server crash left worktrees behind in `.worktrees/`, run
`git worktree prune` + remove orphaned dirs at gateway startup. Keep the `task/*`
branches so partial work isn't lost — only nuke worktree metadata.

### Concurrency cap on /task
Add `_MAX_CONCURRENT_TASKS = 4` and a queue. New tasks beyond the cap get
`status="queued"` and start when a slot frees. Avoids OOM when the iOS app
spam-submits.

### Provider enum keys instead of strings
`providers.json` is keyed by string ("ollama", "claude", etc.) but `ModelProvider` enum
already exists. Validate JSON values against the enum at load time and key the runtime
dict by enum — turns silent typos into loud errors.

### Move task_ctx out of agents/
`core/agents/task_ctx.py` is imported by `core/log.py` (lazy, to avoid circular).
Cleaner: move it to `core/task_ctx.py` (or even `core/log.py` itself). Mechanical
refactor — touches every importer.
[Update 2026-05-10: partially addressed — task_ctx + agent_ctx split done in cleanup pass `87acead`. The lazy import in log.py is still there but is now expected/documented as the split's seam.]

---

## Added 2026-05-10 (next branch after `long-running-agents` merges)

### `@<task_id>` to continue a prior conversation
Today every `POST /task` is a fresh coder loop with no memory. When a task ends with
clarifying questions (or the user has more to say), there's no way to reply. They
have to copy-paste context manually.

**UX:** user types `@f91a7b38 here are the answers...`. A chip appears: `↳ continuing
f91a7b38`. On submit, gateway resolves the prior task, prepends its prompt + result
as context, runs as a fresh coder. New card in the feed shows `↳ from f91a7b38`.

**Three options** (cheapest first):

| | A. Context injection | B. Persisted ConversationHistory | C. Long-running coder |
|---|---|---|---|
| How | Prepend prior prompt+result as text | Pickle prior task's `ConversationHistory` to disk; rehydrate in new coder | Don't end the coder loop on text — keep it idle, resume on `POST /tasks/{id}/message` |
| Memory loss | Keeps Q+A only | Full fidelity | Full fidelity |
| Workspace | New tmp/worktree | New tmp/worktree | Same workspace |
| LOC | ~30 backend, ~50 UI | ~80 backend, ~50 UI | ~200 backend, ~100 UI |

**Recommendation: A first.** Covers ~90% of "answer my clarifying questions" with minimal code. Promote to B if A turns out lossy. Skip C unless A+B both feel awkward.

**Backend sketch (option A):**
```python
# core/gateway/server.py
class TaskRequest(BaseModel):
    task: str; tier: str = "ultra_cheap"
    skills: list[str] = []; images: list[str] = []
    continue_task_id: str | None = None  # NEW

# In submit_task:
if req.continue_task_id:
    prior = get(req.continue_task_id)
    if not prior or prior.status not in ("done", "failed"):
        raise HTTPException(400, "continue_task_id must reference a completed task")
    prompt = (
        f"Previous conversation:\nUSER: {prior.prompt}\n"
        f"ASSISTANT: {prior.result or '(no answer)'}\n\n"
        f"USER: {req.task}"
    )
else:
    prompt = req.task
```

**Frontend sketch:**
- Detect `^@([0-9a-f]{8})` at the start of textarea input
- Strip from displayed text, store as `state.continueTaskId`
- Render chip: `↳ continuing <id>` with × to clear
- Optional: `@` opens a dropdown of recent task IDs (need to keep them client-side)
- Pack `continue_task_id` in POST body; reset on submit

**Edge cases:** continuing a continuation (chain context or keep last N exchanges only); attaching new skills/images to a continuation (merge with prior context); cancel chip mid-typing → restore `@<id>` to textarea.

### Chat persistence across server restarts
The in-memory `_registry: dict[str, TaskRecord]` in `core/gateway/tasks.py` is lost
on restart. Tasks disappear from the feed; `@<task_id>` references break.

**Approach:** persist task records to SQLite at submit + on every status change,
rehydrate on startup.

**Backend:**
- Verify `tasks_insert`/`tasks_update` in `core/log.py` schema is rich enough. Likely needs columns: `tier`, `skills` (json), `image_paths` (json — paths NOT base64), `result`, `pr_url`.
- On `_startup`, read all rows, populate `_registry`. Any prior `running` → mark `failed` with error "interrupted by restart".
- For uploaded images: write to `generated/uploads/<task_id>/<n>.png` at submit, persist file paths in DB. Don't bloat the DB with base64.
- Reuse the existing SQLite connection pattern from `core/log.py` (persistent connection + threading.Lock).

**UI:**
- Page-load `GET /tasks` already exists — render last ~20 chronologically into the feed.
- Re-establish SSE for any task still showing as `running` (rare post-restart since we mark them failed, but page-refresh-mid-task should reconnect cleanly).

**Schema migration:** small helper or `try/except` around `ALTER TABLE`.

**Estimate:** ~120 LOC including schema, file storage, startup rehydration, 2-3 sharp pytest tests for the round-trip.

### Sequencing
1. Ship `@<task_id>` option A first (small, isolated, immediately useful). One PR.
2. Then chat persistence (medium, foundational for many future features). One PR.
3. Option B for `@<task_id>` only if A turns out too lossy.

Each pass adds 1-2 sharp pytest tests per `tests/` conventions in `src/core/skills/general/generate-tests/SKILL.md`.

### Other smaller parking-lot items
- **`generate_image` quality param**: default is `medium` (~$0.053/image). Expose `low|medium|high` so the agent can pick `low` for drafts, `high` for hero images.
- **Multipart upload for images**: today base64-in-JSON works <1 MB. Switch to multipart/form-data if attachments grow.
- **Self-compaction tool**: agent calls `compact()` when sensing drift (today auto-fires at 75% context).
- **Inspo image budget**: `inspo2.png` is ~6.7 MB. Either compress all `inspiration/*` to <500 KB at intake, or set a per-skill budget cap with a warning at submit.

---

## Scheduled tasks (its own future branch)

Two distinct use cases, same primitive: **recurring tasks that the gateway runs without a user submission**.

### Use case A — autonomous watcher agents (proactive maintenance)

Background agents that catch upstream-API drift before it breaks anything for the user. Examples:

- **API-shape watcher** — runs nightly. Scrapes / diffs the Anthropic / OpenAI / Gemini / Ollama SDK release notes + docs pages, looks for breaking changes (e.g. Chat Completions → Responses API migration, new `quality` param on gpt-image-2, deprecated model IDs, new auth headers). When something changes, opens a draft PR proposing the code update with a clear changelog reference.
- **Test guardian** — runs `make test` on a schedule (hourly? daily?). On failure, captures the error, opens a draft issue OR a fix-attempt PR with the diagnostics. Bonus: also runs a synthetic smoke task through `POST /task` with each tier to catch routing/runtime regressions tests can't see.
- **Dependency security watcher** — `uv pip list --outdated` + scan known-CVE feed. Opens a PR bumping affected versions with the CVE ID in the body.
- **Skill drift watcher** — every skill body has a `>` summary line. Compare against the current behavior of that skill (does the artifact-design skill still produce artifacts that pass the lint hook? does morning-brief still produce well-structured outputs?). Flag drift as an issue.

These agents always submit work as **draft PRs**, never auto-merge. Human review remains the gate. They show up in `gh pr list` like any other PR.

### Use case B — user-scheduled recurring tasks

The user wires up a task to run on a schedule. Examples:
- "Morning brief, every weekday at 8am, EU markets focus"
- "Stock analysis of my watchlist, every Sunday evening"
- "Weekly recap of my GitHub commits, every Friday afternoon"

Each scheduled task is just a stored `(prompt, tier, skills, images, schedule)` tuple that the gateway runs on cron-style triggers. Result lands in the feed at the scheduled time so the user wakes up to it.

### Implementation sketch

**Storage** — `.agent.db` gets two tables (or extend the existing tasks table):
- `scheduled_tasks(id, owner ('user'|'system'), prompt, tier, skills_json, images_json, schedule, enabled, last_run_at, next_run_at, name, source_skill?)`
- For watchers: `owner='system'`, `source_skill` references the skill that defines the watcher (so watchers self-register from skill files, like `system-watchers/api-shape-watcher/SKILL.md`).

**Scheduler** — cron-style strings (`"0 8 * * 1-5"` for weekdays at 8am) interpreted by `croniter`. A FastAPI startup task spawns one scheduler coroutine that wakes every minute, queries `scheduled_tasks WHERE enabled=true AND next_run_at <= now()`, fires each through `submit_task` programmatically, updates `last_run_at` + computes `next_run_at`. Reschedules on completion.

**Endpoints**:
- `GET /scheduled` — list everything
- `POST /scheduled` — create user task: `{name, prompt, tier, skills, images, cron}`
- `DELETE /scheduled/{id}` — remove
- `POST /scheduled/{id}/run` — fire now (debug)

**UI**:
- New "Scheduled" tab/section in the gateway UI showing user tasks + their next-run times. "+" creates one with the same composer (skill chips + image attach + tier picker) plus a cron string field with a few preset toggles ("daily 8am", "weekdays", "weekly Sunday").
- Watcher agents (system-owned) shown in a separate read-only "system" panel so the user can see what's running without cluttering the personal scheduled list.

**Watcher skill format**:
- Live under `src/core/skills/system-watchers/<name>/SKILL.md`. Same SKILL.md format as user skills, plus a `## Schedule` block with a cron string.
- Discovery on startup: `skills.discover_watchers()` registers each one with the scheduler if not already in the DB. Disabled-by-default to avoid surprise PR spam — user enables explicitly.

**Persistence overlap** — depends on the chat-persistence work above. Scheduler and persisted task records share the same DB and lifecycle assumptions (rehydrate-on-startup, mark abandoned-running as failed, etc.). Probably tackle persistence FIRST so scheduler builds on a stable storage layer.

**Safety rails for watchers**:
- Hard cap: max 1 PR per watcher per 24h (avoids opening 10 PRs if a vendor changes 10 docs pages).
- All watcher-opened PRs labeled `auto:proposal` so they're easy to filter / batch-review.
- Watcher commits include the source URL of whatever change they detected ("OpenAI deprecated `gpt-4-turbo`, see https://...").

**Estimate**: ~400 LOC for the core (DB schema, scheduler loop, endpoints, UI section). Each watcher is ~50-150 LOC of its own task + skill body. Build the framework first with one trivial watcher (e.g. "test guardian — runs make test, opens issue on failure"), then add the others incrementally.

### Sequencing across this whole TODO

1. `@<task_id>` continuation (option A) — small, immediate UX win
2. Chat persistence — foundation everything else builds on
3. Scheduled tasks framework + UI for use case B (user-scheduled)
4. First watcher: test guardian
5. API-shape watcher (the most valuable one — catches the kind of breakage we already had with OpenAI Chat Completions → Responses API migration)
6. Other watchers (dependency security, skill drift) as needed

---

## LLM-based hook critics (extends `core/agents/hooks.py`)

The hook framework shipped in `2714270` is built for this — adding an LLM-based hook is the same `Hook` subclass shape as the deterministic ones, just with an `await client.complete()` inside `check()`. The infrastructure (composition, retry budget, crash isolation, per-call override) all works the same.

Use cases that deterministic regex / shell can't reach:

### `VisualCriticHook` (the highest-impact one)
- Trigger: response contains an HTML artifact.
- Action: spin up a headless browser (Playwright), load the artifact, take a 1280×viewport screenshot. Send to a vision-capable model (gpt-5.4-mini or claude-haiku-4-5) with a tight prompt: *"Does this artifact look professional? Look for: overflow / clipped text, illegible type sizes, low color contrast, broken images, awkward spacing, mixed light/dark mode, gradient artifacts. Reply with a JSON list of issues — empty list if clean."*
- Feedback: format issues as the next user message (same as deterministic hooks).
- Cost: ~$0.005-0.02 per call. Worth it for the long tail of "valid HTML but ugly" issues that lint can't catch.
- Dependency: Playwright in `pyproject.toml` (~30 MB, optional install).

### `CodeCriticHook`
- Trigger: response contains a ```python``` (or any language) code block, OR a coder turn produced edits.
- Action: send the diff + a short context blob to a strong model (Claude Opus, Gemini Pro). Prompt: *"Review this code change for: bugs the author may have missed, security issues (injection, secrets), confusing names, premature abstractions, unhandled error paths."*
- Feedback: same retry-with-issues pattern.
- Cost: ~$0.01-0.05 per call.
- Best paired with the deterministic `PythonLintHook` (ruff catches syntactic issues cheap; the critic catches semantic / design issues).

### `WritingCriticHook`
- Trigger: response is text-heavy (article, briefing, summary) above some length threshold.
- Action: send to a writing-tuned model with a prompt: *"Identify any of: vague sentences, marketing fluff ("rapidly evolving", "in today's landscape"), redundant repetition, claims without specific numbers/dates/names, conclusions that aren't supported."*
- Cheap fix-up that catches the LLM's natural drift toward generic prose.

### `FactCheckerHook`
- Trigger: response cites named entities (companies, people, dates, dollar amounts).
- Action: extract named claims via cheap structured-output call, then for each claim do one Exa search + ask the model "does this claim match what the source says?"
- Catches hallucinated rounds / wrong dates / wrong-investor citations in morning briefs.
- Cost is the heaviest of the LLM critics — only enable for high-stakes tasks (financial briefings, official communications).

### Architectural notes for LLM hooks
- Hooks should `await router.pick(...)` for their own client choice rather than hard-coding a model — same band-restricted routing as the rest of the system. Likely a new `seam="hook"` so the router prompt knows it's an internal critic call.
- Vision-capable critics share the existing multimodal pipeline — just pass the screenshot bytes as `images=[ImageContent(...)]`.
- LLM hooks should ALWAYS have `is_concurrency_safe=True` semantics so multiple critics on the same response can fan out.
- Per-tier disable: `ultra_cheap` tier should default to deterministic hooks only (no LLM critics) since LLM critics defeat the cost premise. Wire via `hooks=` per-call in manager.
- LLM hook results should be cached by `(response_hash, hook_name)` for the lifetime of the task — prevents the visual critic from running twice if the agent's lint-fixed retry produces the same artifact.

### Sequencing within this section
1. `VisualCriticHook` first — biggest UX win, model size requirements low (haiku-class), composes naturally with the existing HtmlLintHook.
2. `CodeCriticHook` — useful when we're asking the agent to write more code (currently mostly artifact HTML).
3. `WritingCriticHook` — once we've shipped a few text-heavy skills (morning brief, weekly recap, etc.).
4. `FactCheckerHook` — last; opt-in per task, not a default hook.
