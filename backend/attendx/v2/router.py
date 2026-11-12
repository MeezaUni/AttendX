"""Central V2 API. Live OpenAPI is the authoritative interface contract."""

import io
import json
import secrets
from datetime import date

import numpy as np
from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Request, Response, UploadFile
from PIL import Image
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from attendx.db import utcnow
from attendx.deps import Auth, client_ip, current_auth, get_db, require_admin, require_student, runtime
from attendx.face.engine import decode_image
from attendx.models import Course, FaceTemplate, Faculty, Section, Student, User
from attendx.routers.admin_people import student_out
from attendx.security import hash_password, password_problem, verify_password
from attendx.services.audit import audit
from attendx.services.schedule import local_today
from attendx.services.verification import EnrollmentError, build_template
from attendx.v2.identity import (
    PIPELINE_VERSION,
    active_batch,
    batches,
    deliver_mail,
    effective_state,
    enrollment_out,
    is_cc,
    issue_token,
    maintenance,
    new_batch_id,
    photo_deadline,
    purge_material,
    queue_mail,
    require_faculty,
    revoke_sessions,
    section_semester,
    token_user,
    valid_assignments,
)
from attendx.v2.models import (
    AdditionalStudent,
    Assignment,
    EnrollmentBatch,
    EnrollmentSample,
    MailMessage,
    SectionSemester,
    Semester,
)

router = APIRouter(prefix="/api/v2", tags=["central-v2"])


def commit(db):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "record conflicts with an existing record") from exc


def get(db, cls, ident):
    value = db.get(cls, ident)
    if value is None:
        raise HTTPException(404, "record not found")
    return value


def validate_email(email: str, cfg):
    email = email.strip().lower()
    parts = email.split("@")
    if (
        len(parts) != 2
        or not parts[0]
        or parts[1] != cfg.university_email_domain.lower()
        or any(c.isspace() or ord(c) < 32 for c in email)
    ):
        raise HTTPException(400, "a registered university email is required")
    return email


class StudentIn(BaseModel):
    roll_number: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9\-_/.]+$")
    name: str = Field(min_length=1, max_length=128)
    email: str = Field(min_length=3, max_length=254)
    department: str = Field(default="", max_length=64)
    semester: int = Field(default=1, ge=1, le=12)
    section_id: int


@router.post("/admin/students")
def create_student(
    body: StudentIn,
    request: Request,
    tasks: BackgroundTasks,
    auth: Auth = Depends(require_admin),
    db: Session = Depends(get_db),
):
    get(db, Section, body.section_id)
    email = validate_email(body.email, request.app.state.settings_obj)
    roll = body.roll_number.strip().upper()
    if db.scalar(select(User.id).where((User.email == email) | (User.username == roll))):
        raise HTTPException(409, "roll number or email already registered")
    student = Student(
        roll_number=roll,
        name=body.name.strip(),
        department=body.department,
        semester=body.semester,
        section_id=body.section_id,
    )
    db.add(student)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "roll number already registered") from exc
    user = User(
        username=roll,
        display_name=student.name,
        role="student",
        student_id=student.id,
        email=email,
        password_hash=hash_password(secrets.token_urlsafe(48)),
        is_active=False,
        account_state="PENDING_ACTIVATION",
    )
    db.add(user)
    db.flush()
    issue_token(db, request.app.state, user, "activate")
    audit(db, auth.user, "v2.student_invited", "student", student.id, auth.ip)
    commit(db)
    db.refresh(student)
    tasks.add_task(deliver_mail, request.app.state)
    return {
        **student_out(student),
        "email": email,
        "account_state": user.account_state,
        "enrollment_state": "NOT_ENROLLED",
        "invitation_delivery": "queued",
    }


@router.post("/admin/students/{sid}/invite")
def resend_invitation(
    sid: int,
    request: Request,
    tasks: BackgroundTasks,
    auth: Auth = Depends(require_admin),
    db: Session = Depends(get_db),
):
    student = get(db, Student, sid)
    if not student.user or student.user.account_state != "PENDING_ACTIVATION":
        raise HTTPException(409, "account is not awaiting activation")
    issue_token(db, request.app.state, student.user, "activate")
    audit(db, auth.user, "v2.invitation_reissued", "student", sid, auth.ip)
    db.commit()
    tasks.add_task(deliver_mail, request.app.state)
    return {"delivery": "queued"}


