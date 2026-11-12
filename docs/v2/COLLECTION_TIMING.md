# Faculty-started attendance — 4 November 2026

User change: remove fixed attendance-open/close inputs from timetable administration.
Faculty starts collection during the assigned class, or up to five minutes after class end.
Each collection runs for five minutes from its actual start, subject to existing authorization
expiry and privacy locks. At class end, the desktop reminds an unlocked faculty member once
if no session exists, including when the app resumes within the five-minute grace period.

Ruling: grace is the latest start time, inclusive. A class ending 17:10 permits a start at
17:15; that session closes at 17:20. Starting after 17:15 or before class start is rejected.
Holidays, cancellations, scope, duplicate-class prevention and manual approval remain enforced.
Existing legacy window columns stay for V1/database compatibility but do not constrain V2.
Existing authorization grants can use the same five-minute grace without reissuing their slots.

Implementation plan (inline, within the already authorized implementation scope):

1. Add failing local-runtime tests at class/grace boundaries in the institution timezone;
   verify actual-start + five-minute duration and automatic intake closure. Add central
   ingestion tests that accept grace starts but reject forged starts past grace.
2. Share class bounds between runtime, sync validation and reminders. Publish the grace
   duration in snapshot policy. Add native reminder tests for class end, grace, suppression
   after start, duplicate suppression, other weekdays, holidays and cancelled classes.
3. Remove timetable window controls; accept bell-schedule updates using class times only.
   Keep optional legacy fields compatible and allow custom class times without old windows.
   Test API behavior and inspect the browser at mobile/desktop sizes.
4. Run full backend suite, frontend tests/build, targeted lint and offline HTTPS synchronization.
   Review the scoped changes, build and smoke-test the new Windows package, rebuild/restart
   only the V2 central image, verify public access and unchanged existing routes. Document
   evidence and commit locally. No Git push or unrelated-service changes.

Review focus: exact cutoff and seconds; timezone/date boundary; central/local agreement;
notifications after a session already started; older legacy custom attendance windows;
cache/profile preservation during packaging and deployment.
