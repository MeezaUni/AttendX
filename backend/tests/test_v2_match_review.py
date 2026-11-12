"""A match suggests draft presence; faculty and physical reconciliation remain authoritative."""

# ruff: noqa: F811 -- imported pytest fixtures are intentionally injected by name
from datetime import timedelta

import pytest

from tests.test_v2_offline import clock, match, runtime, start  # noqa: F401


def submit_match(runtime, clock, session):
    _, attempt = match(runtime, clock, session)
    clock[0] += timedelta(seconds=5)
    runtime.submit(attempt["attempt_token"], runtime.current_qr(session["id"])["token"], "192.168.137.2")


def test_match_preselection_remains_draft_and_does_not_override_manual_choice(runtime, clock):
    session = start(runtime)
    runtime.mark(session["id"], 1, "ABSENT", "Faculty physically checked the roll")
    submit_match(runtime, clock, session)
    row = runtime.session(session["id"])["roster"][0]
    assert row["status"] == "ABSENT"
    assert row["decision_source"] == "faculty"
    assert row["verification"]["decision"] == "MATCH"
    assert runtime.pending_events() == []


@pytest.mark.parametrize("manual", [False, True])
def test_existing_pending_submission_migrates_only_unapproved_untouched_rows(runtime, tmp_path, clock, manual):
    from attendx.face.engine import FakeFaceEngine
    from attendx.faculty.runtime import FacultyRuntime

    session = start(runtime)
    saved = runtime.store.session(session["id"])
    saved["roster"][0].update(submission={"status": "PENDING_FACULTY_APPROVAL", "method": "face"}, suggested="PRESENT")
    if manual:
        saved["roster"][0].update(method="manual", reason="Faculty explicitly left this for cross-checking")
    with runtime.store.transaction() as db:
        runtime.store.save_session(saved, db)
    reopened = FacultyRuntime(tmp_path / "faculty", engine=FakeFaceEngine(), now=lambda: clock[0])
    reopened.unlock("faculty-pin-9")
    row = reopened.session(session["id"])["roster"][0]
    if manual:
        assert row["status"] == "UNMARKED" and row["method"] == "manual"
    else:
        assert row["status"] == "PRESENT" and row["decision_source"] == "face_suggestion"
    assert reopened.pending_events() == []


def test_headcount_review_prioritizes_missing_submissions_and_supports_recount(runtime, clock):
    session = start(runtime)
    submit_match(runtime, clock, session)
    runtime.close_collection(session["id"])
    runtime.record_headcount(session["id"], 2)
    report = runtime.headcount_review(session["id"], 2)
    assert report["present"] == 1 and report["difference"] == 1
    assert [r["student_id"] for r in report["candidates"]] == [2, 3]
    assert not report["can_approve"]
    runtime.record_headcount(session["id"], 1)
    assert runtime.session(session["id"])["draft_headcount"] == 1
    assert runtime.headcount_review(session["id"], 1)["difference"] == 0
    assert len(runtime.session(session["id"])["audit"]) >= 2
    assert runtime.pending_events() == []


def test_low_headcount_includes_present_rows_for_cross_check(runtime, clock):
    session = start(runtime)
    submit_match(runtime, clock, session)
    report = runtime.headcount_review(session["id"], 0)
    assert report["difference"] == -1
    assert 1 in [r["student_id"] for r in report["candidates"]]
    assert runtime.session(session["id"])["roster"][0]["status"] == "PRESENT"
    with pytest.raises(ValueError):
        runtime.record_headcount(session["id"], -1)


def test_completed_submission_label_reflects_final_approval():
    from attendx.faculty.reconciliation import submission_text

    row = {"submission": {"status": "PENDING_FACULTY_APPROVAL", "method": "face"}}
    assert "awaiting" in submission_text(row)
    assert "approved" in submission_text(row, approved=True).lower()
    assert "awaiting" not in submission_text(row, approved=True)
