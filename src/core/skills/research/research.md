> Web research, synthesis, and knowledge filing — findings saved to knowledge/research/.

# Research

## Agent hints
- **Output path:** `knowledge/research/<topic-slug>.md`
- **Preferred thinking:** `low` (web_search handles freshness; heavy reasoning not needed)
- **Commonly related skills:** none

## Workflow

1. Use `web_search` to gather current information — multiple queries if needed
2. Synthesise into a clear, structured markdown file
3. Save to `knowledge/research/<topic-slug>.md` (use a short, descriptive slug, e.g. `swedish-politics-2026.md`)
4. `git_add` → `git_commit`

## Output format

```markdown
# <Topic Title>

_researched: YYYY-MM-DD_

## Summary
One paragraph overview.

## Key findings
- ...
- ...

## Sources
- [Title](url)
```

## Rules

- Always use `web_search` — never rely on training data for facts, figures, or current events
- Keep findings factual and sourced — no speculation
- One file per topic; append to an existing file if the topic already exists in `knowledge/research/`
