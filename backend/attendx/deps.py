"""Request dependencies: DB session, authentication, CSRF and role checks."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from attendx.db import utcnow
from attendx.models import AuthSession, Student, User
from attendx.security import CSRF_HEADER, SESSION_COOKIE, csrf_ok, lookup_session
from attendx.services.audit import get_runtime

SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def get_db(request: Request) -> Iterator[Session]:
    yield from request.app.state.db.session()


def client_ip(request: Request) -> str:
    if request.app.state.settings_obj.trust_proxy:
        # the LAST entry is the one appended by our own proxy (Tailscale Serve); earlier entries
        # are client-controlled and are ignored
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            return fwd.split(",")[-1].strip()[:64]
    return (request.client.host if request.client else "")[:64]


@dataclass
class Auth:
    user: User
    session: AuthSession
    ip: str

    @property
    def student(self) -> Student:
        if self.user.student is None:
            raise HTTPException(403, "no student profile linked to this account")
        return self.user.student


def current_auth(request: Request, db: Session = Depends(get_db)) -> Auth:
    sess = lookup_session(db, request.cookies.get(SESSION_COOKIE))
    if sess is None:
        raise HTTPException(401, "not signed in")
    user = db.get(User, sess.user_id)
    if user is None or not user.is_active or user.account_state != "ACTIVE":
        raise HTTPException(401, "account disabled")
    if request.method not in SAFE_METHODS and not csrf_ok(sess, request.headers.get(CSRF_HEADER)):
        raise HTTPException(403, "missing or invalid CSRF token")
    now = utcnow()
    if (now - sess.last_seen_at).total_seconds() > 60:
        sess.last_seen_at = now
        db.commit()
    return Auth(user, sess, client_ip(request))


def _password_gate(auth: Auth, request: Request) -> None:
    if auth.user.must_change_password and not request.url.path.endswith("/change-password"):
        raise HTTPException(403, "password change required")


def require_admin(request: Request, auth: Auth = Depends(current_auth)) -> Auth:
    if auth.user.role != "admin":
        raise HTTPException(403, "administrator access required")
    _password_gate(auth, request)
    return auth


def require_student(request: Request, auth: Auth = Depends(current_auth)) -> Auth:
    if auth.user.role != "student" or auth.user.student is None:
        raise HTTPException(403, "student access required")
    _password_gate(auth, request)
    return auth


def runtime(db: Session = Depends(get_db)) -> dict[str, Any]:
    return get_runtime(db)
