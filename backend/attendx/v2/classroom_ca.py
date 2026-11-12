"""One classroom trust anchor; device keys stay on their individual laptops."""

import ipaddress
import plistlib
import threading
import uuid
from datetime import UTC, datetime, timedelta

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy.exc import IntegrityError

from attendx.db import utcnow
from attendx.deps import get_db
from attendx.services.audit import audit
from attendx.services.schedule import local_today
from attendx.v2.identity import valid_assignments
from attendx.v2.models import ClassroomAuthority
from attendx.v2.sync import device_auth

router = APIRouter(prefix="/api/v2", tags=["classroom-trust"])
_creation_lock = threading.Lock()


def authority(db, state):
    with _creation_lock:
        row = db.get(ClassroomAuthority, 1)
        if row is None:
            key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
            now = datetime.now(UTC)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "AttendX offline classroom CA")])
            cert = (
                x509.CertificateBuilder()
                .subject_name(name)
                .issuer_name(name)
                .public_key(key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(minutes=5))
                .not_valid_after(now + timedelta(days=1095))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .add_extension(x509.KeyUsage(True, False, False, False, False, True, True, False, False), critical=True)
                .sign(key, hashes.SHA256())
            )
            row = ClassroomAuthority(
                id=1,
                certificate_pem=cert.public_bytes(serialization.Encoding.PEM),
                private_key_enc=state.cipher.seal(
                    key.private_bytes(
                        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
                    )
                ),
                expires_at=cert.not_valid_after_utc.replace(tzinfo=None),
            )
            db.add(row)
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                row = db.get(ClassroomAuthority, 1)
        if row.expires_at <= utcnow():
            raise HTTPException(503, "Classroom authority expired; administrator must rotate it and notify phone users")
        return row


def phone_profile(ca_pem):
    cert = x509.load_pem_x509_certificate(ca_pem)
    identifier = "org.attendx.classroom." + cert.fingerprint(hashes.SHA256()).hex()[:24]
    return plistlib.dumps(
        {
            "PayloadType": "Configuration",
            "PayloadVersion": 1,
            "PayloadIdentifier": identifier,
            "PayloadUUID": str(uuid.uuid4()),
            "PayloadDisplayName": "AttendX offline classroom camera",
            "PayloadDescription": "One-time classroom camera trust for authorized AttendX faculty laptops.",
            "PayloadContent": [
                {
                    "PayloadType": "com.apple.security.root",
                    "PayloadVersion": 1,
                    "PayloadIdentifier": identifier + ".root",
                    "PayloadUUID": str(uuid.uuid4()),
                    "PayloadDisplayName": "AttendX offline classroom CA",
                    "PayloadContent": cert.public_bytes(serialization.Encoding.DER),
                }
            ],
        }
    )


@router.get("/public/classroom-ca.cer")
def public_ca(request: Request, db=Depends(get_db)):
    ca = x509.load_pem_x509_certificate(authority(db, request.app.state).certificate_pem)
    return Response(
        ca.public_bytes(serialization.Encoding.DER),
        media_type="application/pkix-cert",
        headers={"Content-Disposition": 'attachment; filename="AttendX-classroom.cer"'},
    )


@router.get("/public/classroom.mobileconfig")
def public_profile(request: Request, db=Depends(get_db)):
    return Response(
        phone_profile(authority(db, request.app.state).certificate_pem),
        media_type="application/x-apple-aspen-config",
        headers={"Content-Disposition": 'attachment; filename="AttendX-classroom.mobileconfig"'},
    )


class CertificateRequest(BaseModel):
    csr_pem: str = Field(min_length=100, max_length=16000)
    address: str = Field(max_length=45)


@router.post("/sync/classroom-certificate")
def issue_certificate(body: CertificateRequest, request: Request, identity=Depends(device_auth), db=Depends(get_db)):
    device, user = identity
    if not valid_assignments(db, user.id, local_today(request.app.state.settings_obj.tz), "teaching"):
        raise HTTPException(403, "A current teaching assignment is required")
    if not request.app.state.limiter.hit(f"classroom-cert:{device.id}", 5):
        raise HTTPException(429, "Too many certificate requests; retry later")
    try:
        address = ipaddress.ip_address(body.address)
        private_ranges = [ipaddress.ip_network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
        if not any(address in n for n in private_ranges):
            raise ValueError("Classroom certificates are restricted to private hotspot IPv4 addresses")
        csr = x509.load_pem_x509_csr(body.csr_pem.encode())
        key = csr.public_key()
        if not csr.is_signature_valid or not isinstance(key, rsa.RSAPublicKey) or key.key_size < 2048:
            raise ValueError("A valid CSR with an RSA key of at least 2048 bits is required")
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    row = authority(db, request.app.state)
    ca = x509.load_pem_x509_certificate(row.certificate_pem)
    ca_key = serialization.load_pem_private_key(request.app.state.cipher.open(row.private_key_enc), password=None)
    now = datetime.now(UTC)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, f"AttendX faculty device {device.id}")]))
        .issuer_name(ca.subject)
        .public_key(key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(min(now + timedelta(days=90), ca.not_valid_after_utc))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName([x509.IPAddress(address)]), critical=False)
        .add_extension(x509.ExtendedKeyUsage([x509.oid.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    audit(db, user, "v2.classroom_certificate_issued", "faculty_device", device.id, "", address=str(address))
    db.commit()
    return {
        "certificate_pem": certificate.public_bytes(serialization.Encoding.PEM).decode(),
        "ca_pem": row.certificate_pem.decode(),
        "fingerprint": ca.fingerprint(hashes.SHA256()).hex().upper(),
    }
