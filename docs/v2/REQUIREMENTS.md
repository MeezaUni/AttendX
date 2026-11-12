# ATTENDX V2 — FINAL COMPLETE ENGINEERING MASTER PROMPT

## YOUR ROLE AND MISSION

You are my autonomous senior software architect, full-stack engineer, computer vision engineer, Windows desktop developer, network engineer, database engineer, security engineer, and QA engineer.

Your assignment is to upgrade my EXISTING AttendX repository into:

**AttendX V2 — An Offline-First, Faculty-Controlled AI Attendance and Face Verification System**

This is a university Deep Learning project intended to become a credible GitHub and resume portfolio project.

I need an actually working application, not a design-only submission, conceptual architecture, AI-generated mockup, or collection of disconnected prototypes.

The central concept is:

**Online enrollment and academic administration + offline classroom biometric verification + faculty-controlled attendance approval + reliable synchronization.**

You are operating in:

`C:\Path\To\AttendX`

This is a fresh Codex CLI conversation. You have no previous conversation context.

Read the repository, existing implementation, project notes, Markdown documents, CLAUDE.md files, README, architectural documentation, Git history, tests, and configuration before deciding how to implement anything.

**THIS PROMPT SUPERSEDES ALL PREVIOUS ATTENDX V2 DESIGNS.**

Work incrementally, reuse existing code, run tests, fix failures, and create coherent LOCAL Git commits.

Do not push to GitHub without explicit permission.

Do not deploy publicly or make irreversible networking/infrastructure changes without explicit permission.

Do not stop at planning. Implement as much as is technically feasible and report precisely what remains blocked.

---

# PART 1 — EXISTING PROJECT CONTEXT

## 1.1 AttendX V1

AttendX V1 has already been built, reportedly with:

- FastAPI backend.
- React / TypeScript / Vite / Tailwind frontend.
- SQLAlchemy.
- Alembic.
- SQLite.
- Docker deployment.
- NVIDIA CUDA acceleration.
- SCRFD facial detection.
- Five-point facial alignment.
- AdaFace IR-101 512-dimensional embeddings.
- Face-quality assessment.
- One-to-one facial verification.
- MATCH / NON-MATCH / ABSTAIN decisions.
- Randomized head-turn and blink liveness.
- Student enrollment.
- Admin and student portals.
- Courses, sections and faculty records.
- Timetable management/import.
- Attendance records.
- Reporting and CSV exports.
- Audit logs.
- Tailscale Serve HTTPS.

Previously reported latest commit:

`6f67b26`

Previously reported private AttendX URL:

`https://YOUR-LAPTOP.YOUR-TAILNET.ts.net:8443/`

Treat these as previous implementation reports. Verify everything against actual code and environment.

## 1.2 VEIL-X

The original research project VEIL-X exists in a separate Image Processing folder.

It contains the source computer-vision work from which AttendX reused SCRFD, alignment, AdaFace, quality assessment, and model loading.

DO NOT modify VEIL-X.

Do not retrain the existing models unless justified.

Do not blindly reuse research thresholds across different populations.

Respect third-party model licensing.

Do not copy unrelated datasets or large files.

## 1.3 Windows development environment

The development machine is a Windows laptop with an NVIDIA RTX 4060.

Environment:

- Windows PowerShell.
- VS Code.
- Codex CLI.
- Docker Desktop.
- Tailscale.

There are unrelated Docker projects, including previously reported Rent, LexCorp and Besu services.

A public Tailscale Funnel on port 443 is reportedly assigned to another application.

DO NOT modify, stop, recreate, delete or reconfigure unrelated projects, containers, volumes, routes or Funnel endpoints.

Preserve the working AttendX V1 deployment as a rollback option.

Before coding:

1. Inspect current Git branch/status.
2. Preserve uncommitted user changes.
3. Read project documentation.
4. Inspect source code.
5. Inspect existing Docker/Tailscale configuration without altering it.
6. Run baseline tests.
7. Create an AttendX V2 development branch.
8. Identify reusable functionality.
9. Record existing blockers.
10. Begin implementing actual code.

---

# PART 2 — DEFINITIVE SYSTEM ARCHITECTURE

AttendX V2 has THREE main components.

## COMPONENT A — CENTRAL UNIVERSITY SERVER

A Docker-hosted central backend and web application.

For this prototype, it simulates the university's existing attendance infrastructure.

Do not claim actual integration with the university's existing system.

Responsibilities:

- Admin accounts.
- Faculty accounts.
- Student accounts.
- University-email invitations.
- First-time activation.
- Student central-portal passwords.
- Password change and recovery.
- Three-photo biometric enrollment.
- Enrollment status and approval.
- CC identity verification.
- Admin final approval.
- Semester/re-enrollment management.
- Academic departments.
- Courses.
- Sections/classes.
- Student assignments.
- Faculty assignments.
- Class Coordinator assignments.
- Timetables.
- Academic calendar.
- Holidays.
- Biometric consent.
- Approved face templates.
- Faculty data synchronization.
- Approved attendance synchronization.
- Central attendance records.
- Reporting.
- Audit logging.

The real university already processes OD and Medical Leave.

Do not rebuild those processes.

Provide a documented future university-API integration adapter.

## COMPONENT B — FACULTY WINDOWS APPLICATION

A faculty-only Windows desktop application distributed as an `.exe` or installer.

The application contains the classroom attendance engine.

Responsibilities:

- Faculty-only login.
- Faculty authorization.
- CC permissions where assigned.
- Authorized roster synchronization.
- Local encrypted student face-template cache.
- Semester validity checks.
- Local face detection/recognition.
- Random liveness validation.
- Classroom hotspot management.
- Local student website.
- Rotating attendance QR.
- Attendance collection.
- Live candidate list.
- Manual attendance marking.
- Verification-exception review.
- Physical headcount.
- Final faculty approval.
- Offline persistent storage.
- Sync queue.
- Automatic synchronization.
- Timetable reminders.
- System tray/background operation.
- End-of-day privacy controls.

