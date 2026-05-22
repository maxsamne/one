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

## Branch and PR ownership

`<type>/<short-slug>` — e.g. `fix/diagram-overflow`, `feat/writing-index`, `improve/homepage-design`

Never commit directly to `main`. In normal managed task runs, the manager has already
created the task branch and will push/open/update the PR after you finish. In those
runs, do not create branches, check out branches, push, or open PRs yourself.

Only use branch/push/PR tools when they are explicitly available in your tool list
and the task asks you to manage git lifecycle yourself.

## PR titles

Same rules as commit messages — feature-level, imperative, ≤ 72 chars.

## Workflow

1. Make all changes on the current task branch
2. `git_add` → `git_commit`
3. Let the manager push and open/update the PR
