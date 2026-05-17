> Git conventions — commit messages, branch naming, and PR hygiene for all persistent tasks.

## Keywords
git, commit, branch, pr, pull request, push, version control

## Commit messages

Write commit messages at the **feature/concept level** — explain what changed and why, not which files moved.

**Good:** `Add inspiration images to skills system`
**Bad:** `Moved machines-of-loving-grace.md to xyz/inspiration/`

**Good:** `Fix SVG diagram text overflow in article`
**Bad:** `Updated silicon-sociology.html`

**Never** use the task prompt as the commit message. The prompt is what the user asked; the commit message is what you did.

Rules:
- Imperative mood, present tense: "Add", "Fix", "Remove", "Update" — not "Added" or "Adding"
- First line ≤ 72 chars, no trailing period
- If the change needs more context, add a blank line then a short body paragraph
- One logical change per commit — don't bundle unrelated edits

## Branch naming

`<type>/<short-slug>` — e.g. `fix/diagram-overflow`, `feat/writing-index`, `improve/homepage-design`

Never commit directly to `main`. Always branch, then open a PR.

## PR titles

Same rules as commit messages — feature-level, imperative, ≤ 72 chars.

## Workflow

1. `git_create_branch` with a descriptive slug
2. Make all changes
3. `git_add` → `git_commit` → `git_push`
4. `git_create_pr` with a clear title and a brief body summarising what changed and why
