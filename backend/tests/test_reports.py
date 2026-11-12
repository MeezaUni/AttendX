import csv
import io

from attendx.models import AttendanceRecord
from tests.conftest import make_section_course, make_student, open_session


def _seed(app, admin, db):  # type: ignore[no-untyped-def]
    sid, cid = make_section_course(admin)
    a = make_student(admin, sid, "R001", "Alice Example")
    b = make_student(admin, sid, "R002", "=HYPERLINK(evil)")
    s1 = open_session(app, sid, cid, period=1, offset_min=-50, minutes_open=-40)  # closed
    s2 = open_session(app, sid, cid, period=2, offset_min=-5, minutes_open=10)  # open
    open_session(app, sid, cid, period=3, offset_min=60, minutes_open=70)  # upcoming: not held
    for sess, st, status in ((s1, a, "present"), (s2, a, "present"), (s1, b, "excused")):
        r = admin.put(f"/api/admin/sessions/{sess}/records/{st['id']}", json={"status": status, "reason": "test"})
        assert r.status_code == 200
    return sid, cid, a, b, s1, s2


def test_student_percentages(app, admin, db):
    _seed(app, admin, db)
    rows = {r["roll_number"]: r for r in admin.get("/api/admin/reports/students").json()}
    assert rows["R001"]["held"] == 2 and rows["R001"]["attended"] == 2 and rows["R001"]["percentage"] == 100.0
    # R002: 2 held, 1 excused (not counted), 0 attended -> 0 %
    assert rows["R002"]["excused"] == 1 and rows["R002"]["percentage"] == 0.0
    assert rows["R001"]["courses"][0]["course_code"] == "DL3101"


def test_course_summary(app, admin, db):
    _seed(app, admin, db)
    rows = admin.get("/api/admin/reports/courses").json()
    assert len(rows) == 1 and rows[0]["sessions"] == 2 and rows[0]["possible"] == 4
    assert rows[0]["attended"] == 2 and rows[0]["percentage"] == 50.0


def test_csv_export(app, admin, db):
    _seed(app, admin, db)
    r = admin.get("/api/admin/reports/export.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 4  # 2 held sessions x 2 students
    statuses = sorted((x["roll_number"], x["period"], x["status"]) for x in rows)
    assert statuses == [("R001", "1", "present"), ("R001", "2", "present"),
                        ("R002", "1", "excused"), ("R002", "2", "not_marked")]  # fmt: skip
    # spreadsheet formula injection neutralised
    assert all(not x["student_name"].startswith("=") for x in rows)
    s = admin.get("/api/admin/reports/summary.csv")
    assert s.status_code == 200 and "R001" in s.text


def test_closed_session_counts_absent_in_roster(app, admin, db):
    sid, cid, a, b, s1, s2 = _seed(app, admin, db)
    db.query(AttendanceRecord).filter_by(student_id=b["id"]).delete()
    db.commit()
    roster = {r["roll_number"]: r["status"] for r in admin.get(f"/api/admin/sessions/{s1}").json()["roster"]}
    assert roster == {"R001": "present", "R002": "absent"}


def test_dashboard_and_history(app, admin, db):
    from tests.conftest import student_client

    _seed(app, admin, db)
    d = admin.get("/api/admin/dashboard").json()
    assert d["counts"]["students"] == 2 and d["counts"]["courses"] == 1
    assert d["face_engine"]["engine"] == "fake"
    stu = student_client(app)
    h = stu.get("/api/student/history").json()
    assert h["summary"]["percentage"] == 100.0 and len(h["items"]) == 2


def test_settings_validation_and_audit(admin):
    assert admin.put("/api/admin/settings", json={"match_threshold": 0.2}).status_code == 400  # < nonmatch
    assert admin.put("/api/admin/settings", json={"bogus": 1}).status_code == 400
    r = admin.put("/api/admin/settings", json={"match_threshold": 0.5})
    assert r.json()["runtime"]["match_threshold"] == 0.5
    log = admin.get("/api/admin/audit", params={"action": "settings"}).json()
    assert log[0]["details"]["changes"]["match_threshold"] == [0.4, 0.5]
