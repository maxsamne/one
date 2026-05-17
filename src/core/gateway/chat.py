"""Interactive chat — submit tasks, stream live events, show cost.

Usage:
    task chat

Controls:
    @ultra_cheap / @cheap / @default / @pro  — set spend tier for next task
    Ctrl+C  — exit
"""

import asyncio
import json
import threading
import time
from dataclasses import dataclass, field

import httpx
from rich.console import Console
from rich.text import Text

from core.gateway.ui_theme import CATEGORY_COLORS, CONSOLE_STYLES, TIER_COLORS

_BASE = "http://localhost:5500"
_DEFAULT_TIER = "ultra_cheap"
_TASK_TIMEOUT = 79200.0  # 22 hours

console = Console(highlight=False)

_CAT_STYLE: dict[str, str] = CATEGORY_COLORS
_TIER_STYLE: dict[str, str] = TIER_COLORS
_TIERS = set(_TIER_STYLE)


# ── session cost tracker ───────────────────────────────────────────────────────
@dataclass
class SessionStats:
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    tasks: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, tokens_in: int, tokens_out: int, cost_str: str) -> None:
        usd = _parse_cost(cost_str)
        with self._lock:
            self.tokens_in += tokens_in
            self.tokens_out += tokens_out
            self.cost += usd
            self.tasks += 1

    def status_line(self) -> Text:
        t = Text()
        t.append("  session ", style=CONSOLE_STYLES["dim"])
        t.append(f"{self.tasks} task{'s' if self.tasks != 1 else ''}", style="bold")
        t.append("  ·  in ", style=CONSOLE_STYLES["dim"])
        t.append(f"{self.tokens_in:,}", style=CONSOLE_STYLES["metric"])
        t.append("  out ", style=CONSOLE_STYLES["dim"])
        t.append(f"{self.tokens_out:,}", style=CONSOLE_STYLES["metric"])
        t.append("  ·  cost ", style=CONSOLE_STYLES["dim"])
        t.append(_fmt_cost(self.cost), style=CONSOLE_STYLES["cost"])
        return t


_stats = SessionStats()


