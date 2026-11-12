"""Timetable -> attendance sessions, attendance-window status and student eligibility.

Every check uses the SERVER clock interpreted in the configured institutional timezone; the
phone's clock is never consulted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from attendx.db import utcnow
from attendx.models import (
    AttendanceSession,
    CourseEnrollment,
    Holiday,
    Period,
    Student,
    TimetableEntry,
)

WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")

# Eight default teaching periods (admin-editable). Attendance opens at the class start and
# closes 10 minutes later by default. Gaps 10:40-10:55 (short break) and 12:45-13:30 (lunch).
DEFAULT_PERIODS = [
    (1, "08:50", "09:45"),
    (2, "09:45", "10:40"),
    (3, "10:55", "11:50"),
    (4, "11:50", "12:45"),
    (5, "13:30", "14:25"),
    (6, "14:25", "15:20"),
    (7, "15:20", "16:15"),
    (8, "16:15", "17:10"),
]
DEFAULT_WINDOW_MINUTES = 10


def parse_hm(value: str) -> time:
    return datetime.strptime(value.strip(), "%H:%M").time()


def ensure_default_periods(db: Session) -> None:
    if db.scalar(select(Period.id).limit(1)) is not None:
        return
    for number, start, end in DEFAULT_PERIODS:
        s = parse_hm(start)
        close = (datetime.combine(date.today(), s) + timedelta(minutes=DEFAULT_WINDOW_MINUTES)).time()
        db.add(
            Period(
                number=number,
                label=f"Period {number}",
                start_time=s,
                end_time=parse_hm(end),
                attendance_open=s,
                attendance_close=close,
                is_break=False,
            )
        )


def local_now(tz: ZoneInfo) -> datetime:
    return datetime.now(tz)


def local_today(tz: ZoneInfo) -> date:
    return local_now(tz).date()


def to_utc_naive(d: date, t: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(d, t, tzinfo=tz).astimezone(UTC).replace(tzinfo=None)


def utc_naive_to_local(dt: datetime, tz: ZoneInfo) -> datetime:
    return dt.replace(tzinfo=UTC).astimezone(tz)


def is_holiday(db: Session, d: date) -> Holiday | None:
    return db.scalar(select(Holiday).where(Holiday.date == d))


@dataclass
class SlotTimes:
    start: time
    end: time
    open: time
    close: time
    is_break: bool


def slot_times(entry: TimetableEntry, period: Period | None) -> SlotTimes | None:
    if period is None and (entry.start_time is None or entry.end_time is None):
        return None
    start = entry.start_time or period.start_time  # type: ignore[union-attr]
    end = entry.end_time or period.end_time  # type: ignore[union-attr]
    opn = entry.attendance_open or (period.attendance_open if period else start)
    cls = entry.attendance_close or (period.attendance_close if period else end)
    is_break = bool(entry.is_break or (period.is_break if period else False))
    return SlotTimes(start, end, opn, cls, is_break)


def ensure_sessions_for_date(db: Session, d: date, tz: ZoneInfo) -> list[AttendanceSession]:
    """Materialise sessions for every non-break timetable entry on ``d`` (idempotent).

    Holidays produce no sessions. Existing sessions are refreshed from the timetable unless an
    administrator adjusted them manually."""
    if is_holiday(db, d):
        return []
    periods = {p.number: p for p in db.scalars(select(Period))}
    entries = db.scalars(select(TimetableEntry).where(TimetableEntry.weekday == d.weekday()))
    out = []
    for e in entries:
        times = slot_times(e, periods.get(e.period_number))
        if times is None or times.is_break or e.course_id is None:
            continue
        existing = db.scalar(
            select(AttendanceSession).where(
                AttendanceSession.section_id == e.section_id,
                AttendanceSession.date == d,
                AttendanceSession.period_number == e.period_number,
            )
        )
        fields = dict(
            course_id=e.course_id,
            faculty_id=e.faculty_id or (e.course.faculty_id if e.course else None),
            timetable_entry_id=e.id,
            start_at=to_utc_naive(d, times.start, tz),
            end_at=to_utc_naive(d, times.end, tz),
            open_at=to_utc_naive(d, times.open, tz),
            close_at=to_utc_naive(d, times.close, tz),
        )
        if existing is None:
            existing = AttendanceSession(
                date=d, period_number=e.period_number, section_id=e.section_id, **fields
            )
            db.add(existing)
        elif not existing.manually_adjusted:
            for k, v in fields.items():
                setattr(existing, k, v)
        out.append(existing)
    db.flush()
    return out


def session_status(s: AttendanceSession, now_utc: datetime | None = None) -> str:
    """upcoming | open | closed | cancelled (pure function of server time)."""
    now = now_utc or utcnow()
    if s.cancelled:
        return "cancelled"
    if now < s.open_at:
        return "upcoming"
    if now < s.close_at:
        return "open"
    return "closed"


def session_is_break(db: Session, s: AttendanceSession) -> bool:
    """Defence in depth: a session whose slot is (now) a break never accepts attendance."""
    period = db.scalar(select(Period).where(Period.number == s.period_number))
    if s.timetable_entry_id is not None:
        e = db.get(TimetableEntry, s.timetable_entry_id)
        if e is not None and e.is_break:
            return True
    return bool(period is not None and period.is_break)


def student_eligible(db: Session, student: Student, s: AttendanceSession, policy: str) -> bool:
    if student.section_id != s.section_id:
        return False
    if policy == "course_enrollment":
        return (
            db.scalar(
                select(CourseEnrollment.id).where(
                    CourseEnrollment.student_id == student.id,
                    CourseEnrollment.course_id == s.course_id,
                )
            )
            is not None
        )
    return True


def held_sessions_query(now_utc: datetime | None = None):
    """Sessions that count towards attendance percentages: not cancelled and already opened."""
    now = now_utc or utcnow()
    return select(AttendanceSession).where(
        AttendanceSession.cancelled.is_(False), AttendanceSession.open_at <= now
    )
