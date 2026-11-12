"""Future institutional integration contract. No university system is connected."""

from typing import Protocol


class UniversityAttendanceAdapter(Protocol):
    """Implement only after receiving the university's authorized API contract and credentials.

    The institution remains responsible for OD and medical leave. AttendX publishes only
    explicit faculty-approved attendance and reads institution-owned leave decisions if allowed.
    Implementations must authenticate, validate scopes, and retain idempotency receipts.
    """

    def publish_approved_attendance(self, *, event_id: str, approved_snapshot: dict) -> str:
        """Return a durable institutional receipt for this stable event ID."""
        ...

    def read_academic_changes(self, *, cursor: str | None) -> dict:
        """Return authorized roster/calendar changes and an opaque continuation cursor."""
        ...

    def read_institutional_leave_decisions(self, *, student_ids: list[int], date_from: str, date_to: str) -> list[dict]:
        """Read existing university OD/medical outcomes; never create or approve leave here."""
        ...
