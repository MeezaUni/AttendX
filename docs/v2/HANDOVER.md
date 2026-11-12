# AttendX V2 engineering handover

Date: **4 November 2026, Asia/Calcutta**. This is a working prototype with explicitly
unverified hardware/institutional steps. **The entire requested production/hardware workflow
is not complete.** COMPLETE below means the stated prototype behavior has direct code/test
evidence, not production certification or a real-phone accuracy result.

**Public access update, 4 November 2026:** the user subsequently authorized public central
hosting. The test portal was reachable without Tailscale on phones. This public documentation
uses `https://YOUR-LAPTOP.YOUR-TAILNET.ts.net:10000/` as a placeholder for that address.
New invitation/reset emails use the configured address; old links
can replace only `:8444` with `:10000` while preserving the token. The administrator is now
configured. See [public-access-verification.json](public-access-verification.json) for live
public-ingress checks. The original test evidence below records the earlier private deployment.

**Match/review/camera update:** completed server MATCH plus the second QR now suggests draft
PRESENT without creating final attendance. Faculty overrides are preserved, and untouched old
pending submissions receive the suggestion when reopened. Stable dropdown controls survive
refreshes. Headcount review supports recounts and targeted physical cross-checks. Native and web
appearance follows the system, with outlined checkboxes; camera guidance overlays and 1–4× QR
zoom are available. See [REVIEW_AND_CAMERA.md](REVIEW_AND_CAMERA.md) and
[review-verification.json](review-verification.json) for current checks. The user reported a real
phone submission before this update; the new overlay/zoom checks use synthetic browser cameras,
not a new physical-phone accuracy result.

**After-hours sign-in fix:** the 18:52 operator recording exposed successful login immediately
locking at the configured 18:00 closing time. Sign-in now explains the policy and asks for
explicit authorized after-hours use before consuming entered details. The persistent notice
survives sync messages; Cancel preserves the fields. Daily expiry and ordinary closing locks
remain enforced. See [AFTER_HOURS_FIX.md](AFTER_HOURS_FIX.md) and
[after-hours-verification.json](after-hours-verification.json). Latest backend suite: 199 passed,
one consented real-face fixture test skipped, one upstream deprecation warning.

## Repository and preservation

**Classroom usability update:** class/period selection is automatic; one Start dialog prepares
the owned hotspot and TLS, and the five-minute deadline automatically stops classroom services.
QR codes now use a separate resizable display, with Wi-Fi password below its QR. The real
Windows start/address-check/stop cycle passed. A shared central classroom CA supports one
phone setup across authorized faculty laptops. Existing faculty profiles must reauthorize online
once to migrate to it. See [CLASSROOM_START_FLOW.md](CLASSROOM_START_FLOW.md) and current
operations; original per-laptop certificate instructions/evidence are superseded by this update.
Latest checks: [classroom-verification.json](classroom-verification.json). Start here:
[QUICK_START.md](QUICK_START.md).

- Repository: `C:\Path\To\AttendX`.
- Development branch: `codex/attendx-v2`; original `main` remains at `6f67b26`.
- V1 rollback branch: `codex/attendx-v1-rollback-6f67b26`.
- Earlier development commits remain local. GitHub main contains the public source snapshot.
- V1 container/image/volume and private 8443 route were preserved. The unrelated 443 Funnel,
  Rent, LexCorp and Besu services were not reconfigured, stopped or recreated.
- V2 has its own `attendx-v2` project, `attendx-v2:local` image, `attendx-v2-data` volume,
  central port 8480 and Mailpit port 8026. Initially only private HTTPS 8444 was added;
  the later authorized public handler is HTTPS 10000. Classroom intake is never published.
- The old V1 build helper refuses to rebuild V1 from this V2 checkout. Actual schema migration
  was tested against an isolated populated V1 database copy, not the live V1 volume.
- File inventory: [CHANGED_FILES.txt](CHANGED_FILES.txt). Exact local commit inventory is
  recorded in [COMMITS.txt](COMMITS.txt). Runtime data, `.env.v2`, keys, models and binaries
  are ignored, not committed.

## Required feature status