No student login in this desktop application.

No general administrator login.

A faculty member who is also a CC receives CC privileges only for their assigned sections.

## COMPONENT C — STUDENT WEBSITE

There are TWO separate browser experiences.

### C1. CENTRAL ONLINE STUDENT PORTAL

Accessible online from anywhere, including home, hostel, campus or mobile data, through a properly secured HTTPS endpoint.

Used for:

- First-time account activation.
- University-email verification.
- Password creation.
- Student login.
- Password changes.
- Password recovery.
- Three-photo face enrollment.
- Enrollment status.
- Viewing one's own approved enrollment information.
- Viewing retained enrollment photographs when policy permits.
- Re-enrollment.
- Semester-expiry countdown.
- Consent and privacy controls.

### C2. CLASSROOM-LOCAL STUDENT WEBSITE

Served directly by the faculty laptop.

Accessible ONLY through the faculty-controlled classroom hotspot.

Used for:

- Opening attendance from classroom QR.
- Entering roll number.
- Live camera capture.
- Random head movement/blink challenge.
- Face verification.
- Final QR scan.
- Submission status.

There is NO password login on the classroom website.

There is NO offline credential/token login.

There is NO administrator or faculty login.

The classroom website must not access the central student account/password database.

Students' phones do not run AdaFace or other GPU inference.

All biometric inference happens on the faculty laptop.

---

# PART 3 — CENTRAL ADMINISTRATOR STUDENT CREATION

## 3.1 Admin creates student records

Admin enters only:

- University roll number.
- Full name.
- University email.
- Department.
- Semester.
- Section/class.

Any extra information must be justified.

The admin does NOT upload the initial face photographs.

The new account starts:

`PENDING_ACTIVATION`

Students must not become eligible for automatic face attendance merely because their roll number exists.

## 3.2 University email invitation

Central server sends a student activation invitation to the registered university email.

Preferred mechanism:

- Cryptographically random.
- Single-use.
- Short-lived.
- HTTPS activation link.
- Email delivery status.

If implementing an initial one-time password instead:
- Generate it securely.
- Store only a hash.
- Expire it on first use.
- Require immediate replacement.
- Never log or resend its plaintext.

Prefer the activation-link approach.

Support configurable SMTP and a local development mail catcher.

Do not claim production university-email integration unless actually configured and tested.

## 3.3 First activation

Student opens the invitation link.

Student:

1. Validates activation.
2. Confirms displayed account details.
3. Reads biometric-consent information.
4. Sets central portal password.
5. Captures three facial samples.
6. Passes sample-quality checks.
7. Submits enrollment for CC review.
8. Receives pending-verification status.

The account may be active for normal central portal access even while biometric enrollment is not yet approved.

Keep account activation separate from biometric enrollment approval.

---

# PART 4 — THREE-PHOTO ENROLLMENT

## 4.1 Guided captures

Require exactly three accepted enrollment samples.

Photo 1:
- Forward-facing.
- Neutral expression.
- Adequate lighting.

Photo 2:
- Another high-quality capture.
- Without spectacles if applicable.

Photo 3:
- Another high-quality capture.
- With spectacles if the student normally wears them.
- Otherwise a natural alternate pose or lighting condition.

Do not require glasses for students who never wear them.

The three samples must show the same person.

## 4.2 Technical checks

For each sample:

- Exactly one face.
- Minimum resolution.
- Adequate lighting.
- Blur detection.
- Facial alignment.
- Quality assessment.
- Duplicate-frame detection.
- Identity consistency.
- Liveness when feasible.

Reject and request recapture of invalid samples.

Use existing SCRFD and AdaFace implementations.

Produce three reference embeddings.

## 4.3 Biometric storage

Central server stores:

- Student ID.
- Three embedding templates.
- Enrollment version.
- Recognition model version.
- Alignment/preprocessing version.
- Quality metadata.
- Consent metadata.
- Enrollment date.
- CC verification state.
- Admin approval state.
- Semester expiry date.

Encrypt sensitive biometric information at rest.

Do not keep raw photos without explicit retention policy and consent.

Do not send raw enrollment photos to ordinary faculty laptops.

## 4.4 Student photo transparency

Student central dashboard shows:

- Enrollment status.
- Three sample records.
- Capture date.
- Quality/approval status.
- Enrollment version.
- Semester expiry.
- Next renewal date.
- Countdown until renewal.
- Consent controls.

I also want students to see their three captured enrollment photographs when image retention is enabled.

Implement encrypted, access-controlled photo previews.

Students must see only their own photos.

The assigned CC may view these photos only for authorized enrollment verification.

Admins may access them only where explicitly authorized by policy.

Ordinary faculty must not access enrollment photos.

If retention is disabled, show metadata instead and explain the photos have been deleted.

Never expose photos through public static URLs.

---

# PART 5 — CLASS COORDINATOR (CC) ENROLLMENT APPROVAL

This is a CORE requirement.

Our university has a Class Coordinator system.

A CC is a faculty member assigned to a particular class/section, similar to a class teacher.

A CC has special enrollment-verification authority for that assigned class only.

A faculty member can be the CC for one class and an ordinary lecturer for another.

## 5.1 CC role model

Implement a scope-based permission model.

Roles/permissions:

ADMIN:
- Creates accounts.
- Assigns classes/faculty/CC.
- Manages semesters.
- Gives final biometric enrollment approval.
- Handles permitted account-recovery administration.

FACULTY:
- Conducts attendance for assigned classes.
- Reviews attendance failures.
- Marks present/absent manually.
- Approves final class attendance.
- Cannot approve enrollment identities.

CC:
- Includes faculty permissions for assigned teaching classes.
- Adds enrollment identity verification for assigned coordinator section(s).
- Can see submitted enrollment photos for their assigned students during authorized verification.
- Cannot grant final administrator biometric approval.

STUDENT:
- Manages own central account.
- Captures enrollment images.
- Sees own enrollment information.
- Uses classroom roll-number-plus-face attendance.

## 5.2 Initial in-person CC verification

