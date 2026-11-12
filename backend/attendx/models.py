"""ORM schema (normalised). Every datetime column is naive UTC; dates/times of the timetable are
local to the configured institutional timezone. See docs/database.md."""

from __future__ import annotations

from datetime import date, datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    Time,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from attendx.db import Base, utcnow

ROLES = ("admin", "student", "faculty")
FACE_STATUSES = ("none", "enrollment_open", "pending", "approved", "revoked")
TEMPLATE_STATUSES = ("pending", "approved", "revoked", "superseded")
RECORD_STATUSES = ("present", "late", "absent", "excused")
DECISIONS = ("match", "non_match", "abstain", "rejected")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    display_name: Mapped[str] = mapped_column(String(128), default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)
    student_id: Mapped[int | None] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), unique=True, nullable=True
    )
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    email: Mapped[str | None] = mapped_column(String(254), unique=True, nullable=True)
    account_state: Mapped[str] = mapped_column(String(24), default="ACTIVE", server_default="ACTIVE")
    faculty_id: Mapped[int | None] = mapped_column(ForeignKey("faculty.id", ondelete="SET NULL"), nullable=True)

    student: Mapped[Student | None] = relationship(back_populates="user")
    __table_args__ = (CheckConstraint("role in ('admin','student','faculty')", name="ck_user_role"),)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ip: Mapped[str] = mapped_column(String(64), default="")
    user_agent: Mapped[str] = mapped_column(String(256), default="")


class Faculty(Base):
    __tablename__ = "faculty"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    email: Mapped[str | None] = mapped_column(String(128), nullable=True)
    department: Mapped[str] = mapped_column(String(64), default="")


class Section(Base):
    __tablename__ = "sections"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    department: Mapped[str] = mapped_column(String(64), default="")
    semester: Mapped[int] = mapped_column(Integer, default=1)


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    department: Mapped[str] = mapped_column(String(64), default="")
    faculty_id: Mapped[int | None] = mapped_column(
        ForeignKey("faculty.id", ondelete="SET NULL"), nullable=True
    )
    faculty: Mapped[Faculty | None] = relationship()


class Student(Base):
    __tablename__ = "students"
    id: Mapped[int] = mapped_column(primary_key=True)
    roll_number: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    department: Mapped[str] = mapped_column(String(64), default="")
    semester: Mapped[int] = mapped_column(Integer, default=1)
    section_id: Mapped[int | None] = mapped_column(
        ForeignKey("sections.id", ondelete="SET NULL"), nullable=True, index=True
    )
    face_status: Mapped[str] = mapped_column(String(24), default="none")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    section: Mapped[Section | None] = relationship()
    user: Mapped[User | None] = relationship(back_populates="student", passive_deletes=True)
    courses: Mapped[list[CourseEnrollment]] = relationship(
        cascade="all, delete-orphan", passive_deletes=True
    )


class CourseEnrollment(Base):
    __tablename__ = "course_enrollments"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    course: Mapped[Course] = relationship()
    __table_args__ = (UniqueConstraint("student_id", "course_id", name="uq_course_enrollment"),)


class FaceTemplate(Base):
    """Encrypted reference embedding. Raw face photos are never stored."""

    __tablename__ = "face_templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(16), default="pending")
    template_enc: Mapped[bytes] = mapped_column(LargeBinary)
    model_id: Mapped[str] = mapped_column(String(64))
    n_frames: Mapped[int] = mapped_column(Integer)
    mean_quality: Mapped[float] = mapped_column(Float)
    consistency: Mapped[float] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(24))  # self_live | admin_live | admin_upload | demo
    consent_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Period(Base):
    """Default bell schedule (eight teaching periods by default)."""

    __tablename__ = "periods"
    id: Mapped[int] = mapped_column(primary_key=True)
    number: Mapped[int] = mapped_column(Integer, unique=True)
    label: Mapped[str] = mapped_column(String(32))
    start_time: Mapped[time] = mapped_column(Time)
    end_time: Mapped[time] = mapped_column(Time)
    attendance_open: Mapped[time] = mapped_column(Time)
    attendance_close: Mapped[time] = mapped_column(Time)
    is_break: Mapped[bool] = mapped_column(Boolean, default=False)


