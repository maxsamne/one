# one — mono-repo

> **CRITICAL — this is a public repository.** Never commit API keys, tokens, credentials, internal company names, proprietary business logic, personal data, or anything that could identify private IP. When in doubt, don't commit it.

> **Commit messages** should be clear and technically descriptive — explain *what changed and why* at the feature/concept level, not which specific files moved or were renamed. Good: "Add inspiration images to skills system". Bad: "Moved machines-of-loving-grace.md to xyz/inspiration/".

> **Maintenance rule for assistants**: after any significant change to architecture, agents, tools, or the gateway, update this CLAUDE.md (and `src/core/CLAUDE.md` if relevant) to reflect the new state. Don't wait to be asked. Significant = new tool, new agent primitive, schema change, new dispatch path, deleted feature, instruction-prompt rewrite. Trivial fixes (typos, single-line tweaks) don't qualify.

> **Tests rule for assistants**: after building or substantially modifying any feature (new tool, new client, new dispatch path, new endpoint), run `task test` and confirm all pass before declaring the work done. If a real regression surfaces, fix it. If a test was wrong, fix the test — don't delete it without thinking. New features that introduce a *distinct failure mode* deserve a new test (see `src/core/skills/general/generate-tests/SKILL.md` for conventions — keep it sharp, no exhaustive variants).


## Layout

```
tests/         # pytest suite — sharp, no exhaustive variants. `task test` to run.
src/core/
  ai_client/   # multi-provider AI client + embeddings
  tools/       # fs, shell, git, web, calc, librarian, ctx
  agents/      # manager, coder, compact, ledger, worktree, summarize
  gateway/     # FastAPI task server
  skills/      # markdown skill files + providers.json
apps/
  ios/         # SwiftUI apps (human-authored, reviewed)
  macos/       # Mac apps (human-authored, reviewed)
knowledge/
  research/    # web research findings filed by agents
  analysis/    # data analysis outputs
  wiki/        # curated reference notes
generated/
  reports/     # dated task outputs (YYYY-MM-DD-*.md)
  scripts/     # one-off generated scripts
  apps/        # agent-built apps awaiting review → graduate to apps/ when kept
```

## Agent write scope

Agents write to:
- `knowledge/` — researched and synthesised content worth keeping
- `generated/` — raw task output; date-stamped; may be pruned or promoted
- `docs/` — GitHub Pages website; only when the task explicitly targets the site
- `src/core/` — **only** when the task explicitly modifies engine infrastructure
- `tests/` and repo config files — **only** when the task explicitly modifies repo code, tooling, or agent behavior
- `apps/` — **only** when the task explicitly targets an existing app

Agents **never** write to `src/core/` speculatively or as a side-effect of a non-engine task.
Persistent agents run in isolated git worktrees and may edit repo source when the task explicitly asks for code/config changes. The filesystem write tools still block protected runtime paths such as `.git/`, `.worktrees/`, `.venv/`, `node_modules/`, `__pycache__/`, `.agent.db`, and `.librarian.db`. Shell remains a powerful worktree-scoped tool, so use specific commands rather than broad destructive ones.

## AI client

All clients are created with a fixed model name — use `tiers.json` to configure which model each tier uses. Cloud providers require `model_name`.

```python
from core.ai_client import create_client, ModelProvider, ThinkingLevel

client = create_client(ModelProvider.CLAUDE, model_name="claude-sonnet-4-6")   # ANTHROPIC_API_KEY
client = create_client(ModelProvider.OPENAI, model_name="gpt-5.4-mini")        # OPENAI_API_KEY
client = create_client(ModelProvider.GEMINI, model_name="gemini-3.5-flash")  # GOOGLE_API_KEY
client = create_client(ModelProvider.OLLAMA)                                    # local, no key

text   = await client.complete("task")
text   = await client.complete("task", thinking=ThinkingLevel.HIGH)
result = await client.complete("task", thinking=ThinkingLevel.LOW, response_model=MyPydanticModel)
text   = await client.complete("task", web_search=WebSearch.NATIVE)            # cloud only
text   = await client.complete("task", extra_tools=[my_tool])
```

