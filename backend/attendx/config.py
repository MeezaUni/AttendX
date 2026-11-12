"""Runtime configuration (environment variables prefixed ``ATTENDX_``; see .env.example).

Face/liveness thresholds here are only *defaults*: the effective values live in the ``settings``
table and can be changed by an administrator (audited). All of them are PROVISIONAL until they
have been validated on the deployment population with ``scripts/calibrate_thresholds.py``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATTENDX_", env_file=".env", extra="ignore")

    data_dir: Path = PROJECT_DIR / "data"
    models_dir: Path = PROJECT_DIR / "models"
    static_dir: Path = PROJECT_DIR / "frontend" / "dist"
    database_url: str | None = None  # default: sqlite:///<data_dir>/attendx.db

    # Institutional timezone: every attendance window is evaluated in this zone on the SERVER
    # clock. The phone's clock is never used for decisions.
    timezone: str = "Asia/Kolkata"

    # Face engine: "real" (SCRFD + AdaFace + MediaPipe) or "fake" (tests only).
    face_engine: str = "real"
    device: str = "auto"  # auto | cuda | cpu
    verify_model_hashes: bool = True

    # Sessions / cookies. Secure cookies need HTTPS (Tailscale Serve); set false for plain-HTTP
    # local development only.
    cookie_secure: bool = True
    # The only ingress is a local reverse proxy (Tailscale Serve / Docker port on 127.0.0.1),
    # so the last X-Forwarded-For entry (appended by that proxy) is the client address.
    trust_proxy: bool = True
    session_hours: int = 12
    student_session_hours: int = 4

    # Rate limits
    login_per_minute: int = 10
    login_lockout_failures: int = 5
    login_lockout_minutes: int = 5
    challenges_per_minute: int = 6

    # Request size limits
    max_frame_bytes: int = 250_000
    max_frames: int = 200  # ~10 fps for up to 20 s (blinks need >= ~8 fps to be seen)
    max_enroll_images: int = 8
    max_upload_bytes: int = 10_000_000

    # Template encryption key (Fernet, urlsafe base64). If unset, a key is generated once and
    # stored in <data_dir>/template.key (never in the image, never in Git).
    template_key: str | None = None

    # Demo mode adds a "synthetic data" banner and enables `attendx seed-demo`.
    demo_mode: bool = False
    legacy_v1_enabled: bool = False
    portal_url: str = "https://localhost:8480"
    university_email_domain: str = "example.edu"
    invitation_hours: int = 24
    reset_minutes: int = 30
    admin_photo_access: bool = False
    photo_retention_days: int = 120
    offline_grant_hours: int = 24
    maintenance_interval_seconds: int = 60
    mail_transport: str = "disabled"  # disabled | smtp | memory (tests)
    smtp_host: str = "127.0.0.1"
    smtp_port: int = 1026
    smtp_starttls: bool = True
    smtp_username: str | None = None
    smtp_password: str | None = None
    mail_from: str = "attendx@example.edu"

    @property
    def db_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{(self.data_dir / 'attendx.db').as_posix()}"

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@lru_cache
def get_settings() -> Settings:
    return Settings()


# Defaults for the admin-editable runtime settings (settings table). PROVISIONAL values: see
# docs/thresholds.md for the rationale and the validation procedure.
RUNTIME_DEFAULTS: dict[str, object] = {
    # AdaFace cosine similarity of a live frame vs the enrolled template.
    "match_threshold": 0.40,  # median live score >= this (and every frame >= nonmatch) -> MATCH
    "nonmatch_threshold": 0.25,  # median live score < this -> NON-MATCH; in between -> ABSTAIN
    "min_feature_norm": 14.0,  # AdaFace feature norm (quality proxy) required per frame
    "min_face_px": 80,  # minimum detected face box side in pixels
    "min_sharpness": 12.0,  # Laplacian variance of the aligned 112x112 grey crop
    "brightness_range": [40, 225],  # mean grey level of the aligned crop
    "det_min_score": 0.6,  # SCRFD score (VEIL-X Phase 4F registered value, geometric)
    "max_alignment_residual": 7.34,  # 5-point residual (VEIL-X Phase 4F, p99 clean LFW)
    "enroll_min_frames": 3,
    "enroll_min_consistency": 0.50,  # min pairwise cosine between enrollment frames
    # Liveness
    "challenge_ttl_seconds": 60,
    "challenge_steps": 3,  # number of random actions per challenge (plus the initial centre)
    "yaw_delta": 0.10,  # nose offset change, fraction of face width
    "pitch_delta": 0.06,  # nose height change, fraction of eye-chin distance
    "blink_closed": 0.45,  # blendshape eyeBlink score counted as closed
    "blink_open": 0.30,  # blendshape eyeBlink score counted as open again
    "max_attempts_per_session": 5,
    "eligibility": "section",  # "section" or "course_enrollment"
}
