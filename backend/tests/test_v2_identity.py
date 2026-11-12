"""V2 central contracts. Images are deterministic synthetic pixels, not biometric evidence."""

import json
import re
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from attendx.config import Settings
from attendx.db import utcnow
from tests.conftest import Client, make_section_course, png


@pytest.fixture
def settings(tmp_path):
    return Settings(
        data_dir=tmp_path / "central",
        static_dir=tmp_path / "none",
        face_engine="fake",
        cookie_secure=False,
        legacy_v1_enabled=False,
        mail_transport="memory",
        university_email_domain="example.edu",
        portal_url="https://central.example.edu",
    )


def ok(response, code=200):
    assert response.status_code == code, response.text
    return response.json()


def semester(admin, section):
    d = date.today()
    return ok(
        admin.post(
            "/api/v2/admin/semesters",
            json={
                "name": "Demo semester",
                "academic_year": "2026-27",
                "start_date": str(d - timedelta(days=2)),
                "end_date": str(d + timedelta(days=60)),
                "renewal_deadline": str(d + timedelta(days=53)),
                "section_ids": [section],
                "reminder_days": [30, 7, 1, 0],
            },
        )
    )


def invite(admin, section, roll="V2001"):
    return ok(
        admin.post(
            "/api/v2/admin/students",
            json={
                "roll_number": roll,
                "name": "Synthetic Student",
                "email": f"{roll.lower()}@example.edu",
                "department": "CSE",
                "semester": 5,
                "section_id": section,
            },
        )
    )


def mail_token(app, kind="activate"):
    messages = app.state.mail_sink
    body = next(m["body"] for m in reversed(messages) if f"/{kind}#" in m["body"])
    return re.search(r"#([A-Za-z0-9_-]+)", body).group(1)


def activate(admin, app, section, roll="V2001"):
    student = invite(admin, section, roll)
    token = mail_token(app)
    ok(admin.post("/api/v2/auth/activate", json={"token": token, "password": "student-secret-9"}))
    c = Client(app)
    c.login(roll, "student-secret-9")
    return student, c


def faculty(admin, app, section=None, course=None, *, cc=False, username="lecturer"):
    f = ok(
        admin.post(
            "/api/v2/admin/faculty",
            json={
                "username": username,
                "password": "faculty-secret-9",
                "name": username,
                "email": f"{username}@example.edu",
            },
        )
    )
    if section:
        ok(
            admin.post(
                "/api/v2/admin/assignments",
                json={
                    "faculty_user_id": f["user_id"],
                    "section_id": section,
                    "course_id": course,
                    "kind": "coordinator" if cc else "teaching",
                    "reason": "Synthetic demo assignment",
                },
            )
        )
    c = Client(app)
    c.login(username, "faculty-secret-9")
    return f, c


def enroll(student, *, ident=1, retain=True, password="student-secret-9", n=3):
    files = [("images", (f"sample{i}.png", png(ident, noise=120 + i, tag=i), "image/png")) for i in range(n)]
    return student.post(
        "/api/v2/student/enrollments",
        files=files,
        data={
            "consent": "true",
            "retain_photos": str(retain).lower(),
            "current_password": password,
        },
    )


def submitted(admin, app):
    sec, course = make_section_course(admin)
    semester(admin, sec)
    s, student = activate(admin, app, sec)
    batch = ok(enroll(student))
    _, cc = faculty(admin, app, sec, cc=True, username="coordinator")
    return sec, course, s, student, batch, cc


def test_invitation_activation_is_single_use_and_password_not_returned(admin, app):
    sec, _ = make_section_course(admin)
    s = invite(admin, sec)
    assert s["account_state"] == "PENDING_ACTIVATION"
    assert "initial_password" not in s and "token" not in s
    Client(app).login("V2001", "not-a-password", expect=401)
    token = mail_token(app)
    assert ok(admin.post("/api/v2/auth/activation-info", json={"token": token}))["roll_number"] == "V2001"
    ok(admin.post("/api/v2/auth/activate", json={"token": token, "password": "student-secret-9"}))
    ok(admin.post("/api/v2/auth/activate", json={"token": token, "password": "another-secret-8"}), 400)
    c = Client(app)
    c.login("V2001", "student-secret-9")
    assert ok(c.get("/api/v2/student/enrollment"))["account_state"] == "ACTIVE"
    assert ok(c.get("/api/v2/student/enrollment"))["enrollment_state"] == "NOT_ENROLLED"


