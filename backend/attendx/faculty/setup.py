"""Guided offline classroom preparation. HTTP exposes public trust material only."""

import html
import ipaddress
import plistlib
import threading
import time
import uuid
from functools import wraps
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response

from attendx.faculty.network import create_tls_material, install_shared_tls, validate_tls


def create_phone_setup_app(runtime, ca_path, address, subnet):
    app = FastAPI(docs_url=None, openapi_url=None, redoc_url=None)
    network = ipaddress.ip_network(subnet)
    host = f"{address}:9442"
    ca = x509.load_pem_x509_certificate(Path(ca_path).read_bytes())
    der = ca.public_bytes(serialization.Encoding.DER)
    fingerprint = ca.fingerprint(hashes.SHA256()).hex().upper()

    @app.middleware("http")
    async def local_only(request: Request, call_next):
        try:
            peer = ipaddress.ip_address(request.client.host)
            allowed = peer in network and not peer.is_loopback and str(peer) != address
        except (ValueError, AttributeError):
            allowed = False
        if (
            not allowed
            or request.headers.get("host") != host
            or any(request.headers.get(h) for h in ("forwarded", "x-forwarded-for", "x-forwarded-host"))
        ):
            return JSONResponse({"detail": "Join the faculty Wi-Fi first"}, status_code=403)
        if not runtime.unlocked:
            return JSONResponse({"detail": "Classroom is locked"}, status_code=423)
        if request.method not in ("GET", "HEAD"):
            return JSONResponse({"detail": "This page only provides phone setup"}, status_code=404)
        response = await call_next(request)
        response.headers.update(
            {
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'",
            }
        )
        return response

    @app.get("/", response_class=HTMLResponse)
    def instructions():
        return f"""<!doctype html><html lang="en"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AttendX phone setup</title>
<body style="font:17px system-ui;max-width:36rem;margin:2rem auto;padding:1rem;line-height:1.6">
<h1>One-time phone setup</h1><p>Stay connected to your faculty's Wi-Fi. This certificate lets your browser
use its camera securely on the offline classroom site. This page never collects attendance or photos.</p>
<h2>iPhone</h2><ol><li>Open this page in Safari and
<a href="/classroom.mobileconfig">download the classroom profile</a>.</li>
<li>Open Settings → Profile Downloaded (or General → VPN &amp; Device Management), then Install.</li>
<li>Open Settings → General → About → Certificate Trust Settings.
Enable full trust for the AttendX classroom CA.</li></ol>
<h2>Android</h2><p><a href="/classroom-ca.cer">Download classroom certificate</a>, then install it as a CA certificate
in your phone's security / encryption &amp; credentials settings. Menu names vary by device.</p>
<h2>Check the camera</h2><p><a href="https://{html.escape(address)}:9443/">Open the secure camera check</a>.
Allow the camera and confirm a live preview. Do not bypass a certificate warning; finish trust setup first.</p>
<p>Tell faculty when the camera check works. Authorized AttendX faculty laptops share this trust anchor.
Remove the profile when you stop using this classroom.</p><p>Certificate SHA-256 (compare with the faculty display):</p>
<code style="overflow-wrap:anywhere">{fingerprint}</code></body></html>"""

    @app.get("/classroom.mobileconfig")
    def profile():
        identifier = "org.attendx.classroom." + fingerprint[:24]
        payload = {
            "PayloadType": "Configuration",
            "PayloadVersion": 1,
            "PayloadIdentifier": identifier,
            "PayloadUUID": str(uuid.uuid4()),
            "PayloadDisplayName": "AttendX classroom camera",
            "PayloadDescription": "Trust this faculty laptop for offline classroom camera access.",
            "PayloadContent": [
                {
                    "PayloadType": "com.apple.security.root",
                    "PayloadVersion": 1,
                    "PayloadIdentifier": identifier + ".root",
                    "PayloadUUID": str(uuid.uuid4()),
                    "PayloadDisplayName": "AttendX classroom demo CA",
                    "PayloadContent": der,
                }
            ],
        }
        return Response(
            plistlib.dumps(payload),
            media_type="application/x-apple-aspen-config",
            headers={"Content-Disposition": 'attachment; filename="AttendX-classroom.mobileconfig"'},
        )

    @app.get("/classroom-ca.cer")
    def certificate():
        return Response(
            der,
            media_type="application/pkix-cert",
            headers={"Content-Disposition": 'attachment; filename="AttendX-classroom.cer"'},
        )

    return app


class PhoneSetupListener:
    def __init__(self, runtime, hotspot):
        self.runtime, self.hotspot = runtime, hotspot
        self.server, self.thread = None, None

    def start(self, address, ca_path):
        self.stop()
        import uvicorn

        app = create_phone_setup_app(self.runtime, ca_path, address, self.hotspot.verify_address(address))
        self.server = uvicorn.Server(
            uvicorn.Config(
                app,
                host=address,
                port=9442,
                proxy_headers=False,
                server_header=False,
                access_log=False,
                log_config=None,
                limit_concurrency=16,
                timeout_keep_alive=5,
            )
        )
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 10
        while self.thread.is_alive() and not self.server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        if not self.server.started:
            self.stop()
            raise ValueError("Phone setup could not start on the hotspot; check Windows Firewall")

    def stop(self):
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=5)
        self.server, self.thread = None, None


