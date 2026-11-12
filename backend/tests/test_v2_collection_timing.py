"""Faculty chooses the start; timetable supplies class bounds and a five-minute grace."""

# ruff: noqa: F811 -- imported pytest fixtures are intentionally injected by name
from datetime import timedelta

import pytest

from attendx.faculty.runtime import parse_stamp
from tests.conftest import make_section_course
from tests.test_v2_identity import settings  # noqa: F401
from tests.test_v2_offline import clock, runtime, sample_snapshot  # noqa: F401


def test_current_meeting_detects_period_and_prefers_current_class_over_prior_grace(runtime, clock):
    snapshot = sample_snapshot(clock)
    snapshot["policy"]["timezone"] = "Asia/Kolkata"
    slot = snapshot["timetable"][0]
    slot.update(period_number=7, start_time="15:20:00", end_time="16:15:00")
    snapshot["timetable"].append({**slot, "period_number": 8, "start_time": "16:15:00", "end_time": "17:10:00"})
    runtime.install_snapshot(snapshot)
    clock[0] = clock[0].replace(hour=10, minute=47)  # 16:17 IST: P8 plus P7 grace
    meetings = runtime.available_meetings()
    assert [m["period_number"] for m in meetings] == [8, 7]
    session = runtime.start_session(1, 1, 8)
    assert runtime.available_meetings()[0]["session_id"] == session["id"]
    clock[0] = clock[0].replace(hour=12, minute=0)
    assert runtime.available_meetings() == []


@pytest.mark.parametrize(
    ("hour", "minute", "second", "allowed"),
    [
        (10, 29, 59, False),
        (10, 30, 0, True),
        (11, 39, 0, True),
        (11, 40, 0, True),
        (11, 44, 59, True),
        (11, 45, 0, True),
        (11, 45, 1, False),
    ],
)
def test_faculty_start_uses_class_and_grace_in_institution_timezone(runtime, clock, hour, minute, second, allowed):
    snapshot = sample_snapshot(clock)
    snapshot["policy"]["timezone"] = "Asia/Kolkata"
    snapshot["timetable"][0].update(start_time="16:00:00", end_time="17:10:00")
    runtime.install_snapshot(snapshot)
    clock[0] = clock[0].replace(hour=hour, minute=minute, second=second)
    if not allowed:
        with pytest.raises(ValueError, match="scheduled class"):
            runtime.start_session(1, 1, 1)
        assert runtime.store.sessions() == []
        return
    session = runtime.start_session(1, 1, 1)
    assert parse_stamp(session["started_at"]) == clock[0]
    assert parse_stamp(session["close_at"]) == clock[0] + timedelta(minutes=5)
    runtime.current_qr(session["id"])
    clock[0] += timedelta(minutes=5)
    with pytest.raises(ValueError, match="closed"):
        runtime.current_qr(session["id"])


def test_periods_accept_only_class_times_and_custom_slot_can_move_class(admin):
    section, course = make_section_course(admin)
    response = admin.put(
        "/api/admin/periods",
        json=[
            {
                "number": 1,
                "label": "Evening class",
                "start_time": "16:00",
                "end_time": "17:10",
                "is_break": False,
            }
        ],
    )
    assert response.status_code == 200, response.text
    result = admin.post(
        "/api/admin/timetable",
        json={
            "weekday": 2,
            "period_number": 1,
            "section_id": section,
            "course_id": course,
            "start_time": "15:00",
            "end_time": "16:00",
        },
    )
    assert result.status_code == 200, result.text
    assert result.json()["start_time"] == "15:00"
    assert result.json()["end_time"] == "16:00"


@pytest.mark.parametrize(("minute", "accepted"), [(44, True), (46, False)])
def test_central_ingestion_checks_grace_from_the_original_grant(
    admin, app, tmp_path, monkeypatch, clock, minute, accepted
):
    from datetime import time

    from fastapi.testclient import TestClient

    from attendx.face.engine import FakeFaceEngine
    from attendx.faculty.runtime import FacultyRuntime, stamp
    from attendx.models import TimetableEntry
    from attendx.v2 import sync
    from tests.test_v2_identity import activate, faculty, ok

    section, course = make_section_course(admin)
    student, _ = activate(admin, app, section)
    teacher, lecturer = faculty(admin, app, section, course)
    monkeypatch.setattr(sync, "utcnow", lambda: clock[0])
    with app.state.db.SessionLocal() as db:
        db.add(
            TimetableEntry(
                weekday=clock[0].weekday(),
                period_number=1,
                section_id=section,
                course_id=course,
                faculty_id=teacher["faculty_id"],
                start_time=time(16),
                end_time=time(17, 10),
            )
        )
        db.commit()
    device = ok(lecturer.post("/api/v2/faculty/devices", json={"name": "Grace test"}))
    headers = {"Authorization": "Bearer " + device["credential"]}
    client = TestClient(app)
    snapshot = ok(client.get("/api/v2/sync/snapshot", headers=headers))
    rt = FacultyRuntime(tmp_path / "grace", engine=FakeFaceEngine(), now=lambda: clock[0])
    rt.provision(snapshot, "faculty-pin-9")
    clock[0] = clock[0].replace(hour=11, minute=39)
    session = rt.start_session(section, course, 1)
    rt.mark(session["id"], student["id"], "PRESENT", "Physical identity check")
    rt.close_collection(session["id"])
    rt.approve(session["id"], 1)
    event = rt.pending_events()[0]
    started = clock[0].replace(minute=minute)
    event.update(
        started_at=stamp(started),
        close_at=stamp(started + timedelta(minutes=5)),
        closed_at=stamp(started + timedelta(minutes=5)),
        approved_at=stamp(started + timedelta(minutes=5)),
    )
    clock[0] = started + timedelta(minutes=6)
    response = client.post("/api/v2/sync/events", json=event, headers=headers)
    assert response.status_code == (200 if accepted else 409), response.text
