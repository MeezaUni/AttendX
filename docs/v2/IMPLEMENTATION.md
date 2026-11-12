# AttendX V2 implementation ledger

Specification: [REQUIREMENTS.md](REQUIREMENTS.md). This specification is the user's approved
design and execution instruction. Work proceeds locally without another design approval gate.

## Architecture decisions

Reuse FastAPI, SQLAlchemy/Alembic, React, Argon2id, SCRFD, five-point alignment, AdaFace,
MediaPipe server-side liveness, and the timetable/import tools. Extend the central identity
model with faculty accounts and separate account/enrollment states. Keep V2 enrollment and
approved attendance in new versioned tables. V1 mutation routes that bypass V2 approval are
disabled by default; legacy tests explicitly enable the legacy compatibility mode.

The faculty runtime is a separate FastAPI service with its own encrypted SQLite store, no
central account database, and no student passwords. A PySide6 shell controls it over loopback.
The student listener binds only to an explicitly configured hotspot address and rejects clients
outside its configured subnet, loopback/proxy forwarding, and untrusted origins. HTTPS and
Windows hotspot readiness must fail closed. A network subnet alone is not proof of presence.

Full snapshots replace authorized cache contents, while session roster snapshots and approved
outbox events survive cache refreshes. Offline grants expire. Central ingestion rechecks faculty
authorization and roster membership, requires complete explicit marks/headcount/reasons, and
rejects conflicting revisions. Stable UUID events and content hashes make retries idempotent.

## Execution tasks

1. M0: inventory, baseline tests, V1 rollback ref, development branch. Verify migration on a
   populated V1 database copy before claiming compatibility.
2. M1–M5: tests first for invitation activation/reset, separate account state, exactly three
   samples, encryption/photo authorization, CC section scope, admin approval, semester renewal.
   Implement additive migrations, central API contracts, mail outbox, privacy/retention jobs.
3. M6–M9: tests first for full roster distribution, inactive-template exclusion, offline grant,
   durable manual roster, explicit headcount/approval, amendments, replay-safe outbox ingestion,
   restart/retry/conflict, two QR stages, local face/liveness verification and closed windows.
4. Central React pages for activation/reset, guided enrollment/status/previews, admin V2 setup,
   faculty CC review. Preserve V1 academic tools. Build and inspect in a browser.
5. M10–M11: faculty desktop login/provisioning, roster controls, QR, tray, notifications,
   privacy lock, DPAPI keys, Windows hotspot probe/control and TLS provisioning guide. Build
   executable if dependencies/platform allow; record exact evidence and external requirements.
6. M12: run complete tests/builds, exercise separated services, review security boundaries,
   export OpenAPI, write startup/demo/handover documentation, coherent local commits.

Each behavioral task uses failing regression tests before implementation, targeted checks and
the full backend suite at milestone boundaries. UI changes use TypeScript/build plus browser
checks. No invented real-face accuracy or phone/hotspot results.

## Review focus

- Invitation/reset replay and expired credentials, inactive accounts and revoked sessions.
- Wrong-section CC access and legacy endpoints bypassing CC/admin approval.
- Unenrolled/expired roster members remaining UNMARKED until faculty decides.
- Crash between approval and upload; duplicate events versus conflicting payloads/revisions.
- Network exposure, stale authorization, changed templates, closing collection during inference.

## M0 evidence

- Initial branch `main`, clean, commit `6f67b26`.
- Rollback ref `codex/attendx-v1-rollback-6f67b26`; working branch `codex/attendx-v2`.
- Backend baseline: 93 passed, 1 skipped (consented face inputs absent), one upstream
  Starlette/httpx deprecation warning. Frontend production build passed.
- Existing container `attendx` healthy on loopback 8470. Other projects inventoried read-only.
- Existing Tailscale 443 Funnel and tailnet-only 8443 Serve left unchanged.
- No existing faculty/offline desktop implementation; phone/hotspot trust unverified.

## Progress

M0 complete. Subsequent evidence and implementation decisions are appended here.

M1-M5 central API implemented: 15 new identity/enrollment tests passed; complete suite 108 passed, 1 skipped. V2 live OpenAPI remains authoritative. Mail transport is disabled until configured; tests use an in-memory sink. Photos and delivery payloads are encrypted. Approved old templates survive pending renewal and are erased after replacement approval. Default photo retention is capped at semester end. Ruling: reuse existing user/session authentication with an additive role migration; legacy behavior is opt-in for rollback/testing only. Faculty UI and real SMTP/hardware evidence still pending.

M6-M9 implemented and checked: 12 new offline/sync tests, full suite 120 passed, 1 skipped. Faculty SQLite stores encrypted JSON with a current-user DPAPI-protected key on Windows. Explicit UNMARKED/PRESENT/ABSENT decisions, consolidated reviews, physical headcount, immutable approval revisions and transactional outbox persist independently of central availability. Device-scoped grants expire after 24 hours by default; remote changes cannot reach an offline laptop sooner. Two QR stages use 5-second HMAC epochs bound to attempts; median-of-three reference scoring remains provisional. Real hardware hotspot/mobile HTTPS still untested.

