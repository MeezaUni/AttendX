"""Migration and security regressions for V2 boundary behavior."""
# ruff: noqa: F811 -- imported pytest fixtures are intentionally injected by name

from datetime import timedelta

from sqlalchemy import select, text

from tests.conftest import make_section_course
from tests.test_v2_identity import activate, ok, settings, submitted  # noqa: F401
from tests.test_v2_offline import clock, finish_marks, runtime, sample_snapshot, start  # noqa: F401


def test_faculty_password_reset_revokes_old_device_credentials(admin, app):
    from fastapi.testclient import TestClient

    from tests.test_v2_identity import faculty, mail_token

    _, faculty_client = faculty(admin, app)
    device = ok(faculty_client.post("/api/v2/faculty/devices", json={"name": "Demo laptop"}))
    anonymous = TestClient(app)
    ok(anonymous.post("/api/v2/auth/forgot-password", json={"email": "lecturer@example.edu"}))
    token = mail_token(app, "reset")
    ok(anonymous.post("/api/v2/auth/reset-password", json={"token": token, "password": "renewed-faculty-secret-9"}))
    assert (
        anonymous.get("/api/v2/sync/snapshot", headers={"Authorization": "Bearer " + device["credential"]}).status_code
        == 401
    )


def test_consent_withdrawal_cannot_be_overwritten_by_inflight_admin_approval(admin, app, monkeypatch):
    import threading

    from attendx.v2 import router as central

    _, _, _, student, batch, cc = submitted(admin, app)
    ok(cc.post(f"/api/v2/faculty/enrollments/{batch['id']}/verify", json={"decision": "confirm", "in_person": True}))
    entered, release = threading.Event(), threading.Event()
    original = central.is_cc

    def paused_authorization(*args, **kwargs):
        allowed = original(*args, **kwargs)
        entered.set()
        assert release.wait(5)
        return allowed

    monkeypatch.setattr(central, "is_cc", paused_authorization)
    responses = []
    worker = threading.Thread(
        target=lambda: responses.append(admin.post(f"/api/v2/admin/enrollments/{batch['id']}/approve"))
    )
    worker.start()
    assert entered.wait(3)
    ok(student.post("/api/v2/student/consent/revoke"))
    release.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert responses[0].status_code == 409
    assert ok(student.get("/api/v2/student/enrollment"))["enrollment_state"] == "REVOKED"


def test_v1_populated_database_migration_preserves_foreign_keys(tmp_path):
    from alembic import command

    from attendx.db import Database
    from attendx.migrate import alembic_config, upgrade_or_create

    db = Database(f"sqlite:///{(tmp_path / 'v1-copy.db').as_posix()}")
    cfg = alembic_config(str(db.engine.url))
    with db.engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0001")
        conn.execute(text("INSERT INTO sections VALUES (1,'S','CSE',5)"))
        conn.execute(text("INSERT INTO students VALUES (1,'R','Student','CSE',5,1,'approved',0,'2026-11-01')"))
        conn.execute(
            text(
                "INSERT INTO users (id,username,password_hash,role,display_name,is_active,must_change_password,student_id,failed_logins,created_at) VALUES (1,'R','hash','student','Student',1,0,1,0,'2026-11-01')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO auth_sessions VALUES ('hashed-token',1,'csrf','2026-11-01','2099-01-01','2026-11-01','','')"
            )
        )
        conn.execute(
            text(
                "INSERT INTO face_templates (id,student_id,status,template_enc,model_id,n_frames,mean_quality,consistency,source,created_at,created_by_user_id) VALUES (1,1,'approved',X'1234','legacy',3,20,.9,'self_live','2026-11-01',1)"
            )
        )
    upgrade_or_create(db)
    with db.engine.connect() as conn:
        for name in ("students", "users", "auth_sessions", "face_templates"):
            assert conn.execute(text(f"SELECT count(*) FROM {name}")).scalar() == 1
        assert conn.execute(text("PRAGMA foreign_keys")).scalar() == 1
        assert conn.execute(text("PRAGMA foreign_key_check")).all() == []
        assert conn.execute(text("SELECT account_state FROM users")).scalar() == "ACTIVE"


