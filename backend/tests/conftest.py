from __future__ import annotations

import io
import json
from datetime import timedelta
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from attendx.config import Settings
from attendx.db import utcnow
from attendx.face.engine import FakeFaceEngine
from attendx.main import create_app
from attendx.models import AttendanceSession, Course, Section, User
from attendx.security import hash_password

ADMIN_PW = "admin-pass-123"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path / "data",
        models_dir=tmp_path / "models",
        static_dir=tmp_path / "no-frontend",
        face_engine="fake",
        cookie_secure=False,
        timezone="Asia/Kolkata",
        legacy_v1_enabled=True,  # V1 compatibility tests; V2 uses fail-closed defaults.
    )


@pytest.fixture
def app(settings: Settings):
    application = create_app(settings, engine=FakeFaceEngine())
    with application.state.db.SessionLocal() as s:
        s.add(User(username="admin", role="admin", display_name="Admin",
                   password_hash=hash_password(ADMIN_PW)))  # fmt: skip
        s.commit()
    return application


@pytest.fixture
def db(app):
    with app.state.db.SessionLocal() as s:
        yield s


class Client:
    """TestClient wrapper that keeps the CSRF token of the signed-in user."""

    def __init__(self, app) -> None:  # type: ignore[no-untyped-def]
        self.c = TestClient(app)
        self.app = app
        self.csrf = ""

    def login(self, username: str, password: str, expect: int = 200):  # type: ignore[no-untyped-def]
        r = self.c.post("/api/auth/login", json={"username": username, "password": password},
                        headers={"X-Requested-With": "attendx"})  # fmt: skip
        assert r.status_code == expect, r.text
        if r.status_code == 200:
            self.csrf = r.json()["csrf_token"]
        return r

    def _h(self, kw):  # type: ignore[no-untyped-def]
        h = dict(kw.pop("headers", {}) or {})
        h.setdefault("X-CSRF-Token", self.csrf)
        return h

    def get(self, url, **kw):  # type: ignore[no-untyped-def]
        return self.c.get(url, **kw)

    def post(self, url, **kw):  # type: ignore[no-untyped-def]
        return self.c.post(url, headers=self._h(kw), **kw)

    def put(self, url, **kw):  # type: ignore[no-untyped-def]
        return self.c.put(url, headers=self._h(kw), **kw)

    def delete(self, url, **kw):  # type: ignore[no-untyped-def]
        return self.c.delete(url, headers=self._h(kw), **kw)


@pytest.fixture
def admin(app) -> Client:
    c = Client(app)
    c.login("admin", ADMIN_PW)
    return c


def new_client(app) -> Client:  # type: ignore[no-untyped-def]
    return Client(app)


# ------------------------------------------------------------------ synthetic images


def png(ident: int, *, noise: int = 128, norm: int = 100, yaw: float = 0.0, pitch: float = 0.5,
        blink: float = 0.0, tag: int = 0) -> bytes:  # fmt: skip
    """Fake-engine image: identity, embedding noise and quality in pixel (0,0); liveness
    metrics in pixel (0,1); ``tag`` makes every frame byte-unique."""
    a = np.full((64, 64, 3), 90, np.uint8)
    a[0, 0] = (ident, noise, norm)
    a[0, 1] = (int(np.clip(128 + yaw * 400, 0, 255)), int(np.clip(128 + (pitch - 0.5) * 400, 0, 255)),
               int(np.clip(blink * 255, 0, 255)))  # fmt: skip
    a[1, 0] = (tag % 256, tag // 256, 7)
    buf = io.BytesIO()
    Image.fromarray(a).save(buf, format="PNG")
    return buf.getvalue()


def frames_for(steps: list[str], ident: int, *, dt: float = 100.0) -> tuple[list[bytes], list[float]]:
    seq: list[dict] = [{}] * 4  # baseline (looking straight)
    for st in steps:
        if st == "turn_left":
            seq += [{"yaw": 0.2}] * 3
        elif st == "turn_right":
            seq += [{"yaw": -0.2}] * 3
        elif st == "look_up":
            seq += [{"pitch": 0.38}] * 3
        elif st == "center":
            seq += [{}] * 3
        elif st == "blink_twice":
            seq += [{}, {"blink": 0.8}, {"blink": 0.8}, {}, {"blink": 0.8}, {}, {}]
    seq += [{}] * 3
    frames = [png(ident, tag=i, noise=120 + (i % 16), **kw) for i, kw in enumerate(seq)]
    return frames, [1000.0 + i * dt for i in range(len(frames))]


def multipart_frames(frames: list[bytes], ts: list[float]):  # type: ignore[no-untyped-def]
    files = [("frames", (f"f{i}.png", f, "image/png")) for i, f in enumerate(frames)]
    return files, {"timestamps": json.dumps(ts)}


# ------------------------------------------------------------------ domain helpers


def make_section_course(admin: Client) -> tuple[int, int]:
    sec = admin.post("/api/admin/sections", json={"name": "CSE-5A", "department": "CSE", "semester": 5})
    assert sec.status_code == 200, sec.text
    crs = admin.post("/api/admin/courses", json={"code": "DL3101", "name": "Deep Learning"})
    assert crs.status_code == 200, crs.text
    return sec.json()["id"], crs.json()["id"]


def make_student(admin: Client, section_id: int, roll: str = "R001", name: str = "Test Student",
                 password: str = "student-pw-1") -> dict:  # fmt: skip
    r = admin.post("/api/admin/students", json={"roll_number": roll, "name": name,
                                                "section_id": section_id, "password": password})  # fmt: skip
    assert r.status_code == 200, r.text
    return r.json()


def student_client(app, roll: str = "R001", password: str = "student-pw-1",  # type: ignore[no-untyped-def]
                   new_password: str = "student-pw-2") -> Client:  # fmt: skip
    c = Client(app)
    c.login(roll, password)
    r = c.post("/api/auth/change-password", json={"current_password": password, "new_password": new_password})
    assert r.status_code == 200, r.text
    return c


def enroll_face(admin: Client, student_id: int, ident: int) -> dict:
    files = [("images", (f"e{i}.png", png(ident, noise=120 + i, tag=i), "image/png")) for i in range(4)]
    r = admin.post(f"/api/admin/students/{student_id}/face", files=files,
                   data={"source": "admin_upload", "consent": "true"})  # fmt: skip
    assert r.status_code == 200, r.text
    return r.json()


def open_session(app, section_id: int, course_id: int, *, period: int = 1, minutes_open: int = 10,
                 offset_min: int = -1) -> int:  # fmt: skip
    """An ad-hoc session for today whose window is open now (server time)."""
    from attendx.services.schedule import local_today

    tz = app.state.settings_obj.tz
    now = utcnow()
    with app.state.db.SessionLocal() as s:
        sess = AttendanceSession(
            date=local_today(tz), period_number=period, section_id=section_id, course_id=course_id,
            start_at=now + timedelta(minutes=offset_min), end_at=now + timedelta(minutes=55),
            open_at=now + timedelta(minutes=offset_min), close_at=now + timedelta(minutes=minutes_open),
            manually_adjusted=True,
        )  # fmt: skip
        s.add(sess)
        s.commit()
        return sess.id


__all__ = ["Section", "Course"]
