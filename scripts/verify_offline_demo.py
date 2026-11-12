"""Real HTTPS disconnect/restart/retry demo with isolated synthetic academic data.

No production service, route, credential, biometric image or database is used.
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
URL = "https://127.0.0.1:18480"
PIN = "synthetic-faculty-pin-9"


def tls(directory):
    import ipaddress

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "AttendX isolated HTTPS test")])
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .sign(key, hashes.SHA256())
    )
    (directory / "test-ca.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (directory / "test-server.key").write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )


def actor(stage, directory):
    from attendx.face.engine import FakeFaceEngine
    from attendx.faculty.runtime import FacultyRuntime
    from attendx.faculty.sync_client import CentralClient

    runtime = FacultyRuntime(directory / "faculty", engine=FakeFaceEngine())
    central = CentralClient(URL, ca_bundle=str(directory / "test-ca.pem"))
    if stage == "provision":
        device = central.provision("offline-faculty", "faculty-secret-9", "Synthetic HTTPS laptop")
        snapshot = central.download(device["credential"])
        runtime.provision(snapshot, PIN)
        runtime.store.kv_set("central", {"url": URL, **device})
        return {"roster_count": len(snapshot["classes"][0]["roster"]), "central_https_verified": True}
    assert not runtime.unlocked
    runtime.unlock(PIN)
    if stage == "offline":
        c = runtime._require()["classes"][0]
        session = runtime.start_session(c["section_id"], c["course_id"], 1)
        for i, row in enumerate(session["roster"]):
            runtime.mark(
                session["id"], row["student_id"], "PRESENT" if i < 2 else "ABSENT", "Synthetic physical roll call"
            )
        runtime.close_collection(session["id"])
        runtime.approve(session["id"], 2)
        result = central.synchronize(runtime)
        assert result["pending"] == 1 and result["acknowledged"] == 0
        return {"approved_offline": True, "pending_after_connection_refused": result["pending"]}
    if stage == "restart":
        sessions = runtime.list_sessions()
        assert sessions[0]["state"] == "APPROVED" and len(runtime.pending_events()) == 1
        return {"approved_after_separate_process_restart": True, "pending": 1}
    if stage == "sync":
        deadline = time.monotonic() + 20
        while runtime.pending_events() and time.monotonic() < deadline:
            central.synchronize(runtime)
            if runtime.pending_events():
                time.sleep(0.25)
        assert not runtime.pending_events()
        config = runtime.store.kv_get("central")
        with runtime.store.connect() as db:
            event = runtime.store.decode(db.execute("SELECT enc FROM outbox ORDER BY rowid LIMIT 1").fetchone()[0])
        headers = {"Authorization": "Bearer " + config["credential"]}
        for _ in range(2):
            r = central.client.post("/api/v2/sync/events", json=event, headers=headers)
            r.raise_for_status()
            assert r.json()["duplicate"]
        login = central.client.post(
            "/api/auth/login",
            json={"username": "offline-faculty", "password": "faculty-secret-9"},
            headers={"X-Requested-With": "attendx"},
        )
        login.raise_for_status()
        records = central.client.get("/api/v2/faculty/attendance")
        records.raise_for_status()
        assert len(records.json()) == 1 and len(records.json()[0]["roster"]) == 3
        return {
            "central_approved_meetings": 1,
            "central_roster_marks": 3,
            "duplicate_retries": 2,
            "remaining_outbox": 0,
        }
    raise ValueError("unknown demonstration stage")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--actor", choices=["provision", "offline", "restart", "sync"])
    parser.add_argument("--directory", type=Path)
    args = parser.parse_args()
    if args.actor:
        print(json.dumps(actor(args.actor, args.directory)))
        return
    import httpx

    directory = ROOT / "build" / ("offline-http-" + uuid.uuid4().hex[:8])
    directory.mkdir(parents=True)
    tls(directory)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 18480))
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "backend")
    env["ATTENDX_HTTP_FIXTURE_DATA"] = str(directory / "central")
    process = None
    log = (directory / "central.log").open("w", encoding="utf-8")

    def start_central():
        nonlocal process
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "tests.http_fixture:create_app",
                "--factory",
                "--host",
                "127.0.0.1",
                "--port",
                "18480",
                "--no-access-log",
                "--ssl-certfile",
                str(directory / "test-ca.pem"),
                "--ssl-keyfile",
                str(directory / "test-server.key"),
            ],
            cwd=ROOT / "backend",
            env=env,
            stdout=log,
            stderr=log,
        )
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("synthetic service startup failed; inspect " + str(directory / "central.log"))
            try:
                with httpx.Client(verify=str(directory / "test-ca.pem"), timeout=1) as c:
                    if c.get(URL + "/api/health").status_code == 200:
                        return
            except httpx.HTTPError:
                pass
            time.sleep(0.2)
        raise RuntimeError("synthetic central HTTPS service did not become ready")

    def run(stage):
        result = subprocess.run(
            [sys.executable, str(Path(__file__).resolve()), "--actor", stage, "--directory", str(directory)],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    try:
        start_central()
        report = {"provision": run("provision")}
        process.terminate()
        process.wait(timeout=10)
        process = None
        report["offline"] = run("offline")
        report["restart"] = run("restart")
        start_central()
        report["sync"] = run("sync")
        report["synthetic_faces_used"] = False
        report["report_path"] = str(directory / "report.json")
        (directory / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2))
    finally:
        if process and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        log.close()


if __name__ == "__main__":
    main()
