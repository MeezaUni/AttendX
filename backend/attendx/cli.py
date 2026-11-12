"""Command line: ``attendx create-admin | serve | migrate | check-models | seed-demo``."""

from __future__ import annotations

import argparse
import getpass
import random
import sys
from datetime import timedelta

from sqlalchemy import select


def _db():  # type: ignore[no-untyped-def]
    from attendx.config import get_settings
    from attendx.db import Database
    from attendx.main import init_database

    settings = get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    db = Database(settings.db_url)
    init_database(db)
    return settings, db


def cmd_create_admin(args: argparse.Namespace) -> int:
    from attendx.models import User
    from attendx.security import hash_password, password_problem
    from attendx.services.audit import audit

    _, db = _db()
    if args.password_stdin:
        password = sys.stdin.readline().rstrip("\r\n")
    else:
        password = getpass.getpass("New admin password: ")
        if getpass.getpass("Repeat password: ") != password:
            print("Passwords do not match.", file=sys.stderr)
            return 1
    if problem := password_problem(password):
        print(problem, file=sys.stderr)
        return 1
    with db.SessionLocal() as s:
        user = s.scalar(select(User).where(User.username == args.username))
        if user is not None and not args.reset:
            print(f"User {args.username!r} exists (use --reset to set a new password).", file=sys.stderr)
            return 1
        if user is None:
            user = User(username=args.username, role="admin", display_name=args.name or args.username,
                        password_hash=hash_password(password))  # fmt: skip
            s.add(user)
        else:
            if user.role != "admin":
                print("That username belongs to a student.", file=sys.stderr)
                return 1
            user.password_hash = hash_password(password)
            user.locked_until = None
            user.is_active = True
        s.flush()
        audit(s, None, "admin.create_cli" if not args.reset else "admin.reset_cli", "user", user.id,
              username=user.username)  # fmt: skip
        s.commit()
    print(f"Administrator {args.username!r} is ready.")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    import os

    import uvicorn

    if hasattr(os, "umask"):
        os.umask(0o077)  # database, WAL files and template key readable by the service user only

    uvicorn.run(
        "attendx.main:create_app", factory=True, host=args.host, port=args.port,
        proxy_headers=False, log_level="info", server_header=False,
    )  # fmt: skip
    return 0


def cmd_migrate(_: argparse.Namespace) -> int:
    settings, _db_ = _db()
    print(f"Database at revision head: {settings.db_url}")
    return 0


def cmd_check_models(_: argparse.Namespace) -> int:
    import time

    import numpy as np

    from attendx.config import RUNTIME_DEFAULTS, get_settings
    from attendx.face.engine import RealFaceEngine

    s = get_settings()
    eng = RealFaceEngine(s.models_dir, s.device, s.verify_model_hashes)
    t = time.perf_counter()
    eng.warmup()
    print(f"loaded in {time.perf_counter() - t:.1f}s: {eng.status()}")
    blank = np.full((480, 640, 3), 128, np.uint8)
    obs = eng.observe(blank, dict(RUNTIME_DEFAULTS))
    print(f"blank frame -> faces={obs.n_faces} problems={obs.problems}")
    return 0


