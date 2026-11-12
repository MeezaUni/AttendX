# REST API

Interactive OpenAPI documentation is served by the running app at **`/api/docs`**
(`/api/openapi.json`). All endpoints are under `/api`, return JSON, and use the session cookie.
Every non-GET request needs the `X-CSRF-Token` header (value from `/api/auth/login` or
`/api/auth/me`). Login additionally requires `X-Requested-With: attendx`.

## Public
| Method | Path | Notes |
|---|---|---|
| GET | `/api/health` | DB, face-engine status, timezone, server time, whether an admin exists |
| GET | `/api/public/face_landmarker.task` | MediaPipe model for in-browser guidance |

## Auth
| Method | Path | Notes |
|---|---|---|
| POST | `/api/auth/login` | `{username, password}` → user + `csrf_token`; lockout after 5 failures |
| POST | `/api/auth/logout` | |
| GET | `/api/auth/me` | current user + `csrf_token` |
| POST | `/api/auth/change-password` | required at first sign-in; signs out other sessions |

## Admin (role `admin`)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/admin/dashboard` | today's counts, attempt outcomes, low attendance, engine status |
| GET/POST | `/api/admin/sections` · PUT/DELETE `/{id}` | |
| POST | `/api/admin/sections/{id}/enroll-course/{course_id}` | enroll every student of the section |
| GET/POST | `/api/admin/courses` · PUT/DELETE `/{id}` | |
| GET/POST | `/api/admin/faculty` · PUT/DELETE `/{id}` | |
| GET/POST | `/api/admin/students` · GET/PUT/DELETE `/{id}` | create returns a one-time `initial_password` |
| POST | `/api/admin/students/{id}/reset-password` | new one-time password |
| POST | `/api/admin/students/{id}/face` | multipart `images[]`, `source` (admin_live / admin_upload), `consent=true`; auto-approved |
| POST | `/api/admin/students/{id}/enrollment/open` | allow self-enrollment |
| DELETE | `/api/admin/students/{id}/face` | permanently delete all templates |
| GET | `/api/admin/enrollments?status=pending|approved|all` | |
| POST | `/api/admin/templates/{id}/approve` · `/revoke` | |
| GET/PUT | `/api/admin/periods` | replace the bell schedule (validated as a unit) |
| GET/POST | `/api/admin/timetable[?section_id]` · PUT/DELETE `/{id}` | |
| GET/POST | `/api/admin/holidays` · DELETE `/{id}` | adding cancels generated sessions |
| POST | `/api/admin/timetable/import/preview` | multipart `file` → rows with flags (nothing saved) |
| POST | `/api/admin/timetable/import/commit` | `{rows, default_section_id, replace_sections}` |
| GET | `/api/admin/sessions[?day=YYYY-MM-DD]` | generates sessions from the timetable for that day |
| POST | `/api/admin/sessions` | extra (ad-hoc) session |
| POST | `/api/admin/sessions/{id}/window` | `action` ∈ open_now, close_now, cancel, restore, set_window |
| GET | `/api/admin/sessions/{id}` | live roster |
| PUT | `/api/admin/sessions/{id}/records/{student_id}` | manual correction `{status, reason}` |
| GET | `/api/admin/attempts[?session_id&student_id]` | verification attempts |
| GET | `/api/admin/reports/students` · `/reports/courses` | filters `d_from, d_to, section_id, course_id` |
| GET | `/api/admin/reports/export.csv` · `/reports/summary.csv` | CSV (formula-injection safe) |
| GET | `/api/admin/audit` | audit log |
| GET/PUT | `/api/admin/settings` | runtime thresholds (validated, audited) |

## Student (role `student`)
| Method | Path | Notes |
|---|---|---|
| GET | `/api/student/today` | eligible sessions today with server-side status |
| GET | `/api/student/history` | percentages and recent classes |
| GET/POST | `/api/student/enrollment` | self-enrollment (only when opened by an admin; consent required) |
| POST | `/api/student/attendance/challenge` | `{session_id}` → `{challenge_id, steps, ttl_seconds, guidance}` |
| POST | `/api/student/attendance/challenge/{id}/submit` | multipart `frames[]` (JPEG) + `timestamps` (JSON ms) → `{decision, reason, marked, attempts_left}` |

Decisions: `match` (marked present), `non_match`, `abstain` (insufficient or uncertain
evidence), `rejected` (liveness, timing or input checks failed). Similarity scores are visible
to administrators only.
