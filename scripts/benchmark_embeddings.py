"""Benchmark QWEN vs GEMMA embedding models for librarian retrieval quality and latency.

Runs three configurations:
  - QWEN   native 1024 dims
  - QWEN   truncated to 768 dims  (fair comparison vs GEMMA)
  - GEMMA  native 768 dims

Tests hit rate by query category (exact / paraphrase / semantic / unrelated),
MRR, mean cosine score, and embed latency.

Usage:
    uv run python scripts/benchmark_embeddings.py
"""

import asyncio
import time

import numpy as np

from core.ai_client import EmbeddingModel, create_embedding_client

# ── Corpus: 14 simulated cached Exa search results ──────────────────────────

CORPUS = [
    {
        "id": "spain_pop",
        "query": "population of Spain 2024",
        "result": "Spain's population as of 2024 is approximately 47.4 million people according to the INE. The population has grown slightly due to immigration offsetting a low birth rate of 1.16 children per woman.",
    },
    {
        "id": "us_inflation",
        "query": "current US inflation rate CPI 2024",
        "result": "US CPI inflation for March 2024 was 3.5% year-over-year, driven by shelter (+5.7%) and energy costs. Core CPI rose 3.8%. The Federal Reserve's target is 2%; rate cuts expected late 2024.",
    },
    {
        "id": "iphone16",
        "query": "iPhone 16 features and specs",
        "result": "iPhone 16 features the Apple A18 chip, 48MP main camera with 4K 120fps, Action button, USB-C, and improved battery. Starting at $799. The Pro adds a 5x telephoto and titanium frame.",
    },
    {
        "id": "python_async",
        "query": "Python asyncio best practices 2024",
        "result": "Key asyncio best practices: use async/await consistently, avoid blocking calls in coroutines, use asyncio.gather for parallel tasks, prefer TaskGroup for structured concurrency in Python 3.11+.",
    },
    {
        "id": "swiftui_nav",
        "query": "SwiftUI NavigationStack tutorial iOS 16",
        "result": "SwiftUI NavigationStack (iOS 16+) replaces NavigationView. Use navigationDestination(for:) for type-safe routing and NavigationPath for programmatic navigation. Lazy destination loading is automatic.",
    },
    {
        "id": "revenuecat",
        "query": "RevenueCat iOS SDK setup Swift Package Manager",
        "result": "Add RevenueCat via SPM: https://github.com/RevenueCat/purchases-ios. Initialise with Purchases.configure(withAPIKey:). Use CustomerInfo to check entitlements. StoreKit 2 supported by default in SDK 4+.",
    },
    {
        "id": "openai_pricing",
        "query": "OpenAI GPT-4o API pricing per token 2024",
        "result": "GPT-4o costs $5.00 per million input tokens and $15.00 per million output tokens. GPT-4o-mini is $0.15/$0.60. Batch API gives 50% discount. Context caching reduces costs for repeated prompts.",
    },
    {
        "id": "postgres_json",
        "query": "PostgreSQL JSONB vs JSON performance difference",
        "result": "JSONB stores parsed binary data — faster queries but slightly slower writes. JSON stores raw text — faster writes, slower reads. Use JSONB for queried fields; JSON for audit logs. GIN indexes work on JSONB.",
    },
    {
        "id": "react_hooks",
        "query": "React useEffect cleanup function pattern",
        "result": "Return a cleanup function from useEffect to prevent memory leaks: useEffect(() => { const sub = subscribe(); return () => sub.unsubscribe(); }, [dep]). Cleanup runs before next effect and on unmount.",
    },
    {
        "id": "docker_compose",
        "query": "Docker Compose health check configuration",
        "result": "Define healthcheck in compose.yml: healthcheck: { test: ['CMD', 'curl', '-f', 'http://localhost/health'], interval: 30s, timeout: 10s, retries: 3 }. Use depends_on: service: condition: service_healthy.",
    },
    {
        "id": "git_rebase",
        "query": "git rebase vs merge differences when to use",
        "result": "Rebase rewrites history — cleaner linear log, good for feature branches before merging. Merge preserves history — better for shared branches. Never rebase published commits. Use merge for main, rebase for local cleanup.",
    },
    {
        "id": "tailwind_dark",
        "query": "Tailwind CSS dark mode configuration class strategy",
        "result": "Set darkMode: 'class' in tailwind.config.js. Toggle dark class on <html>. Use dark: prefix for dark variants: dark:bg-gray-900. Store preference in localStorage and apply before render to avoid flash.",
    },
    {
        "id": "anthropic_claude",
        "query": "Anthropic Claude API models and context windows",
        "result": "Claude 3.5 Sonnet: 200k context, best balance. Claude 3 Haiku: fastest/cheapest. Claude 3 Opus: most capable. All support tool use, vision, and streaming. Input: $3–$15/MTok; Output: $15–$75/MTok.",
    },
    {
        "id": "sqlite_wal",
        "query": "SQLite WAL mode benefits concurrent reads writes",
        "result": "WAL (Write-Ahead Log) mode allows concurrent reads during writes — readers don't block writers. Enable with PRAGMA journal_mode=WAL. Better for multi-reader workloads. Slight write overhead; file stays small with regular checkpointing.",
    },
]

