from datetime import timedelta

from attendx.db import utcnow
from attendx.models import (
    AttendanceRecord,
    AttendanceSession,
    LivenessChallenge,
    Period,
    VerificationAttempt,
)
from tests.conftest import (
    enroll_face,
    frames_for,
    make_section_course,
    make_student,
    multipart_frames,
    open_session,
    student_client,
)


def setup(app, admin, ident=5):  # type: ignore[no-untyped-def]
    sid, cid = make_section_course(admin)
    st = make_student(admin, sid)
    enroll_face(admin, st["id"], ident)
    sess = open_session(app, sid, cid)
    return st, sess, student_client(app)


def challenge(stu, sess, elapsed_s=20):  # type: ignore[no-untyped-def]
    """Issue a challenge, then pretend the student spent ``elapsed_s`` performing it (the server
    refuses frame timelines longer than the real time since issue)."""
    r = stu.post("/api/student/attendance/challenge", json={"session_id": sess})
    assert r.status_code == 200, r.text
    with stu.app.state.db.SessionLocal() as s:
        c = s.get(LivenessChallenge, r.json()["challenge_id"])
        c.issued_at = c.issued_at - timedelta(seconds=elapsed_s)
        s.commit()
    return r.json()


def submit(stu, ch, ident=5, frames=None):  # type: ignore[no-untyped-def]
    steps = [s["action"] for s in ch["steps"]]
    fr, ts = frames or frames_for(steps, ident)
    files, data = multipart_frames(fr, ts)
    return stu.post(f"/api/student/attendance/challenge/{ch['challenge_id']}/submit", files=files, data=data)


def test_full_flow_marks_present_once(app, admin, db):
    st, sess, stu = setup(app, admin)
    today = stu.get("/api/student/today").json()
    assert today["face_ready"] and today["sessions"][0]["status"] == "open"
    ch = challenge(stu, sess)
    assert 2 <= len(ch["steps"]) <= 6
    r = submit(stu, ch).json()
    assert r["decision"] == "match" and r["marked"] is True, r
    assert "score" not in r  # not exposed to students
    rec = db.query(AttendanceRecord).one()
    assert rec.status == "present" and rec.method == "face" and rec.liveness_passed
    assert rec.match_score is not None and rec.match_score > 0.9
    # duplicate prevention: no new challenge once marked
    dup = stu.post("/api/student/attendance/challenge", json={"session_id": sess})
    assert dup.status_code == 409 and "already recorded" in dup.json()["detail"]
    # admin sees it on the roster
    roster = admin.get(f"/api/admin/sessions/{sess}").json()["roster"]
    assert roster[0]["status"] == "present" and roster[0]["match_score"] > 0.9
    assert stu.get("/api/student/today").json()["sessions"][0]["record"]["status"] == "present"


def test_impostor_is_not_marked(app, admin, db):
    st, sess, stu = setup(app, admin, ident=5)
    r = submit(stu, challenge(stu, sess), ident=9).json()
    assert r["decision"] == "non_match" and r["marked"] is False
    assert db.query(AttendanceRecord).count() == 0
    a = db.query(VerificationAttempt).one()
    assert a.decision == "non_match" and a.liveness_passed is True


def test_failed_liveness_is_rejected(app, admin, db):
    st, sess, stu = setup(app, admin)
    ch = challenge(stu, sess)
    still = frames_for([], 5)  # never performs the actions
    fr, ts = still[0] * 1, still[1]
    r = submit(stu, ch, frames=(fr + fr[:0], ts)).json()
    assert r["decision"] == "rejected" and not r["marked"]
    assert db.query(VerificationAttempt).one().liveness_passed is False


def test_challenge_cannot_be_reused(app, admin):
    st, sess, stu = setup(app, admin)
    ch = challenge(stu, sess)
    submit(stu, ch, ident=9)
    again = submit(stu, ch, ident=5)
    assert again.status_code == 409


def test_new_challenge_supersedes_old(app, admin):
    st, sess, stu = setup(app, admin)
    old = challenge(stu, sess)
    challenge(stu, sess)
    assert submit(stu, old).status_code == 409


def test_expired_challenge(app, admin, db):
    st, sess, stu = setup(app, admin)
    ch = challenge(stu, sess)
    c = db.get(LivenessChallenge, ch["challenge_id"])
    c.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert submit(stu, ch).status_code == 410


def test_frozen_feed_rejected(app, admin):
    st, sess, stu = setup(app, admin)
    ch = challenge(stu, sess)
    fr, ts = frames_for([s["action"] for s in ch["steps"]], 5)
    frozen = [fr[0]] * len(fr)
    r = submit(stu, ch, frames=(frozen, ts)).json()
    assert r["decision"] == "rejected" and "frozen" in r["reason"]


def test_timing_must_fit_server_clock(app, admin):
    st, sess, stu = setup(app, admin)
    ch = challenge(stu, sess)
    fr, ts = frames_for([s["action"] for s in ch["steps"]], 5, dt=1400.0)  # claims ~40 s
    r = submit(stu, ch, frames=(fr, ts)).json()
    assert r["decision"] == "rejected"


