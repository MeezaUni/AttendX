"""Durable faculty authority, two-stage rotating QR and laptop-only inference."""

import copy
import hashlib
import hmac
import math
import secrets
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from zoneinfo import ZoneInfo

import numpy as np

from attendx.db import utcnow
from attendx.face.engine import decode_image
from attendx.faculty.reconciliation import headcount_report
from attendx.faculty.storage import LocalStore, canonical
from attendx.liveness.challenge import LABELS, generate_steps, validate
from attendx.security import hash_password, password_problem, verify_password
from attendx.services.collection_timing import COLLECTION_SECONDS, collection_start_allowed
from attendx.services.verification import cosine, decide
from attendx.v2.identity import PIPELINE_VERSION


def stamp(value):
    return value.isoformat() + "Z"


def parse_stamp(value):
    return datetime.fromisoformat(value.removesuffix("Z"))


def content_hash(event):
    return hashlib.sha256(canonical(event).encode()).hexdigest()


class FacultyRuntime:
    def __init__(self, directory: Path, *, engine, now=utcnow):
        self.store = LocalStore(directory)
        self.engine, self.now = engine, now
        self.lock = threading.RLock()
        self.unlocked = False
        self.attempts = {}
        self.pin_failures = 0
        self.pin_locked_until = None
        # Unsafe challenges never survive restart. Completed submissions, marks and outbox do.
        with self.store.transaction() as db:
            for s in self.store.sessions():
                changed = False
                if s["state"] == "COLLECTING":
                    s["state"], s["closed_at"] = "REVIEW", stamp(min(self.now(), parse_stamp(s["close_at"])))
                    changed = True
                if s["state"] != "APPROVED":
                    for row in s["roster"]:
                        changed = self._suggest_present(s, row) or changed
                if changed:
                    self.store.save_session(s, db)

    def _suggest_present(self, session, row):
        submission = row.get("submission")
        if (
            not submission
            or submission.get("method") != "face"
            or submission.get("status") != "PENDING_FACULTY_APPROVAL"
        ):
            return False
        if (
            row["status"] != "UNMARKED"
            or row.get("decision_source") == "faculty"
            or row.get("method") == "manual"
            or row.get("reason", "").strip()
        ):
            return False
        row.update(
            status="PRESENT",
            method="face",
            decision_source="face_suggestion",
            reason="Face matched and fresh second QR received; draft presence awaiting faculty approval",
        )
        row.setdefault("verification", {"decision": "MATCH", "at": submission.get("at", stamp(self.now()))})
        session.setdefault("audit", []).append(
            {
                "action": "suggest_present",
                "student_id": row["student_id"],
                "previous": "UNMARKED",
                "status": "PRESENT",
                "at": stamp(self.now()),
            }
        )
        return True

    def provision(self, snapshot, pin: str):
        if self.store.kv_get("faculty_pin") is not None:
            raise ValueError("device already provisioned; unlock before changing its authorization")
        if problem := password_problem(pin):
            raise ValueError("Offline PIN: " + problem)
        self._validate_snapshot(snapshot)
        with self.store.transaction() as db:
            self.store.kv_set("snapshot", snapshot, db)
            self.store.kv_set("faculty_pin", hash_password(pin), db)
        self.unlocked = True

    def _validate_snapshot(self, snapshot):
        if snapshot.get("schema_version") != 2 or snapshot.get("pipeline_version") != PIPELINE_VERSION:
            raise ValueError("incompatible roster/model pipeline; synchronize a compatible version")
        if parse_stamp(snapshot["offline_valid_until"]) <= self.now():
            raise ValueError("offline faculty authorization expired; connect to central server")
        existing = self.store.kv_get("snapshot")
        if existing and existing["faculty"]["user_id"] != snapshot["faculty"]["user_id"]:
            raise ValueError("cache belongs to another faculty member; use a separate device profile")

    def unlock(self, pin):
        if self.pin_locked_until and self.now() < self.pin_locked_until:
            raise ValueError("Offline PIN temporarily locked after repeated failures")
        stored = self.store.kv_get("faculty_pin")
        if stored is None or not verify_password(stored, pin):
            self.pin_failures += 1
            if self.pin_failures >= 5:
                self.pin_locked_until = self.now() + timedelta(minutes=5)
                self.pin_failures = 0
            raise ValueError("incorrect offline faculty PIN")
        self._validate_snapshot(self.store.kv_get("snapshot"))
        self.pin_failures, self.pin_locked_until, self.unlocked = 0, None, True

    def _require(self):
        if not self.unlocked:
            raise ValueError("faculty interface locked; unlock with the offline PIN")
        snapshot = self.store.kv_get("snapshot")
        self._validate_snapshot(snapshot)
        return snapshot

    def install_snapshot(self, snapshot):
        with self.lock:
            self._require()
            self._validate_snapshot(snapshot)
            with self.store.transaction() as db:
                self.store.kv_set("snapshot", snapshot, db)
                # A new authorization snapshot invalidates open biometric intake/challenges.
                for s in self.store.sessions():
                    if s["state"] == "COLLECTING":
                        s["state"], s["closed_at"] = "REVIEW", stamp(min(self.now(), parse_stamp(s["close_at"])))
                        self.store.save_session(s, db)
            self.attempts.clear()

    def refresh_authorization(self, snapshot, pin):
        with self.lock:
            stored = self.store.kv_get("faculty_pin")
            if not stored or not verify_password(stored, pin):
                raise ValueError("incorrect offline faculty PIN")
            self._validate_snapshot(snapshot)
            self.privacy_lock()
            self.store.kv_set("snapshot", snapshot)
            self.unlocked = True

    def list_sessions(self):
        self._require()
        return [self._public_session(s) for s in self.store.sessions()]

    def _public_session(self, s):
        out = copy.deepcopy(s)
        out.pop("qr_secret", None)
        return out

    def session(self, sid):
        self._require()
        return self._public_session(self.store.session(sid))

    def _class(self, snapshot, section, course):
        for c in snapshot["classes"]:
            if c["section_id"] == section and c["course_id"] == course:
                return c
        raise ValueError("faculty is not authorized for this class; synchronize or request assignment")

    def start_session(self, section_id, course_id, period_number):
        with self.lock:
            snap = self._require()
            cls = self._class(snap, section_id, course_id)
            local = self.now().replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(snap["policy"]["timezone"]))
            day = str(local.date())
            if any(
                c["date"] == day
                and c["section_id"] == section_id
                and c["course_id"] == course_id
                and c["period_number"] == period_number
                for c in snap.get("cancelled_classes", [])
            ):
                raise ValueError("class was cancelled; classroom collection is unavailable")
            if any(h["date"] == day for h in snap["holidays"]):
                raise ValueError("holiday: classroom collection is unavailable")
            if cls["assignment_start"] > day or (cls.get("assignment_end") and cls["assignment_end"] < day):
                raise ValueError("faculty class authorization expired")
            slot = next(
                (
                    t
                    for t in snap["timetable"]
                    if t["weekday"] == local.weekday()
                    and t["period_number"] == period_number
                    and t["section_id"] == section_id
                    and t["course_id"] == course_id
                ),
                None,
            )
            if slot is None or slot.get("is_break"):
                raise ValueError("no assigned teaching period at this time")
            period = next((p for p in snap["periods"] if p["number"] == period_number), {})
            if period.get("is_break"):
                raise ValueError("period is a break")
            start = slot.get("start_time") or period.get("start_time")
            end = slot.get("end_time") or period.get("end_time")
            if not collection_start_allowed(local, start, end):
                raise ValueError("outside the scheduled class and five-minute start grace; check the timetable")
            for existing in self.store.sessions():
                if (existing["section_id"], existing["course_id"], existing["period_number"], existing["date"]) == (
                    section_id,
                    course_id,
                    period_number,
                    day,
                ):
                    raise ValueError("attendance session already exists for this class; open its saved roster")
                if existing["state"] == "COLLECTING":
                    raise ValueError("close the current classroom collection first")
            close_at = min(self.now() + timedelta(seconds=COLLECTION_SECONDS), parse_stamp(snap["offline_valid_until"]))
            rows = []
            for student in cls["roster"]:
                rows.append(
                    {k: v for k, v in student.items() if k not in ("references", "model_id", "pipeline_version")}
                )
                rows[-1].update(
                    status="UNMARKED", method=None, reason="", suggested=None, submission=None, review=None, attempts=0
                )
            session = {
                "id": str(uuid.uuid4()),
                "faculty_user_id": snap["faculty"]["user_id"],
                "grant_id": snap["grant_id"],
                "section_id": section_id,
                "course_id": course_id,
                "section": cls["section"],
                "course": cls["course"],
                "period_number": period_number,
                "date": day,
                "state": "COLLECTING",
                "started_at": stamp(self.now()),
                "close_at": stamp(close_at),
                "closed_at": None,
                "revision": 0,
                "qr_secret": secrets.token_hex(32),
                "roster": rows,
                "audit": [],
            }
            with self.store.transaction() as db:
                self.store.save_session(session, db)
            return self._public_session(session)

    def available_meetings(self):
        """Eligible meetings, newest current class first, with existing roster links."""
        snap = self._require()
        local = self.now().replace(tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo(snap["policy"]["timezone"]))
        day = str(local.date())
        if any(h["date"] == day for h in snap["holidays"]):
            return []
        meetings = []
        sessions = self.store.sessions()
        for slot in snap["timetable"]:
            if slot["weekday"] != local.weekday() or slot.get("is_break"):
                continue
            cls = next(
                (
                    c
                    for c in snap["classes"]
                    if c["section_id"] == slot["section_id"] and c["course_id"] == slot["course_id"]
                ),
                None,
            )
            if not cls or cls["assignment_start"] > day or (cls.get("assignment_end") and cls["assignment_end"] < day):
                continue
            if any(
                c["date"] == day and all(c[k] == slot[k] for k in ("section_id", "course_id", "period_number"))
                for c in snap.get("cancelled_classes", [])
            ):
                continue
            period = next((p for p in snap["periods"] if p["number"] == slot["period_number"]), {})
            start = slot.get("start_time") or period.get("start_time")
            end = slot.get("end_time") or period.get("end_time")
            if period.get("is_break") or not collection_start_allowed(local, start, end):
                continue
            existing = next(
                (
                    s
                    for s in sessions
                    if s["date"] == day and all(s[k] == slot[k] for k in ("section_id", "course_id", "period_number"))
                ),
                None,
            )
            meetings.append(
                {
                    "section_id": slot["section_id"],
                    "course_id": slot["course_id"],
                    "period_number": slot["period_number"],
                    "section": cls["section"],
                    "course": cls["course"],
                    "start_time": start,
                    "end_time": end,
                    "session_id": existing["id"] if existing else None,
                }
            )
        return sorted(meetings, key=lambda m: m["start_time"], reverse=True)

    def _open(self, sid):
        snap = self._require()
        s = self.store.session(sid)
        self._class(snap, s["section_id"], s["course_id"])
        if s["state"] != "COLLECTING" or self.now() >= parse_stamp(s["close_at"]):
            raise ValueError("classroom collection has closed; faculty review remains available")
        return s, snap

    def close_collection(self, sid):
        with self.lock:
            self._require()
            with self.store.transaction() as db:
                s = self.store.session(sid, db)
                if s["state"] == "COLLECTING":
                    s["state"], s["closed_at"] = "REVIEW", stamp(min(self.now(), parse_stamp(s["close_at"])))
                    self.store.save_session(s, db)
            self.attempts = {k: a for k, a in self.attempts.items() if a["session_id"] != sid}
            return self._public_session(s)

    def current_qr(self, sid):
        with self.lock:
            s, _ = self._open(sid)
            epoch = int(self.now().timestamp()) // 5
            message = f"{sid}.{epoch}"
            signature = hmac.new(bytes.fromhex(s["qr_secret"]), message.encode(), hashlib.sha256).hexdigest()[:32]
            return {"token": message + "." + signature, "seconds_remaining": 5 - int(self.now().timestamp()) % 5}

    def _qr(self, token):
        try:
            sid, slot, signature = token.split(".")
            s, snap = self._open(sid)
            expected = self.current_qr(sid)["token"]
            if not hmac.compare_digest(token, expected):
                raise ValueError("QR expired or invalid; scan the current classroom QR")
            return s, snap, int(slot)
        except (TypeError, KeyError, AttributeError) as exc:
            raise ValueError("invalid QR token") from exc

    def enter(self, qr_token, ip):
        with self.lock:
            s, _, epoch = self._qr(qr_token)
            self.attempts = {k: a for k, a in self.attempts.items() if a["expires_at"] > self.now()}
            if len(self.attempts) >= 1000:
                raise ValueError("classroom service busy; ask faculty for assistance")
            token = secrets.token_urlsafe(32)
            self.attempts[token] = {
                "session_id": s["id"],
                "entry_qr": qr_token,
                "entry_epoch": epoch,
                "ip": ip,
                "expires_at": min(self.now() + timedelta(seconds=120), parse_stamp(s["close_at"])),
                "student_id": None,
                "state": "ENTRY",
            }
            return {"attempt_token": token, "status": "ENTRY", "expires_in": 120}

    def _attempt(self, token, ip):
        attempt = self.attempts.get(token)
        if not attempt or attempt["ip"] != ip or attempt["expires_at"] <= self.now():
            raise ValueError("attempt expired or belongs to another device; scan the current QR")
        s, snap = self._open(attempt["session_id"])
        return attempt, s, snap

    def _row(self, s, sid):
        row = next((r for r in s["roster"] if r["student_id"] == sid), None)
        if row is None:
            raise ValueError("student not on session roster")
        return row

    def _review(self, s, sid, reason):
        row = self._row(s, sid)
        prior = row["review"]
        row["review"] = {
            "reason": reason,
            "attempts": (prior["attempts"] if prior else 0) + 1,
            "resolved": False,
            "last_attempt": stamp(self.now()),
        }
        with self.store.transaction() as db:
            self.store.save_session(s, db)

    def claim(self, token, roll_number, ip):
        with self.lock:
            attempt, s, snap = self._attempt(token, ip)
            if attempt["state"] != "ENTRY":
                raise ValueError("roll number already claimed; scan a new entry QR to retry")
            student = next(
                (
                    r
                    for r in self._class(snap, s["section_id"], s["course_id"])["roster"]
                    if r["roll_number"].upper() == roll_number.strip().upper()
                ),
                None,
            )
            if student is None:
                raise ValueError("unable to continue; check your roll number or ask faculty")
            row = self._row(s, student["student_id"])
            if row["submission"]:
                raise ValueError("submission already received; awaiting faculty confirmation")
            attempt["student_id"] = student["student_id"]
            if (
                student["enrollment_state"] != "ACTIVE"
                or len(student["references"]) != 3
                or not student["expires_on"]
                or student["expires_on"] < s["date"]
                or student.get("model_id") != self.engine.model_id
                or student.get("pipeline_version") != PIPELINE_VERSION
            ):
                attempt["state"] = "REVIEW"
                self._review(
                    s,
                    row["student_id"],
                    "biometrics unavailable, expired or incompatible; faculty must check physically",
                )
                return {
                    "status": "FACULTY_REVIEW_REQUIRED",
                    "message": "Please ask faculty to mark attendance manually.",
                }
            if row["attempts"] >= int(snap["policy"]["max_attempts_per_session"]):
                raise ValueError("attempt limit reached; ask faculty for manual review")
            # At most one current challenge per student/session. Claiming a roll never marks attendance.
            for a in self.attempts.values():
                if a is not attempt and a["session_id"] == s["id"] and a["student_id"] == student["student_id"]:
                    a["state"] = "SUPERSEDED"
            row["attempts"] += 1
            with self.store.transaction() as db:
                self.store.save_session(s, db)
            steps = generate_steps(int(snap["policy"]["challenge_steps"]))
            attempt.update(
                state="CHALLENGE",
                steps=steps,
                issued_at=self.now(),
                expires_at=min(
                    self.now() + timedelta(seconds=int(snap["policy"]["challenge_ttl_seconds"])),
                    parse_stamp(s["close_at"]),
                ),
            )
            return {
                "status": "CHALLENGE",
                "steps": [{"action": a, "label": LABELS[a]} for a in steps],
                "ttl_seconds": int(snap["policy"]["challenge_ttl_seconds"]),
                "guidance": {k: snap["policy"][k] for k in ("yaw_delta", "pitch_delta", "blink_closed", "blink_open")},
            }

    def verify(self, token, frames, timestamps, ip):
        with self.lock:
            attempt, s, snap = self._attempt(token, ip)
            if attempt["state"] != "CHALLENGE":
                raise ValueError("challenge already used or superseded")
            attempt["state"] = "CONSUMED"
            rt = snap["policy"]

            def reject(reason, decision="rejected"):
                attempt["state"] = "REVIEW"
                self._row(s, attempt["student_id"])["verification"] = {
                    "decision": decision.upper(),
                    "at": stamp(self.now()),
                }
                self._review(s, attempt["student_id"], reason)
                return {"decision": decision, "reason": reason, "marked": False}

            if not 6 <= len(frames) <= 200 or len(frames) != len(timestamps):
                return reject("invalid frame count or timestamps")
            if any(len(f) > 250_000 for f in frames) or not all(math.isfinite(t) for t in timestamps):
                return reject("frame size or timing invalid")
            elapsed = (self.now() - attempt["issued_at"]).total_seconds() * 1000
            if timestamps[-1] - timestamps[0] > elapsed + 2000:
                return reject("frame timing inconsistent with challenge")
            digests = [hashlib.sha256(f).digest() for f in frames]
            if sum(a == b for a, b in zip(digests, digests[1:], strict=False)) / (len(frames) - 1) > 0.3:
                return reject("camera feed appears frozen")
            try:
                images = [decode_image(f, max_side=1280) for f in frames]
                metrics = [self.engine.frame_metrics(i) for i in images]
                live = validate(attempt["steps"], list(zip(timestamps, metrics, strict=True)), rt)
                if not live.passed:
                    return reject(live.reason)
                student = next(
                    r
                    for r in self._class(snap, s["section_id"], s["course_id"])["roster"]
                    if r["student_id"] == attempt["student_id"]
                )
                refs = [np.asarray(r, dtype=np.float32) for r in student["references"]]
                scores = []
                for idx in dict.fromkeys(live.start_frames + live.end_frames):
                    obs = self.engine.observe(images[idx], rt)
                    if obs.usable and obs.embedding is not None:
                        # Median of three reference scores; never an uncalibrated max-of-three rule.
                        scores.append(median(cosine(obs.embedding, ref) for ref in refs))
                decision = decide(scores, rt)
            except Exception:
                # No frames or sensitive exception strings in persisted records or responses.
                return reject("inference unavailable; ask faculty for manual review", "abstain")
            # Expiry/closing are checked after potentially slow GPU/CPU work as well.
            try:
                self._open(s["id"])
                if attempt["expires_at"] <= self.now():
                    return reject("challenge expired during verification")
            except ValueError:
                return reject("collection closed during verification")
            if decision.decision != "match":
                return reject(decision.reason, decision.decision)
            attempt.update(
                state="MATCH",
                match_at=self.now(),
                expires_at=min(self.now() + timedelta(seconds=90), parse_stamp(s["close_at"])),
            )
            self._row(s, attempt["student_id"])["verification"] = {"decision": "MATCH", "at": stamp(self.now())}
            with self.store.transaction() as db:
                self.store.save_session(s, db)
            return {
                "decision": "match",
                "reason": "Face matched; scan the fresh classroom QR to submit.",
                "marked": False,
            }

    def submit(self, token, qr_token, ip):
        with self.lock:
            attempt, s, _ = self._attempt(token, ip)
            if attempt["state"] != "MATCH":
                raise ValueError("valid unused server-side MATCH is required before final QR submission")
            other, _, epoch = self._qr(qr_token)
            if other["id"] != s["id"] or epoch <= attempt["entry_epoch"] or qr_token == attempt["entry_qr"]:
                raise ValueError("scan a fresh QR from the same classroom session")
            row = self._row(s, attempt["student_id"])
            if row["submission"]:
                raise ValueError("submission already received")
            row["suggested"] = "PRESENT"
            row["submission"] = {"status": "PENDING_FACULTY_APPROVAL", "at": stamp(self.now()), "method": "face"}
            if row["review"]:
                row["review"]["resolved"] = True
            self._suggest_present(s, row)
            with self.store.transaction() as db:
                self.store.save_session(s, db)
            attempt["state"] = "SUBMITTED"
            return {
                "status": "PENDING_FACULTY_APPROVAL",
                "message": "Submitted successfully. Awaiting faculty confirmation.",
            }

    def mark(self, sid, student_id, status, reason):
        with self.lock:
            self._require()
            if status not in ("PRESENT", "ABSENT", "UNMARKED") or len(reason.strip()) < 3:
                raise ValueError("explicit status and a reason of at least three characters are required")
            with self.store.transaction() as db:
                s = self.store.session(sid, db)
                if s["state"] == "APPROVED":
                    raise ValueError("approved attendance is frozen; create an audited amendment")
                row = self._row(s, student_id)
                previous = row["status"]
                row.update(
                    status=status,
                    reason=reason.strip(),
                    method="face" if status == "PRESENT" and row["submission"] else "manual",
                    decision_source="faculty",
                )
                if row["review"]:
                    row["review"]["resolved"] = status != "UNMARKED"
                s["audit"].append(
                    {
                        "action": "mark",
                        "student_id": student_id,
                        "previous": previous,
                        "status": status,
                        "reason": reason.strip(),
                        "at": stamp(self.now()),
                    }
                )
                self.store.save_session(s, db)
            return self._public_session(s)

    def headcount_review(self, sid, headcount):
        return headcount_report(self.session(sid), headcount)

    def record_headcount(self, sid, headcount):
        with self.lock:
            self._require()
            with self.store.transaction() as db:
                session = self.store.session(sid, db)
                if session["state"] == "APPROVED":
                    raise ValueError("approved headcount is frozen; use an audited amendment")
                headcount_report(session, headcount)
                previous = session.get("draft_headcount")
                if previous != headcount:
                    session["draft_headcount"] = headcount
                    session["audit"].append(
                        {
                            "action": "headcount_recount",
                            "previous": previous,
                            "headcount": headcount,
                            "at": stamp(self.now()),
                        }
                    )
                    self.store.save_session(session, db)
                return self._public_session(session)

    def _approved_event(self, s, headcount, mismatch_reason, amendment_reason=""):
        current_grant = self._require()["grant_id"]
        if any(r["status"] == "UNMARKED" for r in s["roster"]):
            raise ValueError("resolve every UNMARKED student explicitly before approval")
        if any(r["review"] and not r["review"]["resolved"] for r in s["roster"]):
            raise ValueError("resolve faculty review cases before approval")
        count = sum(r["status"] == "PRESENT" for r in s["roster"])
        if not isinstance(headcount, int) or headcount < 0 or headcount > 10000:
            raise ValueError("invalid physical headcount")
        if headcount != count and len(mismatch_reason.strip()) < 3:
            raise ValueError("headcount differs from present marks; record an explicit discrepancy reason")
        s["state"], s["headcount"], s["mismatch_reason"] = "APPROVED", headcount, mismatch_reason
        s["revision"] += 1
        s["approved_at"] = stamp(self.now())
        event = {k: copy.deepcopy(v) for k, v in s.items() if k not in ("qr_secret", "state", "id")}
        event.update(event_id=str(uuid.uuid4()), session_id=s["id"], amendment_reason=amendment_reason)
        event["approval_grant_id"] = current_grant
        return event

    def approve(self, sid, headcount, mismatch_reason=""):
        with self.lock:
            self._require()
            with self.store.transaction() as db:
                s = self.store.session(sid, db)
                if s["state"] == "APPROVED":
                    raise ValueError("attendance already approved")
                if s["state"] == "COLLECTING" and self.now() < parse_stamp(s["close_at"]):
                    raise ValueError("close collection before final faculty approval")
                s["closed_at"] = s["closed_at"] or s["close_at"]
                event = self._approved_event(s, headcount, mismatch_reason)
                self.store.save_session(s, db)
                db.execute("INSERT INTO outbox(id,enc) VALUES(?,?)", (event["event_id"], self.store.encode(event)))
            return self._public_session(s)

    def amend(self, sid, student_id, status, reason, headcount, mismatch_reason=""):
        with self.lock:
            self._require()
            if status not in ("PRESENT", "ABSENT") or len(reason.strip()) < 3:
                raise ValueError("amendment needs an explicit mark and reason")
            with self.store.transaction() as db:
                s = self.store.session(sid, db)
                if s["state"] != "APPROVED":
                    raise ValueError("only approved attendance can be amended")
                row = self._row(s, student_id)
                s["audit"].append(
                    {
                        "action": "amend",
                        "student_id": student_id,
                        "previous": row["status"],
                        "status": status,
                        "reason": reason,
                        "at": stamp(self.now()),
                    }
                )
                row.update(status=status, method="manual", reason=reason)
                event = self._approved_event(s, headcount, mismatch_reason, reason)
                self.store.save_session(s, db)
                db.execute("INSERT INTO outbox(id,enc) VALUES(?,?)", (event["event_id"], self.store.encode(event)))
            return self._public_session(s)

    def pending_events(self):
        return self.store.pending()

    def acknowledge(self, response):
        with self.store.transaction() as db:
            row = db.execute("SELECT enc FROM outbox WHERE id=?", (response.get("event_id"),)).fetchone()
            if not row or content_hash(self.store.decode(row[0])) != response.get("content_hash"):
                raise ValueError("central acknowledgment does not match the approved event")
            db.execute("UPDATE outbox SET acknowledged=1,last_error='' WHERE id=?", (response["event_id"],))

    def privacy_lock(self):
        # Revoke intake immediately, even while an inference thread owns the runtime lock.
        # That thread's post-inference authorization check must observe this flag.
        self.unlocked = False
        with self.lock:
            with self.store.transaction() as db:
                for s in self.store.sessions():
                    if s["state"] == "COLLECTING":
                        s["state"], s["closed_at"] = "REVIEW", stamp(min(self.now(), parse_stamp(s["close_at"])))
                        self.store.save_session(s, db)
            self.attempts.clear()
            self.unlocked = False
