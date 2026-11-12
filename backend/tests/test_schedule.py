from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from attendx.db import utcnow
from attendx.models import AttendanceSession, Period, TimetableEntry
from attendx.services import schedule as sch
from tests.conftest import make_section_course

IST = ZoneInfo("Asia/Kolkata")
MONDAY = date(2026, 11, 2)


def test_eight_default_periods(admin):
    ps = admin.get("/api/admin/periods").json()
    assert [p["number"] for p in ps] == list(range(1, 9))
    assert ps[0]["start_time"] == "08:50" and ps[0]["attendance_close"] == "09:00"
    assert not any(p["is_break"] for p in ps)


def test_replace_periods_validation(admin):
    ps = admin.get("/api/admin/periods").json()
    ps[0]["attendance_close"] = "08:40"  # before opening
    assert admin.put("/api/admin/periods", json=ps).status_code == 400
    ps[0]["attendance_close"] = "09:05"
    ps[1]["is_break"] = True
    r = admin.put("/api/admin/periods", json=ps)
    assert r.status_code == 200 and r.json()[1]["is_break"] is True
    assert admin.put("/api/admin/periods", json=ps + [ps[0]]).status_code == 400  # duplicate number


def test_timezone_conversion():
    # 08:50 IST == 03:20 UTC
    assert sch.to_utc_naive(MONDAY, time(8, 50), IST) == datetime(2026, 11, 2, 3, 20)
    assert sch.utc_naive_to_local(datetime(2026, 11, 2, 3, 20), IST).strftime("%H:%M") == "08:50"


def test_session_generation_and_breaks(app, admin, db):
    sid, cid = make_section_course(admin)
    assert admin.post("/api/admin/timetable", json={"weekday": 0, "period_number": 1, "section_id": sid,
                                                   "course_id": cid}).status_code == 200  # fmt: skip
    assert admin.post("/api/admin/timetable", json={"weekday": 0, "period_number": 2, "section_id": sid,
                                                   "is_break": True}).status_code == 200  # fmt: skip
    r = admin.post("/api/admin/timetable", json={"weekday": 0, "period_number": 1, "section_id": sid, "course_id": cid})
    assert r.status_code == 409  # same slot twice
    no_course = admin.post("/api/admin/timetable", json={"weekday": 0, "period_number": 3, "section_id": sid})
    assert no_course.status_code == 400
    sessions = sch.ensure_sessions_for_date(db, MONDAY, IST)
    assert len(sessions) == 1  # the break slot creates no session
    s = sessions[0]
    assert s.open_at == datetime(2026, 11, 2, 3, 20) and s.close_at == datetime(2026, 11, 2, 3, 30)
    assert sch.ensure_sessions_for_date(db, MONDAY, IST)[0].id == s.id  # idempotent
    assert sch.ensure_sessions_for_date(db, MONDAY + timedelta(days=1), IST) == []  # Tuesday: none


def test_entry_override_times(app, admin, db):
    sid, cid = make_section_course(admin)
    r = admin.post("/api/admin/timetable", json={"weekday": 0, "period_number": 1, "section_id": sid,
                   "course_id": cid, "attendance_open": "08:55", "attendance_close": "09:05"})  # fmt: skip
    assert r.status_code == 200, r.text
    s = sch.ensure_sessions_for_date(db, MONDAY, IST)[0]
    assert s.open_at == datetime(2026, 11, 2, 3, 25)
    bad = admin.post("/api/admin/timetable", json={"weekday": 1, "period_number": 1, "section_id": sid,
                     "course_id": cid, "attendance_open": "10:00", "attendance_close": "10:05"})  # fmt: skip
    assert bad.status_code == 400  # window outside the class


def test_status_uses_server_time():
    now = datetime(2026, 11, 2, 3, 25)
    s = AttendanceSession(open_at=datetime(2026, 11, 2, 3, 20), close_at=datetime(2026, 11, 2, 3, 30), cancelled=False)
    assert sch.session_status(s, now) == "open"
    assert sch.session_status(s, datetime(2026, 11, 2, 3, 19)) == "upcoming"
    assert sch.session_status(s, datetime(2026, 11, 2, 3, 30)) == "closed"  # close is exclusive
    s.cancelled = True
    assert sch.session_status(s, now) == "cancelled"


def test_holiday_blocks_sessions(app, admin, db):
    sid, cid = make_section_course(admin)
    admin.post("/api/admin/timetable", json={"weekday": 0, "period_number": 1, "section_id": sid, "course_id": cid})
    sch.ensure_sessions_for_date(db, MONDAY, IST)
    db.commit()
    r = admin.post("/api/admin/holidays", json={"date": MONDAY.isoformat(), "name": "Festival"})
    assert r.json()["cancelled_sessions"] == 1
    db.expire_all()
    assert db.query(AttendanceSession).one().cancelled
    assert sch.ensure_sessions_for_date(db, MONDAY, IST) == []
    assert admin.post("/api/admin/holidays", json={"date": MONDAY.isoformat(), "name": "dup"}).status_code == 409


def test_period_break_flag_blocks_session(app, admin, db):
    sid, cid = make_section_course(admin)
    admin.post("/api/admin/timetable", json={"weekday": 0, "period_number": 4, "section_id": sid, "course_id": cid})
    p = db.query(Period).filter_by(number=4).one()
    p.is_break = True
    db.commit()
    assert sch.ensure_sessions_for_date(db, MONDAY, IST) == []
    adhoc = admin.post("/api/admin/sessions", json={"date": MONDAY.isoformat(), "period_number": 4,
                       "section_id": sid, "course_id": cid, "start": "11:50", "end": "12:45",
                       "open": "11:50", "close": "12:00"})  # fmt: skip
    assert adhoc.status_code == 400


def test_admin_sessions_endpoint_today(app, admin, db):
    sid, cid = make_section_course(admin)
    today = sch.local_today(app.state.settings_obj.tz)
    admin.post("/api/admin/timetable", json={"weekday": today.weekday(), "period_number": 1,
                                             "section_id": sid, "course_id": cid})  # fmt: skip
    body = admin.get("/api/admin/sessions").json()
    assert body["date"] == today.isoformat() and len(body["sessions"]) == 1
    assert body["sessions"][0]["start"] == "08:50"


def test_manual_adjustment_survives_regeneration(app, admin, db):
    sid, cid = make_section_course(admin)
    admin.post("/api/admin/timetable", json={"weekday": 0, "period_number": 1, "section_id": sid, "course_id": cid})
    s = sch.ensure_sessions_for_date(db, MONDAY, IST)[0]
    s.manually_adjusted = True
    s.close_at = utcnow()
    db.commit()
    e = db.query(TimetableEntry).one()
    e.attendance_close = time(9, 10)
    db.commit()
    again = sch.ensure_sessions_for_date(db, MONDAY, IST)[0]
    assert again.close_at == s.close_at
