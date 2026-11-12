"""Authorized full roster export. Never export central credentials or enrollment photographs."""

import json
import secrets
import uuid
from datetime import UTC, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from attendx.db import utcnow
from attendx.deps import Auth, get_db, require_admin, require_student
from attendx.faculty.storage import canonical
from attendx.models import AttendanceSession, Course, Holiday, Period, Section, Student, TimetableEntry
from attendx.services.audit import audit, get_runtime
from attendx.services.collection_timing import COLLECTION_SECONDS, START_GRACE_SECONDS, collection_start_allowed
from attendx.services.schedule import local_today
from attendx.v2.identity import (
    PIPELINE_VERSION,
    active_batch,
    batches,
    digest,
    effective_state,
    require_faculty,
    valid_assignments,
)
from attendx.v2.models import (
    AdditionalStudent,
    ApprovedSession,
    AttendanceEvent,
    EnrollmentSample,
    FacultyDevice,
    FacultyGrant,
    SectionSemester,
    Semester,
)

router = APIRouter(prefix="/api/v2", tags=["faculty-sync"])


def roster_for(db, section_id, course_id, day):
    ids = {s.id for s in db.scalars(select(Student).where(Student.section_id == section_id))}
    ids.update(
        db.scalars(
            select(AdditionalStudent.student_id).where(
                AdditionalStudent.section_id == section_id,
                AdditionalStudent.course_id == course_id,
                AdditionalStudent.start_date <= day,
                AdditionalStudent.end_date.is_(None) | (AdditionalStudent.end_date >= day),
            )
        )
    )
    return list(db.scalars(select(Student).where(Student.id.in_(ids)).order_by(Student.roll_number)))


def snapshot(db, state, user, device_id=None):
    day = local_today(state.settings_obj.tz)
    assignments = valid_assignments(db, user.id, day, "teaching")
    classes = []
    for a in assignments:
        section, course = db.get(Section, a.section_id), db.get(Course, a.course_id)
        roster = []
        for s in roster_for(db, a.section_id, a.course_id, day):
            active = active_batch(db, s.id, day)
            history = batches(db, s.id)
            link = db.get(SectionSemester, s.section_id) if s.section_id else None
            sem = db.get(Semester, link.semester_id) if link else None
            state_name = effective_state(active or (history[0] if history else None), day)
            if active and sem and (day >= sem.renewal_deadline or active.semester_id != sem.id):
                state_name = "RE_ENROLLMENT_DUE"
                active = None  # strict default: renewal-due -> manual attendance
            refs = []
            if active and s.user and s.user.is_active and s.user.account_state == "ACTIVE":
                for sample in db.scalars(
                    select(EnrollmentSample)
                    .where(EnrollmentSample.batch_id == active.id)
                    .order_by(EnrollmentSample.slot)
                ):
                    refs.append(state.cipher.decrypt(sample.embedding_enc, active.model_id).tolist())
            if len(refs) != 3:
                refs = []
            roster.append(
                {
                    "student_id": s.id,
                    "roll_number": s.roll_number,
                    "name": s.name,
                    "enrollment_state": state_name,
                    "references": refs,
                    "version": active.version if active else None,
                    "model_id": active.model_id if active else None,
                    "pipeline_version": active.pipeline_version if active else None,
                    "expires_on": str(active.expires_on) if active else None,
                }
            )
        classes.append(
            {
                "assignment_id": a.id,
                "section_id": section.id,
                "section": section.name,
                "course_id": course.id,
                "course": course.code,
                "course_name": course.name,
                "assignment_start": str(a.start_date),
                "assignment_end": str(a.end_date) if a.end_date else None,
                "roster": roster,
            }
        )
    pairs = {(a.section_id, a.course_id) for a in assignments}
    timetable = []
    for t in db.scalars(select(TimetableEntry)):
        if (t.section_id, t.course_id) in pairs and (t.faculty_id in (None, user.faculty_id)):
            timetable.append(
                {
                    "weekday": t.weekday,
                    "period_number": t.period_number,
                    "section_id": t.section_id,
                    "course_id": t.course_id,
                    "room": t.room,
                    "is_break": t.is_break,
                    "start_time": str(t.start_time) if t.start_time else None,
                    "end_time": str(t.end_time) if t.end_time else None,
                }
            )
    now = utcnow()
    period_defaults = {p.number: p for p in db.scalars(select(Period))}
    grant = FacultyGrant(
        id=str(uuid.uuid4()),
        user_id=user.id,
        device_id=device_id,
        generated_at=now,
        expires_at=now + timedelta(hours=state.settings_obj.offline_grant_hours),
        roster_scope=json.dumps(
            [
                {
                    "section_id": c["section_id"],
                    "course_id": c["course_id"],
                    "student_ids": [r["student_id"] for r in c["roster"]],
                    "slots": [
                        {
                            **t,
                            "start_time": t["start_time"] or str(period_defaults[t["period_number"]].start_time),
                            "end_time": t["end_time"] or str(period_defaults[t["period_number"]].end_time),
                        }
                        for t in timetable
                        if t["section_id"] == c["section_id"]
                        and t["course_id"] == c["course_id"]
                        and not t["is_break"]
                        and t["period_number"] in period_defaults
                        and not period_defaults[t["period_number"]].is_break
                    ],
                }
                for c in classes
            ]
        ),
    )
    db.add(grant)
    db.commit()
    return {
        "schema_version": 2,
        "grant_id": grant.id,
        "faculty": {"user_id": user.id, "name": user.display_name},
        "generated_at": now.isoformat() + "Z",
        "offline_valid_until": grant.expires_at.isoformat() + "Z",
        "pipeline_version": PIPELINE_VERSION,
        "classes": classes,
        "timetable": timetable,
        "cancelled_classes": [
            {
                "date": str(s.date),
                "section_id": s.section_id,
                "course_id": s.course_id,
                "period_number": s.period_number,
            }
            for s in db.scalars(
                select(AttendanceSession).where(AttendanceSession.cancelled.is_(True), AttendanceSession.date >= day)
            )
            if (s.section_id, s.course_id) in pairs
        ],
        "holidays": [{"date": str(h.date), "name": h.name} for h in db.scalars(select(Holiday))],
        "periods": [
            {"number": p.number, "start_time": str(p.start_time), "end_time": str(p.end_time), "is_break": p.is_break}
            for p in db.scalars(select(Period))
        ],
        "policy": {
            **get_runtime(db),
            "timezone": state.settings_obj.timezone,
            "collection_seconds": COLLECTION_SECONDS,
            "start_grace_seconds": START_GRACE_SECONDS,
            "qr_rotation_seconds": 5,
            "manual_attendance_without_biometrics": True,
        },
    }


class DeviceIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    device_id: str | None = Field(default=None, max_length=36)


@router.post("/faculty/devices")
def register_device(body: DeviceIn, auth: Auth = Depends(require_faculty), db=Depends(get_db)):
    credential = secrets.token_urlsafe(48)
    row = db.get(FacultyDevice, body.device_id) if body.device_id else None
    if body.device_id and (row is None or row.user_id != auth.user.id):
        raise HTTPException(403, "device belongs to a different faculty profile or is unavailable")
    if row:
        row.credential_hash, row.expires_at, row.revoked = digest(credential), utcnow() + timedelta(days=30), False
    else:
        row = FacultyDevice(
            id=str(uuid.uuid4()),
            user_id=auth.user.id,
            name=body.name,
            credential_hash=digest(credential),
            expires_at=utcnow() + timedelta(days=30),
        )
        db.add(row)
    audit(db, auth.user, "v2.faculty_device_registered", "device", row.id, auth.ip)
    db.commit()
    return {"device_id": row.id, "credential": credential, "expires_at": row.expires_at.isoformat() + "Z"}


@router.delete("/faculty/devices/{device_id}")
def revoke_device(device_id: str, auth: Auth = Depends(require_faculty), db=Depends(get_db)):
    row = db.get(FacultyDevice, device_id)
    if row is None or row.user_id != auth.user.id:
        raise HTTPException(404, "device not found")
    row.revoked = True
    audit(db, auth.user, "v2.faculty_device_revoked", "device", row.id, auth.ip)
    db.commit()
    return {"ok": True}


def device_auth(request: Request, db=Depends(get_db)):
    from attendx.models import User

    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer ") or len(header) > 200:
        raise HTTPException(401, "faculty device credential required")
    device = db.scalar(select(FacultyDevice).where(FacultyDevice.credential_hash == digest(header[7:])))
    user = db.get(User, device.user_id) if device else None
    if (
        device is None
        or device.revoked
        or device.expires_at <= utcnow()
        or user is None
        or user.role != "faculty"
        or user.faculty_id is None
        or not user.is_active
        or user.account_state != "ACTIVE"
    ):
        raise HTTPException(401, "device authorization expired or revoked; sign in centrally")
    return device, user


@router.get("/sync/snapshot")
def device_snapshot(request: Request, identity=Depends(device_auth), db=Depends(get_db)):
    device, user = identity
    return snapshot(db, request.app.state, user, device.id)


