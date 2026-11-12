# AttendX

### AI-powered attendance with 1:1 face verification and active liveness checks

AttendX is a web application for taking class attendance from students' phones. A student signs
in, opens the class that is currently open, completes a short **random liveness challenge** in
front of the phone camera ("turn left → back to centre → blink twice"), and the server verifies
their face **against their own enrolled template only** (1:1, never a search across everyone).
The server records MATCH, NON-MATCH or ABSTAIN, and marks the student present only on MATCH.

> **University Deep Learning course project / prototype.** It is not certified biometric
> security and must not be the only basis for consequential decisions. A manual, non-biometric
> attendance path is always available to administrators. See [Limitations](#limitations).

![Admin dashboard](docs/screenshots/admin-dashboard.png)

| Phone: today's classes | Phone: verification | Admin: live session roster |
|---|---|---|
| ![](docs/screenshots/mobile-today.png) | ![](docs/screenshots/mobile-verify-intro.png) | ![](docs/screenshots/admin-sessions.png) |

All screenshots come from the running application with **synthetic demo data**: no real
students and no faces appear.

---

## Contents

- [Features](#features)
- [How it works](#how-it-works)
- [Quick start (Windows, Docker, Tailscale)](#quick-start-windows-docker-tailscale)
- [Using AttendX](#using-attendx)
- [Development](#development)
- [Testing](#testing)
- [Limitations](#limitations)
- [Documentation](#documentation)
- [Credits and licences](#credits-and-licences)

## Features

**Administrators**
- Student, section, course and faculty management; student logins with one-time passwords.
- Face enrollment by live capture, authorised photo upload, or student self-enrollment with
  approval. Templates can be approved, revoked, re-enrolled or permanently deleted.
- Timetable: eight default periods with configurable attendance windows, weekday schedules,
  per-slot overrides, break slots, holidays, extra sessions, and manual open/close/cancel.
- Timetable import from **CSV, XLSX, PDF or a photo/scan (OCR)** into an editable review table.
  Unreadable values are flagged and never invented.
- Live session roster (auto-refresh), manual corrections with a required reason, attendance
  percentages by student and course, CSV exports, verification-attempt log and audit log.

**Students (mobile-first)**
- Today's classes with server-side window status, camera verification with live guidance,
  result screen, attendance history and percentages, and self-enrollment with explicit consent.

**Security and privacy**
- Argon2id passwords, server-side sessions, CSRF tokens, login lockout, rate limits and
  per-class attempt limits.
- Encrypted face templates (Fernet); raw photos and camera frames are never stored or logged.
- Everything runs on one laptop and is reachable only inside your Tailscale tailnet over HTTPS.

## How it works

```
Phone browser ──HTTPS──▶ Tailscale Serve (tailnet only) ──▶ 127.0.0.1:8470 ──▶ AttendX container
                                                                               ├─ React SPA (static)
                                                                               ├─ FastAPI /api
                                                                               ├─ SQLite (volume)
                                                                               └─ SCRFD · AdaFace · MediaPipe (GPU)
```

1. **Challenge.** The server checks the attendance window on *its own clock*, the student's
   eligibility, duplicates and attempt limits, then issues a random, single-use challenge
   (60 s by default).
2. **Capture.** The phone records about 10 frames/s while the student performs the actions;
   in-browser MediaPipe only shows progress. Photo uploads are impossible on this path.
3. **Liveness (server).** Every frame is re-measured with MediaPipe Face Landmarker: exactly one
   face, continuous movement, head yaw/pitch changes and blinks **in the issued order**, and
   plausible timing. Frozen feeds and reused or expired challenges are rejected.
4. **Identity (server).** Frontal frames from the start and end of the challenge are detected
   with **SCRFD**, aligned to the ArcFace 5-point template, quality-checked and embedded with
   **AdaFace IR-101**. Cosine similarity to the student's template gives MATCH, NON-MATCH or
   ABSTAIN (insufficient or inconsistent evidence).
5. **Record.** On MATCH the backend writes one attendance record; a unique constraint prevents
   duplicates. Every attempt is logged separately from the final record.

The detection, alignment and embedding code is reused from **VEIL-X** (the author's face
verification research project): SCRFD decoding, Umeyama alignment, the strict safetensors loader
and the IR-101 architecture. VEIL-X's calibrated research thresholds are **not** reused, because
they were fitted to a different population. AttendX ships provisional thresholds and a
[validation procedure](docs/thresholds.md).

## Quick start (Windows, Docker, Tailscale)

Requirements: Windows 10/11, Docker Desktop (WSL2), Tailscale on the laptop **and** the phone,
same tailnet, HTTPS certificates enabled for the tailnet. An NVIDIA GPU is optional.

```powershell
git clone <this repo> AttendX; cd AttendX
copy .env.example .env                       # adjust ATTENDX_TIMEZONE if needed

# 1. Models (about 280 MB, verified by SHA-256; never committed)
py -3.12 scripts\fetch_models.py             # or: --from-dir <folder that already has them>

# 2. Build and start (GPU). No NVIDIA GPU: .\scripts\attendx.ps1 up-cpu
.\scripts\attendx.ps1 up

# 3. First administrator (you are prompted for the password; nothing is hard-coded)
.\scripts\attendx.ps1 create-admin admin

# 4. Tailnet-only HTTPS for phones (Tailscale Serve, NOT Funnel)
.\scripts\attendx.ps1 serve
tailscale serve status                       # shows https://<machine>.<tailnet>.ts.net:8443
```

Open the printed `https://…ts.net:8443` address on the laptop or on a phone that is signed in
to the same tailnet. Full guide and troubleshooting: [docs/deployment.md](docs/deployment.md).

## Using AttendX

1. **Set up:** *Courses & sections* → add sections, courses and faculty. *Timetable* → check the
   periods and windows, then fill the weekly grid or *Import timetable*.
2. **Add students:** *Students* → *Add student*. Hand the one-time password to the student.
3. **Enroll faces:** open the student → tick consent → *Live capture* (5 photos) or *Upload
   photos*, or *Allow self-enrollment* and approve under *Face enrollment*.
4. **Take attendance:** sessions open automatically by timetable (server time). *Attendance*
   shows each class; *Roster* updates live. Use *Open 10 min* for an ad-hoc window.
5. **Students:** sign in on the phone → *Mark attendance* → follow the challenge.
6. **Reports:** *Reports* → filter by date, section or course → *Attendance CSV* or
   *Summary CSV*. Corrections: roster → *Correct* (reason required, audited).

A scripted end-to-end demonstration, including a synthetic-data mode, is in
[docs/demo.md](docs/demo.md).

## Development

```powershell
# backend (Python 3.12, uv)
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe torch --index-url https://download.pytorch.org/whl/cu128
uv pip install --python .venv\Scripts\python.exe -e ".[dev]"
$env:ATTENDX_COOKIE_SECURE="false"; .venv\Scripts\attendx.exe serve --port 8470

# frontend (Node 22+): dev server on :5173 proxies /api to :8470
cd ..\frontend; npm install; npm run dev
```

Structure: `backend/attendx` (API, ORM, face engine, liveness, timetable import),
`backend/tests`, `frontend/src` (React + TypeScript + Tailwind), `docker/`, `scripts/`, `docs/`.

## Testing

```powershell
cd backend; .venv\Scripts\python.exe -m pytest -q          # 93 tests, about 30 s
$env:ATTENDX_TEST_FACES="C:\path\to\consented\faces"         # optional real-face test
cd ..\frontend; npm run build                                 # type check + production build
```

What is automated and what was checked by hand is listed in [docs/testing.md](docs/testing.md).

## Limitations

- **Liveness is basic active liveness.** It defeats printed photos and still images. A
  pre-recorded video of the right actions, a screen replay, a virtual camera or a real-time
  face-swap injection **can** defeat it. There is no passive (texture/depth) anti-spoofing model.
- **Thresholds are provisional.** They were checked only on a small synthetic (DigiFace-1M)
  sample, which is not an accuracy estimate for real students or phone cameras. Validate them with
  [scripts/calibrate_thresholds.py](docs/thresholds.md) before relying on them.
- **Client timestamps** are checked only for consistency with the server clock; a modified
  client can still lie about frame timing within those bounds.
- **Single-node prototype:** SQLite, in-memory rate limits, one container.
- Not evaluated for demographic fairness; face recognition error rates can differ across groups.
- Pretrained model licences are **non-commercial research only** (see below).

## Documentation

| Topic | File |
|---|---|
| Architecture and data flow | [docs/architecture.md](docs/architecture.md) |
| REST API | [docs/api.md](docs/api.md) (live OpenAPI at `/api/docs`) |
| Database schema | [docs/database.md](docs/database.md) |
| Docker, Tailscale, Windows setup, troubleshooting | [docs/deployment.md](docs/deployment.md) |
| Thresholds and validation procedure | [docs/thresholds.md](docs/thresholds.md) |
| Security, privacy and threat model | [docs/security.md](docs/security.md) |
| Tests (automated vs manual) | [docs/testing.md](docs/testing.md) |
| Demonstration script | [docs/demo.md](docs/demo.md) |

## Credits and licences

AttendX code: MIT ([LICENSE](LICENSE)). Third-party models and libraries:
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). In short:

- **SCRFD** det_10g (InsightFace buffalo_l v0.7): Guo et al., ICLR 2022. Non-commercial research.
- **AdaFace IR-101** trained on WebFace4M (CVLface release): Kim et al., CVPR 2022. Non-commercial research.
- **MediaPipe Face Landmarker** (Google): Apache-2.0.
- **RapidOCR** (ONNX PaddleOCR models): Apache-2.0.
- Detection, alignment and loader code adapted from VEIL-X (MIT).

Model weights are downloaded by `scripts/fetch_models.py`, verified by SHA-256 and never
committed. No real biometric data is in this repository.
