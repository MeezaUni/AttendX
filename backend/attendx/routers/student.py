"""Student portal: today's classes, history, self-enrollment and live attendance verification.

The browser never marks attendance: it only uploads the camera frames of a server-issued
challenge. The server re-checks the window, eligibility, duplicate state and attempt limits,
validates liveness from the frames, verifies identity 1:1 against the student's own template,
and records the decision."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from attendx.db import utcnow
from attendx.deps import Auth, get_db, require_student, runtime
from attendx.face.engine import FrameMetrics, decode_image
from attendx.liveness.challenge import LABELS, generate_steps, validate
from attendx.models import (
    AttendanceRecord,
    AttendanceSession,
    FaceTemplate,
    LivenessChallenge,
    Student,
    VerificationAttempt,
)
from attendx.routers.admin_schedule import session_out
from attendx.services import schedule as sch
from attendx.services.audit import audit
from attendx.services.enrollment import active_template, enroll
from attendx.services.verification import MATCH, cosine, decide

router = APIRouter(prefix="/api/student", tags=["student"])

MAX_DUPLICATE_FRACTION = 0.3


@router.get("/today")
def today(request: Request, auth: Auth = Depends(require_student), db: Session = Depends(get_db),
          rt: dict = Depends(runtime)):  # fmt: skip
    tz = request.app.state.settings_obj.tz
    st = auth.student
    d = sch.local_today(tz)
    sch.ensure_sessions_for_date(db, d, tz)
    db.commit()
    holiday = sch.is_holiday(db, d)
    rows = []
    for s in db.scalars(
        select(AttendanceSession)
        .where(AttendanceSession.date == d, AttendanceSession.section_id == st.section_id)
        .order_by(AttendanceSession.start_at)
    ):
        if not sch.student_eligible(db, st, s, rt["eligibility"]):
            continue
        rec = db.scalar(
            select(AttendanceRecord).where(
                AttendanceRecord.session_id == s.id, AttendanceRecord.student_id == st.id
            )
        )
        attempts = db.scalar(
            select(func.count()).select_from(VerificationAttempt).where(
                VerificationAttempt.session_id == s.id, VerificationAttempt.student_id == st.id
            )
        )
        out = session_out(db, s, tz, with_counts=False)
        out["record"] = (
            {"status": rec.status, "method": rec.method,
             "verified_at": rec.verified_at.isoformat() + "Z" if rec.verified_at else None}
            if rec else None
        )  # fmt: skip
        out["attempts_left"] = max(0, int(rt["max_attempts_per_session"]) - int(attempts or 0))
        rows.append(out)
    return {
        "date": d.isoformat(),
        "weekday": sch.WEEKDAYS[d.weekday()],
        "holiday": holiday.name if holiday else None,
        "server_time": sch.local_now(tz).isoformat(),
        "face_ready": active_template(db, st.id) is not None,
        "face_status": st.face_status,
        "sessions": rows,
    }


@router.get("/history")
def history(request: Request, auth: Auth = Depends(require_student), db: Session = Depends(get_db)):
    from attendx.routers.admin_reports import compute_student_summary

    tz = request.app.state.settings_obj.tz
    st = auth.student
    summary = compute_student_summary(db, student_id=st.id)
    sessions = db.scalars(
        sch.held_sessions_query()
        .where(AttendanceSession.section_id == st.section_id)
        .order_by(AttendanceSession.date.desc(), AttendanceSession.start_at.desc())
        .limit(300)
    )
    recs = {r.session_id: r for r in db.scalars(select(AttendanceRecord).where(AttendanceRecord.student_id == st.id))}
    items = []
    for s in sessions:
        r = recs.get(s.id)
        items.append({
            "date": s.date.isoformat(), "weekday": sch.WEEKDAYS[s.date.weekday()],
            "period": s.period_number, "course_code": s.course.code, "course_name": s.course.name,
            "start": sch.utc_naive_to_local(s.start_at, tz).strftime("%H:%M"),
            "status": r.status if r else ("absent" if sch.session_status(s) == "closed" else "not_marked"),
            "method": r.method if r else None,
        })  # fmt: skip
    return {"summary": summary[0] if summary else None, "items": items}


# ------------------------------------------------------------------ self enrollment


@router.get("/enrollment")
def enrollment_status(auth: Auth = Depends(require_student), db: Session = Depends(get_db)):
    st = auth.student
    latest = db.scalar(
        select(FaceTemplate).where(FaceTemplate.student_id == st.id).order_by(FaceTemplate.id.desc())
    )
    return {
        "face_status": st.face_status,
        "can_enroll": st.face_status == "enrollment_open",
        "has_active_template": active_template(db, st.id) is not None,
        "latest": {"status": latest.status, "created_at": latest.created_at.isoformat() + "Z"} if latest else None,
    }


@router.post("/enrollment")
def self_enroll(
    request: Request,
    images: list[UploadFile] = File(...),
    consent: bool = Form(False),
    auth: Auth = Depends(require_student),
    db: Session = Depends(get_db),
    rt: dict = Depends(runtime),
):
    st = auth.student
    if st.face_status != "enrollment_open":
        raise HTTPException(403, "face enrollment has not been opened for you by an administrator")
    if not consent:
        raise HTTPException(400, "you must consent to biometric enrollment")
    app = request.app.state
    if not app.limiter.hit(f"enroll:{st.id}", 5):
        raise HTTPException(429, "too many enrollment attempts; wait a minute")
    max_n, max_b = app.settings_obj.max_enroll_images, app.settings_obj.max_frame_bytes * 4
    if not images or len(images) > max_n:
        raise HTTPException(400, f"send between 1 and {max_n} images")
    data = []
    for f in images:
        b = f.file.read(max_b + 1)
        if len(b) > max_b:
            raise HTTPException(413, "image too large")
        data.append(b)
    result = enroll(db, app.engine, app.cipher, st, data, rt,
                    source="self_live", actor=auth.user, auto_approve=False, ip=auth.ip)  # fmt: skip
    if not result["ok"]:
        st.face_status = "enrollment_open"  # allow retry
        db.commit()
    return result


# ------------------------------------------------------------------ attendance


class ChallengeIn(BaseModel):
    session_id: int


def _check_session(db: Session, st: Student, s: AttendanceSession | None, rt: dict) -> AttendanceSession:
    """Server-side gate shared by challenge issue and submission."""
    if s is None:
        raise HTTPException(404, "class not found")
    if not sch.student_eligible(db, st, s, rt["eligibility"]):
        raise HTTPException(403, "you are not enrolled in this class")
    if sch.is_holiday(db, s.date):
        raise HTTPException(409, "today is a holiday")
    if sch.session_is_break(db, s):
        raise HTTPException(409, "this period is a break; attendance is not taken")
    status = sch.session_status(s)
    if status != "open":
        msg = {"upcoming": "attendance has not opened yet", "closed": "attendance window has closed",
               "cancelled": "this class was cancelled"}[status]  # fmt: skip
        raise HTTPException(409, msg)
    if db.scalar(
        select(AttendanceRecord.id).where(
            AttendanceRecord.session_id == s.id, AttendanceRecord.student_id == st.id
        )
    ):
        raise HTTPException(409, "attendance is already recorded for this class")
    return s


def _attempts(db: Session, st: Student, s: AttendanceSession) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(VerificationAttempt).where(
                VerificationAttempt.session_id == s.id, VerificationAttempt.student_id == st.id
            )
        )
        or 0
    )


@router.post("/attendance/challenge")
def issue_challenge(body: ChallengeIn, request: Request, auth: Auth = Depends(require_student),
                    db: Session = Depends(get_db), rt: dict = Depends(runtime)):  # fmt: skip
    st = auth.student
    app = request.app.state
    if not app.limiter.hit(f"challenge:{st.id}", app.settings_obj.challenges_per_minute):
        raise HTTPException(429, "too many attempts; wait a minute")
    s = _check_session(db, st, db.get(AttendanceSession, body.session_id), rt)
    if active_template(db, st.id) is None:
        raise HTTPException(409, "your face is not enrolled (or not yet approved)")
    if _attempts(db, st, s) >= int(rt["max_attempts_per_session"]):
        raise HTTPException(429, "no verification attempts left for this class; ask your instructor")
    # one live challenge per student: older unused ones are invalidated
    db.execute(
        update(LivenessChallenge)
        .where(LivenessChallenge.student_id == st.id, LivenessChallenge.status == "issued")
        .values(status="superseded")
    )
    ttl = int(rt["challenge_ttl_seconds"])
    steps = generate_steps(int(rt["challenge_steps"]))
    ch = LivenessChallenge(
        id=str(uuid.uuid4()), student_id=st.id, session_id=s.id, steps=json.dumps(steps),
        expires_at=utcnow() + timedelta(seconds=ttl),
    )  # fmt: skip
    db.add(ch)
    db.commit()
    return {
        "challenge_id": ch.id,
        "steps": [{"action": a, "label": LABELS[a]} for a in steps],
        "ttl_seconds": ttl,
        "expires_at": ch.expires_at.isoformat() + "Z",
        "guidance": {k: rt[k] for k in ("yaw_delta", "pitch_delta", "blink_closed", "blink_open")},
    }


def _record_attempt(db: Session, st: Student, s: AttendanceSession, ch_id: str, decision: str,
                    reason: str, started: float, ip: str, **kw) -> VerificationAttempt:  # fmt: skip
    a = VerificationAttempt(
        student_id=st.id, session_id=s.id, challenge_id=ch_id, decision=decision, reason=reason,
        processing_ms=int((time.perf_counter() - started) * 1000), ip=ip,
        match_score=kw.pop("match_score", None), quality=kw.pop("quality", None),
        liveness_passed=kw.pop("liveness_passed", None), n_frames=kw.pop("n_frames", 0),
        details=json.dumps(kw, default=str),
    )  # fmt: skip
    db.add(a)
    db.flush()
    return a


@router.post("/attendance/challenge/{challenge_id}/submit")
def submit_challenge(
    challenge_id: str,
    request: Request,
    frames: list[UploadFile] = File(...),
    timestamps: str = Form(...),
    auth: Auth = Depends(require_student),
    db: Session = Depends(get_db),
    rt: dict = Depends(runtime),
):
    started = time.perf_counter()
    app = request.app.state
    cfg = app.settings_obj
    st = auth.student
    ch = db.get(LivenessChallenge, challenge_id)
    if ch is None or ch.student_id != st.id:
        raise HTTPException(404, "challenge not found")
    # Atomically consume: a challenge can be submitted exactly once.
    now = utcnow()
    consumed = db.execute(
        update(LivenessChallenge)
        .where(LivenessChallenge.id == ch.id, LivenessChallenge.status == "issued")
        .values(status="consumed", consumed_at=now)
    ).rowcount
    db.commit()
    if consumed != 1:
        raise HTTPException(409, "this challenge was already used or replaced; start again")
    if now > ch.expires_at:
        raise HTTPException(410, "challenge expired; start again")
    s = _check_session(db, st, db.get(AttendanceSession, ch.session_id), rt)
    if _attempts(db, st, s) >= int(rt["max_attempts_per_session"]):
        raise HTTPException(429, "no verification attempts left for this class")

    # ---- parse the upload (in memory only; frames are never written or logged)
    try:
        ts = [float(t) for t in json.loads(timestamps)]
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, "invalid timestamps") from exc
    if not frames or len(frames) > cfg.max_frames or len(frames) != len(ts):
        raise HTTPException(400, f"send 6-{cfg.max_frames} frames with one timestamp each")
    raw: list[bytes] = []
    for f in frames:
        b = f.file.read(cfg.max_frame_bytes + 1)
        if len(b) > cfg.max_frame_bytes:
            raise HTTPException(413, "a frame is too large")
        raw.append(b)
    steps = json.loads(ch.steps)
    base = {"steps": steps, "n_frames": len(raw)}

    def reject(reason: str, **kw):  # type: ignore[no-untyped-def]
        _record_attempt(db, st, s, ch.id, "rejected", reason, started, auth.ip, **base, **kw)
        db.commit()
        return {"decision": "rejected", "reason": reason, "marked": False,
                "attempts_left": max(0, int(rt["max_attempts_per_session"]) - _attempts(db, st, s))}  # fmt: skip

    elapsed_ms = (now - ch.issued_at).total_seconds() * 1000.0
    if ts and ts[-1] - ts[0] > elapsed_ms + 2000:
        return reject("frame timing is inconsistent with the challenge", liveness_passed=False)
    digests = [hashlib.sha256(b).digest() for b in raw]
    dup = sum(1 for a, b in zip(digests, digests[1:], strict=False) if a == b)
    if len(raw) > 1 and dup / (len(raw) - 1) > MAX_DUPLICATE_FRACTION:
        return reject("the camera feed appears frozen", liveness_passed=False)

    images = []
    for b in raw:
        try:
            images.append(decode_image(b, max_side=1280))
        except ValueError:
            return reject("a camera frame could not be read", liveness_passed=False)
    del raw

    # ---- liveness (server-side measurement of every frame)
    engine = app.engine
    metrics: list[FrameMetrics] = [engine.frame_metrics(img) for img in images]
    order = sorted(range(len(ts)), key=lambda i: ts[i])
    live = validate(steps, [(ts[i], metrics[i]) for i in order], rt)
    if not live.passed:
        return reject(live.reason, liveness_passed=False, liveness=live.details,
                      completed_steps=live.completed_steps)  # fmt: skip

    # ---- identity: 1:1 against this student's own approved template
    tpl = active_template(db, st.id)
    if tpl is None:
        return reject("no approved face template")
    try:
        template = app.cipher.decrypt(tpl.template_enc, engine.model_id)
    except ValueError as exc:
        return reject(str(exc))
    picks = [order[i] for i in dict.fromkeys(live.start_frames + live.end_frames)]
    scores, norms, problems = [], [], []
    for i in picks:
        obs = engine.observe(images[i], rt)
        if obs.usable and obs.embedding is not None:
            scores.append(cosine(obs.embedding, template))
            norms.append(obs.feature_norm)
        else:
            problems.extend(obs.problems)
    del images
    d = decide(scores, rt)
    quality = min(norms) if norms else None
    attempt = _record_attempt(
        db, st, s, ch.id, d.decision, d.reason if scores else (problems[0] if problems else d.reason),
        started, auth.ip, match_score=d.score, quality=quality, liveness_passed=True,
        n_frames=len(ts), steps=steps, liveness=live.details, scores=d.scores,
        frame_problems=sorted(set(problems)), template_id=tpl.id,
    )  # fmt: skip
    marked = False
    if d.decision == MATCH:
        rec = AttendanceRecord(
            session_id=s.id, student_id=st.id, course_id=s.course_id, section_id=s.section_id,
            date=s.date, status="present", method="face", verified_at=utcnow(),
            match_score=d.score, quality_score=quality, liveness_passed=True, attempt_id=attempt.id,
        )  # fmt: skip
        db.add(rec)
        try:
            db.flush()
            marked = True
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "attendance is already recorded for this class") from None
        audit(db, auth.user, "attendance.face_present", "session", s.id, auth.ip, student_id=st.id,
              score=round(d.score or 0, 3))  # fmt: skip
    db.commit()
    return {
        "decision": d.decision,
        "reason": d.reason if scores or not problems else problems[0],
        "marked": marked,
        # similarity scores are shown to administrators only (no feedback for hill-climbing)
        "liveness": {"passed": True, "steps": live.completed_steps},
        "course_code": s.course.code,
        "verified_at": sch.local_now(cfg.tz).isoformat() if marked else None,
        "attempts_left": max(0, int(rt["max_attempts_per_session"]) - _attempts(db, st, s)),
    }