| # | Requested handover item | Status and evidence/limit |
|---|---|---|
| 1 | Repository path | COMPLETE — path above |
| 2 | Git branch | COMPLETE — `codex/attendx-v2` |
| 3 | Commits created | COMPLETE — local milestone commits, see commit inventory |
| 4 | Files changed | COMPLETE — manifest includes source, tests, contracts, build/deployment scripts and documentation |
| 5 | Existing V1 reused | COMPLETE — FastAPI/React, Argon2id/sessions/CSRF, SQLAlchemy/Alembic/SQLite, SCRFD, alignment, AdaFace, quality gates, liveness validator, academic/timetable/import tools and CSV escaping; VEIL-X was not modified |
| 6 | Central server | COMPLETE prototype — separate Docker service, real models/CUDA, V2 enrollment/authorization/sync APIs; not a real university integration |
| 7 | Admin portal | PARTIAL — setup, invitations, semester policies, scoped faculty/CC assignments, enrollment final approval, approved attendance and CSV work; full academic editing, pagination, percentage reports and reconciliation workbench remain limited |
| 8 | Student activation | COMPLETE prototype — university-domain validation, expiring single-use hashed token, password creation, account status separate from enrollment; local catcher verified, real university SMTP BLOCKED on authorized configuration |
| 9 | Three-photo enrollment | COMPLETE prototype quality/consistency/versioning path — exactly three accepted samples, one face/quality/alignment checks and duplicate pixels rejected; browser guided capture implemented; active enrollment liveness and real-person enrollment evaluation NOT TESTED |
| 10 | CC verification | COMPLETE prototype — assigned-section queue/photos, explicit in-person assertion, confirm/reject, reason/audit, wrong-section denial; the physical identity check remains the human CC's responsibility |
| 11 | Admin final enrollment approval | COMPLETE — cannot bypass CC; conditional state transitions prevent in-flight approval resurrecting withdrawn consent |
| 12 | Semester re-enrollment | PARTIAL — configured dates/deadline/reminders, countdown, expiry, new three-sample versions and CC/admin reapproval; strict renewal/manual fallback policy; advanced future-semester/grace-policy management is limited |
| 13 | Student photo transparency | COMPLETE prototype — own encrypted previews or deletion metadata, time-limited CC access, ordinary-faculty denial, admin access policy off by default |
| 14 | Password/recovery | COMPLETE central email-token path — Argon2id, reauthentication/change notification, generic forgot response, reset replay/expiry/session/device revocation; optional face-assisted recovery NOT IMPLEMENTED, face-only reset unavailable |
| 15 | Faculty/class assignment | PARTIAL — dated teaching/CC scopes, revocation, additional students, full section rosters and API support for substitutes; departments/academic years are existing text fields, not a full university SIS |
| 16 | Windows executable | COMPLETE build artifact at `dist\faculty\AttendXFaculty\AttendXFaculty.exe`; native GUI smoke and real CUDA model load tested. Overall desktop deployment PARTIAL pending full real-classroom use. Distribute the whole approximately 4.8 GB folder and external licensed models |
| 17 | Local hotspot | PARTIAL overall — actual Windows OFF → ON → verified hotspot adapter/address → OFF cycle passed on this laptop; guided setup/cleanup tested; full phone connection remains NOT TESTED |
| 18 | Offline HTTPS | PARTIAL — shared central CA and distinct laptop keys, offline certificate cache, setup-only certificate downloads, HTTPS camera diagnostic and hotspot-only intake implemented/tested; real-phone trust/camera operation still NOT TESTED |
| 19 | Student-local website | PARTIAL — no-login React capture/QR flow and isolated service implemented; no face model runs on the phone; actual iOS/Android browser workflow NOT TESTED |
| 20 | First QR scan | COMPLETE state-machine/API behavior — deep link establishes ENTRY once, short-lived QR validation, peer/session binding; physical phone scan NOT TESTED |
| 21 | Roll-number flow | COMPLETE — authorized roster lookup, limits/generic errors, pending/expired/missing biometrics route to review, roll alone never marks attendance |
| 22 | Random liveness | PARTIAL — existing server validator reused and sequence/expiry/frozen-feed tests pass; phone uses timed instructions only; real consenting-person capture remains NOT TESTED |
| 23 | AdaFace verification | PARTIAL — pinned real models load on CUDA, real blank/noise and normalized deterministic embedding checks pass; multi-reference decision logic tested synthetically, no real-population false-match/accuracy claim |
| 24 | Second QR scan | COMPLETE core state-machine behavior — requires unused MATCH and newer current QR for same meeting, creates PENDING_FACULTY_APPROVAL only; physical rear-camera scan NOT TESTED |
| 25 | Faculty review/manual attendance | COMPLETE core — all roster members present, PRESENT/ABSENT/UNMARKED, required reasons, consolidated reviews, explicit faculty decisions; native UI included |
| 26 | Physical headcount | COMPLETE core/UI — discrepancies require an explicit reason; no silent resolution |
| 27 | Final approval | COMPLETE — collection must close, unmarked/review cases resolved, durable frozen snapshot plus audit, explicit amendments with ordered revisions |
| 28 | Offline storage | COMPLETE prototype — encrypted SQLite envelopes, Windows current-user DPAPI key, restart locks/invalidates unsafe challenges, completed submissions/marks/approved events retained |
| 29 | Central synchronization | COMPLETE core — real-process HTTPS disconnect/restart/retry demonstrated; durable outbox/ack/hash, duplicate/conflict detection, grant and immutable meeting validation; conflict-resolution UI remains PARTIAL |
| 30 | Tests | See verified results below and `verification.json`; no fabricated accuracy/hardware claims |
| 31 | Manual tests still needed | Real hotspot start/stop, CA trust on each phone, camera/liveness/MATCH/second QR, concurrent room load, native notification delivery, after-hours network cleanup, CPU throughput and attack trials |
| 32 | Exact startup/shutdown | Commands below and [OPERATIONS.md](OPERATIONS.md) |
| 33 | Real-phone demo | Ten-step procedure in [OPERATIONS.md](OPERATIONS.md), including enrollment/CC/admin, offline class/manual attendance, restart and duplicate-free upload |
| 34 | Known limitations | Listed below; basic liveness, provisional thresholds, one-node SQLite, expiring offline authority and untested real-phone/hotspot behavior |
| 35 | Remaining blockers | Authorized university domain/SMTP/API contracts, admission-photo permission if desired, real-phone CA trust/consenting participants, hardware/load/security validation; administrator setup and public central access now configured |