During the first class of the semester, or another authorized in-person enrollment verification session:

1. Student attends physically.
2. CC opens assigned-section enrollment review.
3. CC sees student name and roll number.
4. CC sees the three submitted enrollment photos.
5. CC may see the university admission photo if an authorized integration exists.
6. CC physically compares the student with the images and institutionally trusted records.
7. CC confirms or rejects identity.
8. CC records verification decision and time.
9. Approved CC verification moves to `PENDING_ADMIN_APPROVAL`.
10. Admin reviews CC verification.
11. Admin gives final enrollment approval.
12. Enrollment becomes `ACTIVE`.
13. Approved face templates become eligible for faculty synchronization.

Do not claim the university's actual admission-photo database is connected unless integration exists.

For the prototype, support a separately authorized reference-admission-photo field or demonstrate without that integration.

## 5.3 CC permissions

A CC can verify only students in assigned sections.

A CC cannot:
- Approve arbitrary students from other sections.
- Bypass admin final approval.
- View student passwords.
- Download university-wide biometric records.
- Directly alter approved template embeddings.
- Secretly replace enrollment photos.

Every verification action must be auditable.

## 5.4 CC verification location

Prefer a CC-specific central portal interface available to authenticated faculty.

The faculty Windows app may offer a secure CC enrollment-review interface when online, but final central enrollment approval remains with admin.

Do not expose CC verification through the student-local hotspot site.

The CC's identity verification should be performed in person.

Do not automatically accept remote face matching as a substitute for first-time CC verification.

## 5.5 Incomplete enrollment

Students may be absent during the first CC class or may not have completed photo submission.

Such students remain on the official academic roster.

Their biometric enrollment status remains pending.

They can still be marked PRESENT or ABSENT manually by faculty for any assigned class.

**Biometric enrollment must never be a prerequisite for appearing in the attendance roster.**

---

# PART 6 — ENROLLMENT STATE MACHINE

Use distinct account, biometric enrollment and attendance states.

## 6.1 Account states

Examples:

- PENDING_ACTIVATION.
- ACTIVE.
- SUSPENDED.
- DISABLED.

## 6.2 Biometric enrollment states

Examples:

- NOT_ENROLLED.
- CAPTURE_IN_PROGRESS.
- PENDING_CC_VERIFICATION.
- CC_REJECTED.
- PENDING_ADMIN_APPROVAL.
- ACTIVE.
- RE_ENROLLMENT_DUE.
- EXPIRED.
- REVOKED.

Do not conflate account status with biometric enrollment status.

## 6.3 Attendance eligibility

Every student on the assigned course roster remains visible to faculty.

| Biometric enrollment | Automated biometric attendance | Manual faculty attendance |
|---|---|---|
| ACTIVE | Allowed | Allowed |
| NOT_ENROLLED | Not allowed | Allowed |
| PENDING_CC_VERIFICATION | Not allowed | Allowed |
| PENDING_ADMIN_APPROVAL | Not allowed | Allowed |
| CC_REJECTED | Not allowed | Allowed |
| RE_ENROLLMENT_DUE | Policy-dependent | Allowed |
| EXPIRED | Not allowed | Allowed |
| REVOKED | Not allowed | Allowed |

Do not automatically classify students as absent because they lack approved biometrics.

---

# PART 7 — SEMESTER RE-ENROLLMENT

## 7.1 Semester expiry

Admin defines:

- Academic year.
- Semester name.
- Semester start date.
- Semester end date.
- Enrollment renewal deadline.
- Grace period if applicable.
- Reminder schedule.

For approved student enrollment, biometric template validity normally ends on the configured last day of the semester.

Do not hardcode six-month semesters.

## 7.2 Renewal procedure

Student may begin re-enrollment before expiry.

Student logs into central portal and captures three new samples.

Renewal requires:
- Appropriate central reauthentication.
- New guided captures.
- Quality checks.
- Identity consistency checks.
- CC verification according to policy.
- Admin final approval.
- Template version update.

The assigned CC verifies in person during the first class or another authorized verification session.

Admin then approves.

Old templates must not be destroyed until the new enrollment is safely processed.

Never retain superseded templates longer than the approved retention policy.

## 7.3 Renewal expiry

If renewal is overdue:

- Student stays on roster.
- Faculty sees `RE_ENROLLMENT_DUE` or `EXPIRED`.
- Automatic biometric attendance is restricted according to policy.
- Faculty can still mark present or absent manually.
- Student sees renewal requirements on the central portal.

## 7.4 Reminders

Student dashboard shows:

"Face enrollment expires in X days."

Configurable email reminders.

Suggested defaults:
- 30 days before.
- 7 days before.
- 1 day before.
- On expiry.

Do not hardcode reminder dates.

---

# PART 8 — CENTRAL STUDENT PASSWORDS AND RECOVERY

Passwords exist ONLY for the central online account-management portal.

They are NEVER sent to faculty devices.

## 8.1 Password creation

Student sets a personal password on first activation.

Use strong password hashing such as Argon2id.

Never email reusable plaintext passwords.

## 8.2 Password change

Authenticated student can change password.

Require appropriate reauthentication.

Invalidate relevant central sessions.

Notify via university email.

## 8.3 Forgot password

Implement:

1. Student requests password reset.
2. Central server responds generically to prevent account enumeration.
3. Single-use expiring reset link sent to registered university email.
4. Student sets new password.
5. Old eligible sessions are revoked.
6. Student receives confirmation.

Admin must not see or manually distribute the new password.

## 8.4 Optional face-assisted recovery

The student may provide live facial evidence during an exceptional recovery case.

Result:
- MATCH.
- NON-MATCH.
- ABSTAIN.

Admin may review the result and other trusted identity evidence.

A face MATCH alone must NEVER reset a password.

Use verified university email or a separate trusted institutional identity-verification process.

Admins authorize recovery; students choose passwords themselves.

Audit all actions.

Do not retain raw recovery frames unnecessarily.

---

# PART 9 — ACADEMIC STRUCTURE AND ASSIGNMENTS

