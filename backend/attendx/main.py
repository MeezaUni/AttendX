"""FastAPI application factory. One origin serves the SPA and ``/api`` (no CORS needed)."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select, text

from attendx.config import Settings, get_settings
from attendx.db import Database
from attendx.face import spec
from attendx.face.engine import FaceEngine, FakeFaceEngine, RealFaceEngine
from attendx.models import Base, User
from attendx.routers import admin_people, admin_reports, admin_schedule, auth, student
from attendx.security import RateLimiter
from attendx.services import schedule as sch
from attendx.services.verification import TemplateCipher
from attendx.v2.classroom_ca import router as classroom_ca_router
from attendx.v2.router import router as v2_router
from attendx.v2.sync import router as sync_router

log = logging.getLogger("attendx")

CSP = (
    "default-src 'self'; script-src 'self' 'wasm-unsafe-eval'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; "
    "worker-src 'self' blob:; font-src 'self'; object-src 'none'; base-uri 'self'; "
    "frame-ancestors 'none'; form-action 'self'"
)


def build_engine(settings: Settings) -> FaceEngine:
    if settings.face_engine == "fake":
        return FakeFaceEngine()
    return RealFaceEngine(settings.models_dir, settings.device, settings.verify_model_hashes)


def init_database(db: Database) -> None:
    """Create tables for a fresh database (Alembic manages later upgrades; see migrations/)."""
    from attendx.migrate import upgrade_or_create

    upgrade_or_create(db)
    with db.SessionLocal() as s:
        sch.ensure_default_periods(s)
        s.commit()


def create_app(settings: Settings | None = None, engine: FaceEngine | None = None) -> FastAPI:
    settings = settings or get_settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    database = Database(settings.db_url)
    init_database(database)
    face_engine = engine or build_engine(settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI):  # type: ignore[no-untyped-def]
        if isinstance(face_engine, RealFaceEngine):
            try:
                import anyio

                await anyio.to_thread.run_sync(face_engine.warmup)
                log.info("face engine ready: %s", face_engine.status())
            except Exception as exc:  # the app still serves; /api/health reports the error
                log.error("face engine failed to load: %s", exc)

        async def periodic_maintenance():
            import anyio

            from attendx.v2.identity import maintenance

            while True:
                try:
                    await anyio.to_thread.run_sync(maintenance, app.state)
                except Exception as exc:
                    log.warning("V2 maintenance failed: %s", type(exc).__name__)
                await asyncio.sleep(max(10, settings.maintenance_interval_seconds))

        job = asyncio.create_task(periodic_maintenance()) if not settings.legacy_v1_enabled else None
        try:
            yield
        finally:
            if job:
                job.cancel()
                with suppress(asyncio.CancelledError):
                    await job
            if isinstance(face_engine, RealFaceEngine):
                import anyio

                await anyio.to_thread.run_sync(face_engine.close)

    app = FastAPI(
        title="AttendX API",
        version="2.0.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.settings_obj = settings
    app.state.db = database
    app.state.engine = face_engine
    app.state.cipher = TemplateCipher.from_settings(settings.template_key, settings.data_dir)
    app.state.limiter = RateLimiter()
    app.state.mail_sink = []  # used only by explicitly selected in-memory test mail transport

    @app.middleware("http")
    async def security_headers(request: Request, call_next):  # type: ignore[no-untyped-def]
        if not settings.legacy_v1_enabled:
            import re

            path, method = request.url.path, request.method
            unsafe = (
                path.startswith("/api/student/attendance/")
                or path in ("/api/student/history", "/api/student/today")
                or path.startswith("/api/admin/reports/")
                or (method in ("GET", "HEAD") and re.match(r"/api/admin/sessions/\d+$", path))
                or (
                    method not in ("GET", "HEAD")
                    and (
                        path == "/api/student/enrollment"
                        or path == "/api/admin/students"
                        or re.match(r"/api/admin/students/\d+/(reset-password|face|enrollment/open)$", path)
                        or re.match(r"/api/admin/templates/\d+/(approve|revoke)$", path)
                        or re.match(r"/api/admin/sessions/\d+/records/", path)
                    )
                )
            )
            if unsafe:
                return JSONResponse(
                    {"detail": "V1 workflow disabled; use V2 central enrollment and faculty-local attendance"},
                    status_code=410,
                )
        cl = request.headers.get("content-length")
        limit = settings.max_frames * settings.max_frame_bytes + 1_000_000
        if cl and cl.isdigit() and int(cl) > limit:
            return JSONResponse({"detail": "request too large"}, status_code=413)
        resp: Response = await call_next(request)
        resp.headers.setdefault("Content-Security-Policy", CSP)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
        resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        if request.url.path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"
        return resp

    for r in (
        auth.router,
        admin_people.router,
        admin_schedule.router,
        admin_reports.router,
        student.router,
        v2_router,
        sync_router,
        classroom_ca_router,
    ):
        app.include_router(r)

    @app.get("/api/health")
    def health() -> dict:
        with database.SessionLocal() as s:
            s.execute(text("select 1"))
            has_admin = s.scalar(select(User.id).where(User.role == "admin").limit(1)) is not None
        return {
            "status": "ok",
            "database": "ok",
            "admin_configured": has_admin,
            "face_engine": face_engine.status(),
            "timezone": settings.timezone,
            "server_time": sch.local_now(settings.tz).isoformat(),
            "demo_mode": settings.demo_mode,
            "v2": not settings.legacy_v1_enabled,
        }

    @app.get("/api/public/face_landmarker.task")
    def landmarker_model() -> FileResponse:
        """MediaPipe model for in-browser guidance (served locally; no third-party CDN)."""
        path = settings.models_dir / spec.MEDIAPIPE_DIR / spec.MEDIAPIPE_FILE
        if not path.is_file():
            raise HTTPException(404, "model not installed")
        return FileResponse(path, media_type="application/octet-stream",
                            headers={"Cache-Control": "public, max-age=86400"})  # fmt: skip

    _mount_spa(app, settings.static_dir)
    return app


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    index = static_dir / "index.html"
    if not index.is_file():

        @app.get("/")
        def no_frontend() -> dict:
            return {"detail": "frontend not built; run `npm run build` in frontend/"}

        return
    if (static_dir / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")
    if (static_dir / "mediapipe").is_dir():
        app.mount("/mediapipe", StaticFiles(directory=static_dir / "mediapipe"), name="mediapipe")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        if path.startswith("api/"):
            raise HTTPException(404, "not found")
        candidate = (static_dir / path).resolve()
        if path and candidate.is_file() and static_dir.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def _unused() -> None:  # keep Base imported for metadata registration
    _ = Base
