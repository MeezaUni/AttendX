# After-hours sign-in regression — 4 November 2026

The operator's 18:52 recording showed successful online sign-in immediately followed by the
one-second timer locking the app. The cached closing time was 18:00 in Asia/Kolkata. The
after-hours checkbox was hidden inside Advanced network settings, and background sync replaced
the generic lock message. This resembled an authentication failure even though credentials
were accepted. No credentials were recovered from the recording.

The sign-in page now has a persistent closing-time notice and an explicit, outlined authorized
after-hours checkbox. Online sign-in and cached unlock ask before consuming credentials if
after-hours use has not been confirmed. Cancel preserves the entered fields and starts no
network request. Accepting permits today's authorized use, so the next timer tick does not
immediately relock the session. The choice expires on the next institution-local day. Ordinary
closing-time locks still close intake, preserve saved rosters and explain the reason; sync
cannot replace the separate notice. Closing-time checks now use the same institution-local
runtime clock as class selection and daily expiry.

Seven regression cases were added after observing their failures against the previous code.
All 35 native desktop cases pass. The full backend suite passes 199 tests, with one consented
real-face fixture test skipped and one upstream Starlette/httpx deprecation warning. Native
preview checks use an isolated synthetic profile; no operator account/roster is modified.
Class timetable windows remain enforced; after-hours authorization does not create an
unscheduled classroom session. The central API, Docker deployment and public routes are unchanged.