Central admin manages:

- Departments.
- Academic years.
- Semesters.
- Sections.
- Courses.
- Faculty.
- Class Coordinators.
- Student enrollment.
- Faculty-to-course assignment.
- Faculty-to-section assignment.
- Timetable.
- Special additional student assignments.

Example:

Course code: CAI2502.

Section: 5CAI02.

CC: Assigned class coordinator.

Faculty: Assigned Deep Learning lecturer.

Students: Authorized roster for that course/section.

Faculty receives only students relevant to assigned teaching classes.

CC receives enrollment-verification access only to students in their coordinator sections.

## 9.1 Additional students

Allow administrators to add legitimate cross-section or elective students.

Each assignment should have:
- Student.
- Course/section.
- Effective date.
- Optional end date.
- Authorizing admin.
- Reason.

## 9.2 Faculty changes

Support:
- Faculty reassignment.
- Substitute lecturers.
- CC reassignment.
- Course cancellation.
- Class-group changes.
- Student transfers.

Changes must synchronize to authorized faculty devices.

Revoke no-longer-authorized template access.

Do not allow unrelated faculty to retrieve student biometric data.

---

# PART 10 — FACULTY SYNCHRONIZATION AND DATA CACHE

## 10.1 Faculty online authentication

Faculty logs into the Windows application using central faculty credentials.

Initial provisioning requires central connectivity.

Offline use is allowed after secure provisioning under a defined authorization-expiry policy.

Do not permit username-only offline access.

## 10.2 Data received by faculty application

Synchronize only:

- Assigned faculty identity.
- Authorized courses.
- Authorized sections.
- Assigned class rosters.
- Student roll numbers.
- Student names.
- Enrollment status.
- Three approved face embeddings per active student.
- Enrollment/model versions.
- Biometric template expiry.
- Timetable.
- Holidays.
- Relevant policy settings.

Do NOT synchronize:

- Student passwords.
- Student password hashes.
- University-wide account records.
- Original enrollment photographs.
- Unrelated students' biometrics.
- Central server private signing keys.

## 10.3 Model compatibility

Central server creates reference embeddings during enrollment.

Faculty laptop extracts live embeddings during attendance.

Both must use compatible:
- Detection model/version.
- Alignment configuration.
- Embedding model/version.
- Image preprocessing.
- Embedding normalization.

Version the pipeline.

Reject incompatible template versions and flag them for sync or manual fallback.

## 10.4 Encrypted cache

Protect local biometric templates with encryption.

Use Windows device-protected key storage where practical.

Provide:
- Cache version.
- Last successful sync.
- Expiry/freshness policy.
- Relevant student count.
- Missing template alerts.
- Offline authorization expiry.

Do not claim a fully offline laptop instantly receives remote changes.

## 10.5 Roster includes unenrolled students

CRITICAL:

Synchronize the FULL authorized academic class roster, even when some students have:

- No face enrollment.
- Pending CC verification.
- Pending admin approval.
- Expired enrollment.
- Rejected enrollment.
- Re-enrollment due.

For those students, the faculty app stores their roll number/name/status without usable active biometric templates.

All can still be manually marked present or absent.

---

# PART 11 — CLASSROOM ATTENDANCE IS HOTSPOT-ONLY

This requirement is absolute.

**Classroom attendance must always use the faculty laptop's local hotspot.**

Do not implement university Wi-Fi attendance mode.

Do not implement Tailscale classroom attendance mode.

Do not make attendance depend on central-server internet access.

University Wi-Fi/mobile internet is used for:
- Online enrollment.
- Admin portal.
- CC enrollment verification.
- Faculty synchronization.
- Central attendance synchronization.

Classroom attendance is separate.

## 11.1 Hotspot workflow

1. Faculty opens Windows application.
2. Faculty selects authorized class.
3. Faculty starts attendance.
4. App activates or confirms local hotspot.
5. App shows Wi-Fi connection QR.
6. Students connect to faculty hotspot.
7. Faculty displays rotating attendance QR.
8. Students access local classroom website.

There are two QR types:

**Wi-Fi QR:** Connects device to hotspot.

**Attendance QR:** Rotates and authorizes attendance workflow.

## 11.2 Windows hotspot automation

Investigate real Windows capabilities:

- Wi-Fi adapter support.
- Windows Mobile Hotspot APIs.
- Permissions.
- Hotspot password control.
- Firewall behavior.
- Local routing.
- Docker interaction.
- Sleep/power handling.
- Connected-device limits.

Provide automatic hotspot control if supported.

Otherwise provide guided setup.

Do not falsely report unsupported functionality as implemented.

Prefer a fresh hotspot credential per attendance session if reliable.

Do not rotate the Wi-Fi password during an active session.

## 11.3 Local-only access

Restrict classroom attendance service to the intended hotspot interface as much as technically possible.

Do not expose it on the central public endpoint.

Do not allow central website attendance submissions.

Do not trust IP addresses as proof of physical presence.

Hotspot range extension, relaying and QR sharing remain possible.

Faculty oversight is mandatory.

---

# PART 12 — OFFLINE MOBILE HTTPS FEASIBILITY

This is the major unresolved platform issue.

Student phones must access the camera over the local hotspot, even when university internet is unavailable.

Mobile browsers generally require a trustworthy HTTPS secure context for camera access.

Investigate:
- Android Chrome.
- iPhone Safari.
- Offline HTTPS.
- Local DNS.
- Certificate trust.
- Windows hotspot behavior.
- Browser camera permissions.
- Offline hostname resolution.

Do not assume a plain `http://192.168.x.x` site reliably supports `getUserMedia()`.

Do not assume Tailscale Serve works with no internet.

Do not ask users to bypass certificate warnings.

Do not disable browser security protections.

Implement the best technically sound solution.

If frictionless trusted HTTPS on arbitrary phones is infeasible without installation/provisioning, document that clearly.

Provide a tested prototype fallback and identify its prerequisites.

Treat local phone-camera HTTPS as an early feasibility gate, not an afterthought.