The model is fixed per client (from `tiers.json`); the only per-call dial is `thinking` (MINIMAL / LOW / MEDIUM / HIGH). Each provider honors thinking differently — Claude uses `budget_tokens`, OpenAI maps to `reasoning.effort`, Gemini sets `thinking_config`, Ollama treats any non-`None` value as `think=True`.

Local (Ollama) default: `qwen3.5:9b`. Any `ThinkingLevel` → `think=True`; `None` → `think=False` (must be explicit — Qwen3 thinks by default if omitted).

### Embeddings

```python
from core.ai_client import create_embedding_client, EmbeddingModel
embedder = create_embedding_client(EmbeddingModel.QWEN, dimensions=768)  # default
```

QWEN (`qwen3-embedding:0.6b`) at 768 dims is the benchmarked default — 29/29 hits, MRR 1.000. See `src/core/CLAUDE.md` for full benchmark and hybrid scoring details.

### Custom tools

```python
tool = Tool(name="x", description="...", parameters={...}, fn=my_fn,
            is_read_only=True, is_concurrency_safe=True)
```

Safe tools run in parallel within a turn; unsafe tools run serially. `_execute_tools`
automatically caps the returned tool-output batch before any provider feeds it
back to the model: 8k tokens per individual result and 12k tokens per parallel-call
batch, preserving head/tail content and marking truncation. Tool authors should
still prefer targeted ranges, pagination, and path-only search modes so the
model receives the most relevant slice instead of a truncated dump.

### Exa web search (as tool)

```python
from core.tools.web import make_web_search_tool
tool = make_web_search_tool()  # returns None if EXA_API_KEY not set
```

Routes through `LIBRARIAN_CTX` automatically for dedup + vector caching when set.

---

## Code style

- Comments only for non-obvious *why*. No docstrings narrating what code does.
- Enums over raw strings. Minimal diffs. No half-finished abstractions.

---

## Tools

```python
from core.tools import FS_TOOLS, SHELL_TOOLS, GIT_TOOLS
from core.tools.calc import CALC_TOOLS
from core.tools.todo import TODO_TOOL
from core.tools.web import make_web_search_tool
```

All paths relative to `WORKDIR` (ContextVar, defaults to repo root — overridden per worktree).

**FS:** `read_file`, `write_file`, `edit_file`, `grep_file`, `list_dir`, `delete_file`
  · `grep_file` accepts a file or directory (empty path = repo root), defaults to matching file paths, and supports `output_mode="content"` for line-numbered matches with 3 context lines or `output_mode="count"` for per-file counts.
**Shell:** `run_shell` — arbitrary shell commands in the workdir
**Git:** `git_status`, `git_diff`, `git_log`, `git_add`, `git_commit`, `git_push`, `git_create_branch`, `git_checkout`
**Calc:** `calculate` (safe AST math, supports `^`), `months_between` (ISO dates or `"today"`)
**Todo:** `todo_write` / `todo_read` — per-agent task tracking (keyed by `TODO_KEY` ContextVar)
**Web:** `make_web_search_tool()` — returns `Tool | None`; `None` if `EXA_API_KEY` unset
**Visual refs:** `load_website_image_refs(max_images?, from_task_id?)` — opt-in multimodal reference loader for article/site visual style matching. Scans `docs/*.html`, resolves `/one/images/foo.png` to `docs/images/foo.png` (or optionally `task/<from_task_id>`), and attaches the selected images once to the next provider iteration.
**Board:** `board_post(kind, payload, target_role?, responded_to_seq?)` — append entries to the session board (see Session Board below). `task_id` and `role` come from context.
**Sub-agents:** `spawn_subagent(description, prompt, edit_mode)` — top-level coders can delegate bounded work to fresh-context sub-agents (see Sub-agents below).