class TimetableEntry(Base):
    __tablename__ = "timetable_entries"
    id: Mapped[int] = mapped_column(primary_key=True)
    weekday: Mapped[int] = mapped_column(Integer)  # 0 = Monday
    period_number: Mapped[int] = mapped_column(Integer)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"))
    course_id: Mapped[int | None] = mapped_column(
        ForeignKey("courses.id", ondelete="CASCADE"), nullable=True
    )
    faculty_id: Mapped[int | None] = mapped_column(
        ForeignKey("faculty.id", ondelete="SET NULL"), nullable=True
    )
    room: Mapped[str] = mapped_column(String(32), default="")
    is_break: Mapped[bool] = mapped_column(Boolean, default=False)
    # Optional per-entry overrides of the period defaults
    start_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    end_time: Mapped[time | None] = mapped_column(Time, nullable=True)
    attendance_open: Mapped[time | None] = mapped_column(Time, nullable=True)
    attendance_close: Mapped[time | None] = mapped_column(Time, nullable=True)

    section: Mapped[Section] = relationship()
    course: Mapped[Course | None] = relationship()
    faculty: Mapped[Faculty | None] = relationship()
    __table_args__ = (
        UniqueConstraint("weekday", "period_number", "section_id", name="uq_timetable_slot"),
        CheckConstraint("weekday between 0 and 6", name="ck_weekday"),
    )


class Holiday(Base):
    __tablename__ = "holidays"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, unique=True)
    name: Mapped[str] = mapped_column(String(128))


class AttendanceSession(Base):
    """One class meeting (section x date x period). Windows are stored in UTC."""

    __tablename__ = "attendance_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    period_number: Mapped[int] = mapped_column(Integer)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    faculty_id: Mapped[int | None] = mapped_column(
        ForeignKey("faculty.id", ondelete="SET NULL"), nullable=True
    )
    timetable_entry_id: Mapped[int | None] = mapped_column(
        ForeignKey("timetable_entries.id", ondelete="SET NULL"), nullable=True
    )
    start_at: Mapped[datetime] = mapped_column(DateTime)
    end_at: Mapped[datetime] = mapped_column(DateTime)
    open_at: Mapped[datetime] = mapped_column(DateTime)
    close_at: Mapped[datetime] = mapped_column(DateTime)
    cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    manually_adjusted: Mapped[bool] = mapped_column(Boolean, default=False)
    note: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    section: Mapped[Section] = relationship()
    course: Mapped[Course] = relationship()
    faculty: Mapped[Faculty | None] = relationship()
    __table_args__ = (
        UniqueConstraint("section_id", "date", "period_number", name="uq_session_slot"),
    )


class AttendanceRecord(Base):
    """Final attendance decision. Verification attempts are kept separately."""

    __tablename__ = "attendance_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("attendance_sessions.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"))
    date: Mapped[date] = mapped_column(Date, index=True)
    status: Mapped[str] = mapped_column(String(16))
    method: Mapped[str] = mapped_column(String(16))  # face | manual
    verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    liveness_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    attempt_id: Mapped[int | None] = mapped_column(
        ForeignKey("verification_attempts.id", ondelete="SET NULL"), nullable=True
    )
    override_by_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    override_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    previous_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    student: Mapped[Student] = relationship()
    session: Mapped[AttendanceSession] = relationship()
    __table_args__ = (
        UniqueConstraint("session_id", "student_id", name="uq_attendance_once"),
        CheckConstraint(
            "status in ('present','late','absent','excused')", name="ck_record_status"
        ),
    )


class LivenessChallenge(Base):
    __tablename__ = "liveness_challenges"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[int] = mapped_column(
        ForeignKey("attendance_sessions.id", ondelete="CASCADE")
    )
    steps: Mapped[str] = mapped_column(Text)  # JSON list
    issued_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(16), default="issued")  # issued|consumed
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class VerificationAttempt(Base):
    __tablename__ = "verification_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(
        ForeignKey("students.id", ondelete="CASCADE"), index=True
    )
    session_id: Mapped[int] = mapped_column(
        ForeignKey("attendance_sessions.id", ondelete="CASCADE"), index=True
    )
    challenge_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    decision: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(256), default="")
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    quality: Mapped[float | None] = mapped_column(Float, nullable=True)
    liveness_passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    details: Mapped[str] = mapped_column(Text, default="{}")  # JSON, never images
    n_frames: Mapped[int] = mapped_column(Integer, default=0)
    processing_ms: Mapped[int] = mapped_column(Integer, default=0)
    ip: Mapped[str] = mapped_column(String(64), default="")


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor_user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    actor: Mapped[str] = mapped_column(String(64), default="system")
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(32), default="")
    entity_id: Mapped[str] = mapped_column(String(64), default="")
    details: Mapped[str] = mapped_column(Text, default="{}")
    ip: Mapped[str] = mapped_column(String(64), default="")


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)  # JSON
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