---

# PART 13 — TIMETABLE AND ATTENDANCE INITIATION

Retain timetable management from V1.

Support:
- Eight editable periods.
- Course codes.
- Sections.
- Faculty.
- Breaks.
- Lunch.
- Holidays.
- Cancellations.
- Timetable overrides.

Remove V1's fixed student attendance time windows.

## 13.1 Faculty attendance start

Faculty starts attendance manually during the scheduled class.

Default allowed start:

Class start → class end + 10 minutes.

Example:

Class: 08:50–09:45.

Allowed attendance start: 08:50–09:55.

## 13.2 Collection duration

Once started:
- Student collection lasts a maximum of five minutes.
- Faculty can end early.
- Countdown visible.
- Student submissions after closing are rejected.
- Review and approval may happen later.

## 13.3 Reminder

Two minutes before class ends, if no attendance session was initiated:

Show a Windows notification.

Example:

"Attendance has not been taken for CAI2502."

Do not notify for holidays, breaks or canceled classes.

Avoid duplicates.

Use native notification support if possible.

---

# PART 14 — CLASSROOM STUDENT EXPERIENCE

No classroom password or central login.

## 14.1 Entry

The student connects to the hotspot.

The classroom attendance QR should function as a deep link or tokenized local page address.

The first scan must open the website and establish the ENTRY stage.

Do not unnecessarily require scanning the first attendance QR a second time.

## 14.2 Roll number

Website prompts:

"Enter your university roll number."

Student enters roll number.

Faculty service checks:
- Current authorized class roster.
- Active attendance session.
- Claimed roll number existence.
- No duplicate completed submission.

If no record exists, display a generic correction/error state.

Use rate limits to prevent roll-number enumeration.

Do not reveal private student records before verification.

## 14.3 Enrollment status

If student has ACTIVE biometric enrollment:
- Continue to face/liveness.

If NOT_ENROLLED:
- Inform student that faculty must mark attendance manually.
- Create a non-biometric review/request entry if appropriate.
- Do not attempt unauthorized face recognition.

If PENDING_CC or PENDING_ADMIN:
- Manual attendance path.

If EXPIRED:
- Manual attendance path and re-enrollment reminder.

All students remain in the faculty roster.

Do not automatically mark such students absent.

---

# PART 15 — RANDOMIZED LIVENESS AND FACE VERIFICATION

Reuse AttendX V1's functioning components.

## 15.1 Models

- SCRFD face detection.
- Five-point alignment.
- AdaFace IR-101 embeddings.
- Image-quality checks.
- One-to-one cosine comparison.
- MATCH / NON-MATCH / ABSTAIN.

Faculty laptop performs inference locally.

Use RTX 4060 GPU where available, CPU fallback where feasible.

## 15.2 Liveness challenges

Generate unpredictable challenge sequences.

Examples:
- Turn LEFT.
- Turn RIGHT.
- Return CENTER.
- Look UP.
- Blink TWICE.

Validate:
- Sequence.
- Head pose.
- Blink count.
- Frame continuity.
- Challenge expiry.
- Image quality.
- Exactly one face.
- Attempt limits.

Validation must be server-side.

Do not blindly trust frontend-reported completion.

Do not claim resistance to sophisticated virtual-camera injection or deepfakes without evidence.

## 15.3 Three-template comparison

Faculty has three approved enrollment embeddings.

Implement a documented matching strategy.

Do not assume selecting the maximum similarity over three references is automatically safe.

Calibrate false-match behavior.

Keep provisional thresholds labeled.

## 15.4 Outcomes

MATCH:
- Continue to final QR.

NON-MATCH:
- Create faculty review case.

ABSTAIN:
- Create faculty review case.

LIVENESS FAILURE:
- Retry within limits or escalate.

Do not automatically mark students absent for any of these outcomes.

Consolidate repeated failures into one reviewable student/session case.

---

# PART 16 — SECOND ROTATING QR SCAN

After successful face/liveness verification:

1. Student taps "Scan to submit".
2. Website releases front-facing camera stream.
3. Website opens rear-facing QR scanner.
4. Student scans CURRENT rotating attendance QR.
5. Faculty service validates token.
6. Token must be different from initial entry token.
7. Token must be short-lived and unexpired.
8. Token must belong to same class/session.
9. Student must have a valid server-side MATCH result.
10. Verification attempt must not be expired.
11. No duplicate submission may exist.
12. Successful submission becomes `PENDING_FACULTY_APPROVAL`.

The student sees:

"Submitted successfully. Awaiting faculty confirmation."

This must not be falsely presented as final university attendance.

## 16.1 QR security

Use:
- Cryptographically unpredictable tokens.
- Approximately five-second rotation.
- Server-side token validation.
- Entry/finalization state separation.
- Attempt binding.
- Token replay protection.
- Correct student/section/session checks.
- Expiration.
- Idempotency.

Browser app-switching detection is not a reliable security boundary.

Do not claim rotating QR proves physical presence.

---

# PART 17 — FACULTY ATTENDANCE ROSTER

This is one of the most important features.

Every student in the faculty's authorized academic roster appears, regardless of enrollment status.

Faculty must be able to manually mark EACH student:

- PRESENT.
- ABSENT.
- UNMARKED.

Enrollment status is separate from attendance status.

## 17.1 Roster example

Student A:
- Enrollment ACTIVE.
- Face MATCH.
- QR submitted.
- Suggested PRESENT.
- Faculty can confirm or modify.

Student B:
- PENDING_CC_VERIFICATION.
- No automated verification.
- Faculty sees pending enrollment.
- Faculty can manually mark PRESENT.

Student C:
- NOT_ENROLLED.
- Not physically in class.
- Faculty can mark ABSENT.

Student D:
- ACTIVE.
- Face NON-MATCH due to recognition failure.
- Faculty calls roll number.
- Physically verifies the student.
- Faculty manually marks PRESENT with reason.

Student E:
- ACTIVE.
- No submission.
- Faculty may mark ABSENT after checking.

