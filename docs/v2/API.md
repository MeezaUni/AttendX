# V2 API contracts

FastAPI is the interface source. Generate `openapi.json` with
`backend/.venv/Scripts/python.exe scripts/export_v2_openapi.py`. The live full schema is
`/api/openapi.json`; `/api/docs` supplies interactive documentation. No Postman workspace was
published. API verification used pytest/TestClient and real HTTPS subprocesses, not a claimed
Postman CLI run. The API Engineer workflow selected OpenAPI as the reusable contract artifact.

## Faculty-started collection timing (4 November update)

`PUT /api/admin/periods` accepts class `start_time`/`end_time` without attendance-open/close
fields. Legacy window fields remain optional and deprecated for compatibility; they do not
restrict V2 collection. Custom timetable entries likewise need only class start/end overrides.
Snapshot policy includes `collection_seconds: 300` and `start_grace_seconds: 300`.
The laptop and ingestion both authorize starts from class start through class end + five
minutes, inclusive, using the institution timezone and the original grant's class times.
Each collection closes five minutes after its actual start (or earlier on authorization expiry
or privacy lock). Starting at 17:15 for a class ending 17:10 closes collection at 17:20.
Existing grant slot formats remain compatible; clients should upgrade the desktop application.

## Shared classroom trust

`GET /api/v2/public/classroom-ca.cer` and `GET /api/v2/public/classroom.mobileconfig` provide
only the common public trust anchor. `POST /api/v2/sync/classroom-certificate` requires an active
faculty-device Bearer credential and a current teaching assignment. Body: `csr_pem` (signed
RSA CSR, minimum 2048 bits) and `address` (RFC1918 hotspot IPv4). The server chooses an IP-only
SAN and `CA:false`; CSR-requested extensions are not copied. Response: certificate/CA PEM and
CA fingerprint, never a private key. Issuance is rate-limited and audited.

The root key is encrypted using the central data cipher in `v2_classroom_authority` (migration
0004); root lifetime is three years. Each laptop generates its own key and caches a 90-day
leaf. Online provisioning renews that leaf. Cached shared material works offline; a legacy
per-laptop CA, changed address, expired leaf or changed central source needs online renewal.
Phone trust repeats only after root replacement/removal, not normal leaf renewal or class changes.

The separate hotspot HTTP 9442 service serves only public certificate/profile downloads and
setup instructions, with direct-peer subnet/host checks and no forwarding. It has no account,
camera upload or attendance routes. HTTPS 9443 remains the sole local attendance/camera origin.

## Central authentication

Existing `/api/auth/login` accepts `{username,password}` plus `X-Requested-With: attendx`.
It returns role, account details and `csrf_token`, and sets an opaque HttpOnly/Secure/Strict
cookie. Cookie-authenticated mutations require `X-CSRF-Token`. Faculty, student and admin
permissions are separate. `/api/auth/change-password` requires current/new passwords, revokes
other eligible sessions and reset links, notifies the registered email and revokes faculty
device credentials where applicable. No student credentials or hashes appear in faculty exports.

| Method | V2 path (prefix `/api/v2`) | Contract |
|---|---|---|
| POST | `/admin/students` | Admin: roll/name/email/department/semester/section; creates PENDING_ACTIVATION and queues invitation, never returns a password/token |
| POST | `/admin/students/{id}/invite` | Reissues only pending invitations, invalidating the earlier token |
| POST | `/auth/activation-info` | Single-use link token in body; returns account confirmation/consent notice |
| POST | `/auth/activate` | `{token,password}`; activates account, leaves biometrics NOT_ENROLLED |
| POST | `/auth/forgot-password` | `{email}`; generic response for eligible/ineligible/unknown addresses |
| POST | `/auth/reset-password` | `{token,password}`; consumes expiring token, revokes sessions/devices and notifies email |
| POST | `/admin/faculty` | Creates faculty login linked to faculty identity; no student/general-admin desktop access |
| POST/DELETE | `/admin/assignments[/{id}]` | Teaching section/course or coordinator section; start/end/reason; audited revocation |
| POST | `/admin/additional-students` | Student/course/section/start/end/reason/authorizer for cross-section/elective rosters |
| POST | `/admin/semesters` | Academic year/name/start/end/renewal deadline/section IDs/reminder offsets |
| GET | `/student/enrollment` | Own separate account/enrollment state, history, samples, expiry/countdown and active version |
| POST | `/student/enrollments` | Multipart exactly three `images`, `consent`, `retain_photos`, `current_password`; validates all samples atomically |
| GET | `/enrollment-photos/{id}` | Own student, assigned CC during pending review, or explicit admin photo policy only; no-store encrypted preview |
| GET | `/faculty/enrollments` | Only assigned coordinator sections' pending enrollment requests |
| POST | `/faculty/enrollments/{id}/verify` | `{decision:confirm|reject,in_person,reason}`; confirmation produces PENDING_ADMIN_APPROVAL; rejection needs reason |
| GET | `/admin/enrollments` | Enrollment requests/versions/metadata; photo URLs remain independently access controlled |
| POST | `/admin/enrollments/{id}/approve` | Requires current scoped CC confirmation, matching semester and pending state; final ACTIVE transition is conditional/atomic |
| POST | `/student/consent/revoke` | Logical erasure of retained V2 photos/templates and migrated V1 templates; roster retained |
| POST | `/admin/maintenance` | Expiry, configured reminders, retention and queued-mail retry; also runs periodically |
| GET | `/admin/status` | Delivery status (no token/body), faculty accounts, assignments and semesters |
| GET | `/faculty/attendance` | Faculty's synchronized approved snapshots only |
| GET | `/student/attendance` | Own explicit synchronized results only |
| GET | `/admin/attendance[.csv]` | Latest approved snapshots or formula-safe CSV; never derives absence from missing data |

