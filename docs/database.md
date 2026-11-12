# Database schema

SQLite (WAL, foreign keys on), managed by Alembic (`backend/attendx/migrations`). Every
`DateTime` is **naive UTC**; timetable `Time`/`Date` values are in the institutional timezone
(`ATTENDX_TIMEZONE`).

| Table | Purpose | Key columns / constraints |
|---|---|---|
| `users` | admin and student logins | `username` unique, `password_hash` (Argon2id), `role` ∈ {admin, student}, `student_id` unique FK, `must_change_password`, `failed_logins`, `locked_until` |
| `auth_sessions` | server-side sessions | `token_hash` PK (SHA-256 of the cookie token), `csrf_token`, `expires_at` |
| `faculty` | instructors | name, email, department |
| `sections` | class sections | `name` unique, department, semester |
| `courses` | courses | `code` unique, name, `faculty_id` |
| `students` | student profiles | `roll_number` unique, name, department, semester, `section_id`, `face_status`, `is_synthetic` |
| `course_enrollments` | student ↔ course | unique (`student_id`, `course_id`) |
| `face_templates` | encrypted reference embeddings | `template_enc` (Fernet blob), `model_id`, `n_frames`, `mean_quality`, `consistency`, `status` ∈ {pending, approved, revoked, superseded}, `source`, `consent_at`, approver |
| `periods` | bell schedule (8 by default) | `number` unique, start/end, attendance open/close, `is_break` |
| `timetable_entries` | weekly slots | unique (`weekday`, `period_number`, `section_id`), course, faculty, room, `is_break`, optional per-slot time overrides |
| `holidays` | no-attendance days | `date` unique |
| `attendance_sessions` | one class meeting | unique (`section_id`, `date`, `period_number`), course, UTC `start_at`/`end_at`/`open_at`/`close_at`, `cancelled`, `manually_adjusted` |
| `attendance_records` | final attendance | **unique (`session_id`, `student_id`)**, `status` ∈ {present, late, absent, excused}, `method` ∈ {face, manual, synthetic}, `verified_at`, `match_score`, `quality_score`, `liveness_passed`, `attempt_id`, override user/reason, `previous_status` |
| `verification_attempts` | every attempt, kept separately | decision ∈ {match, non_match, abstain, rejected}, reason, score, quality, liveness, JSON details (metrics only, never images), processing time, IP |
| `liveness_challenges` | issued challenges | UUID PK, steps (JSON), `expires_at`, `status` ∈ {issued, consumed, superseded} |
| `audit_logs` | who did what | actor, action, entity, JSON details, IP |
| `settings` | admin-editable runtime values | key → JSON value |

Notes:

* **Absence is derived, not stored.** A held session (not cancelled, window opened) with no
  record counts as *absent* after it closes, or *not marked* while it is open. Manual
  corrections create explicit records.
* **Percentages:** `attended / (held − excused)`, where attended = present + late.
* **Duplicates:** the unique constraint on `attendance_records` is the final guard, behind the
  API pre-checks and the single-use challenge.
* Deleting a student cascades to the login, enrollments, templates, records and attempts.
  *Delete all face data* removes only `face_templates`.
