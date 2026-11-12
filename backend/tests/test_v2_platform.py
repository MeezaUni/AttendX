# ruff: noqa: F811 -- imported pytest fixtures are intentionally injected by name
from datetime import timedelta

import pytest

from tests.test_v2_offline import clock, finish_marks, runtime, sample_snapshot, start  # noqa: F401


def test_privacy_lock_after_grant_expiry_closes_intake_and_keeps_records(runtime, clock):
    s = start(runtime)
    finish_marks(runtime, s)
    runtime.approve(s["id"], 2)
    clock[0] += timedelta(hours=25)
    runtime.privacy_lock()
    assert runtime.unlocked is False and len(runtime.pending_events()) == 1


def test_expired_authorization_still_allows_emergency_collection_shutdown(runtime, clock):
    s = start(runtime)
    clock[0] += timedelta(hours=25)
    runtime.privacy_lock()
    assert runtime.unlocked is False
    assert runtime.store.session(s["id"])["state"] == "REVIEW"


def test_online_refresh_can_replace_expired_offline_authorization(runtime, clock):
    clock[0] += timedelta(hours=25)
    runtime.refresh_authorization(sample_snapshot(clock), "faculty-pin-9")
    assert runtime.unlocked
    assert runtime._require()["offline_valid_until"] == sample_snapshot(clock)["offline_valid_until"]


def test_tls_material_has_hotspot_ip_san_and_ca_is_not_trusted_automatically(tmp_path):
    from cryptography import x509

    from attendx.faculty.network import create_tls_material, validate_tls

    paths = create_tls_material(tmp_path / "certs", "192.168.137.1")
    assert paths["ca"].is_file() and paths["cert"].is_file()
    cert = x509.load_pem_x509_certificate(paths["cert"].read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert str(san.get_values_for_type(x509.IPAddress)[0]) == "192.168.137.1"
    validate_tls(paths["cert"], paths["key"], "192.168.137.1")
    with pytest.raises(ValueError):
        validate_tls(paths["cert"], paths["key"], "192.168.137.99")


def test_sync_client_rejects_plain_http_and_retains_events_on_failure(runtime):
    import httpx

    from attendx.faculty.sync_client import CentralClient

    with pytest.raises(ValueError, match="HTTPS"):
        CentralClient("http://central.example")
    s = start(runtime)
    finish_marks(runtime, s)
    runtime.approve(s["id"], 2)
    runtime.store.kv_set("central", {"credential": "test-device-credential"})

    def unavailable(request):
        raise httpx.ConnectError("disconnected")

    transport = httpx.MockTransport(unavailable)
    client = CentralClient(
        "https://central.example", client=httpx.Client(base_url="https://central.example", transport=transport)
    )
    result = client.synchronize(runtime)
    assert result["pending"] == 1 and result["acknowledged"] == 0
    assert runtime.pending_events()[0]["event_id"]


def test_student_server_rejects_host_spoof_and_cross_origin(runtime):
    from fastapi.testclient import TestClient

    from attendx.faculty.server import create_student_app

    app = create_student_app(runtime, "192.168.137.1", "192.168.137.0/24", "https://192.168.137.1:9443")
    c = TestClient(app, base_url="https://192.168.137.1:9443", client=("192.168.137.3", 4000))
    assert c.get("/", headers={"host": "evil.example"}).status_code == 403
    assert (
        c.post(
            "/classroom/api/entry",
            json={"qr_token": "x" * 30},
            headers={"Origin": "https://evil.example", "X-Requested-With": "attendx"},
        ).status_code
        == 403
    )


def test_tls_camera_diagnostic_has_no_attendance_endpoints(runtime):
    from fastapi.testclient import TestClient

    from attendx.faculty.server import create_student_app

    app = create_student_app(
        runtime, "192.168.137.1", "192.168.137.0/24", "https://192.168.137.1:9443", diagnostic_only=True
    )
    client = TestClient(app, base_url="https://192.168.137.1:9443", client=("192.168.137.3", 4000))
    assert "HTTPS camera check" in client.get("/").text
    assert client.get("/camera-check.js").status_code == 200
    assert (
        client.post(
            "/classroom/api/entry",
            json={"qr_token": "x" * 30},
            headers={"Origin": "https://192.168.137.1:9443", "X-Requested-With": "attendx"},
        ).status_code
        == 404
    )


def test_online_snapshot_revocation_locks_cached_intake(runtime):
    import httpx

    from attendx.faculty.sync_client import CentralClient

    client = CentralClient(
        "https://central.example",
        client=httpx.Client(
            base_url="https://central.example",
            transport=httpx.MockTransport(lambda request: httpx.Response(401, json={"detail": "revoked"})),
        ),
    )
    with pytest.raises(httpx.HTTPStatusError):
        client.download("revoked-device-credential", runtime=runtime)
    assert not runtime.unlocked


def test_cancelled_class_in_snapshot_cannot_start_collection(runtime, clock):
    snapshot = sample_snapshot(clock)
    snapshot["cancelled_classes"] = [
        {"date": str(clock[0].date()), "section_id": 1, "course_id": 1, "period_number": 1}
    ]
    runtime.install_snapshot(snapshot)
    with pytest.raises(ValueError, match="cancelled"):
        start(runtime)


def test_frozen_frame_feed_never_passes(runtime, clock):
    s = start(runtime)
    from tests.conftest import png
    from tests.test_v2_offline import entry

    _, a, _ = entry(runtime, s)
    clock[0] += timedelta(seconds=4)
    response = runtime.verify(a["attempt_token"], [png(1)] * 30, list(range(0, 3000, 100)), "192.168.137.2")
    assert response["decision"] == "rejected" and "frozen" in response["reason"]


def test_backoff_predecessor_prevents_amendment_overtaking(runtime):
    import httpx

    from attendx.faculty.sync_client import CentralClient

    s = start(runtime)
    finish_marks(runtime, s)
    runtime.approve(s["id"], 2)
    first = runtime.pending_events()[0]
    with runtime.store.transaction() as db:
        db.execute(
            "UPDATE outbox SET next_attempt=? WHERE id=?", (runtime.now().timestamp() + 36000, first["event_id"])
        )
    runtime.amend(s["id"], 2, "ABSENT", "Physical correction", 1)
    runtime.store.kv_set("central", {"credential": "test-credential"})
    requests = []

    def received(request):
        requests.append(request)
        return httpx.Response(409, json={"detail": "out of order"})

    c = CentralClient(
        "https://central.example",
        client=httpx.Client(base_url="https://central.example", transport=httpx.MockTransport(received)),
    )
    c.synchronize(runtime)
    assert requests == []
