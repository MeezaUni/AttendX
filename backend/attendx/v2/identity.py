"""Single-use central credentials, encrypted delivery outbox and scoped enrollment access."""

import hashlib
import json
import secrets
import smtplib
import uuid
from datetime import UTC, datetime, time, timedelta
from email.message import EmailMessage

from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from attendx.db import utcnow
from attendx.deps import Auth, current_auth
from attendx.models import AuthSession, Student, User
from attendx.services.audit import audit
from attendx.services.schedule import local_today
from attendx.v2.models import ActionToken, Assignment, EnrollmentBatch, MailMessage, SectionSemester, Semester

PIPELINE_VERSION = "scrfd-det10g:umeyama-112:adaface-ir101:rgb-l2:v1"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def require_faculty(request: Request, auth: Auth = Depends(current_auth)) -> Auth:
    if auth.user.role != "faculty" or auth.user.faculty_id is None:
        raise HTTPException(403, "faculty access required")
    if auth.user.must_change_password:
        raise HTTPException(403, "password change required")
    return auth


def valid_assignments(db: Session, user_id: int, day, kind: str | None = None):
    q = select(Assignment).where(
        Assignment.faculty_user_id == user_id,
        Assignment.revoked.is_(False),
        Assignment.start_date <= day,
        (Assignment.end_date.is_(None) | (Assignment.end_date >= day)),
    )
    if kind:
        q = q.where(Assignment.kind == kind)
    return list(db.scalars(q))


def is_cc(db: Session, user_id: int, section_id: int | None, day) -> bool:
    return any(a.section_id == section_id for a in valid_assignments(db, user_id, day, "coordinator"))


def section_semester(db: Session, student: Student) -> Semester:
    link = db.get(SectionSemester, student.section_id) if student.section_id else None
    sem = db.get(Semester, link.semester_id) if link else None
    if sem is None:
        raise HTTPException(409, "administrator must configure the section's semester first")
    return sem


def effective_state(batch: EnrollmentBatch | None, day) -> str:
    if batch is None:
        return "NOT_ENROLLED"
    if batch.status == "ACTIVE" and batch.expires_on < day:
        return "EXPIRED"
    return batch.status


def active_batch(db: Session, sid: int, day) -> EnrollmentBatch | None:
    return db.scalar(
        select(EnrollmentBatch)
        .where(EnrollmentBatch.student_id == sid, EnrollmentBatch.status == "ACTIVE", EnrollmentBatch.expires_on >= day)
        .order_by(EnrollmentBatch.version.desc())
    )


def batches(db: Session, sid: int):
    return list(
        db.scalars(
            select(EnrollmentBatch).where(EnrollmentBatch.student_id == sid).order_by(EnrollmentBatch.version.desc())
        )
    )


def queue_mail(db: Session, state, to: str, subject: str, body: str):
    db.add(
        MailMessage(payload_enc=state.cipher.seal(json.dumps({"to": to, "subject": subject, "body": body}).encode()))
    )


def deliver_mail(state):
    """No plaintext tokens/logs on disk; SMTP failures retain encrypted messages for retry."""
    cfg = state.settings_obj
    if cfg.mail_transport == "disabled":
        return
    with state.db.SessionLocal() as db:
        for row in db.scalars(select(MailMessage).where(MailMessage.status == "pending").limit(100)):
            row.attempts += 1
            try:
                payload = json.loads(state.cipher.open(row.payload_enc))
                if cfg.mail_transport == "memory":
                    state.mail_sink.append(payload)
                elif cfg.mail_transport == "smtp":
                    msg = EmailMessage()
                    msg["From"], msg["To"], msg["Subject"] = cfg.mail_from, payload["to"], payload["subject"]
                    msg.set_content(payload["body"])
                    with smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=10) as smtp:
                        if cfg.smtp_starttls:
                            smtp.starttls()
                        if cfg.smtp_username:
                            smtp.login(cfg.smtp_username, cfg.smtp_password or "")
                        smtp.send_message(msg)
                else:
                    raise ValueError("unsupported mail transport")
                row.status, row.last_error = "sent", ""
                # Do not retain usable activation credentials after successful handoff.
                row.payload_enc = state.cipher.seal(
                    json.dumps({"to": payload["to"], "subject": payload["subject"], "body": "[delivered]"}).encode()
                )
            except Exception as exc:
                row.last_error = type(exc).__name__
            db.commit()


def issue_token(db: Session, state, user: User, kind: str):
    db.execute(
        update(ActionToken)
        .where(ActionToken.user_id == user.id, ActionToken.kind == kind, ActionToken.consumed_at.is_(None))
        .values(consumed_at=utcnow())
    )
    value = secrets.token_urlsafe(32)
    cfg = state.settings_obj
    ttl = timedelta(hours=cfg.invitation_hours) if kind == "activate" else timedelta(minutes=cfg.reset_minutes)
    db.add(ActionToken(token_hash=digest(value), user_id=user.id, kind=kind, expires_at=utcnow() + ttl))
    # Fragment keeps the credential out of HTTP access logs and referrer URLs.
    link = f"{cfg.portal_url.rstrip('/')}/{kind}#{value}"
    queue_mail(
        db,
        state,
        user.email,
        f"AttendX: {kind} your central account",
        f"Open this single-use link: {link}\nDo not forward this invitation. It expires in {ttl}.",
    )