# ── Test queries ─────────────────────────────────────────────────────────────
# (query, expected_id | None, category)
# Categories: exact, paraphrase, semantic, cross_domain, unrelated

TEST_QUERIES = [
    # ── Exact (same wording) ──────────────────────────────────────────────────
    ("population of Spain 2024",                    "spain_pop",    "exact"),
    ("Python asyncio best practices 2024",          "python_async", "exact"),
    ("PostgreSQL JSONB vs JSON performance difference", "postgres_json", "exact"),
    ("git rebase vs merge differences when to use", "git_rebase",   "exact"),

    # ── Paraphrase (different words, same meaning) ────────────────────────────
    ("how many people live in Spain today",         "spain_pop",    "paraphrase"),
    ("what is US consumer price index right now",   "us_inflation", "paraphrase"),
    ("latest Apple smartphone specifications",      "iphone16",     "paraphrase"),
    ("async Python coroutine patterns",             "python_async", "paraphrase"),
    ("SwiftUI screen routing and navigation",       "swiftui_nav",  "paraphrase"),
    ("in-app subscriptions iOS RevenueCat",         "revenuecat",   "paraphrase"),
    ("how does git rebase work vs merge",           "git_rebase",   "paraphrase"),
    ("SQLite concurrent access write ahead log",    "sqlite_wal",   "paraphrase"),

    # ── Semantic (same domain, vaguer phrasing) ───────────────────────────────
    ("Spain demographics and census data",          "spain_pop",    "semantic"),
    ("American cost of living and price levels",    "us_inflation", "semantic"),
    ("new iPhone hardware camera upgrade",          "iphone16",     "semantic"),
    ("iOS app purchase and entitlement check",      "revenuecat",   "semantic"),
    ("LLM API costs and token pricing",             "openai_pricing","semantic"),
    ("storing nested data in relational database",  "postgres_json","semantic"),
    ("React component side effects and cleanup",    "react_hooks",  "semantic"),
    ("container service dependency and readiness",  "docker_compose","semantic"),
    ("Claude Sonnet Haiku pricing context",         "anthropic_claude","semantic"),
    ("database concurrency read performance",       "sqlite_wal",   "semantic"),
    ("CSS utility dark theme toggling",             "tailwind_dark","semantic"),

    # ── Cross-domain (query overlaps two entries — correct one should rank #1) ─
    ("API token cost comparison OpenAI vs Claude",  "openai_pricing","cross_domain"),
    ("Python database concurrent writes",           "sqlite_wal",   "cross_domain"),

    # ── Unrelated (should NOT match anything above threshold) ─────────────────
    ("French cuisine sauce reduction techniques",   None,           "unrelated"),
    ("quantum computing qubit entanglement",        None,           "unrelated"),
    ("Roman history Julius Caesar Gallic Wars",     None,           "unrelated"),
    ("football offside rule explained",             None,           "unrelated"),
]

THRESHOLD   = 0.55
CATEGORIES  = ["exact", "paraphrase", "semantic", "cross_domain", "unrelated"]
CONFIGS     = [
    (EmbeddingModel.QWEN,  1024, "QWEN-1024 (native)"),
    (EmbeddingModel.QWEN,   768, "QWEN-768  (truncated)"),
    (EmbeddingModel.GEMMA,  768, "GEMMA-768 (native)"),
]


def cosine(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-10))