def validate_event(event, db, device, user, timezone):
    from datetime import date

    from attendx.faculty.runtime import parse_stamp

    try:
        uuid.UUID(event["event_id"])
        uuid.UUID(event["session_id"])
        day = date.fromisoformat(event["date"])
        started = parse_stamp(event["started_at"])
        approved = parse_stamp(event["approved_at"])
        closed = parse_stamp(event["closed_at"])
        grant = db.get(FacultyGrant, event["grant_id"])
        approval_grant = db.get(FacultyGrant, event.get("approval_grant_id", event["grant_id"]))
        if (
            grant is None
            or grant.user_id != user.id
            or grant.device_id != device.id
            or event["faculty_user_id"] != user.id
            or not grant.generated_at <= started <= closed <= approved
            or started >= grant.expires_at
            or closed > grant.expires_at
            or approval_grant is None
            or approval_grant.user_id != user.id
            or approval_grant.device_id != device.id
            or not approval_grant.generated_at <= approved <= approval_grant.expires_at
            or approved > utcnow() + timedelta(minutes=5)
        ):
            raise ValueError("faculty grant does not authorize the event times or device")
        section, course = event["section_id"], event["course_id"]
        if db.scalar(
            select(AttendanceSession.id).where(
                AttendanceSession.section_id == section,
                AttendanceSession.course_id == course,
                AttendanceSession.date == day,
                AttendanceSession.period_number == event["period_number"],
                AttendanceSession.cancelled.is_(True),
            )
        ):
            raise ValueError("class was cancelled; administrator reconciliation required")
        assigned = any(
            a.section_id == section and a.course_id == course for a in valid_assignments(db, user.id, day, "teaching")
        )
        if not assigned:
            raise ValueError("teaching assignment revoked or unavailable; administrator reconciliation required")
        scope = next(
            (c for c in json.loads(grant.roster_scope) if c["section_id"] == section and c["course_id"] == course), None
        )
        local_started = started.replace(tzinfo=UTC).astimezone(ZoneInfo(timezone))
        if day != local_started.date():
            raise ValueError("class date does not match the authorized collection start")
        slot = next(
            (
                t
                for t in (scope or {}).get("slots", [])
                if t["weekday"] == day.weekday()
                and t["period_number"] == event["period_number"]
                and collection_start_allowed(local_started, t["start_time"], t["end_time"])
            ),
            None,
        )
        if slot is None:
            raise ValueError("period was not authorized in the collection grant timetable")
        if closed > parse_stamp(event["close_at"]) or parse_stamp(event["close_at"]) > started + timedelta(
            seconds=COLLECTION_SECONDS
        ):
            raise ValueError("collection exceeded the authorized five-minute window")
        rows = event["roster"]
        ids = [r["student_id"] for r in rows]
        current = {s.id for s in roster_for(db, section, course, day)}
        if not scope or len(ids) != len(set(ids)) or set(ids) != set(scope["student_ids"]) or set(ids) != current:
            raise ValueError("roster changed or incomplete; administrator reconciliation required")
        if not isinstance(event["revision"], int) or event["revision"] < 1 or not 1 <= event["period_number"] <= 24:
            raise ValueError("invalid event revision or period")
        if any(
            r["status"] not in ("PRESENT", "ABSENT")
            or len(r.get("reason", "").strip()) < 3
            or (r.get("review") and not r["review"]["resolved"])
            for r in rows
        ):
            raise ValueError("every student must have an explicit faculty decision and reason")
        count = sum(r["status"] == "PRESENT" for r in rows)
        if not isinstance(event["headcount"], int) or not 0 <= event["headcount"] <= 10000:
            raise ValueError("invalid physical headcount")
        if count != event["headcount"] and len(event.get("mismatch_reason", "").strip()) < 3:
            raise ValueError("headcount discrepancy requires a reason")
        if event["revision"] > 1 and len(event.get("amendment_reason", "").strip()) < 3:
            raise ValueError("amendment requires a reason")
    except (KeyError, TypeError, ValueError, AttributeError, StopIteration) as exc:
        raise HTTPException(409, str(exc) or "invalid faculty approval envelope") from exc