Never infer absence merely from missing biometric enrollment.

## 17.2 Verification alerts

For NON-MATCH, ABSTAIN, liveness failure or technical issues:

Show one consolidated review case per student/session.

Faculty sees:
- Roll number.
- Name.
- Enrollment status.
- Verification status.
- Reason code.
- Retry count.

Faculty may:
- Approve manually.
- Reject.
- Request retry.
- Leave pending.

No ordinary faculty access to enrollment photographs is required.

## 17.3 First day of semester

The first semester class may have many students awaiting CC verification/admin approval.

The faculty roster must still be completely usable.

Faculty manually marks present/absent.

A CC teaching the class can also use their separately authorized enrollment-verification interface.

The absence of approved biometrics must never prevent normal attendance.

---

# PART 18 — FACULTY HEADCOUNT AND APPROVAL

Faculty can enter physical headcount.

Display:
- Total roster.
- Active biometric enrollments.
- Pending enrollments.
- QR submissions.
- Verified submissions.
- Manual presents.
- Manual absents.
- Unmarked students.
- Review cases.
- Physical headcount.

Highlight discrepancies.

## 18.1 Final approval

After collection ends, faculty reviews the roster.

Faculty can edit attendance even after the five-minute QR closes.

Faculty explicitly clicks:

"Approve Final Attendance"

Before approval:
- Flag unmarked students.
- Require review or an explicit, auditable decision to mark remaining unmarked students absent.
- Highlight unresolved review cases.
- Show headcount discrepancies.

Do not silently classify unknown students absent.

After approval:
- Freeze an approved snapshot.
- Store it durably.
- Create sync outbox records.
- Record faculty identity/time.
- Record manual override reasons.

Post-approval corrections must become audited amendments.

Only approved records sync as final attendance.

---

# PART 19 — OFFLINE-FIRST FACULTY STORAGE

The classroom system must work with NO university internet.

Faculty app has:

- Authorized cached roster.
- Student names/roll numbers.
- Enrollment statuses.
- Approved encrypted face templates.
- Template expiry.
- Timetable.
- Local QR service.
- Face/liveness inference.
- Attendance session state.
- Faculty approval workflow.
- Local SQLite database.
- Transactional synchronization queue.

Do not cache student passwords.

Do not transfer raw enrollment photos.

## 19.1 Security

Protect face templates and sensitive records using encryption.

Use Windows device-protected key storage where practical.

Restrict local database access.

Show last successful central sync.

Handle stale rosters, revoked enrollments and disconnected faculty devices with explicit policies.

## 19.2 Crash recovery

On application restart:
- Preserve completed student submissions.
- Preserve manual attendance decisions.
- Preserve finalized approved records.
- Preserve unsynced events.
- Expire unsafe active challenges.
- Restore consistent local state.

Never lose approved attendance because internet was unavailable.

---

# PART 20 — CENTRAL SERVER SYNCHRONIZATION

Central server and faculty application communicate through authenticated APIs.

Faculty app downloads:
- Authorized roster changes.
- Faculty assignment changes.
- Student enrollment status.
- New face-template versions.
- Template expiry.
- Timetable changes.
- Holidays.
- Relevant policy settings.

Faculty app uploads:
- Faculty-approved attendance.
- Audited amendments.
- Required synchronization metadata.

Implement:
- Transactional outbox.
- Stable event IDs.
- Idempotency keys.
- Retry with backoff.
- Durable acknowledgments.
- Duplicate prevention.
- Conflict detection.
- Audit records.
- Restart recovery.

The faculty app must not directly write to the central SQLite database file.

## 20.1 Offline demo

1. Sync roster online.
2. Disconnect central server.
3. Start classroom attendance locally.
4. Record submissions/manual decisions.
5. Approve locally.
6. Restart faculty app.
7. Confirm approved attendance remains.
8. Restore central-server connectivity.
9. Sync records.
10. Confirm central database updated once.
11. Retry sync.
12. Verify no duplicates.

Use real service separation, not fake frontend connectivity toggles.

---

# PART 21 — WINDOWS FACULTY EXECUTABLE

Create a distributable faculty Windows application.

Evaluate PySide6, Tauri or equivalent.

Reuse React/Python code where reasonable.

Features:
- Faculty login.
- Assigned timetable.
- Active class.
- Hotspot controls.
- QR display.
- Live attendance roster.
- Manual PRESENT/ABSENT/UNMARKED controls.
- Review cases.
- Headcount.
- Final approval.
- Sync status.
- System tray.
- Native reminders.
- Local model inference.
- GPU support.
- CPU fallback.
- Secure offline storage.
- Safe startup/shutdown.

Provide:
- Real `.exe` build.
- Reproducible build script.
- Required dependencies.
- Model installation instructions.
- Logs.
- Troubleshooting.
- App icon.

Do not claim the application is fully standalone if it needs external model files or runtime components.

Respect non-commercial model licensing.

---

# PART 22 — END-OF-DAY PRIVACY

At configured university closing hours:

- Stop classroom collection.
- Reject new student submissions.
- Stop biometric intake.
- Close student-facing server where appropriate.
- Clear temporary frames and challenges.
- Disable application-managed hotspot where safe.
- Lock faculty UI.
- Preserve approved attendance.
- Preserve unsynced records.
- Continue authorized synchronization if configured.

Do not destroy pending attendance.

Do not terminate unrelated services.

Provide authorized faculty after-hours override.

---

# PART 23 — ONLINE PORTAL DEPLOYMENT

Central enrollment portal must eventually be accessible from anywhere over the internet.

Prototype deployment:
- Docker.
- Existing private Tailscale Serve where appropriate.
- Test university-email delivery.
- Local SMTP catcher.
- No unauthorized public exposure.

Future internet-facing deployment:
- Proper HTTPS domain.
- Public-access security controls.
- University identity validation.
- SMTP integration.
- Secure storage.
- Proper authentication.
- Approved network exposure.
- Monitoring and abuse protection.

Do not change the existing public Tailscale Funnel for unrelated services.

