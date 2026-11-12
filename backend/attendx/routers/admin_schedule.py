"""Admin: bell schedule, timetable, holidays, timetable import, sessions, live roster and
manual attendance corrections."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from attendx.db import utcnow
from attendx.deps import Auth, get_db, require_admin, runtime
from attendx.models import (
    AttendanceRecord,
    AttendanceSession,
    Course,
    Faculty,
    Holiday,
    Period,
    Section,
    Student,
    TimetableEntry,
    VerificationAttempt,
)
from attendx.services import schedule as sch
from attendx.services.audit import audit
from attendx.services.timetable_import import ImportError_, preview_upload

router = APIRouter(prefix="/api/admin", tags=["admin-schedule"])

HM = r"^([01]\d|2[0-3]):[0-5]\d$"


def hm(t: time | None) -> str | None:
    return t.strftime("%H:%M") if t else None


def _404(what: str):  # type: ignore[no-untyped-def]
    raise HTTPException(404, f"{what} not found")


# ------------------------------------------------------------------ periods (bell schedule)


class PeriodIn(BaseModel):
    number: int = Field(ge=1, le=16)
    label: str = Field(default="", max_length=32)
    start_time: str = Field(pattern=HM)
    end_time: str = Field(pattern=HM)
    attendance_open: str | None = Field(default=None, pattern=HM, deprecated=True)
    attendance_close: str | None = Field(default=None, pattern=HM, deprecated=True)
    is_break: bool = False


def period_out(p: Period) -> dict:
    return {
        "id": p.id, "number": p.number, "label": p.label, "start_time": hm(p.start_time),
        "end_time": hm(p.end_time), "attendance_open": hm(p.attendance_open),
        "attendance_close": hm(p.attendance_close), "is_break": p.is_break,
    }  # fmt: skip


def _check_window(start: time, end: time, opn: time, cls: time) -> None:
    if not start < end:
        raise HTTPException(400, "class end must be after class start")
    if not opn < cls:
        raise HTTPException(400, "attendance must close after it opens")
    if opn < (datetime.combine(date.today(), start) - timedelta(minutes=30)).time() or cls > end:
        raise HTTPException(
            400, "attendance window must lie within the class (opening up to 30 min early)"
        )


@router.get("/periods")
def list_periods(_: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    return [period_out(p) for p in db.scalars(select(Period).order_by(Period.number))]


@router.put("/periods")
def replace_periods(body: list[PeriodIn], auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    """Replace the whole bell schedule (validated as a unit)."""
    numbers = [p.number for p in body]
    if len(set(numbers)) != len(numbers):
        raise HTTPException(400, "period numbers must be unique")
    parsed = []
    for p in body:
        st, en = sch.parse_hm(p.start_time), sch.parse_hm(p.end_time)
        op, cl = sch.parse_hm(p.attendance_open or p.start_time), sch.parse_hm(p.attendance_close or p.end_time)
        _check_window(st, en, op, cl)
        parsed.append((p, st, en, op, cl))
    existing = {p.number: p for p in db.scalars(select(Period))}
    for num, p in existing.items():
        if num not in numbers:
            db.delete(p)
    for p, st, en, op, cl in parsed:
        row = existing.get(p.number) or Period(number=p.number)
        row.label = p.label or f"Period {p.number}"
        row.start_time, row.end_time, row.attendance_open, row.attendance_close = st, en, op, cl
        row.is_break = p.is_break
        db.add(row)
    audit(db, auth.user, "periods.replace", "periods", "", auth.ip, periods=[p.model_dump() for p in body])
    db.commit()
    return list_periods(auth, db)


# ------------------------------------------------------------------ timetable entries


class EntryIn(BaseModel):
    weekday: int = Field(ge=0, le=6)
    period_number: int = Field(ge=1, le=16)
    section_id: int
    course_id: int | None = None
    faculty_id: int | None = None
    room: str = Field(default="", max_length=32)
    is_break: bool = False
    start_time: str | None = Field(default=None, pattern=HM)
    end_time: str | None = Field(default=None, pattern=HM)
    attendance_open: str | None = Field(default=None, pattern=HM)
    attendance_close: str | None = Field(default=None, pattern=HM)


def entry_out(e: TimetableEntry) -> dict:
    return {
        "id": e.id, "weekday": e.weekday, "weekday_name": sch.WEEKDAYS[e.weekday],
        "period_number": e.period_number, "section_id": e.section_id,
        "section": e.section.name if e.section else None, "course_id": e.course_id,
        "course_code": e.course.code if e.course else None,
        "course_name": e.course.name if e.course else None,
        "faculty_id": e.faculty_id, "faculty": e.faculty.name if e.faculty else None,
        "room": e.room, "is_break": e.is_break, "start_time": hm(e.start_time),
        "end_time": hm(e.end_time), "attendance_open": hm(e.attendance_open),
        "attendance_close": hm(e.attendance_close),
    }  # fmt: skip


def _apply_entry(db: Session, e: TimetableEntry, body: EntryIn) -> None:
    db.get(Section, body.section_id) or _404("section")
    if body.course_id is not None:
        db.get(Course, body.course_id) or _404("course")
    if body.faculty_id is not None:
        db.get(Faculty, body.faculty_id) or _404("faculty")
    if not body.is_break and body.course_id is None:
        raise HTTPException(400, "a teaching slot needs a course (or mark it as a break)")
    e.weekday, e.period_number, e.section_id = body.weekday, body.period_number, body.section_id
    e.course_id = None if body.is_break else body.course_id
    e.faculty_id, e.room, e.is_break = body.faculty_id, body.room, body.is_break
    for key in ("start_time", "end_time", "attendance_open", "attendance_close"):
        v = getattr(body, key)
        setattr(e, key, sch.parse_hm(v) if v else None)
    period = db.scalar(select(Period).where(Period.number == body.period_number))
    # A custom class interval without legacy attendance overrides must not inherit
    # a different period's old fixed window. V2 collection is faculty-started.
    if (body.start_time or body.end_time) and not (body.attendance_open or body.attendance_close):
        e.attendance_open = e.start_time or (period.start_time if period else None)
        e.attendance_close = e.end_time or (period.end_time if period else None)
    times = sch.slot_times(e, period)
    if times is None:
        raise HTTPException(400, "period has no default times; give start and end times")
    _check_window(times.start, times.end, times.open, times.close)


@router.get("/timetable")
def list_timetable(section_id: int | None = None, _: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    stmt = select(TimetableEntry).order_by(TimetableEntry.weekday, TimetableEntry.period_number)
    if section_id:
        stmt = stmt.where(TimetableEntry.section_id == section_id)
    return [entry_out(e) for e in db.scalars(stmt)]


@router.post("/timetable")
def create_entry(body: EntryIn, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    e = TimetableEntry()
    _apply_entry(db, e, body)
    db.add(e)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "this section already has a class in that slot") from exc
    audit(db, auth.user, "timetable.create", "timetable", e.id, auth.ip, **body.model_dump())
    db.commit()
    return entry_out(e)


@router.put("/timetable/{eid}")
def update_entry(eid: int, body: EntryIn, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    e = db.get(TimetableEntry, eid) or _404("timetable entry")
    _apply_entry(db, e, body)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "this section already has a class in that slot") from exc
    audit(db, auth.user, "timetable.update", "timetable", eid, auth.ip, **body.model_dump())
    db.commit()
    return entry_out(e)


@router.delete("/timetable/{eid}")
def delete_entry(eid: int, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    e = db.get(TimetableEntry, eid) or _404("timetable entry")
    db.delete(e)
    audit(db, auth.user, "timetable.delete", "timetable", eid, auth.ip)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ holidays


class HolidayIn(BaseModel):
    date: date
    name: str = Field(min_length=1, max_length=128)


@router.get("/holidays")
def list_holidays(_: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    return [
        {"id": h.id, "date": h.date.isoformat(), "name": h.name}
        for h in db.scalars(select(Holiday).order_by(Holiday.date))
    ]


@router.post("/holidays")
def create_holiday(body: HolidayIn, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    h = Holiday(date=body.date, name=body.name)
    db.add(h)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "a holiday already exists on that date") from exc
    # cancel sessions already generated for that day
    n = 0
    for s in db.scalars(select(AttendanceSession).where(AttendanceSession.date == body.date)):
        s.cancelled = True
        s.note = f"Holiday: {body.name}"
        n += 1
    audit(db, auth.user, "holiday.create", "holiday", h.id, auth.ip, date=str(body.date), cancelled_sessions=n)
    db.commit()
    return {"id": h.id, "date": h.date.isoformat(), "name": h.name, "cancelled_sessions": n}


@router.delete("/holidays/{hid}")
def delete_holiday(hid: int, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    h = db.get(Holiday, hid) or _404("holiday")
    db.delete(h)
    audit(db, auth.user, "holiday.delete", "holiday", hid, auth.ip, date=str(h.date))
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ timetable import


@router.post("/timetable/import/preview")
def import_preview(request: Request, file: UploadFile = File(...), auth: Auth = Depends(require_admin)):
    max_bytes = request.app.state.settings_obj.max_upload_bytes
    data = file.file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise HTTPException(413, "file too large (10 MB max)")
    name = (file.filename or "upload").rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    try:
        preview = preview_upload(name, data)
    except ImportError_ as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:  # malformed files from third-party parsers
        raise HTTPException(422, f"could not read the file: {type(exc).__name__}") from exc
    return preview.to_dict()


class ImportRowIn(BaseModel):
    weekday: int | None = Field(default=None, ge=0, le=6)
    period: int | None = Field(default=None, ge=1, le=16)
    start: str | None = Field(default=None, pattern=HM)
    end: str | None = Field(default=None, pattern=HM)
    course_code: str | None = Field(default=None, max_length=32)
    course_name: str | None = Field(default=None, max_length=128)
    section: str | None = Field(default=None, max_length=64)
    faculty: str | None = Field(default=None, max_length=128)
    room: str | None = Field(default=None, max_length=32)
    is_break: bool = False

    @field_validator("start", "end", "course_code", "course_name", "section", "faculty", "room", mode="before")
    @classmethod
    def blank_none(cls, v):  # type: ignore[no-untyped-def]
        return None if isinstance(v, str) and not v.strip() else v


class ImportCommitIn(BaseModel):
    rows: list[ImportRowIn] = Field(max_length=400)
    default_section_id: int | None = None
    replace_sections: bool = False


@router.post("/timetable/import/commit")
def import_commit(body: ImportCommitIn, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    """Save reviewed rows. Every row must be complete; nothing is guessed here."""
    errors: list[str] = []
    default_section = db.get(Section, body.default_section_id) if body.default_section_id else None
    periods = {p.number: p for p in db.scalars(select(Period))}
    plan = []
    for k, r in enumerate(body.rows, start=1):
        if r.weekday is None or r.period is None:
            errors.append(f"row {k}: weekday and period are required")
            continue
        section = (
            db.scalar(select(Section).where(Section.name == r.section.strip())) if r.section else default_section
        )
        if section is None:
            errors.append(f"row {k}: section '{r.section or ''}' not found (create it first or choose a default)")
            continue
        if not r.is_break and not r.course_code:
            errors.append(f"row {k}: course code is required for a teaching slot")
            continue
        if r.period not in periods and not (r.start and r.end):
            errors.append(f"row {k}: period {r.period} has no default times; give start and end")
            continue
        plan.append((k, r, section))
    if errors:
        raise HTTPException(422, {"errors": errors})
    created_courses = []
    if body.replace_sections:
        for sid in {s.id for _, _, s in plan}:
            db.execute(delete(TimetableEntry).where(TimetableEntry.section_id == sid))
    saved = 0
    for k, r, section in plan:
        course = None
        if not r.is_break:
            code = r.course_code.strip().upper()  # type: ignore[union-attr]
            course = db.scalar(select(Course).where(Course.code == code))
            if course is None:
                if not r.course_name:
                    db.rollback()
                    raise HTTPException(422, {"errors": [f"row {k}: new course {code} needs a course name"]})
                course = Course(code=code, name=r.course_name.strip())
                db.add(course)
                db.flush()
                created_courses.append(code)
        faculty = None
        if r.faculty:
            faculty = db.scalar(select(Faculty).where(Faculty.name == r.faculty.strip()))
            if faculty is None:
                faculty = Faculty(name=r.faculty.strip())
                db.add(faculty)
                db.flush()
        e = db.scalar(
            select(TimetableEntry).where(
                TimetableEntry.weekday == r.weekday,
                TimetableEntry.period_number == r.period,
                TimetableEntry.section_id == section.id,
            )
        ) or TimetableEntry(weekday=r.weekday, period_number=r.period, section_id=section.id)
        p = periods.get(r.period)  # type: ignore[arg-type]
        st = sch.parse_hm(r.start) if r.start else None
        en = sch.parse_hm(r.end) if r.end else None
        e.start_time = st if (st and (p is None or st != p.start_time)) else None
        e.end_time = en if (en and (p is None or en != p.end_time)) else None
        if e.start_time and p is not None and e.attendance_open is None:
            # keep the period's window length, shifted to the new start
            length = datetime.combine(date.today(), p.attendance_close) - datetime.combine(
                date.today(), p.attendance_open
            )
            e.attendance_open = e.start_time
            e.attendance_close = (datetime.combine(date.today(), e.start_time) + length).time()
        elif p is None and st and en:
            e.attendance_open = st
            e.attendance_close = min(en, (datetime.combine(date.today(), st) + timedelta(minutes=10)).time())
        e.is_break = r.is_break
        e.course_id = course.id if course else None
        e.faculty_id = faculty.id if faculty else (course.faculty_id if course else None)
        e.room = r.room or ""
        db.add(e)
        saved += 1
    audit(
        db, auth.user, "timetable.import", "timetable", "", auth.ip,
        rows=saved, created_courses=created_courses, replace=body.replace_sections,
    )  # fmt: skip
    db.commit()
    return {"saved": saved, "created_courses": created_courses}


# ------------------------------------------------------------------ sessions


def session_out(db: Session, s: AttendanceSession, tz, with_counts: bool = True) -> dict:  # type: ignore[no-untyped-def]
    out = {
        "id": s.id, "date": s.date.isoformat(), "period_number": s.period_number,
        "section_id": s.section_id, "section": s.section.name, "course_id": s.course_id,
        "course_code": s.course.code, "course_name": s.course.name,
        "faculty": s.faculty.name if s.faculty else None,
        "start": sch.utc_naive_to_local(s.start_at, tz).strftime("%H:%M"),
        "end": sch.utc_naive_to_local(s.end_at, tz).strftime("%H:%M"),
        "open": sch.utc_naive_to_local(s.open_at, tz).strftime("%H:%M"),
        "close": sch.utc_naive_to_local(s.close_at, tz).strftime("%H:%M"),
        "open_at": s.open_at.isoformat() + "Z", "close_at": s.close_at.isoformat() + "Z",
        "status": sch.session_status(s), "cancelled": s.cancelled,
        "manually_adjusted": s.manually_adjusted, "note": s.note,
    }  # fmt: skip
    if with_counts:
        out["present"] = len(
            db.scalars(
                select(AttendanceRecord.id).where(
                    AttendanceRecord.session_id == s.id,
                    AttendanceRecord.status.in_(("present", "late")),
                )
            ).all()
        )
        out["enrolled"] = len(db.scalars(select(Student.id).where(Student.section_id == s.section_id)).all())
    return out


@router.get("/sessions")
def list_sessions(request: Request, day: date | None = None, _: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    tz = request.app.state.settings_obj.tz
    d = day or sch.local_today(tz)
    sch.ensure_sessions_for_date(db, d, tz)
    db.commit()
    rows = db.scalars(
        select(AttendanceSession)
        .where(AttendanceSession.date == d)
        .order_by(AttendanceSession.start_at, AttendanceSession.section_id)
    )
    holiday = sch.is_holiday(db, d)
    return {
        "date": d.isoformat(),
        "weekday": sch.WEEKDAYS[d.weekday()],
        "holiday": holiday.name if holiday else None,
        "server_time": sch.local_now(tz).isoformat(),
        "sessions": [session_out(db, s, tz) for s in rows],
    }


class AdhocSessionIn(BaseModel):
    date: date
    period_number: int = Field(ge=1, le=16)
    section_id: int
    course_id: int
    start: str = Field(pattern=HM)
    end: str = Field(pattern=HM)
    open: str = Field(pattern=HM)
    close: str = Field(pattern=HM)
    note: str = Field(default="", max_length=256)


@router.post("/sessions")
def create_adhoc_session(body: AdhocSessionIn, request: Request, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    tz = request.app.state.settings_obj.tz
    db.get(Section, body.section_id) or _404("section")
    course = db.get(Course, body.course_id) or _404("course")
    period = db.scalar(select(Period).where(Period.number == body.period_number))
    if period is not None and period.is_break:
        raise HTTPException(400, "that period is a break; attendance cannot be taken")
    if sch.is_holiday(db, body.date):
        raise HTTPException(400, "that date is a holiday")
    st, en, op, cl = (sch.parse_hm(v) for v in (body.start, body.end, body.open, body.close))
    _check_window(st, en, op, cl)
    s = AttendanceSession(
        date=body.date, period_number=body.period_number, section_id=body.section_id,
        course_id=course.id, faculty_id=course.faculty_id,
        start_at=sch.to_utc_naive(body.date, st, tz), end_at=sch.to_utc_naive(body.date, en, tz),
        open_at=sch.to_utc_naive(body.date, op, tz), close_at=sch.to_utc_naive(body.date, cl, tz),
        manually_adjusted=True, note=body.note,
    )  # fmt: skip
    db.add(s)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "a session already exists for that section, date and period") from exc
    audit(db, auth.user, "session.create", "session", s.id, auth.ip, **body.model_dump(mode="json"))
    db.commit()
    return session_out(db, s, tz)


class SessionWindowIn(BaseModel):
    action: str = Field(pattern=r"^(open_now|close_now|cancel|restore|set_window)$")
    minutes: int = Field(default=10, ge=1, le=180)
    open: str | None = Field(default=None, pattern=HM)
    close: str | None = Field(default=None, pattern=HM)
    reason: str = Field(default="", max_length=256)


@router.post("/sessions/{sid}/window")
def adjust_session(sid: int, body: SessionWindowIn, request: Request, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    """Manual opening/closing (server time), cancellation or a new window. Always audited."""
    tz = request.app.state.settings_obj.tz
    s = db.get(AttendanceSession, sid) or _404("session")
    if sch.session_is_break(db, s):
        raise HTTPException(400, "this slot is a break; attendance cannot be opened")
    now = utcnow()
    before = {"open_at": str(s.open_at), "close_at": str(s.close_at), "cancelled": s.cancelled}
    if body.action == "open_now":
        if s.date != sch.local_today(tz):
            raise HTTPException(400, "only today's sessions can be opened now")
        s.open_at, s.close_at, s.cancelled = now, now + timedelta(minutes=body.minutes), False
    elif body.action == "close_now":
        s.close_at = now
        if s.open_at > now:
            s.open_at = now - timedelta(seconds=1)
    elif body.action == "cancel":
        s.cancelled = True
    elif body.action == "restore":
        s.cancelled = False
    else:
        if not (body.open and body.close):
            raise HTTPException(400, "open and close times are required")
        op, cl = sch.parse_hm(body.open), sch.parse_hm(body.close)
        if not op < cl:
            raise HTTPException(400, "attendance must close after it opens")
        s.open_at, s.close_at = sch.to_utc_naive(s.date, op, tz), sch.to_utc_naive(s.date, cl, tz)
    s.manually_adjusted = True
    if body.reason:
        s.note = body.reason
    audit(db, auth.user, f"session.{body.action}", "session", sid, auth.ip, before=before,
          after={"open_at": str(s.open_at), "close_at": str(s.close_at), "cancelled": s.cancelled},
          reason=body.reason)  # fmt: skip
    db.commit()
    return session_out(db, s, tz)


@router.get("/sessions/{sid}")
def session_roster(sid: int, request: Request, _: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    """Live roster: every student of the section with their record and latest attempt."""
    tz = request.app.state.settings_obj.tz
    s = db.get(AttendanceSession, sid) or _404("session")
    records = {
        r.student_id: r
        for r in db.scalars(select(AttendanceRecord).where(AttendanceRecord.session_id == sid))
    }
    attempts: dict[int, VerificationAttempt] = {}
    n_attempts: dict[int, int] = {}
    for a in db.scalars(
        select(VerificationAttempt).where(VerificationAttempt.session_id == sid).order_by(VerificationAttempt.id)
    ):
        attempts[a.student_id] = a
        n_attempts[a.student_id] = n_attempts.get(a.student_id, 0) + 1
    roster = []
    for st in db.scalars(select(Student).where(Student.section_id == s.section_id).order_by(Student.roll_number)):
        r = records.get(st.id)
        a = attempts.get(st.id)
        roster.append({
            "student_id": st.id, "roll_number": st.roll_number, "name": st.name,
            "face_status": st.face_status,
            "status": r.status if r else ("absent" if sch.session_status(s) == "closed" else "not_marked"),
            "method": r.method if r else None,
            "verified_at": r.verified_at.isoformat() + "Z" if r and r.verified_at else None,
            "match_score": round(r.match_score, 3) if r and r.match_score is not None else None,
            "override_reason": r.override_reason if r else None,
            "attempts": n_attempts.get(st.id, 0),
            "last_attempt": {"decision": a.decision, "reason": a.reason,
                             "at": a.created_at.isoformat() + "Z"} if a else None,
        })  # fmt: skip
    return {"session": session_out(db, s, tz), "roster": roster}


class CorrectionIn(BaseModel):
    status: str = Field(pattern=r"^(present|late|absent|excused)$")
    reason: str = Field(min_length=3, max_length=256)


@router.put("/sessions/{sid}/records/{student_id}")
def correct_record(sid: int, student_id: int, body: CorrectionIn, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    """Authorised manual correction (also the non-biometric fallback). Audited with reason."""
    s = db.get(AttendanceSession, sid) or _404("session")
    st = db.get(Student, student_id) or _404("student")
    if st.section_id != s.section_id:
        raise HTTPException(400, "student is not in this session's section")
    r = db.scalar(
        select(AttendanceRecord).where(
            AttendanceRecord.session_id == sid, AttendanceRecord.student_id == student_id
        )
    )
    prev = r.status if r else None
    if r is None:
        r = AttendanceRecord(
            session_id=sid, student_id=student_id, course_id=s.course_id,
            section_id=s.section_id, date=s.date, method="manual",
        )  # fmt: skip
        db.add(r)
    r.status = body.status
    r.previous_status = prev
    r.override_by_user_id = auth.user.id
    r.override_reason = body.reason
    if r.method != "face":
        r.method = "manual"
    audit(db, auth.user, "attendance.correct", "record", f"{sid}:{student_id}", auth.ip,
          previous=prev, new=body.status, reason=body.reason)  # fmt: skip
    db.commit()
    return {"ok": True, "status": r.status, "previous_status": prev}


@router.get("/attempts")
def list_attempts(session_id: int | None = None, student_id: int | None = None, limit: int = 100,
                  _: Auth = Depends(require_admin), db: Session = Depends(get_db)):  # fmt: skip
    stmt = select(VerificationAttempt, Student).join(Student, Student.id == VerificationAttempt.student_id)
    if session_id:
        stmt = stmt.where(VerificationAttempt.session_id == session_id)
    if student_id:
        stmt = stmt.where(VerificationAttempt.student_id == student_id)
    rows = db.execute(stmt.order_by(VerificationAttempt.id.desc()).limit(min(limit, 500))).all()
    return [
        {"id": a.id, "student_id": s.id, "roll_number": s.roll_number, "name": s.name,
         "session_id": a.session_id, "created_at": a.created_at.isoformat() + "Z",
         "decision": a.decision, "reason": a.reason,
         "match_score": round(a.match_score, 3) if a.match_score is not None else None,
         "quality": round(a.quality, 2) if a.quality is not None else None,
         "liveness_passed": a.liveness_passed, "processing_ms": a.processing_ms,
         "details": json.loads(a.details or "{}")}
        for a, s in rows
    ]  # fmt: skip


__all__ = ["router", "session_out"]
_ = runtime
