"""Isolated synthetic UI fixture. Never use this factory for a real deployment."""

from pathlib import Path

from sqlalchemy import select

from attendx.config import PROJECT_DIR, Settings
from attendx.face.engine import FakeFaceEngine
from attendx.main import create_app as central_app
from attendx.models import User
from attendx.security import hash_password
from tests.conftest import Client, make_section_course
from tests.test_v2_identity import activate, enroll, faculty, ok, semester


def create_app():
    app = central_app(
        Settings(
            data_dir=PROJECT_DIR / "build/browser-fixture",
            face_engine="fake",
            static_dir=PROJECT_DIR / "frontend/dist",
            legacy_v1_enabled=False,
            cookie_secure=False,
            demo_mode=True,
            mail_transport="memory",
            university_email_domain="example.edu",
        ),
        engine=FakeFaceEngine(),
    )
    with app.state.db.SessionLocal() as db:
        exists = db.scalar(select(User).where(User.username == "browser-admin"))
        if exists:
            return app
        db.add(
            User(
                username="browser-admin",
                role="admin",
                display_name="Synthetic Browser Admin",
                password_hash=hash_password("browser-demo-9"),
            )
        )
        db.commit()
    admin = Client(app)
    admin.login("browser-admin", "browser-demo-9")
    section, course = make_section_course(admin)
    semester(admin, section)
    _, student = activate(admin, app, section, "BROWSER001")
    ok(enroll(student))
    faculty(admin, app, section, cc=True, username="browser-cc")
    faculty(admin, app, section, course, username="browser-faculty")
    return app