Error prefixes: `FATAL:` (don't retry) · `RETRYABLE:` (fix and retry).

Ordering enforced at runtime: `read_file` before `edit_file`; `git_add` before `git_commit`; `git_commit` before `git_push`.

---

## Skills

Two layouts supported under `src/core/skills/<domain>/`:
- **Flat:**   `<name>.md`               (e.g. `general/python.md`)
- **Folder:** `<name>/SKILL.md`         (e.g. `general/artifact-design/SKILL.md`) — folder may also contain `assets/`, `inspiration/`, etc. for templates and visual references.

Every skill has:
- A leading `> ...` summary line (one sentence) used in the always-injected skills index.
- An optional `## Keywords` section — comma- or newline-separated. NOT auto-loaded. Used by the gateway UI for fuzzy-search and "do you want to add this skill?" suggestions while the user types.

**User-attached + load-on-demand model** (pivoted 2026-05):
- Manager no longer auto-loads anything from text. Pre-loaded skills come from `TASK_SKILLS_CTX`, which the gateway populates from the request body — the user explicitly attaches skills via the UI (chips / `/skill` autocomplete).
- Coder's system prompt always contains an index of all available skills with one-line summaries (cheap, ~200 tokens).
- Coder has the `load_skill(name)` tool to fetch any skill body mid-loop when the task drifts.
- Manager keeps one cheap LLM call: mode classification (`conversational` vs `persistent`) — needed to decide tmp dir vs worktree. Falls back to a length heuristic if the orchestrator is unavailable.

**Gateway endpoints for skills:**
- `GET /skills` — full catalog with `path`, `summary`, `keywords`, `domain`. UI uses this to populate autocomplete on page load.
- `GET /skills/suggest?q=<text>` — server-side keyword match. UI calls as the user types to surface suggestion chips.
- `POST /task` accepts `skills: list[str]` (validated against discover()). Bad paths → 400.

**Notable skills:**
- `general/python.md` — Python scripts and small projects
- `general/artifact-design/SKILL.md` — interactive HTML artifacts (charts, dashboards, mini-sites). Inter font, muted pastels with one deep accent, faint gradients, one expressive serif moment. Folder layout with `assets/template.html` for boilerplate and `inspiration/*.png` for visual references that flow to the model as multimodal content.
- `general/morning-brief/SKILL.md` — topic-agnostic daily briefing; always emits an HTML artifact with one hero image, then 2–5 sections inferred from the request.
- `ios/swiftui.md`, `ios/revenue-cat.md`, `research/research.md`

**Multimodal images on skills + tasks:**
Two image sources merge into the coder's turn-0 multimodal payload:
- **Skill inspirations** — folder-format skills can carry an `inspiration/` subdirectory with `.png/.jpg/.jpeg/.webp/.gif` files. `skills.collect_images(paths)` reads those bytes into `ImageContent` objects.
- **Task uploads** — `POST /task` accepts `images: list[str]` of data URIs (`data:image/png;base64,...`). Gateway parses, validates (max 8, max 10 MB each), stores in `TASK_IMAGES_CTX`. UI does drag-drop / file-picker → base64 client-side.

Manager merges them as `user_images + skill_images` (user-uploads first — more task-specific, model attends more). Coder attaches the union to **turn 0 only** — model internalises everything once and iterates text-only via conversation history (cheap). All three cloud providers (Claude, OpenAI, Gemini) implement multimodal in their `_text_complete`. Ollama accepts the `images` param too but only vision-capable local models (qwen3-vl, llava) actually use them.

**Dynamic website visual references:**
- `load_website_image_refs` is available to coders and sub-agents but should be used only when the task asks to match an existing site/article style, create a cover image in the same visual family, or critique whether an image fits the site.
- The tool is deterministic and opt-in: it scans website HTML, resolves local committed image paths, queues the images in `PENDING_IMAGES`, and provider clients attach them once on the next internal tool-loop request.
- This keeps ordinary tasks cheap while making follow-on article/image work benefit from prior article visuals. It does not change `generate_image`; the model sees the references, then writes a better prompt or critique.

---

## Image generation

`src/core/tools/image_gen.py` exposes the `generate_image(prompt, size?)` tool to every coder and sub-agent. It returns the relative repo path of the saved PNG. Files land at `generated/images/<task_id>/<n>-<slug>.png` (gitignored).

Files are written under the *running coder's WORKDIR* (i.e. into the task's worktree),
so the model can find/move them with the same file tools (e.g. copy a hero into
`docs/images/` for a website task). The gateway resolves `/images/<task_id>/<file>`
URLs by consulting `core.agents.workdir_registry` (set by the manager at dispatch,
cleared in `finally`), falling back to `REPO_ROOT/generated/images` for completed
tasks. `generated/images/` is gitignored — long-term assets must be copied into a
tracked location.