def test_password_change_notifies_email_and_invalidates_existing_reset_link(admin, app):
    sec, _ = make_section_course(admin)
    _, student = activate(admin, app, sec)
    from tests.test_v2_identity import mail_token

    ok(student.post("/api/v2/auth/forgot-password", json={"email": "v2001@example.edu"}))
    reset = mail_token(app, "reset")
    before = len(app.state.mail_sink)
    ok(
        student.post(
            "/api/auth/change-password",
            json={"current_password": "student-secret-9", "new_password": "changed-student-secret-9"},
        )
    )
    assert len(app.state.mail_sink) == before + 1
    ok(student.post("/api/v2/auth/reset-password", json={"token": reset, "password": "attacker-old-link-9"}), 400)


def test_legacy_absence_derivation_is_unavailable_in_v2(admin, app):
    sec, _ = make_section_course(admin)
    _, student = activate(admin, app, sec)
    assert student.get("/api/student/history").status_code == 410
    assert admin.get("/api/admin/reports/students").status_code == 410


def test_retention_and_configured_reminder_job_is_idempotent(admin, app):
    from attendx.v2.models import EnrollmentBatch, EnrollmentSample, Semester

    sec, _, _, student, batch, cc = submitted(admin, app)
    ok(cc.post(f"/api/v2/faculty/enrollments/{batch['id']}/verify", json={"decision": "confirm", "in_person": True}))
    ok(admin.post(f"/api/v2/admin/enrollments/{batch['id']}/approve"))
    with app.state.db.SessionLocal() as db:
        b = db.get(EnrollmentBatch, batch["id"])
        b.photo_delete_at = __import__("attendx.db", fromlist=["utcnow"]).utcnow() - timedelta(seconds=1)
        sem = db.get(Semester, b.semester_id)
        sem.reminder_days = "[60]"
        db.commit()
    before = len(app.state.mail_sink)
    ok(admin.post("/api/v2/admin/maintenance"))
    ok(admin.post("/api/v2/admin/maintenance"))
    assert len(app.state.mail_sink) == before + 1
    with app.state.db.SessionLocal() as db:
        assert all(s.photo_enc is None for s in db.scalars(select(EnrollmentSample)))
    assert student.get(batch["samples"][0]["photo_url"]).status_code == 404


def test_refresh_keeps_old_collection_grant_but_uses_new_approval_grant(runtime, clock):
    s = start(runtime)
    finish_marks(runtime, s)
    clock[0] += timedelta(hours=25)
    snap = sample_snapshot(clock)
    snap["grant_id"] = "new-approval-grant"
    runtime.refresh_authorization(snap, "faculty-pin-9")
    runtime.approve(s["id"], 2)
    event = runtime.pending_events()[0]
    assert event["grant_id"] == "test-grant"
    assert event["approval_grant_id"] == "new-approval-grant"


def test_central_reauthorization_rotates_credential_without_changing_device_identity(admin, app):
    from tests.test_v2_identity import faculty

    f, c = faculty(admin, app)
    a = ok(c.post("/api/v2/faculty/devices", json={"name": "Demo laptop"}))
    b = ok(c.post("/api/v2/faculty/devices", json={"name": "Demo laptop", "device_id": a["device_id"]}))
    assert a["device_id"] == b["device_id"]
    assert a["credential"] != b["credential"]
    from fastapi.testclient import TestClient

    anonymous = TestClient(app)
    assert (
        anonymous.get("/api/v2/sync/snapshot", headers={"Authorization": "Bearer " + a["credential"]}).status_code
        == 401
    )
    assert (
        anonymous.get("/api/v2/sync/snapshot", headers={"Authorization": "Bearer " + b["credential"]}).status_code
        == 200
    )
    ok(admin.delete(f"/api/admin/faculty/{f['faculty_id']}"))
    assert (
        anonymous.get("/api/v2/sync/snapshot", headers={"Authorization": "Bearer " + b["credential"]}).status_code
        == 401
    )