Academic section/course/faculty/period/timetable/holiday CRUD/import routes from V1 are reused
under `/api/admin`. V1 student creation/password-distribution, admin face upload/autoapproval,
remote student attendance, legacy manual-record writes and derived-absence report/history
routes return 410 by default. `ATTENDX_LEGACY_V1_ENABLED=true` is rollback/test compatibility,
not a V2 deployment option.

## Faculty device synchronization

1. Authenticate centrally as faculty with cookie+CSRF.
2. `POST /faculty/devices` with `{name,device_id?}` returns a one-time displayed opaque
   credential. Reauthorization of the same owned device rotates its credential without
   changing its ID or losing pending-event bindings. Credential hash only is central.
3. Use `Authorization: Bearer <credential>` for `/sync/snapshot` and `/sync/events`.
   Ordinary central cookies are not accepted as device credentials. Devices expire after
   30 days; cached offline grants default to 24 hours and have independent identifiers.
4. Snapshot schema version 2 includes faculty ID, generated/expiry timestamps, grant ID,
   full assigned class rosters, three approved compatible references when eligible,
   model/pipeline/enrollment versions, timetable/holidays/periods and relevant policies.
   It contains no student account credentials, original photos or central encryption key.
5. Full cache replacement invalidates active challenges and ends unsafe open collection.
   Approved sessions/outbox are preserved. Expired/missing references use manual attendance.

`POST /sync/events` uploads an immutable faculty-approved envelope. Required facts include
event UUID, session UUID, faculty/section/course/date/period, collection grant/timestamps,
approval grant/timestamp, complete explicit roster marks/reasons, headcount/discrepancy reason,
audit trail and revision. No pending/unmarked record is final attendance.

The collection grant authorizes the original scheduled meeting. A renewed approval grant
permits later review without pretending collection started under a newer grant. Class date,
authorized timetable, roster scope, active faculty/device and revision order are checked.
Amendments cannot change meeting identity or collection times. Legitimate administrative
changes that conflict with an offline snapshot return 409 for reconciliation; the local event
is retained. The UI does not yet provide a complete conflict-reconciliation workbench.

An acknowledgment contains `event_id`, `content_hash`, `revision`, `duplicate`. The client
marks acknowledged only when the hash matches its durable approved envelope. Same ID/content
retries return `duplicate:true`; changed content/device or conflicting revisions return 409.
A backed-off predecessor prevents an amendment from overtaking it. Network failures retry
with capped exponential backoff and jitter; 401/403 locks local intake. No direct central
SQLite file access occurs from the faculty app.

## Classroom service (separate origin/database)

HTTPS binds to the verified hotspot address, normally port 9443. There are no central login,
faculty-control, admin, enrollment-photo or password endpoints. Direct peer subnet, host,
scheme and origin/header checks reject non-hotspot clients and forwarded/proxied requests.

| Method | Path | Contract |
|---|---|---|
| GET | `/classroom#<qr>` | React deep link; fragment is removed immediately after entry |
| POST | `/classroom/api/entry` | `{qr_token}`; establishes ENTRY once, returns random attempt token |
| POST | `/classroom/api/roll` | `{roll_number}` with `X-AttendX-Attempt`; generic correction for unknown roll; manual-review response when biometrics unavailable |
| POST | `/classroom/api/verify` | Multipart live frames + timestamp JSON, attempt header; server remeasures random liveness and compares three own reference embeddings |
| POST | `/classroom/api/submit` | Fresh `{qr_token}`, attempt header; requires unused MATCH, same session, newer five-second epoch and open collection |

Mutations also require same-origin `Origin` and `X-Requested-With: attendx`. Attempts bind to
peer address and session, expire, and are consumed once. Rotating class tokens may be scanned
by multiple students; replay prevention applies to each student's stage/attempt, not by making
the common classroom QR single-use for the entire room.

After the second QR, the response is `PENDING_FACULTY_APPROVAL`. A completed face MATCH suggests
draft PRESENT locally, with `decision_source: face_suggestion`; this is not final attendance
and creates no upload event. An existing faculty decision is preserved. The native roster shows
MATCH and QR completion separately from final faculty approval. Untouched, unapproved legacy
completed submissions receive the same suggestion on reopening. Failures consolidate into review
cases; none infer absence. Physical headcount can be saved/recounted before final approval;
discrepancy review includes missing/uncertain submissions and appropriate marks to cross-check.
Every student still needs a decision and unresolved cases must be resolved before approval.
Reference scoring uses the median of three per-reference cosine scores
for each usable live frame, followed by the existing provisional multi-frame decision rule.
This avoids an uncalibrated maximum-of-three decision but is not a measured false-match guarantee.

The future `UniversityAttendanceAdapter` protocol has no configured implementation. No OD or
medical workflow is rebuilt, no admission-photo API is assumed, and no upstream institutional
attendance integration is claimed.
