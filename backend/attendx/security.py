"""Authentication primitives: Argon2id password hashing, opaque server-side sessions (only the
SHA-256 of the cookie token is stored), per-session CSRF tokens and an in-memory rate limiter."""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlalchemy.orm import Session

from attendx.db import utcnow
from attendx.models import AuthSession, User

SESSION_COOKIE = "attendx_session"
CSRF_HEADER = "X-CSRF-Token"
_ph = PasswordHasher()  # Argon2id, library defaults (RFC 9106 low-memory profile)

MIN_PASSWORD_LEN = 8


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        return _ph.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def password_problem(password: str) -> str | None:
    if len(password) < MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters."
    if len(password) > 128:
        return "Password is too long."
    if password.isdigit() or password.isalpha():
        return "Use a mix of letters and numbers or symbols."
    return None


def generate_password() -> str:
    """Readable random initial password (shown once to the administrator)."""
    alphabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    core = "".join(secrets.choice(alphabet) for _ in range(10))
    return f"{core[:5]}-{core[5:]}{secrets.randbelow(10)}"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(db: Session, user: User, hours: int, ip: str, ua: str) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(24)
    db.add(
        AuthSession(
            token_hash=_token_hash(token),
            user_id=user.id,
            csrf_token=csrf,
            expires_at=utcnow() + timedelta(hours=hours),
            ip=ip[:64],
            user_agent=ua[:256],
        )
    )
    return token, csrf


def lookup_session(db: Session, token: str | None) -> AuthSession | None:
    if not token:
        return None
    sess = db.get(AuthSession, _token_hash(token))
    if sess is None or sess.expires_at <= utcnow():
        return None
    return sess


def delete_session(db: Session, token: str | None) -> None:
    if token:
        sess = db.get(AuthSession, _token_hash(token))
        if sess is not None:
            db.delete(sess)


def csrf_ok(sess: AuthSession, header_value: str | None) -> bool:
    return bool(header_value) and secrets.compare_digest(sess.csrf_token, header_value or "")


class RateLimiter:
    """Sliding-window limiter keyed by an arbitrary string (single-process deployment)."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_s: float = 60.0) -> bool:
        """Record an event; return False when the key exceeded ``limit`` within the window."""
        now = time.monotonic()
        with self._lock:
            q = self._events[key]
            while q and now - q[0] > window_s:
                q.popleft()
            if len(q) >= limit:
                return False
            q.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._events.clear()
