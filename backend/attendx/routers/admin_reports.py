"""Admin: dashboard statistics, attendance reports, CSV export, audit log and settings."""

from __future__ import annotations

import csv
import io
import json
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from attendx.db import utcnow
from attendx.deps import Auth, get_db, require_admin
from attendx.models import (
    AttendanceRecord,
    AttendanceSession,
    AuditLog,
    Course,
    FaceTemplate,
    Section,
    Student,
    VerificationAttempt,
)
from attendx.services import schedule as sch
from attendx.services.audit import audit, get_runtime, set_runtime, validate_runtime_update

router = APIRouter(prefix="/api/admin", tags=["admin-reports"])

ATTENDED = ("present", "late")


def _held(db: Session, d_from: date | None, d_to: date | None, section_id: int | None,
          course_id: int | None) -> list[AttendanceSession]:  # fmt: skip
    stmt = sch.held_sessions_query()
    if d_from:
        stmt = stmt.where(AttendanceSession.date >= d_from)
    if d_to:
        stmt = stmt.where(AttendanceSession.date <= d_to)
    if section_id:
        stmt = stmt.where(AttendanceSession.section_id == section_id)
    if course_id:
        stmt = stmt.where(AttendanceSession.course_id == course_id)
    return list(db.scalars(stmt.order_by(AttendanceSession.date, AttendanceSession.start_at)))


def compute_student_summary(
    db: Session, d_from: date | None = None, d_to: date | None = None,
    section_id: int | None = None, course_id: int | None = None, student_id: int | None = None,
) -> list[dict[str, Any]]:  # fmt: skip
    """Per student x course: held sessions, attended, excused, percentage.

    percentage = attended / (held - excused); a held session is one not cancelled whose
    attendance window has opened."""
    sessions = _held(db, d_from, d_to, section_id, course_id)
    by_section: dict[int, list[AttendanceSession]] = defaultdict(list)
    for s in sessions:
        by_section[s.section_id].append(s)
    ids = [s.id for s in sessions]
    recs: dict[tuple[int, int], str] = {}
    if ids:
        for r in db.scalars(select(AttendanceRecord).where(AttendanceRecord.session_id.in_(ids))):
            recs[(r.session_id, r.student_id)] = r.status
    stmt = select(Student).order_by(Student.roll_number)
    if section_id:
        stmt = stmt.where(Student.section_id == section_id)
    if student_id:
        stmt = stmt.where(Student.id == student_id)
    courses = {c.id: c for c in db.scalars(select(Course))}
    strict = get_runtime(db)["eligibility"] == "course_enrollment"
    out = []
    for st in db.scalars(stmt):
        enrolled = {ce.course_id for ce in st.courses}
        per_course: dict[int, dict[str, int]] = defaultdict(lambda: {"held": 0, "attended": 0, "excused": 0})
        for s in by_section.get(st.section_id or -1, []):
            if strict and s.course_id not in enrolled:
                continue
            c = per_course[s.course_id]
            c["held"] += 1
            status = recs.get((s.id, st.id))
            if status in ATTENDED:
                c["attended"] += 1
            elif status == "excused":
                c["excused"] += 1
        tot = {"held": 0, "attended": 0, "excused": 0}
        rows = []
        for cid, c in sorted(per_course.items(), key=lambda kv: courses[kv[0]].code):
            for k in tot:
                tot[k] += c[k]
            denom = c["held"] - c["excused"]
            rows.append({
                "course_id": cid, "course_code": courses[cid].code, "course_name": courses[cid].name,
                **c, "percentage": round(100 * c["attended"] / denom, 1) if denom else None,
            })  # fmt: skip
        denom = tot["held"] - tot["excused"]
        out.append({
            "student_id": st.id, "roll_number": st.roll_number, "name": st.name,
            "section": st.section.name if st.section else None, **tot,
            "percentage": round(100 * tot["attended"] / denom, 1) if denom else None,
            "courses": rows,
        })  # fmt: skip
    return out