def token_user(db: Session, value: str, kind: str, *, consume: bool = False):
    row = db.get(ActionToken, digest(value))
    if row is None or row.kind != kind or row.expires_at <= utcnow() or row.consumed_at is not None:
        raise HTTPException(400, "invalid or expired link")
    if consume:
        result = db.execute(
            update(ActionToken)
            .where(
                ActionToken.token_hash == row.token_hash,
                ActionToken.consumed_at.is_(None),
                ActionToken.expires_at > utcnow(),
            )
            .values(consumed_at=utcnow())
        )
        if result.rowcount != 1:
            raise HTTPException(400, "invalid or expired link")
    user = db.get(User, row.user_id)
    if user is None:
        raise HTTPException(400, "invalid or expired link")
    return user


def revoke_sessions(db: Session, uid: int):
    db.execute(delete(AuthSession).where(AuthSession.user_id == uid))
    from attendx.v2.models import FacultyDevice

    db.execute(update(FacultyDevice).where(FacultyDevice.user_id == uid).values(revoked=True))


def enrollment_out(db: Session, batch: EnrollmentBatch):
    from attendx.v2.models import EnrollmentSample

    return {
        "id": batch.id,
        "student_id": batch.student_id,
        "version": batch.version,
        "status": batch.status,
        "model_id": batch.model_id,
        "pipeline_version": batch.pipeline_version,
        "expires_on": str(batch.expires_on),
        "created_at": batch.created_at.isoformat() + "Z",
        "consent_at": batch.consent_at.isoformat() + "Z",
        "consent_version": batch.consent_version,
        "retain_photos": batch.retain_photos,
        "photo_delete_at": batch.photo_delete_at.isoformat() + "Z",
        "cc_verified_at": batch.cc_verified_at,
        "cc_reason": batch.cc_reason,
        "approved_at": batch.approved_at,
        "samples": [
            {
                "id": s.id,
                "slot": s.slot,
                "quality": json.loads(s.quality),
                "photo_url": f"/api/v2/enrollment-photos/{s.id}"
                if s.photo_enc and batch.photo_delete_at > utcnow()
                else None,
            }
            for s in db.scalars(
                select(EnrollmentSample).where(EnrollmentSample.batch_id == batch.id).order_by(EnrollmentSample.slot)
            )
        ],
    }


def purge_material(db: Session, state, batch: EnrollmentBatch, *, embeddings: bool = False):
    from attendx.v2.models import EnrollmentSample

    for sample in db.scalars(select(EnrollmentSample).where(EnrollmentSample.batch_id == batch.id)):
        sample.photo_enc = None
        if embeddings:
            sample.embedding_enc = b""
    audit(db, None, "v2.biometric_material_deleted", "enrollment", batch.id, embeddings=embeddings)


def maintenance(state):
    """Idempotent expiry/reminder/retention job, run by CLI or desktop scheduler."""
    from attendx.v2.models import Reminder

    day = local_today(state.settings_obj.tz)
    with state.db.SessionLocal() as db:
        for batch in db.scalars(select(EnrollmentBatch)):
            if batch.photo_delete_at <= utcnow():
                from attendx.v2.models import EnrollmentSample

                if db.scalar(
                    select(EnrollmentSample.id).where(
                        EnrollmentSample.batch_id == batch.id, EnrollmentSample.photo_enc.is_not(None)
                    )
                ):
                    purge_material(db, state, batch)
            if batch.expires_on < day:
                if batch.status == "ACTIVE":
                    batch.status = "EXPIRED"
                from attendx.v2.models import EnrollmentSample

                if db.scalar(
                    select(EnrollmentSample.id).where(
                        EnrollmentSample.batch_id == batch.id, EnrollmentSample.embedding_enc != b""
                    )
                ):
                    purge_material(db, state, batch, embeddings=True)
            sem = db.get(Semester, batch.semester_id)
            remaining = (batch.expires_on - day).days
            if batch.status in ("ACTIVE", "EXPIRED") and remaining in json.loads(sem.reminder_days):
                found = db.scalar(
                    select(Reminder.id).where(Reminder.batch_id == batch.id, Reminder.days_before == remaining)
                )
                student = db.get(Student, batch.student_id)
                if found is None and student.user and student.user.email:
                    queue_mail(
                        db,
                        state,
                        student.user.email,
                        "AttendX enrollment renewal",
                        f"Your face enrollment expires in {remaining} days. Sign into the central portal to renew.",
                    )
                    db.add(Reminder(batch_id=batch.id, days_before=remaining))
        db.commit()
    deliver_mail(state)


def new_batch_id():
    return str(uuid.uuid4())


def photo_deadline(cfg, expires_on):
    return min(
        utcnow() + timedelta(days=cfg.photo_retention_days),
        datetime.combine(expires_on + timedelta(days=1), time.min, tzinfo=cfg.tz).astimezone(UTC).replace(tzinfo=None),
    )