def cmd_seed_demo(args: argparse.Namespace) -> int:
    """Synthetic demonstration data: sections, courses, faculty, timetable, students and past
    attendance. NO biometric data is created; demo students are flagged ``is_synthetic``."""
    from attendx.models import (
        AttendanceRecord,
        Course,
        Faculty,
        Section,
        Student,
        TimetableEntry,
        User,
    )
    from attendx.security import generate_password, hash_password
    from attendx.services import schedule as sch
    from attendx.services.audit import audit

    settings, db = _db()
    if not (settings.demo_mode or args.force):
        print("Set ATTENDX_DEMO_MODE=true (or pass --force) to seed synthetic data.", file=sys.stderr)
        return 1
    rng = random.Random(args.seed)
    with db.SessionLocal() as s:
        if s.scalar(select(Section).where(Section.name == "DEMO-5A")):
            print("Demo data already present.")
            return 0
        fac = [Faculty(name=n, department="CSE") for n in
               ("Dr. Demo Faculty A", "Dr. Demo Faculty B", "Prof. Demo Faculty C")]  # fmt: skip
        s.add_all(fac)
        s.flush()
        courses = [
            Course(code="DL3101", name="Deep Learning", department="CSE", faculty_id=fac[0].id),
            Course(code="CV3102", name="Computer Vision", department="CSE", faculty_id=fac[1].id),
            Course(code="DB3103", name="Database Systems", department="CSE", faculty_id=fac[2].id),
            Course(code="MA3104", name="Probability and Statistics", department="MATH", faculty_id=fac[2].id),
            Course(code="CC3105", name="Cloud Computing", department="CSE", faculty_id=fac[1].id),
            Course(code="HS3106", name="Professional Ethics", department="HSS", faculty_id=fac[0].id),
        ]
        s.add_all(courses)
        sec = Section(name="DEMO-5A", department="CSE", semester=5)
        s.add(sec)
        s.flush()
        # Mon-Fri: six classes, two free periods; Wednesday period 4 is a marked break slot
        for wd in range(5):
            order = courses[wd % 6 :] + courses[: wd % 6]
            for p in range(1, 9):
                if p in (4, 8) and wd != 2:
                    continue
                if wd == 2 and p == 4:
                    s.add(TimetableEntry(weekday=wd, period_number=p, section_id=sec.id, is_break=True))
                    continue
                c = order[(p - 1) % 6]
                s.add(TimetableEntry(weekday=wd, period_number=p, section_id=sec.id,
                                     course_id=c.id, faculty_id=c.faculty_id, room="LH-101"))  # fmt: skip
        passwords = []
        students = []
        for k in range(1, args.students + 1):
            st = Student(roll_number=f"DEMO5A{k:02d}", name=f"Demo Student {k:02d}",
                         department="CSE", semester=5, section_id=sec.id, is_synthetic=True)  # fmt: skip
            s.add(st)
            s.flush()
            pw = generate_password()
            passwords.append((st.roll_number, pw))
            s.add(User(username=st.roll_number, password_hash=hash_password(pw), role="student",
                       display_name=st.name, student_id=st.id, must_change_password=True))  # fmt: skip
            students.append(st)
        s.flush()
        # past attendance (synthetic, method "synthetic"), last 10 school days
        today = sch.local_today(settings.tz)
        d, days = today - timedelta(days=1), 0
        rates = {st.id: rng.uniform(0.6, 0.98) for st in students}
        while days < 10:
            sessions = sch.ensure_sessions_for_date(s, d, settings.tz)
            if sessions:
                days += 1
            for sess in sessions:
                for st in students:
                    if rng.random() < rates[st.id]:
                        s.add(AttendanceRecord(
                            session_id=sess.id, student_id=st.id, course_id=sess.course_id,
                            section_id=sess.section_id, date=d, status="present", method="synthetic",
                            verified_at=sess.open_at + timedelta(minutes=rng.randint(0, 9)),
                        ))  # fmt: skip
            d -= timedelta(days=1)
        audit(s, None, "demo.seed", "demo", "", students=len(students))
        s.commit()
    print("Synthetic demo data created (section DEMO-5A). Initial student passwords:")
    for roll, pw in passwords:
        print(f"  {roll}  {pw}")
    print("Students must change the password at first sign-in. No face data was created.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="attendx")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("create-admin", help="create (or --reset) an administrator account")
    p.add_argument("--username", required=True)
    p.add_argument("--name", default="")
    p.add_argument("--password-stdin", action="store_true", help="read the password from stdin")
    p.add_argument("--reset", action="store_true")
    p.set_defaults(fn=cmd_create_admin)
    p = sub.add_parser("serve", help="run the web server")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8470)
    p.set_defaults(fn=cmd_serve)
    sub.add_parser("migrate", help="apply database migrations").set_defaults(fn=cmd_migrate)
    sub.add_parser("check-models", help="load and smoke-test the face models").set_defaults(fn=cmd_check_models)
    p = sub.add_parser("seed-demo", help="create synthetic demonstration data")
    p.add_argument("--students", type=int, default=12)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_seed_demo)
    args = ap.parse_args(argv)
    return int(args.fn(args))


if __name__ == "__main__":
    sys.exit(main())
