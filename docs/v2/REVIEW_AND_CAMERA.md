# Match review, system theme and camera guidance — 4 November 2026

User requests: visible checkbox outlines, system light/dark appearance for native app and
student/classroom website, clear MATCH and provisional PRESENT after successful second QR,
headcount-guided review/recount, in-camera instruction/arrow/blink overlays, and QR camera zoom.
Additional reported bug: the faculty decision dropdown closes while choosing an option.

Decisions: only a complete server MATCH + second QR preselects draft PRESENT. Final faculty
approval remains explicit. A late submission never overrides an existing faculty decision.
Previously saved, unapproved successful submissions can acquire this draft suggestion on
startup; approved rosters remain immutable. NON-MATCH/ABSTAIN/missing submissions never
become absent automatically. Headcount identifies a discrepancy, never a person's identity.

Plan:
1. Tests first for draft presence, existing manual overrides, old pending-row migration,
   headcount candidate selection/recount persistence and no automatic final event.
2. Keep native row controls stable across timer refreshes. Test that an open dropdown and
   selection survive refresh, plus theme/outline and recount/review UI behavior.
3. Add system theme palettes via Qt colorSchemeChanged and CSS prefers-color-scheme.
   QR pictures and live camera overlays retain high-contrast fixed rendering.
4. Put timed guidance in an unmirrored overlay on the mirrored preview; add side arrows,
   animated blink eyes and accessible/reduced-motion labels. Face inference remains laptop-only.
5. Add a 1–4x rear-camera QR zoom that crops the actual decoder input as well as the preview,
   so browsers lacking hardware zoom also support it. Preserve camera abort/cleanup guarantees.
6. Full tests/build, theme/browser/native checks, scoped review, updated executable and V2
   deployment, evidence and local commits. Preserve existing profiles/approved records and routes.

Implemented as requested. No phone-side face model or public classroom attendance route was
introduced. Incoming fresh QR links remount the classroom attempt even in the same browser tab.
MATCH before the second QR is visible but does not suggest presence until submission completes.

Verification: 192 backend tests passed, one consented real-face fixture test skipped; five
frontend camera/zoom tests passed; TypeScript and production build passed. Native screenshots
cover both palettes, draft MATCH/Present and the headcount review. Synthetic browser checks
cover dark/light pages, a right-arrow cue, animated/reduced-motion blink cue, actual QR decoding
at 4× crop zoom, release of both camera streams and same-tab fresh-attempt restart. These are
interface/regression checks, not measured biometric accuracy or a physical-phone zoom test.
The offline HTTPS demonstration also passed approval, separate-process restart and duplicate
upload retries with no remaining outbox. Scoped independent review found an approved-row label
still saying awaiting approval; this was fixed and regression-tested.

Build and deployment evidence: [review-verification.json](review-verification.json).
Usage: [QUICK_START.md](QUICK_START.md).
