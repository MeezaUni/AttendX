from tests.conftest import ADMIN_PW, Client, make_section_course, make_student, student_client


def test_admin_login_me_logout(app):
    c = Client(app)
    r = c.login("admin", ADMIN_PW)
    assert r.json()["role"] == "admin"
    assert "attendx_session" in r.cookies
    me = c.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["username"] == "admin"
    assert c.post("/api/auth/logout").status_code == 200
    assert c.get("/api/auth/me").status_code == 401


def test_wrong_password_and_unknown_user(app):
    c = Client(app)
    c.login("admin", "nope-nope-1", expect=401)
    c.login("ghost", "whatever-1", expect=401)


def test_login_requires_custom_header(app):
    c = Client(app)
    r = c.c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW})
    assert r.status_code == 400


def test_lockout_after_failures(app):
    c = Client(app)
    for _ in range(5):
        c.login("admin", "wrong-pass-1", expect=401)
    # even the right password is refused while locked
    c.login("admin", ADMIN_PW, expect=429)


def test_login_rate_limit(app):
    app.state.settings_obj.login_per_minute = 3
    c = Client(app)
    for _ in range(3):
        c.login("ghost", "x-wrong-1", expect=401)
    c.login("ghost", "x-wrong-1", expect=429)


def test_csrf_required_for_mutations(admin):
    r = admin.c.post("/api/admin/sections", json={"name": "X"})  # no CSRF header
    assert r.status_code == 403
    r = admin.post("/api/admin/sections", json={"name": "X"}, headers={"X-CSRF-Token": "bad"})
    assert r.status_code == 403
    assert admin.post("/api/admin/sections", json={"name": "X"}).status_code == 200


def test_unauthenticated_and_role_permissions(app, admin):
    anon = Client(app)
    assert anon.get("/api/admin/students").status_code == 401
    assert anon.get("/api/student/today").status_code == 401
    sid, _ = make_section_course(admin)
    make_student(admin, sid)
    stu = student_client(app)
    assert stu.get("/api/admin/students").status_code == 403
    assert stu.get("/api/admin/dashboard").status_code == 403
    assert stu.get("/api/student/today").status_code == 200
    assert admin.get("/api/student/today").status_code == 403


def test_student_must_change_initial_password(app, admin):
    sid, _ = make_section_course(admin)
    make_student(admin, sid)
    c = Client(app)
    r = c.login("R001", "student-pw-1")
    assert r.json()["must_change_password"] is True
    assert c.get("/api/student/today").status_code == 403
    bad = c.post("/api/auth/change-password", json={"current_password": "student-pw-1", "new_password": "short"})
    assert bad.status_code == 400
    ok = c.post("/api/auth/change-password", json={"current_password": "student-pw-1", "new_password": "better-pw-9"})
    assert ok.status_code == 200
    assert c.get("/api/student/today").status_code == 200


def test_passwords_are_hashed(app, admin, db):
    from attendx.models import User

    sid, _ = make_section_course(admin)
    make_student(admin, sid)
    u = db.query(User).filter_by(username="R001").one()
    assert u.password_hash.startswith("$argon2id$")
    assert "student-pw-1" not in u.password_hash


def test_security_headers(app):
    r = Client(app).get("/api/health")
    assert r.status_code == 200
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["permissions-policy"].startswith("camera=(self)")
    assert r.json()["admin_configured"] is True


def test_client_ip_uses_proxy_appended_forwarded_entry(app, db):
    from attendx.models import AuditLog

    c = Client(app)
    r = c.c.post("/api/auth/login", json={"username": "admin", "password": ADMIN_PW},
                 headers={"X-Requested-With": "attendx", "X-Forwarded-For": "6.6.6.6, 100.101.102.103"})  # fmt: skip
    assert r.status_code == 200
    entry = db.query(AuditLog).filter_by(action="auth.login").one()
    assert entry.ip == "100.101.102.103"  # the spoofable client-supplied prefix is ignored