def test_duplicate_roll_email_and_wrong_email_domain(admin):
    sec, _ = make_section_course(admin)
    invite(admin, sec)
    payload = dict(roll_number="V2002", name="Other", email="v2001@example.edu", section_id=sec)
    ok(admin.post("/api/v2/admin/students", json=payload), 409)
    payload["email"] = "x@external.example"
    ok(admin.post("/api/v2/admin/students", json=payload), 400)
    payload.update(roll_number="V2001", email="other@example.edu")
    ok(admin.post("/api/v2/admin/students", json=payload), 409)


def test_expired_invitation(admin, app):
    from attendx.v2.models import ActionToken

    sec, _ = make_section_course(admin)
    invite(admin, sec)
    token = mail_token(app)
    with app.state.db.SessionLocal() as db:
        row = db.scalar(select(ActionToken))
        row.expires_at = utcnow() - timedelta(seconds=1)
        db.commit()
    ok(admin.post("/api/v2/auth/activate", json={"token": token, "password": "student-secret-9"}), 400)


def test_reset_is_generic_single_use_and_revokes_sessions(admin, app):
    sec, _ = make_section_course(admin)
    _, student = activate(admin, app, sec)
    anon = TestClient(app)
    a = anon.post("/api/v2/auth/forgot-password", json={"email": "v2001@example.edu"})
    b = anon.post("/api/v2/auth/forgot-password", json={"email": "unknown@example.edu"})
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    token = mail_token(app, "reset")
    ok(anon.post("/api/v2/auth/reset-password", json={"token": token, "password": "new-student-secret-9"}))
    assert student.get("/api/auth/me").status_code == 401
    ok(anon.post("/api/v2/auth/reset-password", json={"token": token, "password": "other-secret-9"}), 400)
    Client(app).login("V2001", "new-student-secret-9")


@pytest.mark.parametrize("n", [1, 2, 4])
def test_requires_exactly_three_samples(admin, app, n):
    sec, _ = make_section_course(admin)
    semester(admin, sec)
    _, student = activate(admin, app, sec)
    ok(enroll(student, n=n), 400)


def test_duplicate_frames_and_mixed_identity_rejected(admin, app):
    sec, _ = make_section_course(admin)
    semester(admin, sec)
    _, student = activate(admin, app, sec)
    for images in ([png(1)] * 3, [png(1, tag=1), png(2, tag=2), png(1, tag=3)]):
        files = [("images", (f"{i}.png", b, "image/png")) for i, b in enumerate(images)]
        ok(
            student.post(
                "/api/v2/student/enrollments",
                files=files,
                data={"consent": "true", "current_password": "student-secret-9"},
            ),
            400,
        )


@pytest.mark.parametrize("ident,norm", [(0, 100), (255, 100), (1, 1)])
def test_invalid_face_samples_rejected(admin, app, ident, norm):
    sec, _ = make_section_course(admin)
    semester(admin, sec)
    _, student = activate(admin, app, sec)
    files = [("images", (f"{i}.png", png(ident, norm=norm, tag=i), "image/png")) for i in range(3)]
    ok(
        student.post(
            "/api/v2/student/enrollments", files=files, data={"consent": "true", "current_password": "student-secret-9"}
        ),
        400,
    )


