# Testing

## Automated (backend, `pytest`)

```powershell
cd backend
.venv\Scripts\python.exe -m pytest -q                 # all tests
.venv\Scripts\python.exe -m pytest -q -m "not slow"   # skip OCR / real-model tests
$env:ATTENDX_TEST_FACES="C:\private\faces"; .venv\Scripts\python.exe -m pytest -q tests\test_real_models.py
```

Most API tests use `FakeFaceEngine`, which encodes identity, quality and pose in pixel values,
so authentication, authorization and attendance logic are tested deterministically and quickly.
`test_real_models.py` loads the real SCRFD, AdaFace and MediaPipe models (skipped when the
models are absent).

| File | Covers |
|---|---|
| `test_auth.py` | admin/student login, logout, wrong password, lockout, login rate limit, custom-header login CSRF, CSRF on mutations, role permissions, forced password change, Argon2id storage, security headers |
| `test_people.py` | section/course/faculty/student CRUD, validation, duplicate prevention, one-time passwords, deactivation, cascade deletion |
| `test_enrollment.py` | encrypted template creation, consent requirement, no face / two faces / low quality / garbage images, mixed identities rejected, self-enrollment authorisation and approval, revoke, **biometric deletion**, re-enrollment supersedes |
| `test_liveness.py` | every action passes, wrong direction, wrong order, single blink, still photo fails every action, second face, face leaving the frame, abrupt jumps, timestamp checks (order, speed, gaps, too slow), turned baseline, randomness and structure of challenges, landmark geometry signs |
| `test_verification.py` | MATCH / NON-MATCH / ABSTAIN rule including boundaries and inconsistency, configurable thresholds, template consistency, Fernet round trip, wrong key, wrong model |
| `test_attendance.py` | full flow marks present once, **duplicate prevention**, **identity mismatch** not marked, failed liveness rejected, challenge reuse, superseded challenge, **challenge expiry**, frozen feed, timing vs server clock, **outside-window** (upcoming and closed), window closing mid-attempt, **break periods**, **holidays**, other-section eligibility, course-enrollment policy, unenrolled face, attempt limit, challenge rate limit, cross-student challenge, manual open/close/cancel, audited manual corrections |
| `test_schedule.py` | eight default periods, bell-schedule validation, timezone conversion, session generation, break slots, per-slot overrides, server-time status, holidays, period-level breaks, manual adjustments kept |
| `test_import.py` | cell parsers (no invented codes, ambiguous AM/PM flagged), long CSV, grid CSV, XLSX, text PDF, **image OCR** (real RapidOCR), bad files, preview saves nothing, commit validation, admin edits |
| `test_reports.py` | percentages (excused excluded), course summary, CSV export rows, formula-injection neutralisation, absent derivation, dashboard, student history, settings validation and audit |
| `test_real_models.py` | pinned-hash loading, no face in blank or noise, deterministic L2-normalised embeddings, tampered weights refused, and (with `ATTENDX_TEST_FACES`) genuine > impostor similarity |

Frontend: `npm run build` runs the TypeScript compiler (`tsc -b`) and the production build.

## Results recorded on 2026-11-03 (development laptop, RTX 4060)

Backend suite: **93 passed, 1 skipped** (the skipped test needs `ATTENDX_TEST_FACES`; it passed when run with 6 synthetic identities). Frontend: type check + build pass.

Real-model checks done during development:

* Real enrollment through the admin UI (5 padded synthetic DigiFace images) → approved
  template; a set containing degraded augmentations was correctly **refused**.
* Real 1:1 decisions against that stored encrypted template: held-out genuine images scored
  0.81, 0.78, 0.83 (MATCH); two impostor identities scored 0.05–0.23 (NON-MATCH).
* Synthetic calibration run (`docs/results/synthetic_calibration_digiface.json`): see
  `thresholds.md`.

## Manual / device tests

| Test | Status |
|---|---|
| Admin pages render and work in Chromium at 1366×860 | Done (Playwright, real backend, synthetic data) |
| Student pages at 390×844 (phone viewport) | Done (Playwright) |
| Camera opens in a secure context and MediaPipe WASM runs under the CSP | Done in desktop Chromium with a **fake camera** |
| Challenge → frame upload → server liveness → response, on real models | Done (fake camera, no face → correctly rejected; re-submission → 409) |
| Docker image build, container start, health check, GPU in container | Done: image builds, container healthy, AdaFace on `cuda`, image contains no data/model files |
| HTTPS through Tailscale Serve from the laptop | Done: valid certificate, Secure/HttpOnly/SameSite=Strict cookie, admin flows, enrollment on the Docker GPU engine, camera in a secure context, challenge submission (115 ms) |
| **Real phone: camera, liveness challenge with a real person, MATCH and attendance recorded** | **Requires the user's phone and face**; see `demo.md` checklist |
| Impostor attempt with a second consenting person on the phone | Manual |
| iOS Safari and Android Chrome camera permissions | Manual |