## Verification evidence

The initial V1 baseline was **93 passed, 1 skipped** plus a successful frontend build.
The final exact run is recorded in [verification.json](verification.json).

- Backend full suite covers V1 compatibility and V2 identity, enrollment, CC/admin scope,
  retention/reminders, device renewal/revocation, migration preservation, offline authority,
  roster/manual decisions, QR stages, approval/amendments/outbox, calendar cancellation,
  privacy-lock/shutdown races and native resource lifecycle.
- One real-face test is skipped because `ATTENDX_TEST_FACES` is not supplied. Model loading,
  blank/noise rejection and deterministic normalized 512-dimensional embeddings are tested.
- The upstream Starlette/httpx deprecation warning is still present. It is not an application
  test failure. Two extended runs stalled at a MediaPipe GC finalizer; stack inspection located
  the problem. Explicit engine cleanup was added to application shutdown and the real-model
  fixture, then the full suite was rerun. Interrupted/stalled runs were not counted as passes.
- Frontend: two camera cleanup/cancellation tests, TypeScript compilation and Vite production build.
- Chromium synthetic fixture: admin, assigned CC confirmation, admin final approval, student
  protected-photo dashboard; mobile width 390 had no horizontal overflow. These were synthetic
  observations, not real enrollment photographs or a real face accuracy test.
- PyInstaller package: native Windows GUI starts locked with no student listener; SCRFD,
  AdaFace and MediaPipe load on CUDA and correctly reject a blank frame. Final artifact hashes
  and diagnostic status are in the verification record. CPU throughput is not characterized.
- Real HTTPS process separation: central stopped, separate faculty process approved a three-row
  roster offline, another process recovered it, central restarted, one class/three explicit marks
  synchronized, two duplicate retries acknowledged without duplicates, outbox empty.
