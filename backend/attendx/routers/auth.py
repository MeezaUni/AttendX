from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from attendx.db import utcnow
from attendx.deps import Auth, client_ip, current_auth, get_db
from attendx.models import AuthSession, User
from attendx.security import (
    SESSION_COOKIE,
    create_session,
    delete_session,
    hash_password,
    password_problem,
    verify_password,
)
from attendx.services.audit import audit

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Constant-time-ish dummy hash so unknown usernames cost the same as wrong passwords.
_DUMMY_HASH = hash_password("dummy-password-for-timing-1")


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class ChangePasswordIn(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(max_length=128)


def user_out(user: User, csrf: str | None = None) -> dict:
    out = {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "display_name": user.display_name,
        "must_change_password": user.must_change_password,
        "account_state": user.account_state,
        "faculty_id": user.faculty_id,
    }
    if user.student is not None:
        s = user.student
        out["student"] = {
            "id": s.id,
            "roll_number": s.roll_number,
            "name": s.name,
            "section": s.section.name if s.section else None,
            "face_status": s.face_status,
        }
    if csrf:
        out["csrf_token"] = csrf
    return out


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    # Login requires a custom header: cross-site forms cannot send it without a CORS preflight,
    # which this server never grants (login CSRF protection).
    if request.headers.get("x-requested-with") != "attendx":
        raise HTTPException(400, "missing X-Requested-With header")
    st = request.app.state
    ip = client_ip(request)
    if not st.limiter.hit(f"login:{ip}", st.settings_obj.login_per_minute):
        raise HTTPException(429, "too many sign-in attempts; wait a minute")
    username = body.username.strip()
    user = db.scalar(select(User).where(User.username == username))
    now = utcnow()
    if user is not None and user.locked_until and user.locked_until > now:
        raise HTTPException(429, "account temporarily locked after failed attempts; try later")
    ok = verify_password(user.password_hash if user else _DUMMY_HASH, body.password)
    if user is None or not ok or not user.is_active or user.account_state != "ACTIVE":
        if user is not None:
            user.failed_logins += 1
            if user.failed_logins >= st.settings_obj.login_lockout_failures:
                user.locked_until = now + timedelta(minutes=st.settings_obj.login_lockout_minutes)
                user.failed_logins = 0
                audit(db, None, "auth.lockout", "user", user.id, ip, username=user.username)
            db.commit()
        raise HTTPException(401, "incorrect username or password")
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    hours = st.settings_obj.session_hours if user.role == "admin" else st.settings_obj.student_session_hours
    token, csrf = create_session(db, user, hours, ip, request.headers.get("user-agent", ""))
    audit(db, user, "auth.login", "user", user.id, ip)
    db.commit()
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=hours * 3600,
        httponly=True,
        secure=st.settings_obj.cookie_secure,
        samesite="strict",
        path="/",
    )
    return user_out(user, csrf)


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    delete_session(db, request.cookies.get(SESSION_COOKIE))
    db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"ok": True}


@router.get("/me")
def me(auth: Auth = Depends(current_auth)):
    return user_out(auth.user, auth.session.csrf_token)


@router.post("/change-password")
def change_password(
    body: ChangePasswordIn,
    request: Request,
    tasks: BackgroundTasks,
    auth: Auth = Depends(current_auth),
    db: Session = Depends(get_db),
):
    user = db.get(User, auth.user.id)
    assert user is not None
    if not verify_password(user.password_hash, body.current_password):
        raise HTTPException(400, "current password is incorrect")
    problem = password_problem(body.new_password)
    if problem:
        raise HTTPException(400, problem)
    if body.new_password == body.current_password:
        raise HTTPException(400, "choose a different password")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    # sign out every other session of this user
    for s in db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)):
        if s.token_hash != auth.session.token_hash:
            db.delete(s)
    audit(db, user, "auth.change_password", "user", user.id, auth.ip)
    if user.email:
        from attendx.v2.identity import deliver_mail, queue_mail
        from attendx.v2.models import ActionToken, FacultyDevice

        db.execute(
            update(ActionToken)
            .where(ActionToken.user_id == user.id, ActionToken.kind == "reset", ActionToken.consumed_at.is_(None))
            .values(consumed_at=utcnow())
        )
        db.execute(update(FacultyDevice).where(FacultyDevice.user_id == user.id).values(revoked=True))
        queue_mail(
            db, request.app.state, user.email, "AttendX password changed", "Your central portal password was changed."
        )
        tasks.add_task(deliver_mail, request.app.state)
    db.commit()
    return {"ok": True}