class CredentialIn(BaseModel):
    token: str = Field(min_length=20, max_length=128)
    password: str = Field(min_length=8, max_length=128)


class TokenIn(BaseModel):
    token: str = Field(min_length=20, max_length=128)


def public_limit(request, action):
    if not request.app.state.limiter.hit(f"v2-{action}:{client_ip(request)}", 10):
        raise HTTPException(429, "too many requests; try later")


@router.post("/auth/activation-info")
def activation_info(body: TokenIn, request: Request, db: Session = Depends(get_db)):
    public_limit(request, "activation-info")
    user = token_user(db, body.token, "activate")
    return {
        "name": user.display_name,
        "roll_number": user.username,
        "email": user.email,
        "consent_notice": "Biometric enrollment is optional. Faculty can mark attendance manually. "
        "Three encrypted templates are used for attendance; retained photos need your consent.",
    }


@router.post("/auth/activate")
def activate(body: CredentialIn, request: Request, db: Session = Depends(get_db)):
    public_limit(request, "activate")
    if problem := password_problem(body.password):
        raise HTTPException(400, problem)
    user = token_user(db, body.token, "activate", consume=True)
    if user.account_state != "PENDING_ACTIVATION":
        raise HTTPException(400, "invalid or expired link")
    user.password_hash, user.account_state, user.is_active = hash_password(body.password), "ACTIVE", True
    user.must_change_password = False
    audit(db, user, "v2.account_activated", "user", user.id, client_ip(request))
    db.commit()
    return {"ok": True, "account_state": "ACTIVE", "enrollment_state": "NOT_ENROLLED"}


class ForgotIn(BaseModel):
    email: str = Field(min_length=1, max_length=254)


@router.post("/auth/forgot-password")
def forgot(body: ForgotIn, request: Request, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    public_limit(request, "forgot")
    user = db.scalar(
        select(User).where(
            User.email == body.email.strip().lower(), User.account_state == "ACTIVE", User.is_active.is_(True)
        )
    )
    if user:
        issue_token(db, request.app.state, user, "reset")
        audit(db, None, "v2.password_reset_requested", "user", user.id, client_ip(request))
        db.commit()
    tasks.add_task(deliver_mail, request.app.state)
    return {"message": "If the account is eligible, a reset link will be sent to its registered email."}


@router.post("/auth/reset-password")
def reset(body: CredentialIn, request: Request, tasks: BackgroundTasks, db: Session = Depends(get_db)):
    public_limit(request, "reset")
    if problem := password_problem(body.password):
        raise HTTPException(400, problem)
    user = token_user(db, body.token, "reset", consume=True)
    if user.account_state != "ACTIVE" or not user.is_active:
        raise HTTPException(400, "invalid or expired link")
    user.password_hash = hash_password(body.password)
    user.must_change_password, user.failed_logins, user.locked_until = False, 0, None
    revoke_sessions(db, user.id)
    queue_mail(
        db, request.app.state, user.email, "AttendX password changed", "Your central portal password was changed."
    )
    audit(db, user, "v2.password_reset_completed", "user", user.id, client_ip(request))
    db.commit()
    tasks.add_task(deliver_mail, request.app.state)
    return {"ok": True}


class FacultyIn(BaseModel):
    username: str = Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    email: str = Field(min_length=3, max_length=254)
    department: str = Field(default="", max_length=64)


@router.post("/admin/faculty")
def create_faculty(
    body: FacultyIn, request: Request, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)
):
    if problem := password_problem(body.password):
        raise HTTPException(400, problem)
    email = validate_email(body.email, request.app.state.settings_obj)
    if db.scalar(select(User.id).where((User.username == body.username) | (User.email == email))):
        raise HTTPException(409, "username or email exists")
    faculty = Faculty(name=body.name, email=email, department=body.department)
    db.add(faculty)
    db.flush()
    user = User(
        username=body.username,
        display_name=body.name,
        password_hash=hash_password(body.password),
        role="faculty",
        faculty_id=faculty.id,
        email=email,
    )
    db.add(user)
    db.flush()
    audit(db, auth.user, "v2.faculty_created", "user", user.id, auth.ip)
    commit(db)
    return {"user_id": user.id, "faculty_id": faculty.id, "name": faculty.name}