Tier-routed via `image_gen` block in `tiers.json`:
- `ultra_cheap` → ollama `x/flux2-klein:4b` (local, free, requires `ollama pull x/flux2-klein:4b`)
- `cheap` / `default` / `pro` → openai `gpt-image-2`

Backends live in `src/core/ai_client/image_gen.py` (`GptImageClient`, `OllamaImageClient`). The factory `tiers.load_image_gen_client(tier_name)` is cached per `(provider, model)` so repeated calls reuse one HTTP client. `is_concurrency_safe=True` so a coder can fan out multiple image gens in one turn (each writes a distinct numbered file).

Sizes accepted: `1024x1024` (default), `1024x1536`, `1536x1024`, `auto`. (gpt-image-2 also accepts arbitrary /16 WxH up to 3840×2160 within 1:3–3:1 if we want to expand later.) Cost on `gpt-image-2` is quality-dependent: `low` ≈ $0.006, `medium` (default) ≈ $0.053, `high` ≈ $0.211 per 1024×1024 image. We don't expose `quality` yet — defaults to medium. Add a `quality` param to the tool when needed.

---

## Agent pattern

- **Manager** — mode classification (1 LLM call: conversational vs persistent) + deterministic trigger-based skill pre-loading + dispatch
- **DispatchRouter** — auto-runs at every delegation seam to pick `(provider, model, thinking)` (see below)
- **Coder** — agentic tool loop; can spawn sub-agents (see below); has `load_skill` tool for mid-loop pulls; runs **post-response hooks** before declaring done (see Hooks)
- **Hooks** — pluggable deterministic checks (lint, validators, critics) that gate the coder's final output. Can request a fix-up turn with feedback. See `core/agents/hooks.py`
- **Ledger** — `git:repo` lock serialises git write ops across concurrent coders/tasks
- **Board** — SQLite blackboard for cross-loop coordination (see Session Board)

Every persistent task gets a git worktree — single-provider tasks get one worktree, multi-provider tasks get one per provider running in parallel. Main repo HEAD is never touched during task execution. Conversational tasks run in a sandboxed `generated/tmp/<task_id>/` instead.

```python
from core.agents import manager
result = await manager.run(task, clients={"default": ollama, "claude": claude}, orchestrator=openai)
```

### Worktree flow (top-level)

1. `worktree.setup()` — create base branch + one `.worktrees/<task_id>-<provider>` per provider
2. Coders run (in parallel for multi-provider), each with `WORKDIR` set to its worktree path
3. `worktree.merge()` — sequential `--no-ff` merge into base branch, under `git:repo` lock
4. `worktree.cleanup()` — remove worktrees regardless of outcome

### Task identity & per-coder context

`TASK_CTX` (ContextVar) set by gateway per request. All logs, ledger holders, branches, todo files, and worktrees carry `task_id`. `asyncio.gather` copies context into child tasks automatically.

Per-coder context vars set inside `coder.run`:
- `AGENT_ID_CTX` — auto-injected as `agent` field on every log event (UI groups events into per-agent rows)
- `ROLE_CTX` — short role label, used by board entries
- `CURRENT_TURN` — turn number, written deterministically into board entries
- `SPAWN_CTX` — inherited by `spawn_subagent` (carries client, thinking, parent_workdir)
- `SUBAGENT_DEPTH` — caps nesting at 2 levels

---

## Sub-agents

