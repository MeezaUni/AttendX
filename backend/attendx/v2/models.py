"""V2 tables are separate from legacy attendance and template records."""

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from attendx.db import Base, utcnow


class Semester(Base):
    __tablename__ = "v2_semesters"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    academic_year: Mapped[str] = mapped_column(String(32))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    renewal_deadline: Mapped[date] = mapped_column(Date)
    reminder_days: Mapped[str] = mapped_column(Text, default="[30,7,1,0]")


class ClassroomAuthority(Base):
    __tablename__ = "v2_classroom_authority"
    id: Mapped[int] = mapped_column(primary_key=True)
    certificate_pem: Mapped[bytes] = mapped_column(LargeBinary)
    private_key_enc: Mapped[bytes] = mapped_column(LargeBinary)
    expires_at: Mapped[datetime] = mapped_column(DateTime)


class SectionSemester(Base):
    __tablename__ = "v2_section_semesters"
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"), primary_key=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("v2_semesters.id"))


class Assignment(Base):
    __tablename__ = "v2_assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    faculty_user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"))
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"), nullable=True)
    kind: Mapped[str] = mapped_column(String(16))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    authorized_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(String(256))
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class AdditionalStudent(Base):
    __tablename__ = "v2_additional_students"
    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id", ondelete="CASCADE"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id", ondelete="CASCADE"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    authorized_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    reason: Mapped[str] = mapped_column(String(256))


class ActionToken(Base):
    __tablename__ = "v2_action_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MailMessage(Base):
    __tablename__ = "v2_mail_outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    payload_enc: Mapped[bytes] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str] = mapped_column(String(100), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EnrollmentBatch(Base):
    __tablename__ = "v2_enrollment_batches"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    semester_id: Mapped[int] = mapped_column(ForeignKey("v2_semesters.id"))
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32))
    model_id: Mapped[str] = mapped_column(String(100))
    pipeline_version: Mapped[str] = mapped_column(String(128))
    consent_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    consent_version: Mapped[str] = mapped_column(String(32), default="attendx-v2-1")
    retain_photos: Mapped[bool] = mapped_column(Boolean, default=False)
    photo_delete_at: Mapped[datetime] = mapped_column(DateTime)
    expires_on: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    cc_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    cc_verified_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    cc_reason: Mapped[str] = mapped_column(String(256), default="")
    admin_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    __table_args__ = (UniqueConstraint("student_id", "version", name="uq_v2_enrollment_version"),)


class EnrollmentSample(Base):
    __tablename__ = "v2_enrollment_samples"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("v2_enrollment_batches.id", ondelete="CASCADE"), index=True)
    slot: Mapped[int] = mapped_column(Integer)
    embedding_enc: Mapped[bytes] = mapped_column(LargeBinary)
    photo_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    quality: Mapped[str] = mapped_column(Text)
    __table_args__ = (UniqueConstraint("batch_id", "slot", name="uq_v2_sample_slot"),)


class Reminder(Base):
    __tablename__ = "v2_reminders"
    id: Mapped[int] = mapped_column(primary_key=True)
    batch_id: Mapped[str] = mapped_column(ForeignKey("v2_enrollment_batches.id", ondelete="CASCADE"))
    days_before: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("batch_id", "days_before", name="uq_v2_reminder"),)


class FacultyDevice(Base):
    __tablename__ = "v2_faculty_devices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(80))
    credential_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)


class FacultyGrant(Base):
    __tablename__ = "v2_faculty_grants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    device_id: Mapped[str | None] = mapped_column(ForeignKey("v2_faculty_devices.id"), nullable=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    roster_scope: Mapped[str] = mapped_column(Text)


class ApprovedSession(Base):
    __tablename__ = "v2_approved_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    faculty_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("sections.id"))
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"))
    date: Mapped[date] = mapped_column(Date)
    period_number: Mapped[int] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer)
    payload_enc: Mapped[bytes] = mapped_column(LargeBinary)
    __table_args__ = (UniqueConstraint("section_id", "course_id", "date", "period_number", name="uq_v2_class_meeting"),)


class AttendanceEvent(Base):
    __tablename__ = "v2_attendance_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(ForeignKey("v2_approved_sessions.id"))
    device_id: Mapped[str] = mapped_column(ForeignKey("v2_faculty_devices.id"))
    content_hash: Mapped[str] = mapped_column(String(64))
    revision: Mapped[int] = mapped_column(Integer)
    payload_enc: Mapped[bytes] = mapped_column(LargeBinary)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    __table_args__ = (UniqueConstraint("session_id", "revision", name="uq_v2_event_revision"),)