Do not expose AttendX publicly without explicit approval.

The classroom attendance portal is NEVER publicly hosted.

---

# PART 24 — PRIVACY AND SECURITY

Implement:
- Strong central authentication.
- Password hashing.
- University-email activation.
- Secure reset tokens.
- Admin/CC/faculty role scoping.
- Restricted biometric-photo access.
- Consent management.
- Protected face embeddings.
- Minimal data distribution.
- Secure local storage.
- Expiration and retention.
- Audit logging.
- Rate limiting.
- QR replay protection.
- Secure synchronization.
- Manual non-biometric attendance.
- Data deletion requests.

Protect against:
- Fake initial enrollment.
- Account invitation forwarding.
- Unauthorized CC approval.
- Faculty accessing unrelated classes.
- Roll-number enumeration.
- Printed photo attacks.
- Video replay.
- Virtual cameras.
- Deepfakes.
- QR forwarding.
- QR relay.
- Hotspot password sharing.
- Network tunneling.
- Stolen faculty devices.
- Offline roster manipulation.
- Duplicate synchronization.
- Incorrect manual approvals.

Explicitly document residual risks.

Do not claim perfect anti-spoofing or guaranteed physical presence.

---

# PART 25 — AUTOMATED TESTING

Create and run tests for:

## Central account management
- Student creation.
- Duplicate roll/email.
- Invitation expiration.
- First-time activation.
- Password change.
- Password reset.
- Account enumeration protection.

## Three-photo enrollment
- Three valid samples.
- Invalid/missing samples.
- Bad lighting/blur.
- Multiple faces.
- Same-person consistency.
- Enrollment state transitions.
- Protected photo previews.
- Template versioning.

## CC enrollment approval
- Assigned CC access.
- Wrong-section CC denial.
- In-person verification record.
- CC rejection.
- Pending admin approval.
- Admin final approval.
- Unauthorized faculty denial.
- Audit trail.

## Semester renewal
- Admin semester end date.
- Renewal countdown.
- Renewal reminders.
- Expiration.
- New three-photo captures.
- CC/admin reapproval.
- Old/new template version handling.

## Academic assignments
- Faculty-course permissions.
- Faculty-section permissions.
- Special student enrollment.
- Substitute faculty.
- CC assignment.
- Roster isolation.
- Unenrolled student inclusion.

## Local roll-number flow
- Valid roster roll.
- Invalid roll.
- Repeated attempts.
- Missing/expired biometrics.
- Manual-review request.
- No automatic attendance from roll alone.

## QR
- Valid initial scan.
- Expired token.
- Wrong session.
- Replayed token.
- Phase 2 before MATCH.
- Fresh second token.
- Duplicate submission.
- Closed session.

## Face/liveness
- Genuine MATCH.
- Impostor NON-MATCH.
- Quality ABSTAIN.
- No face.
- Multiple faces.
- Blink/head pose.
- Incorrect sequence.
- Challenge expiry.
- Multi-template comparison.

## Attendance roster
- Active enrolled student.
- Pending CC student.
- Pending admin student.
- No enrollment.
- Expired enrollment.
- Manual present.
- Manual absent.
- Unmarked.
- Review case.
- Headcount mismatch.
- Faculty final approval.
- Post-approval amendment.

## Offline/synchronization
- No central internet.
- Cached roster.
- Crash recovery.
- Persistent approved records.
- Sync retry.
- Duplicate prevention.
- Conflict detection.
- Updated template distribution.
- Revocation handling.

## Deployment
- Docker health.
- Central portal.
- Faculty executable build.
- GPU inference.
- Local hotspot.
- Offline HTTPS.
- Mobile camera where actual hardware is available.
- End-of-day behavior.

Distinguish:
- Unit tests.
- Integration tests.
- Hardware tests.
- Manual real-phone tests.

Never fabricate passing tests or accuracy measurements.

---

# PART 26 — COMPLETE DEMONSTRATION

The final project must support this workflow.

## A. Central setup

1. Admin creates section, course and semester.
2. Admin assigns faculty and Class Coordinator.
3. Admin creates student account.
4. Invitation is delivered or captured in test mail system.
5. Student opens online portal.
6. Student activates account and sets password.
7. Student captures three photos.
8. Enrollment becomes pending CC verification.

## B. CC verification

9. CC logs into authorized portal.
10. CC opens only assigned-section enrollment requests.
11. CC physically checks the student.
12. CC compares three submitted photos.
13. CC records identity confirmation.
14. Enrollment becomes pending admin approval.
15. Admin grants final approval.
16. Three templates become active through central server.

## C. Faculty synchronization

17. Faculty logs into Windows application.
18. Faculty downloads authorized roster.
19. Faculty receives approved templates.
20. Faculty receives all other roster members without approved biometrics.
21. Faculty receives timetable and expiry dates.
22. Faculty disconnects central internet.

## D. Classroom attendance

23. Faculty selects scheduled class.
24. Faculty starts five-minute attendance.
25. Laptop hotspot becomes available.
26. Wi-Fi connection QR is displayed.
27. Rotating attendance QR is displayed.
28. Student connects to hotspot.
29. Student scans attendance QR.
30. Student enters roll number.
31. Faculty service verifies claimed roll is on the authorized roster.
32. Student completes randomized live liveness.
33. Faculty laptop compares live face to three approved reference templates.
34. MATCH is returned.
35. Student scans fresh rotating QR.
36. Submission becomes pending faculty approval.

## E. Manual attendance

37. A student without approved biometrics appears in faculty roster.
38. Faculty manually marks the student PRESENT after confirming physically.
39. Another student is absent.
40. Faculty marks ABSENT.
41. A genuine student receives NON-MATCH.
42. Faculty receives one consolidated review case.
43. Faculty calls out the roll number and cross-checks the person.
44. Faculty manually marks PRESENT with reason.

## F. Final approval

45. Faculty enters classroom headcount.
46. Faculty reviews verified/manual/missing students.
47. Faculty resolves unmarked records.
48. Faculty explicitly approves final attendance.
49. The approved snapshot is stored locally.