def test_outside_window_rejected(app, admin, db):
    sid, cid = make_section_course(admin)
    st = make_student(admin, sid)
    enroll_face(admin, st["id"], 5)
    upcoming = open_session(app, sid, cid, period=2, offset_min=30, minutes_open=40)
    closed = open_session(app, sid, cid, period=3, offset_min=-30, minutes_open=-5)
    stu = student_client(app)
    r1 = stu.post("/api/student/attendance/challenge", json={"session_id": upcoming})
    r2 = stu.post("/api/student/attendance/challenge", json={"session_id": closed})
    assert r1.status_code == 409 and "not opened" in r1.json()["detail"]
    assert r2.status_code == 409 and "closed" in r2.json()["detail"]


def test_window_closing_between_challenge_and_submit(app, admin, db):
    st, sess, stu = setup(app, admin)
    ch = challenge(stu, sess)
    s = db.get(AttendanceSession, sess)
    s.close_at = utcnow() - timedelta(seconds=1)
    db.commit()
    assert submit(stu, ch).status_code == 409


def test_break_period_rejected(app, admin, db):
    st, sess, stu = setup(app, admin)
    p = db.query(Period).filter_by(number=1).one()
    p.is_break = True
    db.commit()
    r = stu.post("/api/student/attendance/challenge", json={"session_id": sess})
    assert r.status_code == 409 and "break" in r.json()["detail"]


def test_holiday_rejected(app, admin):
    st, sess, stu = setup(app, admin)
    from attendx.services.schedule import local_today

    today = local_today(app.state.settings_obj.tz).isoformat()
    assert admin.post("/api/admin/holidays", json={"date": today, "name": "Test day"}).status_code == 200
    r = stu.post("/api/student/attendance/challenge", json={"session_id": sess})
    assert r.status_code == 409


def test_other_section_not_eligible(app, admin):
    st, sess, stu = setup(app, admin)
    other = admin.post("/api/admin/sections", json={"name": "CSE-5B"}).json()
    make_student(admin, other["id"], roll="R002")
    stu2 = student_client(app, roll="R002")
    r = stu2.post("/api/student/attendance/challenge", json={"session_id": sess})
    assert r.status_code == 403


def test_course_enrollment_policy(app, admin):
    st, sess, stu = setup(app, admin)
    assert admin.put("/api/admin/settings", json={"eligibility": "course_enrollment"}).status_code == 200
    assert stu.post("/api/student/attendance/challenge", json={"session_id": sess}).status_code == 403
    sid = admin.get("/api/admin/sections").json()[0]["id"]
    cid = admin.get("/api/admin/courses").json()[0]["id"]
    admin.post(f"/api/admin/sections/{sid}/enroll-course/{cid}")
    assert stu.post("/api/student/attendance/challenge", json={"session_id": sess}).status_code == 200


def test_unenrolled_face_cannot_start(app, admin):
    sid, cid = make_section_course(admin)
    make_student(admin, sid)
    sess = open_session(app, sid, cid)
    stu = student_client(app)
    r = stu.post("/api/student/attendance/challenge", json={"session_id": sess})
    assert r.status_code == 409 and "not enrolled" in r.json()["detail"]


def test_attempt_limit(app, admin):
    st, sess, stu = setup(app, admin)
    admin.put("/api/admin/settings", json={"max_attempts_per_session": 2})
    for _ in range(2):
        submit(stu, challenge(stu, sess), ident=9)
    r = stu.post("/api/student/attendance/challenge", json={"session_id": sess})
    assert r.status_code == 429


def test_challenge_rate_limit(app, admin):
    st, sess, stu = setup(app, admin)
    app.state.settings_obj.challenges_per_minute = 2
    challenge(stu, sess)
    challenge(stu, sess)
    assert stu.post("/api/student/attendance/challenge", json={"session_id": sess}).status_code == 429


def test_cannot_submit_someone_elses_challenge(app, admin):
    st, sess, stu = setup(app, admin)
    ch = challenge(stu, sess)
    make_student(admin, admin.get("/api/admin/sections").json()[0]["id"], roll="R002")
    stu2 = student_client(app, roll="R002")
    assert submit(stu2, ch).status_code == 404


def test_manual_admin_open_and_close(app, admin, db):
    sid, cid = make_section_course(admin)
    sess = open_session(app, sid, cid, offset_min=30, minutes_open=40)  # upcoming
    r = admin.post(f"/api/admin/sessions/{sess}/window", json={"action": "open_now", "minutes": 5})
    assert r.json()["status"] == "open"
    r = admin.post(f"/api/admin/sessions/{sess}/window", json={"action": "close_now"})
    assert r.json()["status"] == "closed"
    r = admin.post(f"/api/admin/sessions/{sess}/window", json={"action": "cancel"})
    assert r.json()["status"] == "cancelled"


def test_manual_correction_fallback_is_audited(app, admin, db):
    from attendx.models import AuditLog

    sid, cid = make_section_course(admin)
    st = make_student(admin, sid)
    sess = open_session(app, sid, cid)
    r = admin.put(f"/api/admin/sessions/{sess}/records/{st['id']}", json={"status": "present", "reason": "camera broken"})
    assert r.status_code == 200
    rec = db.query(AttendanceRecord).one()
    assert rec.method == "manual" and rec.override_reason == "camera broken"
    r = admin.put(f"/api/admin/sessions/{sess}/records/{st['id']}", json={"status": "excused", "reason": "medical"})
    assert r.json()["previous_status"] == "present"
    assert db.query(AttendanceRecord).count() == 1
    assert db.query(AuditLog).filter_by(action="attendance.correct").count() == 2
    assert admin.put(f"/api/admin/sessions/{sess}/records/{st['id']}", json={"status": "present", "reason": ""}).status_code == 422