@router.get("/dashboard")
def dashboard(request: Request, _: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    tz = request.app.state.settings_obj.tz
    today = sch.local_today(tz)
    sch.ensure_sessions_for_date(db, today, tz)
    db.commit()
    sessions = list(db.scalars(select(AttendanceSession).where(AttendanceSession.date == today)))
    statuses = defaultdict(int)
    for s in sessions:
        statuses[sch.session_status(s)] += 1
    since = utcnow() - timedelta(days=1)
    decisions = dict(
        db.execute(
            select(VerificationAttempt.decision, func.count())
            .where(VerificationAttempt.created_at >= since)
            .group_by(VerificationAttempt.decision)
        ).all()
    )
    face = dict(db.execute(select(Student.face_status, func.count()).group_by(Student.face_status)).all())
    marked_today = db.scalar(
        select(func.count()).select_from(AttendanceRecord).where(
            AttendanceRecord.date == today, AttendanceRecord.status.in_(ATTENDED)
        )
    )
    week = compute_student_summary(db, today - timedelta(days=6), today)
    pcts = [r["percentage"] for r in week if r["percentage"] is not None]
    low = sorted((r for r in week if r["percentage"] is not None and r["percentage"] < 75),
                 key=lambda r: r["percentage"])[:8]  # fmt: skip
    recent = db.execute(
        select(AttendanceRecord, Student)
        .join(Student, Student.id == AttendanceRecord.student_id)
        .order_by(AttendanceRecord.updated_at.desc())
        .limit(8)
    ).all()
    return {
        "date": today.isoformat(),
        "weekday": sch.WEEKDAYS[today.weekday()],
        "server_time": sch.local_now(tz).isoformat(),
        "timezone": request.app.state.settings_obj.timezone,
        "counts": {
            "students": db.scalar(select(func.count()).select_from(Student)),
            "sections": db.scalar(select(func.count()).select_from(Section)),
            "courses": db.scalar(select(func.count()).select_from(Course)),
            "enrolled_faces": face.get("approved", 0),
            "pending_enrollments": db.scalar(
                select(func.count()).select_from(FaceTemplate).where(FaceTemplate.status == "pending")
            ),
            "sessions_today": len(sessions),
            "open_now": statuses.get("open", 0),
            "marked_today": marked_today,
        },
        "session_statuses": dict(statuses),
        "attempts_24h": decisions,
        "week_average": round(sum(pcts) / len(pcts), 1) if pcts else None,
        "low_attendance": [
            {"student_id": r["student_id"], "roll_number": r["roll_number"], "name": r["name"],
             "percentage": r["percentage"], "held": r["held"]}
            for r in low
        ],  # fmt: skip
        "recent": [
            {"roll_number": s.roll_number, "name": s.name, "status": r.status, "method": r.method,
             "date": r.date.isoformat(), "at": (r.verified_at or r.updated_at).isoformat() + "Z"}
            for r, s in recent
        ],  # fmt: skip
        "face_engine": request.app.state.engine.status(),
    }


@router.get("/reports/students")
def report_students(d_from: date | None = None, d_to: date | None = None, section_id: int | None = None,
                    course_id: int | None = None, _: Auth = Depends(require_admin),
                    db: Session = Depends(get_db)):  # fmt: skip
    return compute_student_summary(db, d_from, d_to, section_id, course_id)


@router.get("/reports/courses")
def report_courses(d_from: date | None = None, d_to: date | None = None, section_id: int | None = None,
                   _: Auth = Depends(require_admin), db: Session = Depends(get_db)):  # fmt: skip
    sessions = _held(db, d_from, d_to, section_id, None)
    agg: dict[tuple[int, int], dict[str, Any]] = {}
    size = dict(db.execute(select(Student.section_id, func.count()).group_by(Student.section_id)).all())
    ids = [s.id for s in sessions]
    attended = defaultdict(int)
    if ids:
        for sid, n in db.execute(
            select(AttendanceRecord.session_id, func.count())
            .where(AttendanceRecord.session_id.in_(ids), AttendanceRecord.status.in_(ATTENDED))
            .group_by(AttendanceRecord.session_id)
        ).all():
            attended[sid] = n
    for s in sessions:
        key = (s.course_id, s.section_id)
        a = agg.setdefault(key, {
            "course_id": s.course_id, "course_code": s.course.code, "course_name": s.course.name,
            "section_id": s.section_id, "section": s.section.name, "sessions": 0,
            "possible": 0, "attended": 0,
        })  # fmt: skip
        a["sessions"] += 1
        a["possible"] += size.get(s.section_id, 0)
        a["attended"] += attended[s.id]
    for a in agg.values():
        a["percentage"] = round(100 * a["attended"] / a["possible"], 1) if a["possible"] else None
    return sorted(agg.values(), key=lambda a: (a["course_code"], a["section"]))


def _csv_response(rows: list[list[Any]], filename: str) -> StreamingResponse:
    buf = io.StringIO()
    w = csv.writer(buf)
    for row in rows:
        # neutralise spreadsheet formula injection
        w.writerow([("'" + v) if isinstance(v, str) and v[:1] in ("=", "+", "-", "@") else v for v in row])
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reports/export.csv")
def export_records(request: Request, d_from: date | None = None, d_to: date | None = None,
                   section_id: int | None = None, course_id: int | None = None,
                   auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):  # fmt: skip
    """One row per (held session x student of the section): present/late/excused/absent."""
    tz = request.app.state.settings_obj.tz
    sessions = _held(db, d_from, d_to, section_id, course_id)
    ids = [s.id for s in sessions]
    recs = {}
    if ids:
        recs = {(r.session_id, r.student_id): r
                for r in db.scalars(select(AttendanceRecord).where(AttendanceRecord.session_id.in_(ids)))}  # fmt: skip
    students: dict[int, list[Student]] = defaultdict(list)
    for st in db.scalars(select(Student).order_by(Student.roll_number)):
        if st.section_id:
            students[st.section_id].append(st)
    rows: list[list[Any]] = [[
        "date", "weekday", "period", "start", "course_code", "course_name", "section",
        "roll_number", "student_name", "status", "method", "verified_at_local", "match_score",
        "liveness_passed", "override_reason",
    ]]  # fmt: skip
    for s in sessions:
        for st in students.get(s.section_id, []):
            r = recs.get((s.id, st.id))
            status = r.status if r else ("absent" if sch.session_status(s) == "closed" else "not_marked")
            rows.append([
                s.date.isoformat(), sch.WEEKDAYS[s.date.weekday()], s.period_number,
                sch.utc_naive_to_local(s.start_at, tz).strftime("%H:%M"), s.course.code,
                s.course.name, s.section.name, st.roll_number, st.name, status,
                r.method if r else "",
                sch.utc_naive_to_local(r.verified_at, tz).strftime("%Y-%m-%d %H:%M:%S") if r and r.verified_at else "",
                f"{r.match_score:.3f}" if r and r.match_score is not None else "",
                "" if not r or r.liveness_passed is None else ("yes" if r.liveness_passed else "no"),
                (r.override_reason or "") if r else "",
            ])  # fmt: skip
    audit(db, auth.user, "report.export", "report", "", auth.ip, rows=len(rows) - 1)
    db.commit()
    return _csv_response(rows, f"attendx_attendance_{sch.local_today(tz).isoformat()}.csv")


@router.get("/reports/summary.csv")
def export_summary(d_from: date | None = None, d_to: date | None = None, section_id: int | None = None,
                   course_id: int | None = None, auth: Auth = Depends(require_admin),
                   db: Session = Depends(get_db)):  # fmt: skip
    data = compute_student_summary(db, d_from, d_to, section_id, course_id)
    rows: list[list[Any]] = [["roll_number", "name", "section", "course_code", "held", "attended", "excused", "percentage"]]
    for st in data:
        for c in st["courses"]:
            rows.append([st["roll_number"], st["name"], st["section"], c["course_code"], c["held"],
                         c["attended"], c["excused"], c["percentage"] if c["percentage"] is not None else ""])  # fmt: skip
        rows.append([st["roll_number"], st["name"], st["section"], "ALL", st["held"], st["attended"],
                     st["excused"], st["percentage"] if st["percentage"] is not None else ""])  # fmt: skip
    audit(db, auth.user, "report.export_summary", "report", "", auth.ip)
    db.commit()
    return _csv_response(rows, "attendx_summary.csv")


@router.get("/audit")
def audit_log(limit: int = 200, action: str = "", _: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(min(limit, 1000))
    if action:
        stmt = stmt.where(AuditLog.action.startswith(action))
    return [
        {"id": a.id, "at": a.created_at.isoformat() + "Z", "actor": a.actor, "action": a.action,
         "entity": a.entity, "entity_id": a.entity_id, "details": json.loads(a.details or "{}"),
         "ip": a.ip}
        for a in db.scalars(stmt)
    ]  # fmt: skip


@router.get("/settings")
def get_settings_(request: Request, _: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    s = request.app.state.settings_obj
    return {
        "runtime": get_runtime(db),
        "fixed": {
            "timezone": s.timezone, "face_engine": s.face_engine, "device": s.device,
            "demo_mode": s.demo_mode, "cookie_secure": s.cookie_secure,
        },  # fmt: skip
        "engine": request.app.state.engine.status(),
    }


@router.put("/settings")
def put_settings(body: dict[str, Any], auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        clean = validate_runtime_update(body)
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    before = get_runtime(db)
    set_runtime(db, clean)
    audit(db, auth.user, "settings.update", "settings", "", auth.ip,
          changes={k: [before[k], v] for k, v in clean.items() if before[k] != v})  # fmt: skip
    db.commit()
    return {"runtime": get_runtime(db)}
