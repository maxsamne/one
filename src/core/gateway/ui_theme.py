from __future__ import annotations

CATEGORY_COLORS: dict[str, str] = {
    "AGENT": "#FACA36",
    "TOOL": "#FBF9CE",
    "LIBRARIAN": "#C8B8F0",
    "LEDGER": "#888880",
    "COMPACT": "#888880",
    "GATEWAY": "#90C878",
}

TIER_COLORS: dict[str, str] = {
    "ultra_cheap": "bright_green",
    "cheap": "green",
    "default": "yellow",
    "pro": "red",
}

CONSOLE_STYLES: dict[str, str] = {
    "dim": "dim",
    "metric": "cyan",
    "cost": "bold yellow",
    "ok": "bold green",
    "ok_value": "green",
    "err": "bold red",
    "err_value": "red",
    "watcher_error": "dim red",
}