class ClassroomSetup:
    def __init__(self, runtime, hotspot, listener, phone_setup, *, static_dir, models_dir, lock=None):
        self.runtime, self.hotspot, self.listener, self.phone_setup = runtime, hotspot, listener, phone_setup
        self.static_dir, self.models_dir = static_dir, models_dir
        self.lock = lock or threading.RLock()

    def serialized(method):
        @wraps(method)
        def call(self, *args, **kwargs):
            with self.lock:
                return method(self, *args, **kwargs)

        return call

    def _guard(self, alive):
        if not alive():
            raise ValueError("Classroom start cancelled because the faculty interface was locked")
        self.runtime._require()

    @serialized
    def prepare(self, ssid, password, *, alive):
        try:
            self._guard(alive)
            if not self.hotspot.started_by_app:
                self.hotspot.start(ssid, password)
            self._guard(alive)
            address = self.hotspot.detect_address()
            self.hotspot.verify_address(address)
            config = self.runtime.store.kv_get("network", {})
            central_config = self.runtime.store.kv_get("central")
            directory = Path(config.get("cert_dir", self.runtime.store.directory / "certs"))
            try:
                validate_tls(directory / "classroom-server.pem", directory / "classroom-server.key", address)
                ca = x509.load_pem_x509_certificate((directory / "classroom-ca.pem").read_bytes())
                if central_config and (
                    not config.get("shared_ca")
                    or config.get("shared_ca_source") != central_config["url"].rstrip("/")
                    or config.get("shared_ca_fingerprint") != ca.fingerprint(hashes.SHA256()).hex().upper()
                ):
                    raise ValueError("Upgrade this laptop's certificate to the shared classroom authority")
            except (OSError, ValueError):
                if central_config:
                    from attendx.faculty.sync_client import CentralClient

                    central = CentralClient(central_config["url"], ca_bundle=central_config.get("ca_bundle") or True)
                    try:
                        directory = install_shared_tls(self.runtime, central, central_config["credential"], address)
                    except Exception as exc:
                        raise ValueError(
                            "Connect this laptop to central once to prepare classroom certificates, then retry Start"
                        ) from exc
                else:
                    # Isolated test/synthetic runtime without a central deployment.
                    directory = self.runtime.store.directory / "certs" / str(uuid.uuid4())
                    create_tls_material(directory, address)
                ca = x509.load_pem_x509_certificate((directory / "classroom-ca.pem").read_bytes())
            fingerprint = ca.fingerprint(hashes.SHA256()).hex().upper()
            self._guard(alive)
            self.listener.start(
                address,
                9443,
                directory / "classroom-server.pem",
                directory / "classroom-server.key",
                phone_trust_verified=False,
                diagnostic_only=True,
                static_dir=self.static_dir,
                models_dir=self.models_dir,
            )
            self.phone_setup.start(address, directory / "classroom-ca.pem")
            self._guard(alive)
            self.runtime.store.kv_set(
                "network", {**config, "ssid": ssid, "address": address, "cert_dir": str(directory)}
            )
            return {
                "address": address,
                "ssid": ssid,
                "password": password,
                "cert_dir": str(directory),
                "fingerprint": fingerprint,
                "phone_ready": config.get("trusted_ca_fingerprint") == fingerprint,
            }
        except Exception:
            self.stop()
            raise

    @serialized
    def begin(self, meeting, prepared, *, phone_confirmed, alive):
        self._guard(alive)
        directory = Path(prepared["cert_dir"])
        ca = x509.load_pem_x509_certificate((directory / "classroom-ca.pem").read_bytes())
        fingerprint = ca.fingerprint(hashes.SHA256()).hex().upper()
        config = self.runtime.store.kv_get("network", {})
        if fingerprint != prepared["fingerprint"] or not (
            phone_confirmed or config.get("trusted_ca_fingerprint") == fingerprint
        ):
            raise ValueError("Finish the one-time phone trust and camera check before starting attendance")
        try:
            self.listener.start(
                prepared["address"],
                9443,
                directory / "classroom-server.pem",
                directory / "classroom-server.key",
                phone_trust_verified=True,
                static_dir=self.static_dir,
                models_dir=self.models_dir,
            )
            self._guard(alive)
            session = self.runtime.start_session(meeting["section_id"], meeting["course_id"], meeting["period_number"])
            self.runtime.store.kv_set("network", {**config, "trusted_ca_fingerprint": fingerprint})
            return session
        except Exception:
            self.stop()
            raise

    @serialized
    def stop(self):
        error = None
        for stop in (self.listener.stop, self.phone_setup.stop, self.hotspot.stop_owned):
            try:
                stop()
            except Exception as exc:
                error = exc
        if error:
            raise error