class AssignmentIn(BaseModel):
    faculty_user_id: int
    section_id: int
    course_id: int | None = None
    kind: str = Field(pattern="^(teaching|coordinator)$")
    start_date: date | None = None
    end_date: date | None = None
    reason: str = Field(min_length=3, max_length=256)


@router.post("/admin/assignments")
def assign(body: AssignmentIn, request: Request, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    user = get(db, User, body.faculty_user_id)
    if user.role != "faculty":
        raise HTTPException(400, "faculty account required")
    get(db, Section, body.section_id)
    start = body.start_date or local_today(request.app.state.settings_obj.tz)
    if body.end_date and body.end_date < start:
        raise HTTPException(400, "assignment ends before it starts")
    if body.kind == "teaching":
        get(db, Course, body.course_id)
    elif body.course_id is not None:
        raise HTTPException(400, "coordinator scope is a section, not a course")
    row = Assignment(**{**body.model_dump(), "start_date": start}, authorized_by=auth.user.id)
    db.add(row)
    db.flush()
    audit(db, auth.user, "v2.assignment_created", "assignment", row.id, auth.ip, **body.model_dump(mode="json"))
    db.commit()
    return {"id": row.id}


@router.delete("/admin/assignments/{aid}")
def revoke_assignment(aid: int, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    row = get(db, Assignment, aid)
    row.revoked = True
    audit(db, auth.user, "v2.assignment_revoked", "assignment", aid, auth.ip)
    db.commit()
    return {"ok": True}


class AdditionalIn(BaseModel):
    student_id: int
    section_id: int
    course_id: int
    start_date: date
    end_date: date | None = None
    reason: str = Field(min_length=3, max_length=256)


@router.post("/admin/additional-students")
def additional(body: AdditionalIn, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    get(db, Student, body.student_id)
    get(db, Section, body.section_id)
    get(db, Course, body.course_id)
    if body.end_date and body.end_date < body.start_date:
        raise HTTPException(400, "invalid assignment dates")
    row = AdditionalStudent(**body.model_dump(), authorized_by=auth.user.id)
    db.add(row)
    db.flush()
    audit(db, auth.user, "v2.additional_student", "assignment", row.id, auth.ip, **body.model_dump(mode="json"))
    db.commit()
    return {"id": row.id}


class SemesterIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    academic_year: str = Field(min_length=1, max_length=32)
    start_date: date
    end_date: date
    renewal_deadline: date
    section_ids: list[int] = Field(min_length=1, max_length=100)
    reminder_days: list[int] = Field(default=[30, 7, 1, 0], max_length=30)

    @model_validator(mode="after")
    def dates(self):
        if not self.start_date <= self.renewal_deadline <= self.end_date:
            raise ValueError("require start <= renewal deadline <= end")
        if any(n < 0 or n > 366 for n in self.reminder_days):
            raise ValueError("reminder days must be between 0 and 366")
        return self


@router.post("/admin/semesters")
def create_semester(body: SemesterIn, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    for sid in body.section_ids:
        get(db, Section, sid)
    row = Semester(
        **body.model_dump(exclude={"section_ids", "reminder_days"}),
        reminder_days=json.dumps(sorted(set(body.reminder_days), reverse=True)),
    )
    db.add(row)
    db.flush()
    for sid in body.section_ids:
        link = db.get(SectionSemester, sid)
        if link:
            link.semester_id = row.id
        else:
            db.add(SectionSemester(section_id=sid, semester_id=row.id))
    audit(db, auth.user, "v2.semester_configured", "semester", row.id, auth.ip, **body.model_dump(mode="json"))
    db.commit()
    return {"id": row.id, **body.model_dump(mode="json")}


@router.get("/student/enrollment")
def student_enrollment(request: Request, auth: Auth = Depends(require_student), db: Session = Depends(get_db)):
    history = batches(db, auth.student.id)
    day = local_today(request.app.state.settings_obj.tz)
    latest = history[0] if history else None
    active = active_batch(db, auth.student.id, day)
    link = db.get(SectionSemester, auth.student.section_id) if auth.student.section_id else None
    sem = db.get(Semester, link.semester_id) if link else None
    status = effective_state(latest, day)
    if active and sem and (day >= sem.renewal_deadline or active.semester_id != sem.id):
        if latest.id == active.id:
            status = "RE_ENROLLMENT_DUE"
    expiry = active.expires_on if active else (latest.expires_on if latest else (sem.end_date if sem else None))
    return {
        "account_state": auth.user.account_state,
        "enrollment_state": status,
        "days_until_expiry": (expiry - day).days if expiry else None,
        "expires_on": expiry,
        "renewal_deadline": sem.renewal_deadline if sem else None,
        "can_enroll": sem is not None and sem.end_date >= day,
        "active_version": active.version if active else None,
        "history": [enrollment_out(db, b) for b in history],
    }


@router.post("/student/enrollments")
def submit_enrollment(
    request: Request,
    images: list[UploadFile] = File(...),
    consent: bool = Form(False),
    retain_photos: bool = Form(False),
    current_password: str = Form(...),
    auth: Auth = Depends(require_student),
    db: Session = Depends(get_db),
    rt: dict = Depends(runtime),
):
    state = request.app.state
    if not state.limiter.hit(f"v2-enroll:{auth.user.id}", 5):
        raise HTTPException(429, "too many enrollment attempts")
    if not verify_password(auth.user.password_hash, current_password):
        raise HTTPException(400, "central reauthentication failed")
    if not consent or len(images) != 3:
        raise HTTPException(400, "consent and exactly three accepted samples are required")
    sem = section_semester(db, auth.student)
    if sem.end_date < local_today(state.settings_obj.tz):
        raise HTTPException(409, "semester has ended; ask administrator to configure renewal")
    raw, observed, hashes, decoded = [], [], set(), []
    import hashlib

    for upload in images:
        data = upload.file.read(state.settings_obj.max_frame_bytes * 4 + 1)
        if len(data) > state.settings_obj.max_frame_bytes * 4:
            raise HTTPException(413, "sample too large")
        try:
            rgb = decode_image(data, max_side=1600)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        # Pixel hash rejects re-encoded duplicates as well as identical uploaded bytes.
        h = hashlib.sha256(rgb.tobytes()).hexdigest()
        if h in hashes:
            raise HTTPException(400, "duplicate frame; capture three distinct samples")
        hashes.add(h)
        obs = state.engine.observe(rgb, rt)
        if not obs.usable or obs.n_faces != 1:
            raise HTTPException(
                400, {"sample": len(raw) + 1, "errors": obs.problems or ["exactly one usable face required"]}
            )
        raw.append(data)
        observed.append(obs)
        decoded.append(rgb)
    try:
        build_template([o.embedding for o in observed], {**rt, "enroll_min_frames": 3})
    except EnrollmentError as exc:
        raise HTTPException(400, str(exc)) from exc
    previous = batches(db, auth.student.id)
    for old in previous:
        if old.status in ("PENDING_CC_VERIFICATION", "PENDING_ADMIN_APPROVAL", "CC_REJECTED"):
            old.status = "SUPERSEDED"
            purge_material(db, state, old, embeddings=True)
    batch = EnrollmentBatch(
        id=new_batch_id(),
        student_id=auth.student.id,
        semester_id=sem.id,
        version=max((b.version for b in previous), default=0) + 1,
        status="PENDING_CC_VERIFICATION",
        model_id=state.engine.model_id,
        pipeline_version=PIPELINE_VERSION,
        retain_photos=retain_photos,
        photo_delete_at=photo_deadline(state.settings_obj, sem.end_date),
        expires_on=sem.end_date,
    )
    db.add(batch)
    db.flush()
    for i, (obs, rgb) in enumerate(zip(observed, decoded, strict=True), 1):
        photo = None
        if retain_photos:
            buffer = io.BytesIO()
            Image.fromarray(rgb).save(buffer, format="JPEG", quality=90)  # strips EXIF
            photo = state.cipher.seal(buffer.getvalue())
        embedding = np.asarray(obs.embedding, dtype=np.float32)
        embedding /= np.linalg.norm(embedding)
        db.add(
            EnrollmentSample(
                batch_id=batch.id,
                slot=i,
                embedding_enc=state.cipher.encrypt(embedding, batch.model_id),
                photo_enc=photo,
                quality=json.dumps(obs.summary()),
            )
        )
    audit(
        db,
        auth.user,
        "v2.enrollment_submitted",
        "enrollment",
        batch.id,
        auth.ip,
        version=batch.version,
        consent_version=batch.consent_version,
        retain_photos=retain_photos,
    )
    commit(db)
    return enrollment_out(db, batch)


@router.get("/enrollment-photos/{sample_id}")
def photo(sample_id: int, request: Request, auth: Auth = Depends(current_auth), db: Session = Depends(get_db)):
    sample = get(db, EnrollmentSample, sample_id)
    batch = get(db, EnrollmentBatch, sample.batch_id)
    student = get(db, Student, batch.student_id)
    day = local_today(request.app.state.settings_obj.tz)
    allowed = auth.user.student_id == student.id and auth.user.role == "student"
    allowed |= (
        auth.user.role == "faculty"
        and batch.status in ("PENDING_CC_VERIFICATION", "PENDING_ADMIN_APPROVAL")
        and is_cc(db, auth.user.id, student.section_id, day)
    )
    allowed |= auth.user.role == "admin" and request.app.state.settings_obj.admin_photo_access
    if not allowed:
        raise HTTPException(403, "photo access is restricted to the student and authorized enrollment reviewers")
    if sample.photo_enc is None or batch.photo_delete_at <= utcnow():
        raise HTTPException(404, "photo was deleted under the retention policy; metadata remains")
    audit(db, auth.user, "v2.enrollment_photo_viewed", "enrollment", batch.id, auth.ip, sample_id=sample_id)
    db.commit()
    return Response(
        request.app.state.cipher.open(sample.photo_enc),
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store", "Content-Disposition": "inline"},
    )


@router.get("/faculty/enrollments")
def cc_queue(request: Request, auth: Auth = Depends(require_faculty), db: Session = Depends(get_db)):
    sections = [
        a.section_id
        for a in valid_assignments(db, auth.user.id, local_today(request.app.state.settings_obj.tz), "coordinator")
    ]
    return [
        {**enrollment_out(db, b), "name": s.name, "roll_number": s.roll_number, "section_id": s.section_id}
        for b, s in db.execute(
            select(EnrollmentBatch, Student)
            .join(Student, Student.id == EnrollmentBatch.student_id)
            .where(
                Student.section_id.in_(sections),
                EnrollmentBatch.status.in_(("PENDING_CC_VERIFICATION", "PENDING_ADMIN_APPROVAL")),
            )
        )
    ]


class VerifyIn(BaseModel):
    decision: str = Field(pattern="^(confirm|reject)$")
    in_person: bool
    reason: str = Field(default="", max_length=256)


@router.post("/faculty/enrollments/{bid}/verify")
def cc_verify(
    bid: str, body: VerifyIn, request: Request, auth: Auth = Depends(require_faculty), db: Session = Depends(get_db)
):
    batch = get(db, EnrollmentBatch, bid)
    student = get(db, Student, batch.student_id)
    if not is_cc(db, auth.user.id, student.section_id, local_today(request.app.state.settings_obj.tz)):
        raise HTTPException(403, "not the assigned class coordinator")
    if not body.in_person or (body.decision == "reject" and len(body.reason.strip()) < 3):
        raise HTTPException(400, "in-person identity check is required; rejection needs a reason")
    if batch.status != "PENDING_CC_VERIFICATION":
        raise HTTPException(409, "enrollment is not awaiting CC verification")
    changed = db.execute(
        update(EnrollmentBatch)
        .where(
            EnrollmentBatch.id == bid,
            EnrollmentBatch.status == "PENDING_CC_VERIFICATION",
            EnrollmentBatch.student_id.in_(select(Student.id).where(Student.section_id == student.section_id)),
        )
        .values(
            status="PENDING_ADMIN_APPROVAL" if body.decision == "confirm" else "CC_REJECTED",
            cc_user_id=auth.user.id,
            cc_verified_at=utcnow(),
            cc_reason=body.reason,
        )
        .execution_options(synchronize_session="fetch")
    ).rowcount
    if changed != 1:
        raise HTTPException(409, "enrollment or section changed during verification; reload the review queue")
    audit(
        db,
        auth.user,
        "v2.cc_identity_verified",
        "enrollment",
        bid,
        auth.ip,
        decision=body.decision,
        in_person=body.in_person,
        reason=body.reason,
    )
    db.commit()
    return enrollment_out(db, batch)


@router.get("/admin/enrollments")
def admin_queue(_: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    return [
        {**enrollment_out(db, b), "name": s.name, "roll_number": s.roll_number, "section_id": s.section_id}
        for b, s in db.execute(
            select(EnrollmentBatch, Student)
            .join(Student, Student.id == EnrollmentBatch.student_id)
            .order_by(EnrollmentBatch.created_at.desc())
            .limit(1000)
        )
    ]


@router.post("/admin/enrollments/{bid}/approve")
def approve(bid: str, request: Request, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    batch = get(db, EnrollmentBatch, bid)
    if batch.status != "PENDING_ADMIN_APPROVAL" or not batch.cc_verified_at:
        raise HTTPException(409, "assigned CC must verify identity in person first")
    student = get(db, Student, batch.student_id)
    sem = section_semester(db, student)
    day = local_today(request.app.state.settings_obj.tz)
    if batch.expires_on < day or batch.semester_id != sem.id:
        raise HTTPException(409, "enrollment semester is expired or changed")
    if not is_cc(db, batch.cc_user_id, student.section_id, day):
        raise HTTPException(409, "CC authorization changed; in-person verification must be repeated")
    for old in batches(db, batch.student_id):
        if old.id != batch.id and old.status == "ACTIVE":
            old.status = "SUPERSEDED"
            purge_material(db, request.app.state, old, embeddings=True)
    changed = db.execute(
        update(EnrollmentBatch)
        .where(EnrollmentBatch.id == bid, EnrollmentBatch.status == "PENDING_ADMIN_APPROVAL")
        .values(status="ACTIVE", admin_user_id=auth.user.id, approved_at=utcnow())
        .execution_options(synchronize_session="fetch")
    ).rowcount
    if changed != 1:
        raise HTTPException(409, "enrollment changed or consent was withdrawn during approval; reload before retrying")
    audit(db, auth.user, "v2.enrollment_approved", "enrollment", bid, auth.ip, cc_user_id=batch.cc_user_id)
    db.commit()
    return enrollment_out(db, batch)


@router.post("/student/consent/revoke")
def revoke_consent(request: Request, auth: Auth = Depends(require_student), db: Session = Depends(get_db)):
    for batch in batches(db, auth.student.id):
        batch.status = "REVOKED"
        purge_material(db, request.app.state, batch, embeddings=True)
    # Migrated V1 templates must also be erased, even though V2 never distributes them.
    db.execute(delete(FaceTemplate).where(FaceTemplate.student_id == auth.student.id))
    auth.student.face_status = "revoked"
    audit(db, auth.user, "v2.consent_revoked", "student", auth.student.id, auth.ip)
    db.commit()
    return {"ok": True, "enrollment_state": "REVOKED", "manual_attendance_available": True}


@router.post("/admin/maintenance")
def run_maintenance(request: Request, _: Auth = Depends(require_admin)):
    maintenance(request.app.state)
    return {"ok": True}


@router.get("/admin/status")
def admin_status(_: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    return {
        "mail": [
            {"id": m.id, "status": m.status, "attempts": m.attempts, "last_error": m.last_error}
            for m in db.scalars(select(MailMessage).order_by(MailMessage.id.desc()).limit(100))
        ],
        "faculty": [
            {"user_id": u.id, "name": u.display_name, "username": u.username}
            for u in db.scalars(select(User).where(User.role == "faculty"))
        ],
        "semesters": [
            {
                "id": s.id,
                "name": s.name,
                "start_date": s.start_date,
                "end_date": s.end_date,
                "renewal_deadline": s.renewal_deadline,
            }
            for s in db.scalars(select(Semester))
        ],
        "assignments": [
            {
                "id": a.id,
                "faculty_user_id": a.faculty_user_id,
                "kind": a.kind,
                "section_id": a.section_id,
                "course_id": a.course_id,
                "revoked": a.revoked,
                "start_date": a.start_date,
                "end_date": a.end_date,
            }
            for a in db.scalars(select(Assignment))
        ],
    }


@router.get("/faculty/snapshot")
def faculty_snapshot(request: Request, auth: Auth = Depends(require_faculty), db: Session = Depends(get_db)):
    from attendx.v2.sync import snapshot

    return snapshot(db, request.app.state, auth.user)
