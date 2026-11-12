"""Windows Mobile Hotspot via WinRT, isolated HTTPS listener, and local classroom CA.

No global firewall, routing, Tailscale, hostednetwork or unrelated service modifications.
An existing hotspot is never reconfigured or stopped by this controller.
"""

import asyncio
import ipaddress
import json
import os
import socket
import ssl
import subprocess
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def _write_private(path, data):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


def create_tls_material(directory: Path, hotspot_ip: str):
    address = ipaddress.ip_address(hotspot_ip)
    if address.is_loopback or not address.is_private:
        raise ValueError("choose a private classroom hotspot address")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    paths = {
        "ca": directory / "classroom-ca.pem",
        "cert": directory / "classroom-server.pem",
        "key": directory / "classroom-server.key",
    }
    if any(p.exists() for p in paths.values()):
        raise ValueError("certificate files already exist; use a new directory to rotate safely")
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "AttendX classroom demo CA")])
    ca = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=180))
        .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    server_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    server = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hotspot_ip)]))
        .issuer_name(ca_name)
        .public_key(server_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(days=90))
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(address)]), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    # The CA signing private key is discarded. Only this classroom server certificate is usable.
    _write_private(
        paths["key"],
        server_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ),
    )
    paths["ca"].write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    paths["cert"].write_bytes(server.public_bytes(serialization.Encoding.PEM))
    return paths


def validate_tls(cert_path, key_path, hotspot_ip):
    cert = x509.load_pem_x509_certificate(Path(cert_path).read_bytes())
    now = datetime.now(UTC)
    if not cert.not_valid_before_utc <= now < cert.not_valid_after_utc:
        raise ValueError("classroom certificate has expired or is not yet valid")
    addresses = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value.get_values_for_type(
        x509.IPAddress
    )
    if ipaddress.ip_address(hotspot_ip) not in addresses:
        raise ValueError("classroom certificate does not cover the hotspot IP address")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.load_cert_chain(cert_path, key_path)


def install_shared_tls(runtime, central, credential, address):
    """Generate the private key here; central signs only its CSR, using the shared CA."""
    import uuid

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "AttendX faculty laptop")]))
        .sign(key, hashes.SHA256())
    )
    response = central.classroom_certificate(credential, csr.public_bytes(serialization.Encoding.PEM).decode(), address)
    certificate = x509.load_pem_x509_certificate(response["certificate_pem"].encode())
    ca = x509.load_pem_x509_certificate(response["ca_pem"].encode())
    certificate.verify_directly_issued_by(ca)
    if certificate.public_key().public_numbers() != key.public_key().public_numbers():
        raise ValueError("Central certificate did not match this laptop's private key")
    directory = runtime.store.directory / "certs" / str(uuid.uuid4())
    directory.mkdir(parents=True, mode=0o700)
    _write_private(
        directory / "classroom-server.key",
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()),
    )
    (directory / "classroom-server.pem").write_text(response["certificate_pem"], encoding="ascii")
    (directory / "classroom-ca.pem").write_text(response["ca_pem"], encoding="ascii")
    validate_tls(directory / "classroom-server.pem", directory / "classroom-server.key", address)
    config = runtime.store.kv_get("network", {})
    runtime.store.kv_set(
        "network",
        {
            **config,
            "address": address,
            "cert_dir": str(directory),
            "shared_ca": True,
            "shared_ca_fingerprint": ca.fingerprint(hashes.SHA256()).hex().upper(),
            "shared_ca_source": central.url,
        },
    )
    return directory