Central UI implemented and verified in Chromium against an isolated synthetic FastAPI fixture: admin setup, assigned CC confirmation, admin final approval, and student dashboard showing three protected photo previews. Student mobile viewport 390x844 has no horizontal overflow. npm test passes 2 camera cancellation/failure regressions; TypeScript/production build passes. Screenshots remain in ignored build/. No actual face or university account was used. Review found device renewal, async privacy lock, modal closing-time and ordered retry issues; regression fixes are being validated.

## Final engineering and verification — 4 November 2026

M10–M12 implementation includes the native PySide6 faculty application, current-user DPAPI
storage, owned WinRT hotspot controls, exact-adapter HTTPS listener, trusted-phone camera
diagnostic without attendance endpoints, tray/reminders and privacy/closing-time cleanup.
All face inference stays on the faculty laptop; the phone captures frames and decodes QR only.
Hardware start/stop, phone CA installation, real camera/liveness and physical QR scans remain
unverified. Full feature statuses and blockers are in HANDOVER.md.

Independent review fixes now have regressions: stable device identity on reauthorization,
cancelled stale provisioning, modal closing-time enforcement, late hotspot cleanup including
shutdown, pending camera cancellation, ordered revision retries, immutable meeting identity,
separate collection and approval grants, credential revocation, and consent-withdrawal races.
Migrations now use frozen DDL and preserve populated V1 user/session/template relationships.
Retention and reminder maintenance runs periodically. Final central reports use approved
attendance only; no V1-derived automatic absences leak into V2 views.

Two extended test runs stalled in MediaPipe garbage collection on an HTTP worker. Stack
inspection identified the resource-finalizer wait. Explicit idempotent engine cleanup and a
yield/finally model fixture resolved it; subsequent complete runs reached 145 passed and one
skipped consented-face test. Interrupted runs are not evidence of success.

The Windows onedir package was actually built and tested natively, including real CUDA model
loading and blank-frame rejection. Packaging initially selected incompatible ICU DLLs from the
host PATH; the build now isolates its dependency search path. Models remain external and the
whole approximately 4.8 GB directory is required. The native screenshot and exact final hashes
are included in the handover evidence; no binary or runtime secret is committed.

The real-process HTTPS demo verifies central disconnection, offline approval, separate-process
recovery, central restart, one approved meeting/three explicit marks, two idempotent duplicate
retries and an empty durable outbox. Synthetic SMTP delivery reached local Mailpit only.
The separate V2 image is deployed privately on HTTPS 8444 with real CUDA inference; no first
administrator password was invented. V1 HTTPS 8443, the unrelated 443 Funnel and other services
remain unchanged. No public deployment or Git push occurred.

Final check counts, executable hashes, contracts, startup/shutdown and manual demo instructions
are recorded in verification.json, API.md, OPERATIONS.md and HANDOVER.md. UI/reporting breadth,
institutional integrations, real-phone trust and hardware/load/accuracy validation are explicitly
limited rather than represented as a completed production deployment.

## Follow-up timing and classroom usability — 4 November 2026

User-authorized changes remove fixed timetable attendance windows. Class times remain;
faculty chooses a start during class or through class end + five minutes (inclusive), and
collection lasts five minutes from actual start. Local/central code shares the same boundary
function. A class-end reminder is suppressed for already-started/cancelled/holiday meetings.
The timing milestone passed 164 backend tests and one skipped consented-face test.

The user then requested a simpler native flow and explicitly retained fully offline,
hotspot-only intake. Current meeting selection uses institution-local laptop time; only genuine
overlaps require a class choice. One modal Start flow probes/prepares networking and TLS;
first-use phone setup does not consume collection time. Wi-Fi credentials and the rotating
attendance QR have a separate resizable display. Controls appear when relevant; advanced
network controls are collapsed. Existing sessions reopen for review rather than duplicating.

One common central CA now signs distinct laptop keys (CSR/device authorization), with the
private CA key encrypted centrally. Native online provisioning renews the laptop leaf; cached
shared material works offline. Legacy per-laptop roots must migrate online. Public profile/CA
downloads contain no private key. The local HTTP setup page serves public trust material only;
camera/intake remains HTTPS on the verified hotspot interface. Phones must explicitly install
trust once per deployment; software cannot remotely grant iOS trust.

Independent review identified duplicate start dialogs, a disabled retry path, privacy-lock
dialog/timer cleanup and legacy-root reuse. Regressions were written failing and then fixed.
Additional tests cover period rollover, cancellation, QR fitting, modal deadline shutdown,
and a blocked central request: network cleanup now runs separately from central synchronization.
The final full suite passed 183 tests, one skipped, one upstream warning (78.31 seconds).
Frontend's two camera tests/build and real HTTPS offline restart/idempotency demo also pass.

Real WinRT hardware test: OFF → ON → verified 192.168.137.1/24 → OFF, ownership cleared.
Native package startup and real CUDA model/blank-frame checks passed. A desktop shortcut
includes the models path. V2 migrated additively to 0004 after a SQLite backup; user/student/
enrollment/sample/approved-session counts were preserved. Existing services/routes stayed intact.
Current HTTPS health/profile checks pass via the configured hostname. Direct public-ingress-IP
probes from this workstation timed out for both existing port 443 and port 10000; fresh external
phone reachability is not claimed from those probes. Original public authorization remains.

Evidence and final executable hash: classroom-verification.json. Physical phone trust/camera,
face accuracy, two QR scans and classroom load remain device-validation tasks.
