"""Separate faculty database + central ingestion; deterministic face/liveness test engine."""

import copy
import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from attendx.db import utcnow
from tests.conftest import frames_for, make_section_course
from tests.test_v2_identity import activate, faculty, ok, semester, settings  # noqa: F401


@pytest.fixture
def clock():
    return [utcnow().replace(hour=10, minute=0, second=0, microsecond=0)]


def sample_snapshot(clock):
    from attendx.config import RUNTIME_DEFAULTS
    from attendx.face.engine import FakeFaceEngine, decode_image
    from attendx.v2.identity import PIPELINE_VERSION
    from tests.conftest import png

    engine = FakeFaceEngine()
    ref = engine.observe(decode_image(png(1)), RUNTIME_DEFAULTS).embedding.tolist()
    day = clock[0].date()
    return {
        "schema_version": 2,
        "grant_id": "test-grant",
        "generated_at": clock[0].isoformat() + "Z",
        "offline_valid_until": (clock[0] + timedelta(hours=24)).isoformat() + "Z",
        "faculty": {"user_id": 2, "name": "Synthetic Lecturer"},
        "pipeline_version": PIPELINE_VERSION,
        "classes": [
            {
                "assignment_id": 1,
                "section_id": 1,
                "course_id": 1,
                "section": "DEMO",
                "course": "DL",
                "assignment_start": str(day),
                "assignment_end": None,
                "roster": [
                    {
                        "student_id": 1,
                        "roll_number": "S001",
                        "name": "Enrolled",
                        "enrollment_state": "ACTIVE",
                        "references": [ref, ref, ref],
                        "version": 1,
                        "model_id": engine.model_id,
                        "pipeline_version": PIPELINE_VERSION,
                        "expires_on": str(day + timedelta(days=30)),
                    },
                    {
                        "student_id": 2,
                        "roll_number": "S002",
                        "name": "Pending CC",
                        "enrollment_state": "PENDING_CC_VERIFICATION",
                        "references": [],
                        "version": None,
                        "model_id": None,
                        "expires_on": None,
                    },
                    {
                        "student_id": 3,
                        "roll_number": "S003",
                        "name": "No enrollment",
                        "enrollment_state": "NOT_ENROLLED",
                        "references": [],
                        "version": None,
                        "model_id": None,
                        "expires_on": None,
                    },
                ],
            }
        ],
        "timetable": [
            {
                "weekday": day.weekday(),
                "period_number": 1,
                "section_id": 1,
                "course_id": 1,
                "is_break": False,
                "start_time": "00:00:00",
                "end_time": "23:59:59",
            }
        ],
        "holidays": [],
        "periods": [],
        "policy": {**RUNTIME_DEFAULTS, "timezone": "UTC", "collection_seconds": 300, "qr_rotation_seconds": 5},
    }


@pytest.fixture
def runtime(tmp_path, clock):
    from attendx.face.engine import FakeFaceEngine
    from attendx.faculty.runtime import FacultyRuntime

    rt = FacultyRuntime(tmp_path / "faculty", engine=FakeFaceEngine(), now=lambda: clock[0])
    rt.provision(sample_snapshot(clock), "faculty-pin-9")
    return rt


def start(runtime):
    return runtime.start_session(1, 1, 1)


def finish_marks(runtime, session):
    for sid, status in [(1, "PRESENT"), (2, "PRESENT"), (3, "ABSENT")]:
        runtime.mark(session["id"], sid, status, "Physical roll call")
    runtime.close_collection(session["id"])


def entry(runtime, session, roll="S001", ip="192.168.137.2"):
    qr = runtime.current_qr(session["id"])
    attempt = runtime.enter(qr["token"], ip)
    claim = runtime.claim(attempt["attempt_token"], roll, ip)
    return qr, attempt, claim