async def benchmark_config(model: EmbeddingModel, dims: int, label: str) -> dict:
    client = create_embedding_client(model, dimensions=dims)
    corpus_queries = [e["query"] for e in CORPUS]
    test_queries   = [q for q, _, _ in TEST_QUERIES]

    # Latency: 3 warm runs of the full corpus batch
    latencies = []
    for _ in range(3):
        t0 = time.perf_counter()
        await client.embed(*corpus_queries)
        latencies.append((time.perf_counter() - t0) * 1000)

    corpus_vecs = [np.array(v) for v in await client.embed(*corpus_queries)]
    test_vecs   = [np.array(v) for v in await client.embed(*test_queries)]

    query_results = []
    for i, (query, expected_id, category) in enumerate(TEST_QUERIES):
        scores = sorted(
            [(CORPUS[j]["id"], cosine(test_vecs[i], corpus_vecs[j])) for j in range(len(CORPUS))],
            key=lambda x: x[1], reverse=True,
        )
        top_id, top_score = scores[0]
        hit = top_score >= THRESHOLD

        if expected_id:
            correct = expected_id == top_id and hit
            rank    = next((r + 1 for r, (cid, _) in enumerate(scores) if cid == expected_id), None)
            rr      = 1 / rank if rank else 0.0
        else:
            correct = not hit
            rr      = 1.0 if not hit else 0.0

        query_results.append({
            "query":    query,
            "expected": expected_id,
            "category": category,
            "top_id":   top_id,
            "top_score":top_score,
            "hit":      hit,
            "correct":  correct,
            "rr":       rr,
        })

    return {
        "label":           label,
        "latency_mean_ms": sum(latencies) / len(latencies),
        "latency_best_ms": min(latencies),
        "query_results":   query_results,
    }


def print_results(results: list[dict]) -> None:
    print("\n" + "=" * 88)
    print("EMBEDDING BENCHMARK  —  QWEN vs GEMMA")
    print("=" * 88)

    for r in results:
        qrs = r["query_results"]
        mrr = sum(q["rr"] for q in qrs) / len(qrs)
        mean_score = sum(q["top_score"] for q in qrs if q["expected"]) / max(1, sum(1 for q in qrs if q["expected"]))

        print(f"\n{'─' * 72}")
        print(f"  {r['label']}   latency: {r['latency_mean_ms']:.0f}ms avg / {r['latency_best_ms']:.0f}ms best"
              f"   MRR: {mrr:.3f}   mean-score: {mean_score:.3f}")
        print(f"{'─' * 72}")
        print(f"  {'QUERY':<48} {'CAT':<13} {'TOP MATCH':<20} {'SCORE':<7} OK?")
        print(f"  {'─'*48} {'─'*13} {'─'*20} {'─'*7} {'─'*4}")
        for q in qrs:
            ok   = "✓" if q["correct"] else "✗"
            note = "" if (q["expected"] is None or q["expected"] == q["top_id"]) else f" (want {q['expected']})"
            print(f"  {q['query'][:48]:<48} {q['category']:<13} {q['top_id']:<20} {q['top_score']:.3f}   {ok}{note}")

    # Summary table
    print(f"\n{'=' * 88}")
    header = f"  {'CONFIG':<26} {'EXACT':>6} {'PARAPH':>7} {'SEMAN':>6} {'CROSS':>6} {'UNREL':>6}  {'MRR':>6}  {'AVG↑':>6}  {'LAT':>7}"
    print(header)
    print(f"  {'─'*26} {'─'*6} {'─'*7} {'─'*6} {'─'*6} {'─'*6}  {'─'*6}  {'─'*6}  {'─'*7}")

    for r in results:
        qrs = r["query_results"]
        by_cat: dict[str, list] = {c: [] for c in CATEGORIES}
        for q in qrs:
            by_cat[q["category"]].append(q["correct"])

        def pct(cat: str) -> str:
            items = by_cat[cat]
            return f"{sum(items)}/{len(items)}" if items else "—"

        mrr        = sum(q["rr"] for q in qrs) / len(qrs)
        mean_score = sum(q["top_score"] for q in qrs if q["expected"]) / max(1, sum(1 for q in qrs if q["expected"]))
        lat        = r["latency_mean_ms"]
        print(
            f"  {r['label']:<26} {pct('exact'):>6} {pct('paraphrase'):>7} {pct('semantic'):>6} "
            f"{pct('cross_domain'):>6} {pct('unrelated'):>6}  {mrr:>6.3f}  {mean_score:>6.3f}  {lat:>6.0f}ms"
        )
    print()


async def main() -> None:
    print(f"Corpus: {len(CORPUS)} entries   Test queries: {len(TEST_QUERIES)}")
    print("Running 3 configs...\n")

    results = []
    for model, dims, label in CONFIGS:
        print(f"  → {label}...", end=" ", flush=True)
        try:
            r = await benchmark_config(model, dims, label)
            results.append(r)
            print(f"done ({r['latency_mean_ms']:.0f}ms avg)")
        except Exception as e:
            print(f"FAILED: {e}")

    if results:
        print_results(results)


if __name__ == "__main__":
    asyncio.run(main())
