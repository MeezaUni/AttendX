"""One public classroom CA, isolated laptop keys, private-address-only issuance."""

# ruff: noqa: F811 -- imported pytest fixtures are intentionally injected by name

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi.testclient import TestClient

from tests.conftest import make_section_course
from tests.test_v2_identity import faculty, ok, settings  # noqa: F401
from tests.test_v2_offline import clock, runtime  # noqa: F401


def csr():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    request = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "faculty-laptop")]))
        .sign(key, hashes.SHA256())
    )
    return key, request.public_bytes(serialization.Encoding.PEM).decode()


def test_laptops_share_one_ca_without_sharing_private_keys(admin, app):
    section, course = make_section_course(admin)
    _, lecturer = faculty(admin, app, section, course)
    public = TestClient(app)
    roots = []
    for n in range(2):
        device = ok(lecturer.post("/api/v2/faculty/devices", json={"name": f"Laptop {n}"}))
        headers = {"Authorization": "Bearer " + device["credential"]}
        key, request = csr()
        signed = public.post(
            "/api/v2/sync/classroom-certificate", headers=headers, json={"csr_pem": request, "address": "192.168.137.1"}
        )
        assert signed.status_code == 200, signed.text
        data = signed.json()
        cert = x509.load_pem_x509_certificate(data["certificate_pem"].encode())
        ca = x509.load_pem_x509_certificate(data["ca_pem"].encode())
        cert.verify_directly_issued_by(ca)
        assert cert.public_key().public_numbers() == key.public_key().public_numbers()
        assert b"PRIVATE KEY" not in signed.content
        roots.append(data["ca_pem"])
    assert roots[0] == roots[1]
    assert public.get("/api/v2/public/classroom-ca.cer").status_code == 200
    assert public.get("/api/v2/public/classroom.mobileconfig").status_code == 200
    _, request = csr()
    assert (
        public.post(
            "/api/v2/sync/classroom-certificate", json={"csr_pem": request, "address": "192.168.137.1"}
        ).status_code
        == 401
    )
    assert (
        public.post(
            "/api/v2/sync/classroom-certificate", headers=headers, json={"csr_pem": request, "address": "8.8.8.8"}
        ).status_code
        == 400
    )
    from attendx.v2.models import ClassroomAuthority

    with app.state.db.SessionLocal() as db:
        row = db.get(ClassroomAuthority, 1)
        assert b"PRIVATE KEY" not in row.private_key_enc
        assert b"PRIVATE KEY" in app.state.cipher.open(row.private_key_enc)


def test_cached_shared_certificate_prepares_offline_without_contacting_central(
    admin, app, runtime, tmp_path, monkeypatch
):
    from attendx.faculty.network import install_shared_tls
    from attendx.faculty.setup import ClassroomSetup
    from attendx.faculty.sync_client import CentralClient
    from tests.test_v2_start_flow import Hotspot, Listener

    section, course = make_section_course(admin)
    _, lecturer = faculty(admin, app, section, course)
    device = ok(lecturer.post("/api/v2/faculty/devices", json={"name": "Offline certificate cache"}))
    central = CentralClient("https://central.example", client=TestClient(app))
    runtime.store.kv_set("central", {"url": central.url, "credential": device["credential"]})
    directory = install_shared_tls(runtime, central, device["credential"], "192.168.137.1")
    assert (directory / "classroom-server.key").exists()

    def offline(*args, **kwargs):
        raise AssertionError("An offline class must not require a central certificate request")

    monkeypatch.setattr(CentralClient, "classroom_certificate", offline)
    flow = ClassroomSetup(runtime, Hotspot(), Listener(), Listener(), static_dir=tmp_path, models_dir=tmp_path)
    prepared = flow.prepare("AttendX-Test", "test-wifi-9", alive=lambda: runtime.unlocked)
    assert prepared["fingerprint"] == runtime.store.kv_get("network")["shared_ca_fingerprint"]
    flow.stop()