## G. Offline recovery/sync

50. Faculty app restarts.
51. Approved records remain.
52. Internet returns.
53. Approved attendance synchronizes.
54. Central server saves final results.
55. Duplicate sync is attempted.
56. Database remains duplicate-free.

## H. Re-enrollment

57. Admin configures semester expiry.
58. Student sees renewal countdown.
59. Student submits three new images.
60. CC confirms identity in person.
61. Admin approves renewed enrollment.
62. Faculty app receives new template version on sync.

Use synthetic academic data and consenting faces.

Do not use real university credentials or infrastructure without authorization.

---

# PART 27 — IMPLEMENTATION MILESTONES

M0 — Inspect repository, preserve V1, baseline tests.

M1 — Central student accounts, email activation, password management.

M2 — Three-photo enrollment, photo privacy, biometric storage.

M3 — Academic class structure, faculty/CC assignments, scope-based authorization.

M4 — CC verification and admin final approval.

M5 — Semester expiry and re-enrollment.

M6 — Faculty synchronization, full roster and encrypted template cache.

M7 — Faculty-controlled sessions and fully editable attendance roster.

M8 — Rotating QR and existing face/liveness integration.

M9 — Offline persistence, faculty approval, synchronization protocol.

M10 — Faculty Windows desktop executable, tray, reminders and packaging.

M11 — Windows hotspot automation and offline mobile HTTPS.

M12 — End-to-end validation, documentation and demonstration.

At every milestone:
- Implement real code.
- Run tests.
- Fix failures.
- Preserve existing working functionality.
- Commit coherent changes locally.

Do not spend the entire execution on design documents.

Do not conceal infrastructure or hardware blockers.

---

# PART 28 — NON-NEGOTIABLE RULES

1. Do not modify VEIL-X.
2. Do not delete or overwrite user work.
3. Do not modify unrelated Docker services.
4. Do not alter existing unrelated Tailscale Funnel routes.
5. Do not push to GitHub without authorization.
6. Do not expose AttendX publicly without authorization.
7. Do not send student passwords to faculty devices.
8. Do not let roll number alone count as attendance.
9. Do not permit face-only password recovery.
10. Do not automatically approve CC enrollment verification as final.
11. Do not allow ordinary faculty to modify biometric enrollment.
12. Do not omit unenrolled students from faculty rosters.
13. Do not equate unenrolled with absent.
14. Do not equate NON-MATCH with absent.
15. Do not equate ABSTAIN with absent.
16. Do not equate missing QR submission with automatic absence.
17. Do not silently mark UNMARKED as ABSENT.
18. Do not finalize class attendance without faculty approval.
19. Do not lose locally approved records.
20. Do not expose enrollment photos to ordinary faculty.
21. Do not bypass offline HTTPS browser restrictions.
22. Do not claim QR/hotspot provides guaranteed physical presence.
23. Do not fabricate model accuracy or test results.
24. Do not claim Windows packaging works unless actually built and tested.
25. Do not call incomplete functionality complete.

---

# PART 29 — FINAL HANDOVER REPORT

At completion, provide:

1. Repository path.
2. Git branch.
3. Commits created.
4. Files changed.
5. Existing V1 components reused.
6. Central server implementation status.
7. Admin portal status.
8. Student activation status.
9. Three-photo enrollment status.
10. CC verification status.
11. Admin enrollment approval status.
12. Semester re-enrollment status.
13. Student photo transparency status.
14. Password/recovery status.
15. Faculty/class assignment status.
16. Faculty Windows `.exe` status and path.
17. Local hotspot status.
18. Offline HTTPS status.
19. Student local website status.
20. First QR scan status.
21. Roll-number flow status.
22. Random liveness status.
23. AdaFace verification status.
24. Second QR status.
25. Faculty review/manual attendance status.
26. Faculty headcount status.
27. Final approval status.
28. Offline storage status.
29. Central synchronization status.
30. Tests executed and results.
31. Manual tests still needed.
32. Exact startup/shutdown commands.
33. Real-phone demo procedure.
34. Known limitations.
35. Remaining blockers.

Mark each major feature honestly as COMPLETE, PARTIAL, BLOCKED or NOT TESTED.

---

# FINAL EXECUTION INSTRUCTION

Start by inspecting the existing AttendX repository and documentation.

Preserve the current working project.

Implement AttendX V2 incrementally.

Prioritize central identity management, CC/admin approval, complete faculty rosters, and reliable local attendance before optional visual polish.

The FINAL workflow is:

ADMIN CREATES STUDENT
→ UNIVERSITY EMAIL ACTIVATION
→ STUDENT SETS PASSWORD
→ THREE FACE CAPTURES
→ CC VERIFIES IDENTITY IN PERSON
→ ADMIN APPROVES ENROLLMENT
→ FACULTY DOWNLOADS AUTHORIZED ROSTER/TEMPLATES
→ FACULTY STARTS CLASSROOM HOTSPOT
→ STUDENT SCANS ROTATING QR
→ ENTERS ROLL NUMBER
→ LIVE LIVENESS + ADAFACE VERIFICATION
→ SCANS FRESH ROTATING QR
→ SUBMITTED FOR FACULTY APPROVAL
→ FACULTY MANUALLY RESOLVES EXCEPTIONS
→ FACULTY MARKS REMAINING PRESENT/ABSENT
→ FACULTY CONFIRMS HEADCOUNT
→ FACULTY APPROVES FINAL ATTENDANCE
→ OFFLINE RECORD PERSISTS
→ CENTRAL SERVER SYNCHRONIZES WHEN ONLINE.

**The classroom attendance system must always be faculty-hotspot-only.**

**All students must remain on the attendance roster regardless of face enrollment status.**

**The faculty retains final authority over attendance.**

Build, test, document and commit locally.

Do not stop after writing a plan.

Do not fabricate completed features or real-device test results.

Deliver a working engineering project, with any remaining platform limitations clearly identified.