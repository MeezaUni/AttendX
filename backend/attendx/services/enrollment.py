"""Face enrollment: images -> quality-checked embeddings -> encrypted template.

Images are decoded in memory, embedded and discarded. Only the template (mean embedding),
counts and quality statistics are stored."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from attendx.db import utcnow
from attendx.face.engine import FaceEngine, decode_image
from attendx.models import FaceTemplate, Student, User
from attendx.services.audit import audit
from attendx.services.verification import EnrollmentError, TemplateCipher, build_template


def enroll(
    db: Session,
    engine: FaceEngine,
    cipher: TemplateCipher,
    student: Student,
    images: list[bytes],
    rt: dict[str, Any],
    *,
    source: str,
    actor: User,
    auto_approve: bool,
    ip: str = "",
) -> dict[str, Any]:
    per_image: list[dict[str, Any]] = []
    embeddings = []
    norms = []
    for k, data in enumerate(images):
        try:
            rgb = decode_image(data, max_side=1600)
        except ValueError as exc:
            per_image.append({"index": k, "ok": False, "problems": [str(exc)]})
            continue
        obs = engine.observe(rgb, rt)
        del rgb
        per_image.append({"index": k, "ok": obs.usable, "problems": obs.problems})
        if obs.usable and obs.embedding is not None:
            embeddings.append(obs.embedding)
            norms.append(obs.feature_norm)
    try:
        template, consistency = build_template(embeddings, rt)
    except EnrollmentError as exc:
        audit(db, actor, "face.enroll_failed", "student", student.id, ip, reason=str(exc))
        db.commit()
        return {"ok": False, "error": str(exc), "images": per_image}

    status = "approved" if auto_approve else "pending"
    now = utcnow()
    if auto_approve:
        for old in db.scalars(
            select(FaceTemplate).where(
                FaceTemplate.student_id == student.id,
                FaceTemplate.status.in_(("approved", "pending")),
            )
        ):
            old.status = "superseded"
    else:
        for old in db.scalars(
            select(FaceTemplate).where(
                FaceTemplate.student_id == student.id, FaceTemplate.status == "pending"
            )
        ):
            old.status = "superseded"
    tpl = FaceTemplate(
        student_id=student.id,
        status=status,
        template_enc=cipher.encrypt(template, engine.model_id),
        model_id=engine.model_id,
        n_frames=len(embeddings),
        mean_quality=float(sum(norms) / len(norms)),
        consistency=consistency,
        source=source,
        consent_at=now,
        created_by_user_id=actor.id,
        approved_by_user_id=actor.id if auto_approve else None,
        approved_at=now if auto_approve else None,
    )
    db.add(tpl)
    student.face_status = "approved" if auto_approve else "pending"
    db.flush()
    audit(
        db, actor, "face.enrolled", "student", student.id, ip,
        template_id=tpl.id, status=status, frames=len(embeddings), source=source,
        consistency=round(consistency, 3),
    )  # fmt: skip
    db.commit()
    return {
        "ok": True,
        "template_id": tpl.id,
        "status": status,
        "frames_used": len(embeddings),
        "consistency": round(consistency, 3),
        "mean_quality": round(tpl.mean_quality, 2),
        "images": per_image,
    }


def active_template(db: Session, student_id: int) -> FaceTemplate | None:
    return db.scalar(
        select(FaceTemplate)
        .where(FaceTemplate.student_id == student_id, FaceTemplate.status == "approved")
        .order_by(FaceTemplate.created_at.desc(), FaceTemplate.id.desc())
    )


def delete_biometrics(db: Session, student: Student, actor: User, ip: str = "") -> int:
    """Permanently delete every face template of the student (right to erasure)."""
    rows = list(db.scalars(select(FaceTemplate).where(FaceTemplate.student_id == student.id)))
    for r in rows:
        db.delete(r)
    student.face_status = "none"
    audit(db, actor, "face.deleted", "student", student.id, ip, templates=len(rows))
    db.commit()
    return len(rows)
