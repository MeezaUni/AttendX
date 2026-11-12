"""One guided classroom start, with fake hardware and real crypto/storage/state."""

# ruff: noqa: F811 -- imported pytest fixtures are intentionally injected by name
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from tests.test_v2_offline import clock, runtime  # noqa: F401


class Hotspot:
    started_by_app = False

    def status(self):
        return "ON" if self.started_by_app else "OFF"

    def start(self, ssid, password):
        self.started_by_app = True

    def detect_address(self):
        return "192.168.137.1"

    def verify_address(self, address):
        return "192.168.137.0/24"

    def stop_owned(self):
        self.started_by_app = False


class Listener:
    server = None
    diagnostic_only = False

    def start(self, *args, **kwargs):
        self.server = True
        self.diagnostic_only = kwargs.get("diagnostic_only", False)

    def stop(self):
        self.server = None


def test_setup_prepares_network_before_timer_and_reuses_phone_trust(runtime, clock, tmp_path):
    from attendx.faculty.setup import ClassroomSetup

    hotspot, listener, bootstrap = Hotspot(), Listener(), Listener()
    flow = ClassroomSetup(runtime, hotspot, listener, bootstrap, static_dir=tmp_path, models_dir=tmp_path)
    prepared = flow.prepare("AttendX-Test", "test-wifi-123", alive=lambda: runtime.unlocked)
    assert hotspot.started_by_app and listener.diagnostic_only
    assert runtime.store.sessions() == []  # No collection time spent installing phone trust.
    assert not prepared["phone_ready"]
    first_cert = prepared["fingerprint"]
    clock[0] += timedelta(minutes=2)
    session = flow.begin(
        runtime.available_meetings()[0], prepared, phone_confirmed=True, alive=lambda: runtime.unlocked
    )
    assert session["started_at"] == clock[0].isoformat() + "Z"
    assert session["close_at"] == (clock[0] + timedelta(minutes=5)).isoformat() + "Z"
    assert not listener.diagnostic_only
    flow.stop()
    assert not hotspot.started_by_app and listener.server is None and bootstrap.server is None
    next_setup = flow.prepare("AttendX-Test", "next-wifi-123", alive=lambda: runtime.unlocked)
    assert next_setup["fingerprint"] == first_cert and next_setup["phone_ready"]
    flow.stop()


def test_cancelled_setup_cleans_late_hotspot_and_does_not_start_attendance(runtime, tmp_path):
    from attendx.faculty.setup import ClassroomSetup

    hotspot, listener, bootstrap = Hotspot(), Listener(), Listener()
    flow = ClassroomSetup(runtime, hotspot, listener, bootstrap, static_dir=tmp_path, models_dir=tmp_path)

    def late_start(ssid, password):
        hotspot.started_by_app = True
        runtime.privacy_lock()

    hotspot.start = late_start
    with pytest.raises(ValueError, match="cancelled|locked"):
        flow.prepare("AttendX-Test", "test-wifi-123", alive=lambda: runtime.unlocked)
    assert not hotspot.started_by_app and listener.server is None and runtime.store.sessions() == []


def test_first_time_setup_cannot_skip_phone_confirmation(runtime, tmp_path):
    from attendx.faculty.setup import ClassroomSetup

    flow = ClassroomSetup(runtime, Hotspot(), Listener(), Listener(), static_dir=tmp_path, models_dir=tmp_path)
    prepared = flow.prepare("AttendX-Test", "test-wifi-123", alive=lambda: runtime.unlocked)
    with pytest.raises(ValueError, match="phone|trust"):
        flow.begin(runtime.available_meetings()[0], prepared, phone_confirmed=False, alive=lambda: runtime.unlocked)
    assert runtime.store.sessions() == []
    flow.stop()


def test_http_phone_setup_serves_public_certificate_only(runtime, tmp_path):
    from attendx.faculty.network import create_tls_material
    from attendx.faculty.setup import create_phone_setup_app

    paths = create_tls_material(tmp_path / "certs", "192.168.137.1")
    app = create_phone_setup_app(runtime, paths["ca"], "192.168.137.1", "192.168.137.0/24")
    phone = TestClient(app, client=("192.168.137.2", 1234), base_url="http://192.168.137.1:9442")
    assert phone.get("/").status_code == 200
    profile = phone.get("/classroom.mobileconfig")
    assert profile.status_code == 200 and b"com.apple.security.root" in profile.content
    assert b"PRIVATE KEY" not in profile.content
    assert phone.get("/classroom-ca.cer").status_code == 200
    assert phone.post("/classroom/api/entry", json={}).status_code == 404
    assert phone.get("/classroom-server.key").status_code == 404
    outsider = TestClient(app, client=("10.0.0.2", 1234), base_url="http://192.168.137.1:9442")
    assert outsider.get("/").status_code == 403
    assert phone.get("/", headers={"X-Forwarded-For": "192.168.137.3"}).status_code == 403


def test_legacy_laptop_certificate_requires_shared_authority_migration(runtime, tmp_path, monkeypatch):
    from attendx.faculty.network import create_tls_material
    from attendx.faculty.setup import ClassroomSetup
    from attendx.faculty.sync_client import CentralClient

    directory = tmp_path / "legacy-certs"
    create_tls_material(directory, "192.168.137.1")
    runtime.store.kv_set("network", {"cert_dir": str(directory), "address": "192.168.137.1"})
    runtime.store.kv_set("central", {"url": "https://central.example", "credential": "test-device"})

    def unavailable(*args, **kwargs):
        raise ConnectionError("offline")

    monkeypatch.setattr(CentralClient, "classroom_certificate", unavailable)
    hotspot = Hotspot()
    flow = ClassroomSetup(runtime, hotspot, Listener(), Listener(), static_dir=tmp_path, models_dir=tmp_path)
    with pytest.raises(ValueError, match="central once"):
        flow.prepare("AttendX-Test", "test-wifi-123", alive=lambda: runtime.unlocked)
    assert not hotspot.started_by_app