- New V2 Docker central and Mailpit are healthy; real model status is CUDA. A synthetic SMTP
  message was captured by local Mailpit. No university email was delivered.
- Private HTTPS 8444 health succeeded with certificate verification; 8443 and the unrelated
  443 Funnel remained unchanged. No classroom endpoint was published through Tailscale.

## Start using this checkout

```powershell
cd C:\Path\To\AttendX
docker compose --env-file .env.v2 -f docker-compose.v2.yml up -d
docker compose --env-file .env.v2 -f docker-compose.v2.yml exec central attendx create-admin --username admin
```

The administrator has now been configured by the operator. The create-admin command above is
for first-time installation; it is unnecessary for the existing account. Open the public portal:
[https://YOUR-LAPTOP.YOUR-TAILNET.ts.net:10000/](https://YOUR-LAPTOP.YOUR-TAILNET.ts.net:10000/).
Mail catcher: [http://127.0.0.1:8026/](http://127.0.0.1:8026/).

```powershell
.\dist\faculty\AttendXFaculty\AttendXFaculty.exe --models-dir C:\Path\To\AttendX\models
# CPU fallback is explicit if necessary:
.\dist\faculty\AttendXFaculty\AttendXFaculty.exe --device cpu --models-dir C:\Path\To\AttendX\models
# Quit the faculty app through its tray menu; window-close minimizes to tray.
docker compose --env-file .env.v2 -f docker-compose.v2.yml stop
```

On another machine, create `.env.v2` using the operations guide; the local settings file is
deliberately not committed. External model installation, build commands, scoped firewall
considerations and the trusted-phone setup are in that guide. Do not delete local faculty
profiles or the central key/volume while records remain unsynced.

## Engineering decisions and limits

- Reused Python/React and chose PySide6 to keep inference local. No alternate prototype
  backend or direct central database write path was introduced.
- The V1 deployment is preserved separately. New V2 attendance is stored in versioned V2
  tables rather than silently treating old V1 automatic records as faculty-approved results.
- A first enrollment cannot become eligible simply because a roll exists or an admin uploads
  photos. CC identity verification and final admin approval are distinct auditable transitions.
- The strict renewal policy sends renewal-due/expired/incompatible cases to manual attendance.
  Old templates remain until replacement is approved; superseded/revoked material is logically
  erased centrally. SQLite pages/backups are not a certified forensic erasure mechanism.
- Full snapshots replace authorized cache contents. Remote revocations cannot reach an offline
  laptop before reconnect or grant expiry. Local encrypted storage assumes the Windows user/OS
  is trustworthy; compromise of an unlocked administrator/user account is outside DPAPI's boundary.
- Reconciliation conflicts retain local events. The current UI does not resolve every roster
  transfer/reassignment/history conflict automatically. Local PIN recovery UI is not implemented;
  preserve the original profile and unsynced records if a PIN is forgotten.
- Faculty final approval is the attendance authority. QR/hotspot membership and an in-person
  checkbox are supporting evidence/assertions, not cryptographic proof of physical presence.
- Liveness remains a basic active check. Printed photos/still feeds are exercised in tests;
  sophisticated screen replay, injected video/virtual cameras and deepfakes can defeat it.
  Median-of-three reference scoring needs consenting deployment-population calibration.
- Real phone scanning, permission behavior, trusted offline TLS, GPU/CPU room throughput and
  native Windows notification delivery remain hardware tests. Driver/firewall/campus policies
  may require operator action. The app never silently falls back to public or ordinary-LAN intake.
- No real university admission-photo, attendance, OD or medical-leave API is connected. The
  future adapter is a protocol only; OD/medical processes remain institution-owned.
- Public central access was subsequently authorized and configured on HTTPS 10000. Actual
  university SMTP delivery remains unconfigured. Model licensing remains non-commercial research.

Independent review findings were addressed with regression checks: preserving device identity
through reauthorization, cancelling stale authorization callbacks after lock, closing-time checks
during modal editing, late hotspot-start cleanup, camera acquisition cleanup, ordered retries,
immutable meeting metadata, and separate collection/approval grants. The remaining limits above
are not hidden behind a blanket COMPLETE claim.