def test_cc_scope_admin_approval_photo_privacy_and_encryption(admin, app):
    from attendx.v2.models import EnrollmentSample

    sec, course, s, student, batch, cc = submitted(admin, app)
    bid = batch["id"]
    assert batch["status"] == "PENDING_CC_VERIFICATION"
    assert len(batch["samples"]) == 3
    ok(admin.post(f"/api/v2/admin/enrollments/{bid}/approve"), 409)
    _, lecturer = faculty(admin, app, sec, course)
    other_sec = ok(admin.post("/api/admin/sections", json={"name": "OTHER"}))["id"]
    _, other_cc = faculty(admin, app, other_sec, cc=True, username="wrong-cc")
    photo = batch["samples"][0]["photo_url"]
    assert student.get(photo).status_code == 200
    assert cc.get(photo).status_code == 200
    assert lecturer.get(photo).status_code == 403
    assert other_cc.get(photo).status_code == 403
    assert admin.get(photo).status_code == 403  # explicit admin photo policy defaults off
    assert TestClient(app).get(photo).status_code == 401
    ok(other_cc.post(f"/api/v2/faculty/enrollments/{bid}/verify", json={"decision": "confirm", "in_person": True}), 403)
    ok(cc.post(f"/api/v2/faculty/enrollments/{bid}/verify", json={"decision": "confirm", "in_person": False}), 400)
    result = ok(cc.post(f"/api/v2/faculty/enrollments/{bid}/verify", json={"decision": "confirm", "in_person": True}))
    assert result["status"] == "PENDING_ADMIN_APPROVAL"
    ok(cc.post(f"/api/v2/admin/enrollments/{bid}/approve"), 403)
    assert ok(admin.post(f"/api/v2/admin/enrollments/{bid}/approve"))["status"] == "ACTIVE"
    assert cc.get(photo).status_code == 403  # review access ends after final approval
    with app.state.db.SessionLocal() as db:
        sample = db.scalar(select(EnrollmentSample))
        assert b"PNG" not in sample.photo_enc
        assert sample.embedding_enc.startswith(b"gAAAA")
    status = ok(student.get("/api/v2/student/enrollment"))
    assert status["enrollment_state"] == "ACTIVE" and status["days_until_expiry"] in (59, 60)
    assert "password" not in json.dumps(ok(lecturer.get("/api/v2/faculty/snapshot"))).lower()


def test_cc_rejection_and_no_retained_images(admin, app):
    sec, _ = make_section_course(admin)
    semester(admin, sec)
    _, student = activate(admin, app, sec)
    batch = ok(enroll(student, retain=False))
    assert all(s["photo_url"] is None for s in batch["samples"])
    _, cc = faculty(admin, app, sec, cc=True)
    result = ok(
        cc.post(
            f"/api/v2/faculty/enrollments/{batch['id']}/verify",
            json={"decision": "reject", "in_person": True, "reason": "Trusted identity documents differ"},
        )
    )
    assert result["status"] == "CC_REJECTED"
    ok(admin.post(f"/api/v2/admin/enrollments/{batch['id']}/approve"), 409)


def test_renewal_preserves_old_active_until_final_approval_and_consent_revocation(admin, app):
    from attendx.v2.models import EnrollmentBatch

    sec, _, s, student, batch, cc = submitted(admin, app)
    bid = batch["id"]
    ok(cc.post(f"/api/v2/faculty/enrollments/{bid}/verify", json={"decision": "confirm", "in_person": True}))
    ok(admin.post(f"/api/v2/admin/enrollments/{bid}/approve"))
    renewal = ok(enroll(student))
    assert renewal["version"] == 2
    with app.state.db.SessionLocal() as db:
        assert db.get(EnrollmentBatch, bid).status == "ACTIVE"
    ok(cc.post(f"/api/v2/faculty/enrollments/{renewal['id']}/verify", json={"decision": "confirm", "in_person": True}))
    ok(admin.post(f"/api/v2/admin/enrollments/{renewal['id']}/approve"))
    with app.state.db.SessionLocal() as db:
        assert db.get(EnrollmentBatch, bid).status == "SUPERSEDED"
    ok(student.post("/api/v2/student/consent/revoke"))
    assert ok(student.get("/api/v2/student/enrollment"))["enrollment_state"] == "REVOKED"


def test_v1_approval_password_and_remote_attendance_bypasses_disabled(admin, app):
    sec, _ = make_section_course(admin)
    _, student = activate(admin, app, sec)
    for path in (
        "/api/admin/students",
        "/api/admin/students/1/reset-password",
        "/api/admin/students/1/face",
        "/api/admin/templates/1/approve",
        "/api/student/attendance/challenge",
        "/api/student/enrollment",
    ):
        assert admin.post(path, json={}).status_code == 410, path
    assert student.post("/api/student/attendance/challenge", json={"session_id": 1}).status_code == 410