def match(runtime, clock, session):
    qr, attempt, claim = entry(runtime, session)
    frames, ts = frames_for([x["action"] for x in claim["steps"]], 1)
    clock[0] += timedelta(seconds=(ts[-1] - ts[0]) / 1000)
    result = runtime.verify(attempt["attempt_token"], frames, ts, "192.168.137.2")
    assert result["decision"] == "match", result
    return qr, attempt


def test_full_roster_manual_authority_headcount_and_durable_outbox(runtime, tmp_path, clock):
    from attendx.face.engine import FakeFaceEngine
    from attendx.faculty.runtime import FacultyRuntime

    session = start(runtime)
    assert len(session["roster"]) == 3
    assert all(r["status"] == "UNMARKED" for r in session["roster"])
    with pytest.raises(ValueError, match="unmarked|UNMARKED|collection"):
        runtime.approve(session["id"], 0)
    assert runtime.pending_events() == []
    finish_marks(runtime, session)
    with pytest.raises(ValueError, match="headcount"):
        runtime.approve(session["id"], 1)
    approved = runtime.approve(session["id"], 2)
    assert approved["state"] == "APPROVED"
    events = runtime.pending_events()
    assert len(events) == 1 and events[0]["revision"] == 1
    reopened = FacultyRuntime(tmp_path / "faculty", engine=FakeFaceEngine(), now=lambda: clock[0])
    with pytest.raises(ValueError, match="locked"):
        reopened.session(session["id"])
    with pytest.raises(ValueError, match="PIN"):
        reopened.unlock("wrong-pin")
    reopened.unlock("faculty-pin-9")
    assert reopened.session(session["id"])["state"] == "APPROVED"
    assert reopened.pending_events() == events
    assert b"Pending CC" not in (tmp_path / "faculty" / "faculty.db").read_bytes()


def test_manual_decision_requires_reason_and_approval_freezes_roster(runtime):
    s = start(runtime)
    with pytest.raises(ValueError, match="reason"):
        runtime.mark(s["id"], 2, "PRESENT", "")
    finish_marks(runtime, s)
    runtime.approve(s["id"], 2)
    with pytest.raises(ValueError, match="approved|APPROVED"):
        runtime.mark(s["id"], 2, "ABSENT", "Correction")
    amendment = runtime.amend(s["id"], 2, "ABSENT", "Roll-call correction", 1)
    assert amendment["revision"] == 2
    assert len(runtime.pending_events()) == 2


def test_second_qr_requires_match_fresh_token_and_no_duplicates(runtime, clock):
    s = start(runtime)
    qr, attempt, claim = entry(runtime, s)
    with pytest.raises(ValueError, match="MATCH|match"):
        runtime.submit(attempt["attempt_token"], qr["token"], "192.168.137.2")
    frames, ts = frames_for([x["action"] for x in claim["steps"]], 1)
    clock[0] += timedelta(seconds=(ts[-1] - ts[0]) / 1000)
    assert runtime.verify(attempt["attempt_token"], frames, ts, "192.168.137.2")["decision"] == "match"
    with pytest.raises(ValueError):
        runtime.submit(attempt["attempt_token"], qr["token"], "192.168.137.2")
    clock[0] += timedelta(seconds=5)
    fresh = runtime.current_qr(s["id"])
    result = runtime.submit(attempt["attempt_token"], fresh["token"], "192.168.137.2")
    assert result["status"] == "PENDING_FACULTY_APPROVAL"
    row = runtime.session(s["id"])["roster"][0]
    assert row["status"] == "PRESENT" and row["suggested"] == "PRESENT"
    assert row["decision_source"] == "face_suggestion"
    assert row["verification"]["decision"] == "MATCH"
    with pytest.raises(ValueError):
        runtime.submit(attempt["attempt_token"], fresh["token"], "192.168.137.2")
    assert runtime.pending_events() == []


