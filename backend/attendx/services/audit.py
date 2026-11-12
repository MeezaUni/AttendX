"""Audit log and admin-editable runtime settings."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from attendx.config import RUNTIME_DEFAULTS
from attendx.models import AuditLog, Setting, User


def audit(
    db: Session,
    actor: User | None,
    action: str,
    entity: str = "",
    entity_id: Any = "",
    ip: str = "",
    **details: Any,
) -> None:
    db.add(
        AuditLog(
            actor_user_id=actor.id if actor else None,
            actor=actor.username if actor else "system",
            action=action,
            entity=entity,
            entity_id=str(entity_id),
            details=json.dumps(details, default=str),
            ip=ip[:64],
        )
    )


def get_runtime(db: Session) -> dict[str, Any]:
    values = dict(RUNTIME_DEFAULTS)
    for row in db.query(Setting).all():
        if row.key in values:
            values[row.key] = json.loads(row.value)
    return values


def validate_runtime_update(updates: dict[str, Any]) -> dict[str, Any]:
    """Type-check and range-check updates; raises ValueError with a readable message."""
    clean: dict[str, Any] = {}
    for key, val in updates.items():
        if key not in RUNTIME_DEFAULTS:
            raise ValueError(f"unknown setting {key!r}")
        default = RUNTIME_DEFAULTS[key]
        if isinstance(default, bool):
            val = bool(val)
        elif isinstance(default, int) and not isinstance(default, bool):
            val = int(val)
        elif isinstance(default, float):
            val = float(val)
        elif isinstance(default, list):
            if not (isinstance(val, list) and len(val) == len(default)):
                raise ValueError(f"{key} must be a list of {len(default)} numbers")
            val = [float(v) for v in val]
        elif isinstance(default, str):
            val = str(val)
        clean[key] = val
    merged = {**RUNTIME_DEFAULTS, **clean}
    if not -1.0 <= merged["nonmatch_threshold"] < merged["match_threshold"] <= 1.0:
        raise ValueError("need -1 <= nonmatch_threshold < match_threshold <= 1")
    if merged["eligibility"] not in ("section", "course_enrollment"):
        raise ValueError("eligibility must be 'section' or 'course_enrollment'")
    if not 1 <= int(merged["challenge_steps"]) <= 5:
        raise ValueError("challenge_steps must be between 1 and 5")
    if not 20 <= int(merged["challenge_ttl_seconds"]) <= 300:
        raise ValueError("challenge_ttl_seconds must be between 20 and 300")
    if not 2 <= int(merged["enroll_min_frames"]) <= 8:
        raise ValueError("enroll_min_frames must be between 2 and 8")
    return clean


def set_runtime(db: Session, updates: dict[str, Any]) -> None:
    for key, val in updates.items():
        row = db.get(Setting, key)
        if row is None:
            db.add(Setting(key=key, value=json.dumps(val)))
        else:
            row.value = json.dumps(val)