@router.post("/sync/events")
def ingest(event: dict, request: Request, identity=Depends(device_auth), db=Depends(get_db)):
    device, user = identity
    if len(canonical(event)) > 2_000_000:
        raise HTTPException(413, "attendance event too large")
    hashed = digest(canonical(event))
    existing = db.get(AttendanceEvent, event.get("event_id", ""))
    if existing:
        if existing.device_id != device.id or existing.content_hash != hashed:
            raise HTTPException(409, "event ID already exists with different content or device")
        return {"event_id": existing.id, "content_hash": hashed, "revision": existing.revision, "duplicate": True}
    validate_event(event, db, device, user, request.app.state.settings_obj.timezone)
    row = db.get(ApprovedSession, event["session_id"])
    if row is None:
        if event["revision"] != 1:
            raise HTTPException(409, "initial approved revision must arrive before amendments")
        row = ApprovedSession(
            id=event["session_id"],
            faculty_user_id=user.id,
            section_id=event["section_id"],
            course_id=event["course_id"],
            date=__import__("datetime").date.fromisoformat(event["date"]),
            period_number=event["period_number"],
            revision=1,
            payload_enc=request.app.state.cipher.seal(canonical(event).encode()),
        )
        db.add(row)
    else:
        if row.faculty_user_id != user.id or event["revision"] != row.revision + 1:
            raise HTTPException(409, "attendance revision conflict; preserve local record for reconciliation")
        original = json.loads(request.app.state.cipher.open(row.payload_enc))
        immutable = (
            "faculty_user_id",
            "section_id",
            "course_id",
            "date",
            "period_number",
            "started_at",
            "close_at",
            "closed_at",
            "grant_id",
        )
        if any(event.get(key) != original.get(key) for key in immutable):
            raise HTTPException(409, "amendment cannot change the approved class meeting identity or collection window")
        row.revision = event["revision"]
        row.payload_enc = request.app.state.cipher.seal(canonical(event).encode())
    try:
        db.flush()
        db.add(
            AttendanceEvent(
                id=event["event_id"],
                session_id=row.id,
                device_id=device.id,
                content_hash=hashed,
                revision=event["revision"],
                payload_enc=row.payload_enc,
            )
        )
        audit(
            db,
            user,
            "v2.attendance_approved_sync",
            "session",
            row.id,
            event_id=event["event_id"],
            revision=row.revision,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # A racing retry is acknowledged only when its exact immutable content matches.
        duplicate = db.get(AttendanceEvent, event["event_id"])
        if duplicate and duplicate.device_id == device.id and duplicate.content_hash == hashed:
            return {"event_id": duplicate.id, "content_hash": hashed, "revision": duplicate.revision, "duplicate": True}
        raise HTTPException(409, "class meeting or revision already exists; reconciliation required") from exc
    return {"event_id": event["event_id"], "content_hash": hashed, "revision": event["revision"], "duplicate": False}


@router.get("/faculty/attendance")
def faculty_attendance(request: Request, auth: Auth = Depends(require_faculty), db=Depends(get_db)):
    return [
        json.loads(request.app.state.cipher.open(s.payload_enc))
        for s in db.scalars(
            select(ApprovedSession)
            .where(ApprovedSession.faculty_user_id == auth.user.id)
            .order_by(ApprovedSession.date.desc())
        )
    ]


@router.get("/admin/attendance")
def admin_attendance(request: Request, _: Auth = Depends(require_admin), db=Depends(get_db)):
    return [
        json.loads(request.app.state.cipher.open(s.payload_enc))
        for s in db.scalars(select(ApprovedSession).order_by(ApprovedSession.date.desc()).limit(1000))
    ]


@router.get("/admin/attendance.csv")
def approved_csv(request: Request, auth: Auth = Depends(require_admin), db=Depends(get_db)):
    from attendx.routers.admin_reports import _csv_response

    rows = [
        [
            "date",
            "period",
            "section",
            "course",
            "roll_number",
            "name",
            "status",
            "method",
            "faculty_reason",
            "headcount",
            "revision",
            "approved_at",
        ]
    ]
    for session in db.scalars(select(ApprovedSession).order_by(ApprovedSession.date)):
        event = json.loads(request.app.state.cipher.open(session.payload_enc))
        for student in event["roster"]:
            rows.append(
                [
                    event["date"],
                    event["period_number"],
                    event["section"],
                    event["course"],
                    student["roll_number"],
                    student["name"],
                    student["status"],
                    student["method"],
                    student["reason"],
                    event["headcount"],
                    event["revision"],
                    event["approved_at"],
                ]
            )
    audit(db, auth.user, "v2.approved_attendance_exported", "report", "attendance", auth.ip, rows=len(rows) - 1)
    db.commit()
    return _csv_response(rows, "attendx_v2_approved_attendance.csv")


@router.get("/student/attendance")
def student_attendance(request: Request, auth: Auth = Depends(require_student), db=Depends(get_db)):
    records = []
    for session in db.scalars(select(ApprovedSession).order_by(ApprovedSession.date.desc())):
        event = json.loads(request.app.state.cipher.open(session.payload_enc))
        row = next((r for r in event["roster"] if r["student_id"] == auth.student.id), None)
        if row:
            records.append(
                {
                    "date": event["date"],
                    "course": event["course"],
                    "status": row["status"],
                    "revision": event["revision"],
                }
            )
    return records