Top-level coders (depth=0) get the `spawn_subagent` tool. Sub-agents inherit the parent's `client` and `thinking` from `SPAWN_CTX`. Multiple `spawn_subagent` calls in one parent turn run in parallel (`is_concurrency_safe=True`).

Three modes:

| `edit_mode` | What it gets | Use for |
|---|---|---|
| `read_only` (default) | Shares parent's `WORKDIR`, write tools stripped | Codebase research, lookups, "find all callers of X" |
| `conversational` | Fresh tmp scratch dir, no git/shell | Q&A, calculations, analysis where intermediate scratch files matter but persistence doesn't |
| `worktree` | Own git worktree branched from parent's HEAD; merges back on success | Bounded write work that runs in parallel with the parent |

Sub-agents get half the parent's max turns (15) and don't themselves get the spawn tool — keeps trees shallow and predictable for v1.

Worktree mode return string includes a `[merge: <status>]` suffix where status is `merged` | `no-op` | `dirty: <line>` | `conflict: <line>`. Merges run in the parent's workdir under the `git:repo` lock — parent is awaiting the spawn so its workdir is idle.

---

## DispatchRouter

`src/core/agents/router.py` — auto-injected hook (not a tool the model calls) that fires at every delegation seam:
- **Manager → top-level coder** (in `manager._dispatch` and `_dispatch_conversational`)
- **Coder → sub-agent** (in `tools/subagent.spawn_subagent`)

For each seam it calls a small picker model (configured under `_router` in `tiers.json`, default `gpt-5.4-nano`) which sees the task + the band's `options` menu and returns `(provider, model, thinking)`. Validated via pydantic; on invalid pick or any failure it falls back to the band's first option with `thinking=medium`.

The band-restricted menu lives per tier in `tiers.json`:
```json
"default": {
  "manager": {...}, "coder": {...},
  "options": [
    {"provider": "openai", "model": "gpt-5.4-mini",      "desc": "Fast, cheap."},
    {"provider": "claude", "model": "claude-sonnet-4-6", "desc": "Best code editing."}
  ]
}
```

Edit option descriptions freely — the router sees them verbatim. The user-selected `tier` (set by gateway via `TIER_CTX`) decides which menu the picker can choose from. The static `manager`/`coder` per tier are still loaded for fallback (when router fails) and are also what the manager itself uses for skill routing.

