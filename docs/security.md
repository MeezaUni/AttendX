# Security, privacy and threat model

AttendX is a **university prototype**. The controls below are reasonable for a course
demonstration on a private tailnet. They do **not** make it production-grade biometric security.

## Controls implemented

| Area | Control |
|---|---|
| Network exposure | Container publishes only on `127.0.0.1:8470`. Phones connect through **Tailscale Serve** (HTTPS, tailnet members only). Funnel (public internet) is not used. |
| Transport | HTTPS with the tailnet's Let's Encrypt certificate; cookies `Secure; HttpOnly; SameSite=Strict`. |
| Passwords | Argon2id (argon2-cffi defaults); minimum length and composition rules; one-time initial passwords that must be changed at first sign-in; no hard-coded or default credentials. |
| Sessions | Random 256-bit tokens; only the SHA-256 is stored; expiry (12 h admin, 4 h student); password change signs out other sessions. |
| CSRF | Per-session token in the `X-CSRF-Token` header for every state-changing request; login requires a custom header (forces a CORS preflight that is never granted). |
| Brute force | Per-IP login rate limit, account lockout after 5 failures, per-student challenge rate limit, per-class attempt limit (default 5). |
| Authorization | Role checks on every endpoint; students can act only on their own data, and a challenge is bound to the student who received it. |
| Attendance integrity | Window, holiday, break, eligibility and duplicate checks happen **server-side** at challenge issue **and** at submission; single-use challenges consumed atomically; unique (session, student) constraint; the browser cannot write records. |
| Liveness | Random action order; server re-measures every frame; one face throughout; continuity; timing consistent with the server clock; frozen-feed detection; challenge expiry. |
| Biometric data | Only templates (mean embeddings) are stored, Fernet-encrypted; the key is in the data volume or `ATTENDX_TEMPLATE_KEY`, never in the image or Git. Raw enrollment images and camera frames are processed in memory, never written or logged. Consent is recorded per template. Templates can be revoked or permanently deleted. |
| Input handling | Size limits on requests, frames and uploads; images decoded with OpenCV and re-checked; timetable files parsed in memory with type and magic checks; CSV exports neutralise formula injection. |
| Headers | Strict CSP (no third-party origins; `wasm-unsafe-eval` for MediaPipe), `X-Frame-Options: DENY`, `nosniff`, `Referrer-Policy: no-referrer`, `Permissions-Policy: camera=(self)`. |
| Auditing | Logins, lockouts, CRUD, enrollments, approvals, deletions, window changes, corrections (with reason), settings changes and exports are audit-logged. |
| Container | Runs as an unprivileged user; models mounted read-only; data in a dedicated named volume. |

## Known limitations (be explicit about these in any demo)

1. **Presentation attacks.** Active liveness stops photos and still screens. It does **not**
   reliably stop a replayed video of a person doing the right actions, a screen held in front of
   the camera showing such a video, a virtual-camera driver, or real-time face-swap and
   deepfake injection. There is no passive anti-spoofing (texture, depth, rPPG) and no device
   attestation.
2. **Client-side timing** cannot be fully trusted; only its consistency with server time is
   checked.
3. **Threshold validity:** thresholds are provisional (see `thresholds.md`). Error rates for
   real students, and differences between demographic groups, have not been measured.
4. **Single host:** a compromised laptop exposes the database **and** the template key, which
   share a volume (unless `ATTENDX_TEMPLATE_KEY` is supplied separately). Rate limits are
   in-memory and reset on restart.
5. **Shared devices:** students must not share accounts or phones; nothing technical prevents a
   student from handing their unlocked phone to an enrolled friend *who is physically present*.

## Privacy practices

* Enroll only students who have given informed consent. Offer the manual attendance path to
  anyone who declines; administrators can mark attendance with a reason.
* Delete face data when a student leaves (*Student → Delete all face data*), or delete the
  student entirely.
* Backups made with `scripts/attendx.ps1 backup` contain templates **and** the key; store them
  encrypted and privately.
* Never commit `data/`, `models/`, `.env`, `backups/` or any face images (enforced by
  `.gitignore` and `.dockerignore`).