def test_qr_wrong_session_expired_closed_and_ip_binding(runtime, clock):
    s = start(runtime)
    qr, attempt, _ = entry(runtime, s)
    with pytest.raises(ValueError):
        runtime.claim(attempt["attempt_token"], "S001", "192.168.137.9")
    clock[0] += timedelta(seconds=6)
    with pytest.raises(ValueError):
        runtime.enter(qr["token"], "192.168.137.2")
    runtime.close_collection(s["id"])
    with pytest.raises(ValueError):
        runtime.current_qr(s["id"])


def test_unenrolled_review_is_consolidated_and_never_absent(runtime):
    s = start(runtime)
    for _ in range(2):
        _, _, claim = entry(runtime, s, "S002")
        assert claim["status"] == "FACULTY_REVIEW_REQUIRED"
    rows = runtime.session(s["id"])["roster"]
    assert len(rows) == 3 and rows[1]["review"]["attempts"] == 2
    assert rows[1]["status"] == "UNMARKED"


@pytest.mark.parametrize("ident", [2, 0, 255])
def test_nonmatch_or_abstain_or_liveness_failure_never_marks_absent(runtime, clock, ident):
    s = start(runtime)
    _, attempt, claim = entry(runtime, s)
    frames, ts = frames_for([x["action"] for x in claim["steps"]], ident)
    clock[0] += timedelta(seconds=(ts[-1] - ts[0]) / 1000)
    r = runtime.verify(attempt["attempt_token"], frames, ts, "192.168.137.2")
    assert r["decision"] != "match"
    row = runtime.session(s["id"])["roster"][0]
    assert row["status"] == "UNMARKED" and row["review"] is not None


def test_stale_grant_revoked_assignment_expiry_and_restart_challenges(runtime, tmp_path, clock):
    from attendx.face.engine import FakeFaceEngine
    from attendx.faculty.runtime import FacultyRuntime

    s = start(runtime)
    _, attempt, _ = entry(runtime, s)
    other = FacultyRuntime(tmp_path / "faculty", engine=FakeFaceEngine(), now=lambda: clock[0])
    other.unlock("faculty-pin-9")
    with pytest.raises(ValueError):
        other.submit(attempt["attempt_token"], "anything", "192.168.137.2")
    snap = sample_snapshot(clock)
    snap["classes"] = []
    other.install_snapshot(snap)
    with pytest.raises(ValueError):
        other.start_session(1, 1, 1)
    clock[0] += timedelta(hours=25)
    with pytest.raises(ValueError, match="expired"):
        other.unlock("faculty-pin-9")


def test_end_of_day_closes_collection_preserves_approved_and_locks(runtime):
    s = start(runtime)
    finish_marks(runtime, s)
    runtime.approve(s["id"], 2)
    runtime.privacy_lock()
    with pytest.raises(ValueError, match="locked"):
        runtime.session(s["id"])
    runtime.unlock("faculty-pin-9")
    assert len(runtime.pending_events()) == 1