**Sub-agent inputs** — spawn carries `description` (parent's intent statement) + `prompt` (full task) + `edit_mode`, all of which the router sees. `parent_intent` plus `edit_mode` is usually enough signal to bias cheap (read_only lookups) vs. strong (worktree builds).

**Override**: `ROUTER_FORCE=provider:model[:thinking]` env var short-circuits the picker. Model names with colons (e.g. `qwen3.5:9b`) are handled — the parser checks if the last token is a thinking level.

**Client cache**: `tiers.get_or_create_client(provider, model)` caches `AiClient` instances per `(provider, model)` so repeated picks reuse one client.

**Per-option fallback**: each entry in a band's `options` may carry an optional `fallback: {provider, model}`. The router never sees this — `router.make_client(choice, tier=...)` reads it from `tiers.json` and wraps the chosen client in a `FallbackClient` (`src/core/ai_client/fallback_client.py`) that quietly swaps to the fallback model on 503/UNAVAILABLE. Per-call only — no memory between calls; if the primary recovers, subsequent calls hit it again. Avoids the gateway-level full-task restart for transient outages.

---

## Hooks (post-response checks)

`src/core/agents/hooks.py` — pluggable checks that fire when the coder is about to declare done. Pattern is *reflexion loop / validator-in-the-loop*: deterministic checks gate the model's output and can request a fix-up turn with structured feedback.

Each `Hook` implements `async check(ctx) -> str | None`:
- `None` → clean, hook is happy
- `str` → feedback fed back as the next turn's user input

Multiple hooks combine their feedback into one message so the agent fixes everything in one retry. A shared retry budget (`hook_retries`, default 2) prevents infinite loops.

**Built-in hooks:**
- `HtmlLintHook` (`core/agents/lint.py`) — catches markdown leaks (`[text](url)` or `**bold**` inside HTML), bare URLs in body text, etc. Cheap regex, zero LLM cost when output is clean.

**Adding a new hook:** subclass `Hook`, implement `check`, append to `DEFAULT_HOOKS`. See `tests/test_hooks.py` for the testing pattern (3 tests cover the entire layer). Future hooks could include: python lint via ruff on edited files, image alt-text presence, color-contrast WCAG check, or a heavier LLM-based visual critic that screenshot-judges artifacts.

**Per-task override:** pass `hooks=[...]` to `coder.run()` — useful for sub-agents that don't need lint, or to inject task-specific custom checks.

---

## Agent Loop Primitives

`src/core/agents/loop.py` defines a small reusable loop for internal sub-workflows that need model turns, a fixed tool set, token-aware compaction, and optional structured-result parsing. It is deliberately not a replacement for `coder.run()`: the coder loop keeps its task-specific responsibilities, including write tools, hooks, board updates, todo state, images, transcript persistence, and managed git conventions. Use the lightweight loop for grader-like inspectors, reviewers, verifiers, and other bounded sub-workflows.

---

## Graders (LLM-as-judge hooks)

`src/core/agents/grader.py` defines `GraderHook` — a stateful LLM-as-judge hook that scores each criterion 0–`MAX_SCORE` (currently 5) and returns actionable feedback until every criterion hits the top score or the shared `hook_retries` budget runs out. Plateau detection (identical scores to prior round) appends a "try a fundamentally different approach" nudge.

**Registry (`src/core/agents/graders.py`)** — graders live as markdown files at `src/core/graders/<domain>/<name>.md`, mirroring how skills are organised. Each file has YAML-ish frontmatter (`judge: provider:model`, `suggested_for_skills: [...]`) and a markdown body with a `> summary` line and `### <name> (weight: N)` blocks under `## Criteria`. Discovery is cached.

**Judge default lives in `tiers.json._grader_judge`** — single source of truth, mirrors the `_router` pattern. Bump the flash model name there once and every grader without an explicit `judge:` override inherits. `core.ai_client.tiers.load_grader_judge_config()` reads it; `core.agents.graders.instantiate(path)` resolves and caches the judge client.

**Attachment** — graders attach per-task. `POST /task` accepts `graders: list[str]` (validated). Gateway sets `TASK_GRADERS_CTX`; manager calls `graders.instantiate(path)` per attached grader and prepends them to `DEFAULT_HOOKS` on `coder.run`, bumping `hook_retries` to `max(GRADER_HOOK_RETRIES, DEFAULT_HOOK_RETRIES)`. Universal linters keep firing alongside.

**Universal `user_satisfaction` baseline** — every `GraderHook` automatically prepends a baked-in `user_satisfaction` criterion (defined in `grader.py`) to whatever criteria the grader file declares. The hook also always (a) injects the original user prompt from `TASK_CTX.prompt` into the judge call and (b) passes `TASK_IMAGES_CTX` to `judge.complete(images=...)`. One judge call per grader covers both the grader's own criteria and the baseline — catches the failure mode where the output follows the skill rules perfectly but ignores what the user literally asked for or the references they attached. If a grader file declares its own `user_satisfaction` criterion, the baseline is skipped (no double-add). Trivial tasks pay nothing — only fires when the user attached a grader. `TaskContext` carries the original prompt for this purpose; gateway sets it alongside `task_id`.

**Changed-file context** — before calling the judge, `GraderHook` adds deterministic task-output context when available. Persistent tasks get a capped git diff from the task's starting HEAD through committed and dirty tracked changes; conversational tasks fall back to capped contents of files touched through write/edit tools. This lets graders inspect what actually changed without asking coders to paste or recreate full HTML/files just for evaluation.

**Read-only grader inspection loop** — capped diff context stays as the cheap/default evidence path. When that context is truncated, omits touched files, spans many files, or points at criteria that need file-level inspection, `GraderHook` first runs `core/agents/grader_inspector.py`. The inspector is an evidence gatherer, not a judge: it runs on the lightweight loop primitive, gets only read-only file/git tools plus `changed_files` and bounded read-only sub-agents, uses coder-style auto-compaction with inspection-specific summary instructions, and returns structured JSON evidence. The final judge prompt receives that evidence under "Read-only grader inspection evidence" and remains responsible for scoring.

**Suggestions** — `GET /graders/suggest?skills=path1,path2` returns graders whose `suggested_for_skills` overlaps the given skills. UI surfaces them as "add grader?" chips when the user attaches a skill.

**Gateway endpoints:** `GET /graders` (catalog), `GET /graders/suggest?skills=…`, plus the `graders` field on `POST /task` and on schedule create/update.

---

## Project presets

`src/core/presets/<name>.json` — convenience bundles of `{tier, skills, graders}` that the UI hydrates the composer from. There is no runtime concept of "the task ran under preset X"; presets exist only at composition time. The user can override every field before submitting.

`core.presets.discover()` walks the directory (cached). `GET /presets` returns the catalog. UI shows pills in a `preset-row` above the tier row; clicking one swaps tier + clears and refills the skill and grader chip rows.

**Shipped presets:** `article-writer` (default tier + `article-writer` skill + `article-voice` grader). Add new presets by dropping a JSON file; no code changes needed.

---

## Session Board

`src/core/agents/board.py` — SQLite-backed blackboard keyed by `task_id`. Every entry has `seq, role, kind, target_role?, responded_to_seq?, payload, turn, ts`.

Three kinds:
- `progress` — "I just did X." Most entries.
- `request` — "I need X from another role." Paired with `target_role`.
- `response` — "Here's what you asked for." Paired with `target_role` + `responded_to_seq`.

Coders read other roles' entries each turn (`board.read_since(task_id, role, last_seq)`) and post via the `board_post` tool. For single-loop tasks the injection stays empty (read_since excludes the caller's own writes). The schema is live and tested but underutilized today — sub-agents don't yet use it for cross-talk.

