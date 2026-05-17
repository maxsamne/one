> Python scripts, utilities, and small projects — output paths, conventions, and tooling.

# Python

## Agent hints
- **Output path:** see table below
- **Preferred thinking:** coding → `low`, complex logic → `medium`
- **Commonly related skills:** none

## Output path rules

| Task type | Where to write |
|-----------|---------------|
| Generated script / one-off task | `generated/scripts/<descriptive-name>.py` |
| Generated multi-file project | `generated/<project-name>/` with `main.py` entry point |
| Reusable agent tool / utility | `src/core/tools/<name>.py` — only if explicitly building core infrastructure |
| Existing app modification | `apps/<project-name>/` — only when task explicitly targets an existing app |

> **Default:** if in doubt, write to `generated/scripts/` or `generated/<project-name>/`. Never write to `src/` unless the task is explicitly about modifying the engine.

## Conventions

- Use `uv` for dependencies — never hardcode version strings
- Entry point: `if __name__ == "__main__":` block or `main()` function
- Type hints on all function signatures
- No print debugging left in committed code — use `logging`

## Running

```bash
uv run python generated/scripts/<name>.py
```

## Testing

```bash
uv run pytest generated/<project-name>/tests/
```
