# Architecture

## Components

```
┌──────────────── Phone / laptop browser ────────────────┐
│ React + TypeScript SPA (Vite, Tailwind)                 │
│  • admin portal  • student portal                       │
│  • getUserMedia camera, MediaPipe Tasks (WASM) guidance │
└───────────────┬────────────────────────────────────────┘
                │ HTTPS (Tailscale certificate), tailnet only
┌───────────────▼──────────────┐
│ Tailscale Serve on Windows   │  https://<machine>.<tailnet>.ts.net:8443
│ (not Funnel)                 │  → http://127.0.0.1:8470
└───────────────┬──────────────┘
┌───────────────▼────────────────────────────────────────────────────┐
│ Docker container "attendx" (Compose project "attendx")              │
│ uvicorn + FastAPI                                                   │
│  /api/auth        sessions, CSRF, lockout                           │
│  /api/admin/*     people, timetable, sessions, reports, settings    │
│  /api/student/*   today, history, enrollment, challenge, submit     │
│  /               SPA static files + /mediapipe WASM                 │
│ Face engine (lazy, one lock):                                       │
│  SCRFD det_10g (onnxruntime) → Umeyama 5-pt alignment → AdaFace     │
│  IR-101 (PyTorch, CUDA or CPU) ; MediaPipe Face Landmarker (CPU)    │
│ SQLite (WAL) + template.key   ── volume attendx-data:/data          │
│ model files                   ── ./models:/models (read-only)       │
└────────────────────────────────────────────────────────────────────┘
```

One origin serves the SPA and the API, so there is no CORS. Cookies are `HttpOnly; Secure;
SameSite=Strict`.

## Backend modules (`backend/attendx`)

| Module | Responsibility |
|---|---|
| `config.py` | environment settings, admin-editable runtime defaults (thresholds) |
| `models.py`, `migrations/` | SQLAlchemy ORM, Alembic migrations (run at start-up) |
| `security.py`, `deps.py` | Argon2id, opaque sessions, CSRF, rate limiter, role guards |
| `face/scrfd.py`, `face/align.py`, `face/preprocess.py` | vendored from VEIL-X (unchanged logic) |
| `face/adaface.py`, `face/spec.py` | IR-101 architecture, strict pinned loader, extractor |
| `face/engine.py` | `FaceEngine` protocol: identity observation, liveness metrics, quality gates; `FakeFaceEngine` for tests |
| `liveness/challenge.py` | random challenge generation and server-side sequence validation |
| `services/verification.py` | template building, Fernet encryption, MATCH/NON-MATCH/ABSTAIN rule |
| `services/enrollment.py` | enrollment and biometric erasure |
| `services/schedule.py` | default periods, timetable → sessions, window status, eligibility |
| `services/timetable_import.py` | CSV/XLSX/PDF/OCR extraction to an editable preview |
| `routers/*` | HTTP API |
| `cli.py` | `create-admin`, `serve`, `migrate`, `check-models`, `seed-demo` |

## Attendance verification sequence

```
student          browser                      server
  │ Mark attendance │                            │
  │────────────────▶│ POST /attendance/challenge │ window open? eligible? enrolled?
  │                 │───────────────────────────▶│ not marked? attempts left? rate limit
  │                 │◀── steps, ttl, challenge id│ store challenge (status=issued)
  │ performs steps  │ capture ~10 fps JPEG       │
  │                 │ MediaPipe JS: progress     │
  │                 │ POST …/submit (frames, ts) │
  │                 │───────────────────────────▶│ atomically consume challenge (once)
  │                 │                            │ expiry, window again, attempt limit
  │                 │                            │ timing vs server clock, frozen-feed check
  │                 │                            │ MediaPipe per frame → validate steps
  │                 │                            │ SCRFD+AdaFace on start/end frontal frames
  │                 │                            │ cosine vs own template → decision
  │                 │                            │ attempt row; on MATCH: record (unique)
  │                 │◀── decision, reason ───────│
```

Frames exist only in request memory; they are never written to disk or logged.

## Liveness geometry

From MediaPipe face-mesh landmarks (unmirrored frame, normalised coordinates):

* `yaw = (nose.x − min(cheek.x)) / cheek_width − 0.5`, which is positive when the subject turns
  to **their left**;
* `pitch = (nose.y − eye_line.y) / (chin.y − eye_line.y)`, which decreases when the subject
  looks **up**;
* `blink = mean(eyeBlinkLeft, eyeBlinkRight)` blendshape scores.

Thresholds are relative to a baseline taken from the first frames, so face shape does not
matter. The same functions exist in Python (authoritative) and TypeScript (guidance only).

## Deployment options

* **Docker (default):** GPU image (`TORCH_VARIANT=cu128`, `--gpus` reservation); GPU
  passthrough on Docker Desktop + WSL2 was verified on the development laptop.
* **CPU image:** `docker-compose.cpu.yml` override.
* **Native Windows:** run `attendx serve` from the backend venv. Tailscale Serve proxies to it
  in the same way.