def _parse_cost(s: str) -> float:
    s = s.strip().lstrip("$").replace("<", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


def _fmt_cost(usd: float) -> str:
    if usd == 0.0:
        return "$0.00"
    if usd < 0.0001:
        return "<$0.0001"
    if usd < 0.01:
        return f"${usd:.4f}"
    return f"${usd:.3f}"


# ── event rendering ────────────────────────────────────────────────────────────
def _render_event(event: dict, task_id: str) -> None:
    """Print a single SSE event from the server in colour."""
    etype = event.get("type")
    cat = event.get("category", "")
    msg = event.get("message", "")
    data = {k: v for k, v in event.items()
            if k not in ("type", "category", "message", "ts", "task_id", "level")}

    if etype == "done":
        tokens_in  = event.get("tokens_in", 0)
        tokens_out = event.get("tokens_out", 0)
        cost_str   = event.get("cost", "$0.00")
        _stats.add(tokens_in, tokens_out, cost_str)
        return  # final result printed separately by _watch

    if not cat or not msg:
        return

    style = _CAT_STYLE.get(cat, "white")
    tid = task_id[:8]

    line = Text()
    line.append(f"  [{tid}] ", style="dim")
    line.append(f"{cat:<10}", style=style + " bold")
    line.append(f"  {msg}", style=style)
    if data:
        extras = "  ".join(
            f"{k}={str(v)[:60]}" for k, v in data.items()
            if k not in ("traceback",) and v is not None
        )
        if extras:
            line.append(f"  {extras}", style="dim")
    console.print(line)


# ── SSE watcher ────────────────────────────────────────────────────────────────
async def _watch(task_id: str, tier: str) -> None:
    deadline = time.monotonic() + _TASK_TIMEOUT
    async with httpx.AsyncClient() as client:
        try:
            async with client.stream(
                "GET", f"{_BASE}/tasks/{task_id}/events",
                timeout=httpx.Timeout(None, connect=5.0),
                headers={"Accept": "text/event-stream"},
            ) as resp:
                buffer = ""
                async for chunk in resp.aiter_text():
                    if time.monotonic() > deadline:
                        break
                    buffer += chunk
                    while "\n\n" in buffer:
                        block, buffer = buffer.split("\n\n", 1)
                        data_lines = [
                            ln[5:] for ln in block.splitlines()
                            if ln.startswith("data:")
                        ]
                        if not data_lines:
                            continue
                        raw = "".join(data_lines).strip()
                        if not raw:
                            continue
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue

                        _render_event(event, task_id)

                        if event.get("type") == "done":
                            status = event.get("status", "done")
                            # Fetch final result
                            try:
                                r = await client.get(f"{_BASE}/tasks/{task_id}", timeout=10.0)
                                rec = r.json()
                                result = rec.get("result") or ""
                                elapsed = rec.get("elapsed_s", "?")
                                error = rec.get("error")
                            except Exception:
                                result, elapsed, error = "", "?", None

                            console.print()
                            if status == "done":
                                console.print(
                                    Text.assemble(
                                        (f"  [{task_id[:8]}] ", CONSOLE_STYLES["dim"]),
                                        ("✓ ", CONSOLE_STYLES["ok"]),
                                        (f"{elapsed}s", CONSOLE_STYLES["ok_value"]),
                                        ("  ·  ", CONSOLE_STYLES["dim"]),
                                        (_stats.status_line()),
                                    )
                                )
                                if result:
                                    console.print(f"\n{result}\n", style="bold white")
                            else:
                                console.print(
                                    Text.assemble(
                                        (f"  [{task_id[:8]}] ", CONSOLE_STYLES["dim"]),
                                        ("✗ ", CONSOLE_STYLES["err"]),
                                        (error or status, CONSOLE_STYLES["err_value"]),
                                    )
                                )
                            console.print(f"\n> ", end="")
                            return
        except Exception as e:
            console.print(f"\n  [watcher error] {e}\n> ", style=CONSOLE_STYLES["watcher_error"], end="")


# ── input helpers ──────────────────────────────────────────────────────────────
def _parse_tier(text: str) -> tuple[str | None, str]:
    """Extract /tier prefix from input. Returns (tier_or_None, cleaned_text)."""
    if not text.startswith("/"):
        return None, text
    parts = text.split(None, 1)
    candidate = parts[0][1:].lower()
    rest = parts[1] if len(parts) > 1 else ""
    if candidate in _TIERS:
        return candidate, rest
    return None, text


def _submit(task: str, tier: str) -> str:
    with httpx.Client() as client:
        resp = client.post(
            f"{_BASE}/task",
            json={"task": task, "tier": tier},
            timeout=10.0,
        )
        resp.raise_for_status()
        return resp.json()["task_id"]


# ── main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    loop = asyncio.new_event_loop()

    def _run_loop() -> None:
        asyncio.set_event_loop(loop)
        loop.run_forever()

    threading.Thread(target=_run_loop, daemon=True).start()

    tier = _DEFAULT_TIER
    tier_style = _TIER_STYLE.get(tier, "white")

    console.print("\n[bold]one[/bold] — submit tasks freely, results print as they finish.", style="dim")
    console.print(f"  tier: [bold {tier_style}]{tier}[/]  (prefix with @tier to change)", style="dim")
    console.print("  Ctrl+C to exit\n", style="dim")

    try:
        while True:
            try:
                raw = input("> ").strip()
            except EOFError:
                break
            if not raw:
                continue

            new_tier, task = _parse_tier(raw)
            if new_tier:
                tier = new_tier
                tier_style = _TIER_STYLE.get(tier, "white")
                if not task.strip():
                    console.print(f"  tier set to [bold {tier_style}]{tier}[/]", style=CONSOLE_STYLES["dim"])
                    continue

            if not task.strip():
                continue

            try:
                task_id = _submit(task, tier)
            except Exception as e:
                console.print(f"  [red]submit failed:[/] {e}")
                continue

            console.print(
                Text.assemble(
                    (f"  [{task_id[:8]}] ", CONSOLE_STYLES["dim"]),
                    ("queued", "bold"),
                    (f"  [{tier}]", f" {tier_style}"),
                )
            )

            future = asyncio.run_coroutine_threadsafe(_watch(task_id, tier), loop)
            future.add_done_callback(
                lambda f: console.print(f"  [watcher error] {f.exception()}\n> ", style=CONSOLE_STYLES["watcher_error"], end="")
                if f.exception() else None
            )

    except KeyboardInterrupt:
        pass

    console.print("\n[dim]bye[/]")

    async def _shutdown() -> None:
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        loop.stop()

    try:
        asyncio.run_coroutine_threadsafe(_shutdown(), loop).result(timeout=5.0)
    except Exception:
        pass


if __name__ == "__main__":
    main()