class HotspotController:
    def __init__(self):
        self.manager = None
        self.started_by_app = False
        self.previous_configuration = None

    def _manager(self):
        if os.name != "nt":
            raise ValueError("Windows Mobile Hotspot requires Windows")
        if self.manager is None:
            from winrt.windows.networking.connectivity import NetworkInformation
            from winrt.windows.networking.networkoperators import NetworkOperatorTetheringManager

            profile = NetworkInformation.get_internet_connection_profile()
            if profile is None:
                profiles = NetworkInformation.get_connection_profiles()
                profile = next((p for p in profiles if p.is_wlan_connection_profile), None)
            if profile is None:
                raise ValueError(
                    "Windows has no usable connection profile for Mobile Hotspot; open Windows hotspot settings"
                )
            capability = NetworkOperatorTetheringManager.get_tethering_capability_from_connection_profile(profile)
            if int(capability) != 0:
                raise ValueError(f"Windows hotspot capability blocked ({capability.name}); use manual attendance")
            self.manager = NetworkOperatorTetheringManager.create_from_connection_profile(profile)
        return self.manager

    def status(self):
        return self._manager().tethering_operational_state.name

    async def _start(self, ssid, password):
        from winrt.windows.networking.networkoperators import NetworkOperatorTetheringAccessPointConfiguration

        manager = self._manager()
        if self.status() == "ON":
            raise ValueError("an existing hotspot is already on; AttendX will not reconfigure it")
        if not 1 <= len(ssid.encode()) <= 32 or not 8 <= len(password) <= 63:
            raise ValueError("hotspot SSID must be 1–32 bytes and password 8–63 characters")
        self.previous_configuration = manager.get_current_access_point_configuration()
        config = NetworkOperatorTetheringAccessPointConfiguration()
        config.ssid, config.passphrase = ssid, password
        await manager.configure_access_point_async(config)
        result = await manager.start_tethering_async()
        if int(result.status) not in (0, 9):
            await manager.configure_access_point_async(self.previous_configuration)
            self.previous_configuration = None
            raise ValueError(
                f"Windows could not start Mobile Hotspot ({result.status.name}); manual attendance remains available"
            )
        self.started_by_app = True

    def start(self, ssid, password):
        asyncio.run(self._start(ssid, password))

    async def _stop(self):
        if self.started_by_app:
            result = await self._manager().stop_tethering_async()
            if int(result.status) != 0:
                raise ValueError(f"Windows could not stop application-managed hotspot ({result.status.name})")
            if self.previous_configuration:
                await self._manager().configure_access_point_async(self.previous_configuration)
            self.started_by_app, self.previous_configuration = False, None

    def stop_owned(self):
        asyncio.run(self._stop())

    def verify_address(self, address):
        ip = ipaddress.ip_address(address)
        if self.status() != "ON":
            raise ValueError("Windows Mobile Hotspot is not ON; student intake is blocked")
        rows = self._addresses()
        row = next((r for r in rows if r["Address"] == str(ip)), None)
        if not row:
            raise ValueError("configured IP is not assigned to a Windows Wi-Fi Direct hotspot adapter")
        return str(ipaddress.ip_network(f"{ip}/{row['Prefix']}", strict=False))

    def detect_address(self):
        if self.status() != "ON":
            raise ValueError("Windows hotspot is not ready yet")
        rows = self._addresses()
        candidates = [
            r["Address"]
            for r in rows
            if ipaddress.ip_address(r["Address"]).is_private and not ipaddress.ip_address(r["Address"]).is_link_local
        ]
        if not candidates:
            raise ValueError("Windows has not assigned a hotspot address yet; wait a moment and try Start again")
        return next((a for a in candidates if a == "192.168.137.1"), candidates[0])

    def _addresses(self):
        # Read only adapter inventory; never bind to campus Wi-Fi, Ethernet, WSL or Tailscale.
        command = (
            "$ErrorActionPreference='Stop'; @(Get-NetIPAddress -AddressFamily IPv4 | ForEach-Object { "
            "$ipRow=$_; $adapter=Get-NetAdapter -IncludeHidden -InterfaceIndex $ipRow.InterfaceIndex "
            "-ErrorAction SilentlyContinue; if($adapter.InterfaceDescription -like '*Wi-Fi Direct Virtual*') { "
            "[pscustomobject]@{Address=$ipRow.IPAddress;Prefix=$ipRow.PrefixLength} } }) | ConvertTo-Json -Compress"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode:
            raise ValueError("unable to verify Windows hotspot interface; intake remains blocked")
        rows = json.loads(result.stdout or "[]")
        if isinstance(rows, dict):
            rows = [rows]
        return rows


class StudentListener:
    def __init__(self, runtime, hotspot):
        self.runtime, self.hotspot, self.server, self.thread = runtime, hotspot, None, None
        self.diagnostic_only = False

    def start(self, address, port, cert, key, *, phone_trust_verified, static_dir, models_dir, diagnostic_only=False):
        if not phone_trust_verified and not diagnostic_only:
            raise ValueError("install and trust the classroom CA on demo phones and verify their browser camera first")
        if self.thread and self.thread.is_alive():
            if self.diagnostic_only == diagnostic_only:
                return
            self.stop()
        subnet = self.hotspot.verify_address(address)
        validate_tls(cert, key, address)
        # Probe the exact owned address without modifying any routes or firewall rules.
        with socket.socket() as probe:
            probe.bind((address, port))
        import uvicorn

        from attendx.faculty.server import create_student_app

        origin = f"https://{address}:{port}"
        app = create_student_app(
            self.runtime,
            address,
            subnet,
            origin,
            static_dir=static_dir,
            models_dir=models_dir,
            diagnostic_only=diagnostic_only,
        )
        self.diagnostic_only = diagnostic_only
        config = uvicorn.Config(
            app,
            host=address,
            port=port,
            ssl_certfile=str(cert),
            ssl_keyfile=str(key),
            proxy_headers=False,
            server_header=False,
            access_log=False,
            log_config=None,
            limit_concurrency=16,
            timeout_keep_alive=5,
        )
        self.server = uvicorn.Server(config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 10
        while self.thread.is_alive() and not self.server.started and time.monotonic() < deadline:
            time.sleep(0.05)
        if not self.server.started:
            self.stop()
            raise ValueError("classroom HTTPS listener failed to start; check certificate, adapter and port")

    def stop(self):
        if self.server:
            self.server.should_exit = True
        if self.thread:
            self.thread.join(timeout=5)
        self.server, self.thread = None, None
