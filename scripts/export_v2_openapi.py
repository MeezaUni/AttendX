"""Export the V2 contract from FastAPI without touching any deployed database."""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from attendx.config import Settings
from attendx.main import create_app

with tempfile.TemporaryDirectory() as directory:
    app = create_app(Settings(data_dir=Path(directory), face_engine="fake", legacy_v1_enabled=False))
    schema = app.openapi()
    schema["paths"] = {
        path: spec
        for path, spec in schema["paths"].items()
        if path.startswith(("/api/v2/", "/api/auth/")) or path == "/api/health"
    }
    schema["info"]["description"] = (
        "V2 central identity and faculty synchronization contract. Cookie-authenticated mutations require "
        "X-CSRF-Token from sign-in. Login requires X-Requested-With: attendx. Faculty device sync uses scoped Bearer credentials. "
        "Student classroom intake runs on a separate hotspot-only HTTPS service, not this central server. "
        "V1 mutation/derived-absence paths are disabled by default. Academic administration tools retain their existing /api/admin paths."
    )
    (ROOT / "docs/v2/openapi.json").write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    app.state.db.engine.dispose()  # release SQLite handles before Windows removes the temp directory
print("Exported docs/v2/openapi.json from FastAPI")
