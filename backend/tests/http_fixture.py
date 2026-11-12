"""Synthetic HTTPS service for the real-process offline demonstration only."""

import os
from datetime import time
from pathlib import Path

from sqlalchemy import select

from attendx.config import Settings
from attendx.face.engine import FakeFaceEngine
from attendx.main import create_app as central_app
from attendx.models import TimetableEntry, User
from attendx.security import hash_password
from attendx.services.schedule import local_today
from tests.conftest import Client, make_section_course
from tests.test_v2_identity import activate, faculty, semester


def create_app():
    directory = Path(os.environ["ATTENDX_HTTP_FIXTURE_DATA"])
    app = central_app(
        Settings(
            data_dir=directory,
            face_engine="fake",
            cookie_secure=True,
            timezone="UTC",
            mail_transport="memory",
            legacy_v1_enabled=False,
            university_email_domain="example.edu",
        ),
        engine=FakeFaceEngine(),
    )
    with app.state.db.SessionLocal() as db:
        if db.scalar(select(User).where(User.username == "offline-admin")):
            return app
        db.add(
            User(
                username="offline-admin",
                role="admin",
                display_name="Synthetic Admin",
                password_hash=hash_password("offline-demo-9"),
            )
        )
        db.commit()
    admin = Client(app)
    admin.c.base_url = __import__("httpx").URL("https://testserver")
    admin.login("offline-admin", "offline-demo-9")
    section, course = make_section_course(admin)
    semester(admin, section)
    # These helpers use TestClient HTTP, so use non-Secure cookies only during isolated seeding.
    app.state.settings_obj.cookie_secure = False
    for i in range(3):
        activate(admin, app, section, f"OFFLINE{i}")
    fac, _ = faculty(admin, app, section, course, username="offline-faculty")
    with app.state.db.SessionLocal() as db:
        db.add(
            TimetableEntry(
                weekday=local_today(app.state.settings_obj.tz).weekday(),
                period_number=1,
                section_id=section,
                course_id=course,
                faculty_id=fac["faculty_id"],
                start_time=time(0),
                end_time=time(23, 59, 59),
            )
        )
        db.commit()
    app.state.settings_obj.cookie_secure = True
    return app
