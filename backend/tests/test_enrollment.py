from tests.conftest import enroll_face, make_section_course, make_student, png, student_client


def _imgs(ident, n=4, **kw):  # type: ignore[no-untyped-def]
    return [("images", (f"e{i}.png", png(ident, tag=i, noise=120 + i, **kw), "image/png")) for i in range(n)]


def test_admin_enrollment_creates_encrypted_template(app, admin, db):
    from attendx.models import FaceTemplate

    sid, _ = make_section_course(admin)
    st = make_student(admin, sid)
    res = enroll_face(admin, st["id"], ident=5)
    assert res["ok"] and res["status"] == "approved" and res["frames_used"] == 4
    t = db.query(FaceTemplate).one()
    assert t.status == "approved" and t.n_frames == 4 and t.source == "admin_upload"
    assert len(t.template_enc) > 100 and t.consent_at is not None
    assert admin.get(f"/api/admin/students/{st['id']}").json()["face_status"] == "approved"


def test_enrollment_requires_consent(admin):
    sid, _ = make_section_course(admin)
    st = make_student(admin, sid)
    r = admin.post(f"/api/admin/students/{st['id']}/face", files=_imgs(5), data={"source": "admin_upload"})
    assert r.status_code == 400


def test_enrollment_rejects_bad_images(admin):
    sid, _ = make_section_course(admin)
    st = make_student(admin, sid)
    no_face = admin.post(f"/api/admin/students/{st['id']}/face", files=_imgs(0),
                         data={"source": "admin_upload", "consent": "true"}).json()  # fmt: skip
    assert not no_face["ok"] and no_face["images"][0]["problems"] == ["no face detected"]
    two = admin.post(f"/api/admin/students/{st['id']}/face", files=_imgs(255),
                     data={"source": "admin_upload", "consent": "true"}).json()  # fmt: skip
    assert not two["ok"]
    lowq = admin.post(f"/api/admin/students/{st['id']}/face", files=_imgs(5, norm=40),
                      data={"source": "admin_upload", "consent": "true"}).json()  # fmt: skip
    assert not lowq["ok"] and "low face-image quality" in lowq["images"][0]["problems"]
    garbage = [("images", ("x.png", b"not an image", "image/png"))] * 3
    g = admin.post(f"/api/admin/students/{st['id']}/face", files=garbage,
                   data={"source": "admin_upload", "consent": "true"}).json()  # fmt: skip
    assert not g["ok"]


def test_mixed_identities_rejected(admin):
    sid, _ = make_section_course(admin)
    st = make_student(admin, sid)
    files = _imgs(5, n=2) + [("images", ("z.png", png(9, tag=50), "image/png"))]
    r = admin.post(f"/api/admin/students/{st['id']}/face", files=files,
                   data={"source": "admin_upload", "consent": "true"}).json()  # fmt: skip
    assert not r["ok"] and "same person" in r["error"]


def test_self_enrollment_flow(app, admin):
    sid, _ = make_section_course(admin)
    st = make_student(admin, sid)
    stu = student_client(app)
    files = _imgs(7)
    assert stu.post("/api/student/enrollment", files=files, data={"consent": "true"}).status_code == 403
    admin.post(f"/api/admin/students/{st['id']}/enrollment/open")
    assert stu.get("/api/student/enrollment").json()["can_enroll"] is True
    r = stu.post("/api/student/enrollment", files=_imgs(7), data={"consent": "true"}).json()
    assert r["ok"] and r["status"] == "pending"
    assert stu.get("/api/student/today").json()["face_ready"] is False  # not approved yet
    pending = admin.get("/api/admin/enrollments").json()
    assert len(pending) == 1 and pending[0]["roll_number"] == "R001"
    assert admin.post(f"/api/admin/templates/{pending[0]['id']}/approve").status_code == 200
    assert stu.get("/api/student/today").json()["face_ready"] is True
    # cannot enroll again unless re-opened
    assert stu.post("/api/student/enrollment", files=_imgs(7), data={"consent": "true"}).status_code == 403


def test_revoke_and_delete_biometrics(app, admin, db):
    from attendx.models import AuditLog, FaceTemplate

    sid, _ = make_section_course(admin)
    st = make_student(admin, sid)
    tid = enroll_face(admin, st["id"], 5)["template_id"]
    assert admin.post(f"/api/admin/templates/{tid}/revoke").json()["status"] == "revoked"
    assert admin.get(f"/api/admin/students/{st['id']}").json()["face_status"] == "revoked"
    enroll_face(admin, st["id"], 5)
    r = admin.delete(f"/api/admin/students/{st['id']}/face").json()
    assert r["deleted_templates"] == 2
    assert db.query(FaceTemplate).count() == 0
    assert admin.get(f"/api/admin/students/{st['id']}").json()["face_status"] == "none"
    assert db.query(AuditLog).filter_by(action="face.deleted").count() == 1


def test_reenrollment_supersedes(admin, db):
    from attendx.models import FaceTemplate

    sid, _ = make_section_course(admin)
    st = make_student(admin, sid)
    enroll_face(admin, st["id"], 5)
    enroll_face(admin, st["id"], 5)
    statuses = sorted(t.status for t in db.query(FaceTemplate).all())
    assert statuses == ["approved", "superseded"]