def test_snapshot_scope_full_roster_and_device_idempotent_sync(admin, app, tmp_path):
    from attendx.face.engine import FakeFaceEngine
    from attendx.faculty.runtime import FacultyRuntime

    sec, course = make_section_course(admin)
    semester(admin, sec)
    students = [activate(admin, app, sec, f"SYNC{i}")[0] for i in range(3)]
    f, lecturer = faculty(admin, app, sec, course)
    device = ok(lecturer.post("/api/v2/faculty/devices", json={"name": "Synthetic laptop"}))
    headers = {"Authorization": f"Bearer {device['credential']}"}
    client = TestClient(app)
    snap = ok(client.get("/api/v2/sync/snapshot", headers=headers))
    assert len(snap["classes"][0]["roster"]) == 3
    assert all(s["references"] == [] for s in snap["classes"][0]["roster"])
    assert not any(word in json.dumps(snap).lower() for word in ("password", "photo_enc", "photo_url"))
    assert "grant_id" in snap
    # Add a real assigned timetable for this integration fixture, then fetch a new grant.
    from datetime import time

    from attendx.models import TimetableEntry
    from attendx.services.schedule import local_today

    with app.state.db.SessionLocal() as db:
        db.add(
            TimetableEntry(
                weekday=local_today(app.state.settings_obj.tz).weekday(),
                period_number=1,
                section_id=sec,
                course_id=course,
                faculty_id=f["faculty_id"],
                start_time=time(0),
                end_time=time(23, 59, 59),
            )
        )
        db.commit()
    snap = ok(client.get("/api/v2/sync/snapshot", headers=headers))
    rt = FacultyRuntime(tmp_path / "separate-faculty", engine=FakeFaceEngine())
    rt.provision(snap, "faculty-pin-9")
    s = rt.start_session(sec, course, 1)
    for i, student in enumerate(students):
        rt.mark(s["id"], student["id"], "PRESENT" if i < 2 else "ABSENT", "Physical identity check")
    rt.close_collection(s["id"])
    rt.approve(s["id"], 2)
    event = rt.pending_events()[0]
    import uuid

    forged = copy.deepcopy(event)
    forged["event_id"], forged["session_id"] = str(uuid.uuid4()), str(uuid.uuid4())
    forged["date"] = str(__import__("datetime").date.fromisoformat(event["date"]) + timedelta(days=1))
    ok(client.post("/api/v2/sync/events", json=forged, headers=headers), 409)
    response = ok(client.post("/api/v2/sync/events", json=event, headers=headers))
    assert response["event_id"] == event["event_id"]
    assert ok(client.post("/api/v2/sync/events", json=event, headers=headers))["duplicate"] is True
    conflict = copy.deepcopy(event)
    conflict["headcount"] = 900
    ok(client.post("/api/v2/sync/events", json=conflict, headers=headers), 409)
    rt.acknowledge(response)
    assert rt.pending_events() == []
    central = ok(lecturer.get("/api/v2/faculty/attendance"))
    assert len(central) == 1 and len(central[0]["roster"]) == 3
    rt.amend(s["id"], students[1]["id"], "ABSENT", "Audited physical correction", 1)
    amendment = rt.pending_events()[0]
    modified = copy.deepcopy(amendment)
    modified["period_number"] = 2
    ok(client.post("/api/v2/sync/events", json=modified, headers=headers), 409)
    ok(client.post("/api/v2/sync/events", json=amendment, headers=headers))
    renewed_device = ok(
        lecturer.post("/api/v2/faculty/devices", json={"name": "Synthetic laptop", "device_id": device["device_id"]})
    )
    headers["Authorization"] = "Bearer " + renewed_device["credential"]
    assert ok(client.post("/api/v2/sync/events", json=amendment, headers=headers))["duplicate"] is True
    export = admin.get("/api/v2/admin/attendance.csv")
    assert export.status_code == 200
    assert len(export.text.splitlines()) == 4
    assert "UNMARKED" not in export.text
    _, unrelated = faculty(admin, app, username="unrelated")
    assert ok(unrelated.get("/api/v2/faculty/snapshot"))["classes"] == []
    assert unrelated.get("/api/v2/faculty/attendance").json() == []


def test_student_listener_denies_non_hotspot_and_no_central_login(runtime):
    from attendx.faculty.server import create_student_app

    app = create_student_app(runtime, "192.168.137.1", "192.168.137.0/24", "https://192.168.137.1:9443")
    bad = TestClient(app, client=("10.0.0.8", 5000), base_url="https://192.168.137.1:9443")
    assert bad.get("/").status_code == 403
    good = TestClient(app, client=("192.168.137.8", 5000), base_url="https://192.168.137.1:9443")
    assert good.get("/").status_code == 200
    assert good.post("/api/auth/login", json={}).status_code == 404
    assert good.get("/", headers={"X-Forwarded-For": "192.168.137.2"}).status_code == 403
