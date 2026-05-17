# Logging & stats — `core.log`

## Storage

| What | Where | Why |
|------|-------|-----|
| Events | `.agent_log.jsonl` | Append-only — no read dependency, tail-able live |
| Stats counters | `.agent_stats.db` (SQLite) | Atomic increments need read-modify-write |

Both files are gitignored. Events use a persistent line-buffered file handle + `threading.Lock` (safe for multi-thread and multi-process). Stats use a persistent SQLite connection + `threading.Lock`.

Every event carries `task_id` automatically when called inside a request — pulled from
`TASK_CTX` (set by the gateway). This is what makes concurrent tasks separable in the log.

Events also carry an `agent` field auto-injected from `AGENT_ID_CTX` (set by `coder.run`).
Top-level coder is `<task_id>:<provider>`; sub-agents are `<task_id>:sub-<id>`. The UI groups
events into per-agent rows using this field. Events with no `agent` (manager-level events
emitted before any coder starts) bucket into the `main` row in the UI.

## Usage

```python
from core.log import log, Category, stat_inc, stats, recent

# Structured event
log(Category.AGENT, "manager routed", domains=["general"], model="ultra_cheap")
log(Category.TOOL, "read_file", path="apps/scripts/hello.py", ok=True)

# Counter
stat_inc("librarian.cache_hits")
print(stats())   # {"librarian.cache_hits": 3, ...}

# Query recent events
recent(Category.TOOL, n=20)             # last 20 tool calls
recent(n=50)                            # last 50 events across all categories
recent(task_id="abc12345")              # everything that happened in one task
recent(Category.AGENT, task_id="...")   # combine filters
```

Tail events live in a terminal:
```bash
tail -f .agent_log.jsonl | python3 -m json.tool
```

## Categories

| Category | Emitted by | Key fields |
|----------|-----------|------------|
| `AGENT` | manager, coder | `task`, `model`, `provider`, `domains`, `skills`, `turns` |
| `TOOL` | ctx.py (every tool call) | `ok`, `path`/`pattern`/etc, `result` (120-char preview) |
| `LIBRARIAN` | librarian.py | `query`, `score` (hit) |
| `LEDGER` | ledger.py | `resource`, `agent` |
| `COMPACT` | compact.py | `turns`, `tokens_before`, `summary_tokens` |
| `GATEWAY` | server.py | `task`, `elapsed_s`, `chars` |

## Stat keys

| Key | Incremented when |
|-----|-----------------|
| `coder.runs` | Coder loop starts |
| `coder.done` | Coder finishes cleanly |
| `coder.timeout` | Coder hits max_turns |
| `compact.events` | Context compaction fires |
| `ledger.queued` | Lock requested |
| `ledger.acquired` | Lock granted |
| `librarian.cache_hits` | Exa search skipped (cache hit) |
| `librarian.cache_misses` | Exa search performed |
| `gateway.tasks` | Task received by gateway |

## Why not SQLite for events?

Events are append-only — nothing reads before writing. A `threading.Lock` is sufficient.
SQLite is reserved for data that requires atomic read-modify-write (stats counters, ledger state, librarian vectors).

---

# Librarian — embedding model choice

## Chosen: QWEN (`qwen3-embedding:0.6b`) at 768 dims

Benchmarked all three local models (NOMIC, QWEN, GEMMA) on 29 test queries across 4
categories (exact, paraphrase, semantic, unrelated) against a 14-entry corpus.

| Model | Hit rate | MRR | Mean score | Latency |
|-------|----------|-----|------------|---------|
| QWEN-1024 (native) | 29/29 | 1.000 | 0.807 | 309ms |
| **QWEN-768 (truncated)** | **29/29** | **1.000** | **0.815** | **282ms** |
| GEMMA-768 (native) | 24/29 | 0.966 | 0.704 | 166ms |
| NOMIC-768 | 12/15\* | — | — | — |

GEMMA's 5 misses were all semantic queries where it couldn't bridge vague phrasing to the
right concept (e.g. "iOS app purchase and entitlement check" → 0.466, below 0.55 threshold).
NOMIC failed on economic/paraphrase queries consistently.

## Why QWEN-768 over native QWEN-1024

QWEN3-embedding is MRL-trained, meaning the first N dims are always a valid standalone
representation — truncation to 768 is safe and confirmed by MTEB as the sweet spot (gains
beyond 768 are minimal). Our benchmark (0.815 vs 0.807) is consistent with this.
Smaller DB and faster queries are a free bonus.

## Hybrid scoring in `_retrieve()`

```
score = (0.7 × cosine_similarity + 0.3 × BM25_normalised) × recency_decay
```

- Cosine: semantic vector match (QWEN embeddings)
- BM25: keyword overlap via SQLite FTS5 — helps exact-term queries
- Recency decay: `0.9 ^ (months_old / 6)` — older entries score lower
- Threshold: `0.55` — below this, treat as cache miss and call Exa

To re-run the benchmark: `uv run python scripts/benchmark_embeddings.py`
