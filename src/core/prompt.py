"""Prompt helpers — date/time and location context injection."""

import os
import time
from datetime import datetime

import httpx

_location_cache: tuple[str, float] | None = None  # (location_str, fetched_at)
_CACHE_TTL_OK = 86_400   # 24 h on success
_CACHE_TTL_FAIL = 300    # 5 min on failure — don't lock out a transient outage


# Provider list, tried in order. Each tuple: (url, fn(json) -> "city, country" or "").
# ipwho.is goes first because it gave a more accurate answer for Telia-routed Swedish IPs
# (correctly identifies Stockholm where free.freeipapi.com returned Roma/Gotland).
_GEO_PROVIDERS: list[tuple[str, "callable"]] = [
    ("https://ipwho.is/", lambda d: ", ".join(filter(None, [d.get("city", ""), d.get("country", "")]))),
    ("https://free.freeipapi.com/api/json", lambda d: ", ".join(filter(None, [d.get("cityName", ""), d.get("countryName", "")]))),
]


def _fetch_location() -> str:
    """Resolve the user's location.

    Priority:
    1. `LOCATION` env var — exact override, e.g. "Stockholm, Sweden". Bypasses cache.
       Use when geo-IP routes through the wrong city (common with mobile/ISP edge).
    2. Cached geo-IP result (24 h on success, 5 min on failure).
    3. Live geo-IP lookup. Tries each provider in `_GEO_PROVIDERS` until one returns a
       non-empty location string.
    """
    override = os.environ.get("LOCATION", "").strip()
    if override:
        return override

    global _location_cache
    now = time.monotonic()
    if _location_cache:
        result, fetched_at = _location_cache
        ttl = _CACHE_TTL_OK if result else _CACHE_TTL_FAIL
        if now - fetched_at < ttl:
            return result

    result = ""
    for url, parse in _GEO_PROVIDERS:
        try:
            r = httpx.get(url, timeout=3.0)
            r.raise_for_status()
            result = parse(r.json()).strip(", ").strip()
            if result:
                break
        except Exception:
            continue
    _location_cache = (result, now)
    return result


def date_context() -> str:
    now = datetime.now()
    d = now.day
    suffix = "th" if 11 <= d <= 13 else {1: "st", 2: "nd", 3: "rd"}.get(d % 10, "th")
    time_str = now.strftime("%I:%M %p").lstrip("0")
    date_str = f"{now.strftime('%A')}, {now.strftime('%B')} {d}{suffix} {now.year}"
    location = _fetch_location()
    location_str = f" The user is located in {location}." if location else ""
    return (
        "Additional context that may be relevant:\n"
        f"Today is {date_str}. The time is currently {time_str}.{location_str}"
    )
