# Repository Agent Instructions

- Do not push directly to `main`.
- For code, docs, or website changes, create a `codex/...` branch, push that branch, and open a pull request into `main`.
- If the user says "commit and push", interpret that as committing on the current feature branch and pushing that branch, not pushing `main`.
- Standard PR flow:
  - `git checkout -b codex/<short-task-name>` from an up-to-date `main` or `origin/main`.
  - Commit the scoped changes on that branch.
  - `git push -u origin codex/<short-task-name>`.
  - Open the PR with `gh pr create --base main --head codex/<short-task-name> --title "<title>" --body "<summary and tests>"`.
- If work was accidentally committed on `main`, create a `codex/...` branch at those commits before changing `main`, and ask before any history rewrite.
