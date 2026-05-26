"""Schedule CRUD against the `schedules` table in .agent.db.

Schema lives in `core.log._get_con` so the connection + WAL setup is shared.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field

from croniter import CroniterBadCronError, croniter

from core.log import _get_con, _lock


@dataclass
class Schedule:
    id: str
    cron: str
    prompt: str
    tier: str = "ultra_cheap"
    skills: list[str] = field(default_factory=list)
    graders: list[str] = field(default_factory=list)
    enabled: bool = True
    catch_up: bool = True
    created_at: float = field(default_factory=time.time)
    last_run_at: float | None = None
    # null = let manager auto-classify; "conversational" / "persistent" = force the mode.
    mode: str | None = None

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "cron":         self.cron,
            "prompt":       self.prompt,
            "tier":         self.tier,
            "skills":       list(self.skills),
            "graders":      list(self.graders),
            "enabled":      self.enabled,
            "catch_up":     self.catch_up,
            "created_at":   self.created_at,
            "last_run_at":  self.last_run_at,
            "mode":         self.mode,
        }


def _row_to_schedule(row: tuple) -> Schedule:
    return Schedule(
        id=row[0], cron=row[1], prompt=row[2], tier=row[3],
        skills=json.loads(row[4] or "[]"),
        enabled=bool(row[5]),
        catch_up=bool(row[6]) if len(row) > 6 else True,
        created_at=row[7], last_run_at=row[8],
        mode=row[9] if len(row) > 9 else None,
        graders=json.loads(row[10] or "[]") if len(row) > 10 else [],
    )


def validate_cron(expr: str) -> None:
    """Raise ValueError if the cron expression is malformed."""
    try:
        croniter(expr, time.time())
    except (CroniterBadCronError, KeyError, ValueError) as e:
        raise ValueError(f"invalid cron expression {expr!r}: {e}")


_VALID_MODES = {None, "conversational", "persistent"}


def _validate_mode(mode: str | None) -> None:
    if mode not in _VALID_MODES:
        raise ValueError(f"mode must be one of {sorted(m for m in _VALID_MODES if m)}, got {mode!r}")


_SELECT = "SELECT id, cron, prompt, tier, skills_json, enabled, catch_up, created_at, last_run_at, mode, graders_json"


def create(*, cron: str, prompt: str, tier: str = "ultra_cheap",
           skills: list[str] | None = None, graders: list[str] | None = None,
           enabled: bool = True, catch_up: bool = True, mode: str | None = None) -> Schedule:
    validate_cron(cron)
    _validate_mode(mode)
    sched = Schedule(
        id=f"sch_{uuid.uuid4().hex[:10]}",
        cron=cron, prompt=prompt, tier=tier,
        skills=list(skills or []),
        graders=list(graders or []),
        enabled=enabled,
        catch_up=catch_up,
        mode=mode,
    )
    with _lock:
        _get_con().execute(
            """INSERT INTO schedules
                   (id, cron, prompt, tier, skills_json, graders_json, enabled, catch_up, created_at, last_run_at, mode)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [sched.id, sched.cron, sched.prompt, sched.tier,
             json.dumps(sched.skills), json.dumps(sched.graders),
             int(sched.enabled), int(sched.catch_up),
             sched.created_at, sched.last_run_at, sched.mode],
        )
        _get_con().commit()
    return sched


def get(sched_id: str) -> Schedule | None:
    with _lock:
        row = _get_con().execute(
            f"{_SELECT} FROM schedules WHERE id = ?", [sched_id],
        ).fetchone()
    return _row_to_schedule(row) if row else None


def list_all() -> list[Schedule]:
    with _lock:
        rows = _get_con().execute(
            f"{_SELECT} FROM schedules ORDER BY created_at DESC",
        ).fetchall()
    return [_row_to_schedule(r) for r in rows]


def update(sched_id: str, **fields) -> Schedule | None:
    """Partial update. Recognised fields: cron, prompt, tier, skills, graders, enabled, catch_up, last_run_at, mode."""
    if not fields:
        return get(sched_id)
    if "cron" in fields:
        validate_cron(fields["cron"])
    if "mode" in fields:
        _validate_mode(fields["mode"])
    sets, params = [], []
    if "cron" in fields:        sets.append("cron = ?");         params.append(fields["cron"])
    if "prompt" in fields:      sets.append("prompt = ?");       params.append(fields["prompt"])
    if "tier" in fields:        sets.append("tier = ?");         params.append(fields["tier"])
    if "skills" in fields:      sets.append("skills_json = ?");  params.append(json.dumps(fields["skills"] or []))
    if "graders" in fields:     sets.append("graders_json = ?"); params.append(json.dumps(fields["graders"] or []))
    if "enabled" in fields:     sets.append("enabled = ?");      params.append(int(bool(fields["enabled"])))
    if "catch_up" in fields:    sets.append("catch_up = ?");     params.append(int(bool(fields["catch_up"])))
    if "last_run_at" in fields: sets.append("last_run_at = ?");  params.append(fields["last_run_at"])
    if "mode" in fields:        sets.append("mode = ?");         params.append(fields["mode"])
    if not sets:
        return get(sched_id)
    params.append(sched_id)
    with _lock:
        _get_con().execute(f"UPDATE schedules SET {', '.join(sets)} WHERE id = ?", params)
        _get_con().commit()
    return get(sched_id)


def delete(sched_id: str) -> bool:
    with _lock:
        cur = _get_con().execute("DELETE FROM schedules WHERE id = ?", [sched_id])
        _get_con().commit()
    return cur.rowcount > 0