---

## Loop planner

`src/core/agents/planner.py` — orchestrator decides 1-N parallel coder loops per task with `role + scope` each. Hard cap of 5 loops, validated via pydantic with one retry on cap violation. Currently **logged-only** — doesn't change dispatch behavior. The current architecture pivoted to sub-agent delegation rather than upfront multi-loop dispatch (see commit log for rationale).

---

## HTML artifacts

The gateway renders any `​```html​` block in a coder's response as a sandboxed iframe + persisted file with an "open ↗" link. Pipeline:

1. Coder emits a complete self-contained HTML document inside a ```html``` block.
2. UI replaces the code block with `<iframe sandbox="allow-scripts allow-popups allow-forms" srcdoc="...">`.
3. UI POSTs the HTML to `/artifacts`, which writes to `generated/artifacts/<task_prefix>-<n>-<slug>.html` and serves it under `/artifacts/<filename>` for opening in a separate tab.

Sandbox CSP: only `cdnjs.cloudflare.com` allowed for scripts. `localStorage` blocked. The `general/interactives.md` skill encodes design + sandbox guidance for the model.

Conversational + persistent instructions both nudge the coder to emit a final ```html``` block when output is a chart, dashboard, or visualization. Vega-Lite was removed in favor of HTML-only.

---

## Gateway UI

Per-task card has a `.trace` element that renders **per-agent rows of progress squares**:
- Manager events (no `AGENT_ID_CTX`) and the top-level coder share the `main` row
- Each sub-agent gets its own `sub-<id>` row, indented and padded-left so its first cube sits under the parent's spawn cube
- Cells pulse on the latest event globally
- Hover pins the desc bar to that cell; leaving snaps back to the latest

**Composer (input area)**:
- **Tier row** at the top — click to switch, or type `/cheap` / `/default` / `/pro` / `/ultra_cheap` inline.
- **Suggest bar** above the input — debounced (250 ms) GET `/skills/suggest?q=<text>` populates "add skill?" chips while you type. Click to attach. Skills already attached are filtered out.
- **Chips row** — attached skills as pills (`+ skill` button opens the dropdown).
- **Thumbnails row** (only visible when images attached) — drag-drop, paste, or file-picker images. × to remove.
- **Skill autocomplete dropdown** — opened by `+` button or by typing `/skill`/`/skills` (or `/<query>` where `<query>` is not a tier name). Arrow keys navigate, Enter selects, Esc closes. Selecting strips the `/` token from the textarea.
- **Drag-drop**: dragging files over the input panel shows a dashed overlay; drop attaches as base64 data URIs.
- **Paste handler**: clipboard images attach automatically.

Submission packs `{task, tier, skills: [...], graders: [...], images: ["data:image/...;base64,..."]}` to `POST /task`. Validation errors (unknown skill / grader path, malformed URI, >8 images) surface via alert.

UI files (`*.js`, `*.css`, `*.html`) are served with `Cache-Control: no-cache` so edits show up on a normal reload.

---

## Gateway API

`POST /task` → `{task_id, status: "queued"}` (202, non-blocking). State in-memory.
Body: `{task, tier, skills?, images?, parent_task_id?}`. `parent_task_id` is the `@task_id` follow-up
hook — the new task's coder seeds its loop from the parent's persisted transcript.

- `GET /tasks[?status=]` · `GET /tasks/{id}` · `DELETE /tasks/{id}` · `GET /tasks/{id}/events` (SSE)
- `GET /schedules` · `POST /schedules` · `PATCH /schedules/{id}` · `DELETE /schedules/{id}`

---

## Scheduled tasks (cron)

In-process scheduler started by the gateway lifespan. State lives in `.agent.db`'s `schedules`
table. `core.scheduler.runner` ticks every 30 s, computes `next_fire_at` for each enabled
schedule via `croniter`, and fires anything `<= now` exactly once (sets `last_run_at = now`,
collapsing missed windows into a single catch-up). Fires call into the same `_spawn_task`
path as `POST /task`, with `schedule_id` set on the resulting `TaskRecord` for join-back.

Schedule fields: `id, cron, prompt, tier, skills[], enabled, mode, created_at, last_run_at`.
`mode` (`null | "conversational" | "persistent"`) bypasses manager classification when set.
Cron strings are validated via `croniter` at create/update time — bad expressions → 400.
`POST /cron-from-nl` translates plain English ("every weekday at 9am") via `gpt-5.4-mini`,
interpreted in `Europe/Stockholm` (no timezone conversion).
UI: topbar `schedules` button opens a modal with list + create/edit form. Each row has
edit/pause/delete; edit loads the schedule into the form and PATCHes on submit.

No catch-up across gateway restarts beyond the single-fire collapse; no distributed
scheduling. `next_run_at` is computed on read for display only.

---

## Task continuation (`@task_id` follow-ups)

After every coder turn, the conversation history snapshot is persisted to `.agent.db`'s
`transcripts` table (`task_id PK, payload JSON`). When a new task is submitted with
`parent_task_id`, `manager.run` loads that snapshot and passes it as `prior_history` to
`coder.run`, which calls `ConversationHistory.load(snapshot)` to seed the loop. The
existing 75 % auto-compaction in `compact.py` keeps token cost bounded as threads grow.

**Same-worktree follow-ups.** `manager._dispatch` checks for the parent's base branch
(`task/<parent_task_id>`). If it still exists locally, the follow-up's worktree forks
from it — so the model can reference the parent's pre-merge file state even before
that work has been merged. If the parent branch was reaped, the follow-up forks from
the current default branch.

UI: composer's `@` button picks from completed tasks; selection becomes a `↩ <id>` chip.
Submission packs `parent_task_id` alongside `task / tier / skills / images`. Unknown
parent → 400.

---

## Logging & stats

→ `src/core/CLAUDE.md` for full reference.

```python
from core.log import recent, Category
recent(task_id="abc12345")               # all events for one task
recent(Category.TOOL, task_id="...")     # combine filters
```
