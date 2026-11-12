"""Admin: students, sections, courses, faculty, course enrollment and face templates."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from attendx.db import utcnow
from attendx.deps import Auth, get_db, require_admin, runtime
from attendx.models import (
    Course,
    CourseEnrollment,
    FaceTemplate,
    Faculty,
    Section,
    Student,
    TimetableEntry,
    User,
)
from attendx.security import generate_password, hash_password, password_problem
from attendx.services.audit import audit
from attendx.services.enrollment import delete_biometrics, enroll

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _commit(db: Session, what: str) -> None:
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, f"{what} conflicts with an existing record") from exc


# ------------------------------------------------------------------ sections


class SectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    department: str = Field(default="", max_length=64)
    semester: int = Field(default=1, ge=1, le=12)


def section_out(s: Section, n_students: int | None = None) -> dict:
    return {
        "id": s.id, "name": s.name, "department": s.department, "semester": s.semester,
        "students": n_students,
    }  # fmt: skip


@router.get("/sections")
def list_sections(_: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    counts = dict(
        db.execute(select(Student.section_id, func.count()).group_by(Student.section_id)).all()
    )
    return [section_out(s, counts.get(s.id, 0)) for s in db.scalars(select(Section).order_by(Section.name))]


@router.post("/sections")
def create_section(body: SectionIn, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    s = Section(name=body.name.strip(), department=body.department.strip(), semester=body.semester)
    db.add(s)
    _commit(db, "section")
    audit(db, auth.user, "section.create", "section", s.id, auth.ip, name=s.name)
    db.commit()
    return section_out(s, 0)


@router.put("/sections/{sid}")
def update_section(sid: int, body: SectionIn, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    s = db.get(Section, sid) or _404("section")
    s.name, s.department, s.semester = body.name.strip(), body.department.strip(), body.semester
    _commit(db, "section")
    audit(db, auth.user, "section.update", "section", s.id, auth.ip, **body.model_dump())
    db.commit()
    return section_out(s)


@router.delete("/sections/{sid}")
def delete_section(sid: int, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    s = db.get(Section, sid) or _404("section")
    db.delete(s)
    audit(db, auth.user, "section.delete", "section", sid, auth.ip, name=s.name)
    db.commit()
    return {"ok": True}


@router.post("/sections/{sid}/enroll-course/{cid}")
def enroll_section_in_course(sid: int, cid: int, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    db.get(Section, sid) or _404("section")
    db.get(Course, cid) or _404("course")
    added = 0
    for st in db.scalars(select(Student).where(Student.section_id == sid)):
        exists = db.scalar(
            select(CourseEnrollment.id).where(
                CourseEnrollment.student_id == st.id, CourseEnrollment.course_id == cid
            )
        )
        if exists is None:
            db.add(CourseEnrollment(student_id=st.id, course_id=cid))
            added += 1
    audit(db, auth.user, "course.enroll_section", "course", cid, auth.ip, section_id=sid, added=added)
    db.commit()
    return {"added": added}


# ------------------------------------------------------------------ faculty


class FacultyIn(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    email: str | None = Field(default=None, max_length=128)
    department: str = Field(default="", max_length=64)


def faculty_out(f: Faculty) -> dict:
    return {"id": f.id, "name": f.name, "email": f.email, "department": f.department}


@router.get("/faculty")
def list_faculty(_: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    return [faculty_out(f) for f in db.scalars(select(Faculty).order_by(Faculty.name))]


@router.post("/faculty")
def create_faculty(body: FacultyIn, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    f = Faculty(**body.model_dump())
    db.add(f)
    _commit(db, "faculty")
    audit(db, auth.user, "faculty.create", "faculty", f.id, auth.ip, name=f.name)
    db.commit()
    return faculty_out(f)


@router.put("/faculty/{fid}")
def update_faculty(fid: int, body: FacultyIn, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    f = db.get(Faculty, fid) or _404("faculty")
    for k, v in body.model_dump().items():
        setattr(f, k, v)
    audit(db, auth.user, "faculty.update", "faculty", fid, auth.ip)
    _commit(db, "faculty")
    return faculty_out(f)


@router.delete("/faculty/{fid}")
def delete_faculty(fid: int, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    f = db.get(Faculty, fid) or _404("faculty")
    db.delete(f)
    audit(db, auth.user, "faculty.delete", "faculty", fid, auth.ip, name=f.name)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ courses


class CourseIn(BaseModel):
    code: str = Field(min_length=2, max_length=32, pattern=r"^[A-Za-z0-9\- ]+$")
    name: str = Field(min_length=1, max_length=128)
    department: str = Field(default="", max_length=64)
    faculty_id: int | None = None


def course_out(c: Course) -> dict:
    return {
        "id": c.id, "code": c.code, "name": c.name, "department": c.department,
        "faculty_id": c.faculty_id, "faculty": c.faculty.name if c.faculty else None,
    }  # fmt: skip


@router.get("/courses")
def list_courses(_: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    return [course_out(c) for c in db.scalars(select(Course).order_by(Course.code))]


@router.post("/courses")
def create_course(body: CourseIn, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    c = Course(
        code=body.code.strip().upper(), name=body.name.strip(),
        department=body.department.strip(), faculty_id=body.faculty_id,
    )  # fmt: skip
    db.add(c)
    _commit(db, "course")
    audit(db, auth.user, "course.create", "course", c.id, auth.ip, code=c.code)
    db.commit()
    return course_out(c)


@router.put("/courses/{cid}")
def update_course(cid: int, body: CourseIn, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    c = db.get(Course, cid) or _404("course")
    c.code, c.name = body.code.strip().upper(), body.name.strip()
    c.department, c.faculty_id = body.department.strip(), body.faculty_id
    _commit(db, "course")
    audit(db, auth.user, "course.update", "course", cid, auth.ip, code=c.code)
    db.commit()
    return course_out(c)


@router.delete("/courses/{cid}")
def delete_course(cid: int, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    c = db.get(Course, cid) or _404("course")
    db.delete(c)
    audit(db, auth.user, "course.delete", "course", cid, auth.ip, code=c.code)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ students


class StudentIn(BaseModel):
    roll_number: str = Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9\-_/.]+$")
    name: str = Field(min_length=1, max_length=128)
    department: str = Field(default="", max_length=64)
    semester: int = Field(default=1, ge=1, le=12)
    section_id: int | None = None
    course_ids: list[int] = Field(default_factory=list)
    password: str | None = Field(default=None, max_length=128)


class StudentUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    department: str = Field(default="", max_length=64)
    semester: int = Field(default=1, ge=1, le=12)
    section_id: int | None = None
    course_ids: list[int] = Field(default_factory=list)
    is_active: bool = True


def student_out(s: Student) -> dict:
    return {
        "id": s.id,
        "roll_number": s.roll_number,
        "name": s.name,
        "department": s.department,
        "semester": s.semester,
        "section_id": s.section_id,
        "section": s.section.name if s.section else None,
        "face_status": s.face_status,
        "is_synthetic": s.is_synthetic,
        "is_active": s.user.is_active if s.user else False,
        "username": s.user.username if s.user else None,
        "course_ids": [ce.course_id for ce in s.courses],
        "courses": [ce.course.code for ce in s.courses],
    }


def _set_courses(db: Session, s: Student, course_ids: list[int]) -> None:
    wanted = set(course_ids)
    for cid in wanted:
        db.get(Course, cid) or _404(f"course {cid}")
    for ce in list(s.courses):
        if ce.course_id not in wanted:
            s.courses.remove(ce)
    have = {ce.course_id for ce in s.courses}
    for cid in wanted - have:
        s.courses.append(CourseEnrollment(course_id=cid))


@router.get("/students")
def list_students(
    q: str = "", section_id: int | None = None,
    _: Auth = Depends(require_admin), db: Session = Depends(get_db),
):  # fmt: skip
    stmt = select(Student).order_by(Student.roll_number)
    if section_id:
        stmt = stmt.where(Student.section_id == section_id)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(Student.name.ilike(like) | Student.roll_number.ilike(like))
    return [student_out(s) for s in db.scalars(stmt.limit(2000))]


@router.get("/students/{sid}")
def get_student(sid: int, _: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    s = db.get(Student, sid) or _404("student")
    out = student_out(s)
    out["templates"] = [
        template_out(t)
        for t in db.scalars(
            select(FaceTemplate).where(FaceTemplate.student_id == sid).order_by(FaceTemplate.id.desc())
        )
    ]
    return out


@router.post("/students")
def create_student(body: StudentIn, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    roll = body.roll_number.strip().upper()
    if db.scalar(select(User.id).where(User.username == roll)) is not None:
        raise HTTPException(409, "a user with this roll number already exists")
    if body.section_id is not None:
        db.get(Section, body.section_id) or _404("section")
    password = body.password or generate_password()
    if body.password and (problem := password_problem(body.password)):
        raise HTTPException(400, problem)
    s = Student(
        roll_number=roll, name=body.name.strip(), department=body.department.strip(),
        semester=body.semester, section_id=body.section_id,
    )  # fmt: skip
    db.add(s)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "roll number already exists") from exc
    _set_courses(db, s, body.course_ids)
    db.add(
        User(
            username=roll, password_hash=hash_password(password), role="student",
            display_name=s.name, student_id=s.id, must_change_password=True,
        )
    )  # fmt: skip
    _commit(db, "student")
    audit(db, auth.user, "student.create", "student", s.id, auth.ip, roll_number=roll)
    db.commit()
    db.refresh(s)
    out = student_out(s)
    out["initial_password"] = password  # shown once; never stored in plain text
    return out


@router.put("/students/{sid}")
def update_student(sid: int, body: StudentUpdate, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    s = db.get(Student, sid) or _404("student")
    if body.section_id is not None:
        db.get(Section, body.section_id) or _404("section")
    s.name, s.department, s.semester = body.name.strip(), body.department.strip(), body.semester
    s.section_id = body.section_id
    _set_courses(db, s, body.course_ids)
    if s.user:
        s.user.is_active = body.is_active
        s.user.display_name = s.name
    audit(db, auth.user, "student.update", "student", sid, auth.ip)
    _commit(db, "student")
    db.refresh(s)
    return student_out(s)


@router.post("/students/{sid}/reset-password")
def reset_password(sid: int, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    s = db.get(Student, sid) or _404("student")
    if s.user is None:
        raise HTTPException(404, "no login account for this student")
    password = generate_password()
    s.user.password_hash = hash_password(password)
    s.user.must_change_password = True
    s.user.locked_until = None
    audit(db, auth.user, "student.reset_password", "student", sid, auth.ip)
    db.commit()
    return {"initial_password": password}


@router.delete("/students/{sid}")
def delete_student(sid: int, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    s = db.get(Student, sid) or _404("student")
    roll = s.roll_number
    if s.user:
        db.delete(s.user)
    db.delete(s)
    audit(db, auth.user, "student.delete", "student", sid, auth.ip, roll_number=roll)
    db.commit()
    return {"ok": True}


# ------------------------------------------------------------------ face templates


def template_out(t: FaceTemplate) -> dict:
    return {
        "id": t.id, "student_id": t.student_id, "status": t.status, "source": t.source,
        "n_frames": t.n_frames, "mean_quality": round(t.mean_quality, 2),
        "consistency": round(t.consistency, 3), "model_id": t.model_id,
        "created_at": t.created_at.isoformat() + "Z",
        "approved_at": t.approved_at.isoformat() + "Z" if t.approved_at else None,
    }  # fmt: skip


@router.get("/enrollments")
def list_enrollments(status: str = "pending", _: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    stmt = select(FaceTemplate, Student).join(Student, Student.id == FaceTemplate.student_id)
    if status != "all":
        stmt = stmt.where(FaceTemplate.status == status)
    rows = db.execute(stmt.order_by(FaceTemplate.created_at.desc()).limit(500)).all()
    return [
        {**template_out(t), "roll_number": s.roll_number, "name": s.name,
         "section": s.section.name if s.section else None}
        for t, s in rows
    ]  # fmt: skip


@router.post("/students/{sid}/enrollment/open")
def open_self_enrollment(sid: int, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    """Authorise the student to enroll their own face from their phone."""
    s = db.get(Student, sid) or _404("student")
    # An existing approved template stays active (attendance keeps working) until a new
    # self-enrollment is approved; face_status only tracks the enrollment workflow.
    s.face_status = "enrollment_open"
    audit(db, auth.user, "face.enrollment_opened", "student", sid, auth.ip)
    db.commit()
    return {"face_status": s.face_status}


@router.post("/students/{sid}/face")
def admin_enroll_face(
    sid: int,
    request: Request,
    images: list[UploadFile] = File(...),
    source: str = Form("admin_live"),
    consent: bool = Form(False),
    auth: Auth = Depends(require_admin),
    db: Session = Depends(get_db),
    rt: dict = Depends(runtime),
):
    """Admin enrollment by live capture or authorised photo upload (auto-approved, audited)."""
    if not consent:
        raise HTTPException(400, "confirm that the student consented to biometric enrollment")
    if source not in ("admin_live", "admin_upload"):
        raise HTTPException(400, "invalid source")
    s = db.get(Student, sid) or _404("student")
    st = request.app.state
    data = _read_images(images, st.settings_obj.max_enroll_images, st.settings_obj.max_upload_bytes)
    return enroll(
        db, st.engine, st.cipher, s, data, rt,
        source=source, actor=auth.user, auto_approve=True, ip=auth.ip,
    )  # fmt: skip


@router.post("/templates/{tid}/approve")
def approve_template(tid: int, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    t = db.get(FaceTemplate, tid) or _404("template")
    if t.status != "pending":
        raise HTTPException(400, f"template is {t.status}, not pending")
    for old in db.scalars(
        select(FaceTemplate).where(
            FaceTemplate.student_id == t.student_id, FaceTemplate.status == "approved"
        )
    ):
        old.status = "superseded"
    t.status = "approved"
    t.approved_by_user_id = auth.user.id
    t.approved_at = utcnow()
    s = db.get(Student, t.student_id)
    assert s is not None
    s.face_status = "approved"
    audit(db, auth.user, "face.approved", "student", s.id, auth.ip, template_id=tid)
    db.commit()
    return template_out(t)


@router.post("/templates/{tid}/revoke")
def revoke_template(tid: int, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    t = db.get(FaceTemplate, tid) or _404("template")
    t.status = "revoked"
    s = db.get(Student, t.student_id)
    assert s is not None
    still = db.scalar(
        select(FaceTemplate.id).where(
            FaceTemplate.student_id == s.id, FaceTemplate.status == "approved"
        )
    )
    if still is None:
        s.face_status = "revoked"
    audit(db, auth.user, "face.revoked", "student", s.id, auth.ip, template_id=tid)
    db.commit()
    return template_out(t)


@router.delete("/students/{sid}/face")
def delete_face(sid: int, auth: Auth = Depends(require_admin), db: Session = Depends(get_db)):
    s = db.get(Student, sid) or _404("student")
    n = delete_biometrics(db, s, auth.user, auth.ip)
    return {"deleted_templates": n}


# ------------------------------------------------------------------ helpers


def _read_images(files: list[UploadFile], max_count: int, max_bytes: int) -> list[bytes]:
    if not files:
        raise HTTPException(400, "no images")
    if len(files) > max_count:
        raise HTTPException(400, f"at most {max_count} images")
    out = []
    for f in files:
        data = f.file.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise HTTPException(413, "image too large")
        out.append(data)
    return out


def _404(what: str):  # type: ignore[no-untyped-def]
    raise HTTPException(404, f"{what} not found")


__all__ = ["router", "student_out", "course_out", "section_out", "TimetableEntry"]
