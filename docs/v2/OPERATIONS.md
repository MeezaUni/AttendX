# AttendX V2 operations

Repository: `C:\Path\To\AttendX`. Commands below run from that directory in PowerShell.
V1 remains running in project `attendx`, image `attendx:local`, volume `attendx-data`, loopback
8470 and private HTTPS 8443. Do not use V1 operational scripts to manage V2.

## Central server

The local ignored `.env.v2` contains only prototype configuration, including this laptop's
public HTTPS URL and the synthetic email domain `example.edu`. On another machine create it:

```powershell
@'
ATTENDX_V2_PORTAL_URL=https://YOUR-LAPTOP.YOUR-TAILNET.ts.net:10000
ATTENDX_UNIVERSITY_EMAIL_DOMAIN=example.edu
ATTENDX_TORCH_VARIANT=cu128
'@ | Set-Content -Encoding ascii .env.v2

docker compose --env-file .env.v2 -f docker-compose.v2.yml up -d --build
docker compose --env-file .env.v2 -f docker-compose.v2.yml exec central attendx create-admin --username admin
```

Choose the first administrator password interactively; no real administrator credentials are
embedded or precreated. For CPU-only central deployment:

```powershell
docker compose --env-file .env.v2 -f docker-compose.v2.yml -f docker-compose.v2.cpu.yml up -d --build
```

V2 binds only `127.0.0.1:8480` locally. The user authorized public central access on
4 November 2026. A dedicated public HTTPS Funnel uses port 10000 without changing 443 or 8443:

```powershell
tailscale funnel --bg --https=10000 http://127.0.0.1:8480
tailscale serve status
Invoke-RestMethod https://YOUR-LAPTOP.YOUR-TAILNET.ts.net:10000/api/health
```

The central student portal works through ordinary mobile data or Wi-Fi without installing
Tailscale on the phone. This laptop, Docker and the laptop's Tailscale service must remain
running. Only the central service is published. The classroom listener must never be proxied
through Tailscale Serve, Funnel, campus LAN, or any public endpoint. Mailpit remains loopback-only.
The earlier private 8444 handler remains available for existing tailnet clients.
Funnel's supported HTTPS ports are documented in the
[Tailscale CLI reference](https://tailscale.com/docs/reference/tailscale-cli/funnel).

```powershell
# Inspect only V2
docker compose --env-file .env.v2 -f docker-compose.v2.yml ps
docker compose --env-file .env.v2 -f docker-compose.v2.yml logs --tail 100 central

# Stop only V2 (keeps its data volume)
docker compose --env-file .env.v2 -f docker-compose.v2.yml stop
# Start existing V2 again
docker compose --env-file .env.v2 -f docker-compose.v2.yml start
# Optional removal of V2's public handler only (leaves other routes intact)
tailscale funnel --https=10000 off
# Optional removal of V2's earlier private HTTPS handler only
tailscale serve --https=8444 off
```

Mailpit at `http://127.0.0.1:8026/` captures SMTP inside the V2 Docker network. It is a test
inbox, not a university email integration. Tokens appear in URL fragments so HTTP access logs
do not contain them. Open the full link from the caught message, activate, and sign in.
Old messages retain the previous private URL: replace only `:8444` with `:10000`, preserving
the path and complete `#` token. This does not renew an expired or already consumed token.
For an expired pending invitation, use the administrator's **Resend invitation** action.
Real SMTP requires authorized host/port/TLS credentials and sender/domain configuration.
The native settings are `ATTENDX_SMTP_HOST`, `ATTENDX_SMTP_PORT`, `ATTENDX_SMTP_STARTTLS`,
`ATTENDX_SMTP_USERNAME`, `ATTENDX_SMTP_PASSWORD`, `ATTENDX_MAIL_FROM`, `ATTENDX_MAIL_TRANSPORT`.
Use secrets outside Git. Confirm actual inbox delivery before claiming university integration.

Periodic central maintenance runs at a configurable interval (default 60 seconds), processes
expiry/retention and configured reminders, and retries pending encrypted mail. Admin can also
run maintenance from the portal. Failed SMTP leaves a queued encrypted record with error class.

## Academic setup and enrollment

1. Sign into V2 central as admin. Create sections/courses under **Courses & sections**.
2. Configure a semester/expiry/renewal deadline for each section in **V2 administration**.
3. Create faculty accounts, then separate teaching and CC assignments. A CC assignment does
   not grant teaching rights to other classes. Configure the actual timetable, faculty and periods.
4. Invite students using only name, roll, registered email, department, semester and section.
5. Open invitation in Mailpit, set a student password, sign in and capture exactly three samples.
   Retained photo previews require separate consent. Invalid sets must be recaptured.
6. Assigned CC signs into `/faculty`, physically checks the student against trusted records,
   reviews retained photos where permitted, and confirms/rejects identity. The checkbox records
   the human assertion; software cannot establish that the physical check actually occurred.
7. Admin gives final enrollment approval. Only approved unexpired compatible templates sync.
8. Dated substitute/additional-student assignments are available through documented V2 APIs;
   the current admin forms cover the common teaching/CC setup, not every academic edit.

University admission-photo integration and OD/medical workflows are not implemented.
`UniversityAttendanceAdapter` is an interface for future authorized integration only.

## Faculty application and build

The tested package is `dist\faculty\AttendXFaculty\AttendXFaculty.exe`. Keep its `_internal`
directory beside it. External model weights are required; they are never embedded in Git or
the executable. The generated CUDA distribution is about 4.8 GB before external model files.

```powershell
# Existing repository model files
.\dist\faculty\AttendXFaculty\AttendXFaculty.exe --models-dir C:\Path\To\AttendX\models
# CPU fallback
.\dist\faculty\AttendXFaculty\AttendXFaculty.exe --device cpu --models-dir C:\Path\To\AttendX\models
# Diagnostic model loading + blank-frame detection, does not measure accuracy
.\dist\faculty\AttendXFaculty\AttendXFaculty.exe --check-models --models-dir C:\Path\To\AttendX\models --report C:\Path\To\AttendX\build\model-check.json
```

Install models with `backend\.venv\Scripts\python.exe scripts\fetch_models.py --dest <model-folder>`.
Alternatively place `models` beside the distributed executable. The model fetcher verifies
pinned hashes. Use `--device cpu` when CUDA allocation/runtime is unavailable; CPU latency has
not been characterized for a room of simultaneous users.

Rebuild on Windows, Python 3.12:

```powershell
uv pip install --python backend/.venv/Scripts/python.exe -e "backend[dev,desktop]"
# Existing CUDA torch: retain it. On a fresh environment install the appropriate official wheel.
uv pip install --python backend/.venv/Scripts/python.exe torch --index-url https://download.pytorch.org/whl/cu128
cd frontend
npm ci
npm run build
cd ..
backend/.venv/Scripts/python.exe scripts/build_faculty.py
```

`backend/requirements-windows.lock.txt` records the tested environment. When using it on a fresh
machine, include the official CUDA wheel index for its CUDA-tagged torch version; CPU builds
need a matching CPU torch installation instead. The build isolates PATH to avoid accidentally
bundling unrelated Poppler/other-tool DLLs. Distribute the full Qt shared-library folder and
appropriate licensing notices, and follow the non-commercial model terms.

In the app, enter the central verified HTTPS URL, faculty credentials and an offline local
PIN/passphrase. Initial provisioning needs central connectivity. Passwords are cleared from
the form; only the device credential, authorized data and local PIN hash are encrypted locally.
Default data directory: `%LOCALAPPDATA%\AttendXFaculty`. `device.key` is current-user DPAPI
protected on Windows. Do not copy this profile between Windows users. Never delete it while
approved events remain unsynced. Use separate profiles for separate faculty members.

Reauthorizing rotates the credential while preserving the device identity and pending-event
bindings. Offline grants default to 24 hours. An offline device cannot receive immediate remote
revocations; a new sync applies revocation, or the cached grant expires. Source and package
logs are in `<data-dir>\faculty.log`; generated build logs stay in ignored workspace files.

## Hotspot and offline trusted HTTPS

1. Launch the updated executable and **Provision or reauthorize online** once. This also
   prepares this laptop's individual TLS key/certificate under the shared AttendX classroom CA.
   Existing profiles need this one-time migration from the old per-laptop demo certificates.
2. In **Attendance**, the assigned timetable and institution-local laptop time choose the
   class and period. Click **Start attendance · 5 minutes**, then **Start** in the dialog.
   Support probing, owned hotspot startup, adapter discovery and certificate/listener setup
   are automatic. Manual IP/path/probe controls are under Settings → Advanced network settings.
3. Open **Show Wi-Fi QR and phone setup** when prompted. Students scan the **Join Wi-Fi** tab;
   the SSID and WPA password are printed below the full QR. The first use on each phone needs
   the shared AttendX profile and explicit trust, once for all faculty on this deployment.
   Students can install it beforehand from their central dashboard, or scan the **Phone setup · once**
   QR while on the hotspot. HTTP port 9442 serves only public CA/profile downloads and instructions.
   No attendance, account credentials or images are accepted there. Camera/attendance use HTTPS 9443.
4. For iPhone, download the profile in Safari, install it in Settings → Profile Downloaded
   (or General → VPN & Device Management), then enable full trust in General → About →
   Certificate Trust Settings. See [Apple's trust instructions](https://support.apple.com/en-au/102390).
   Android's CA installation menu varies by device. Verify the HTTPS camera check without
   bypassing certificate warnings. Confirm readiness in the start dialog; then start collection.
   The timer has not run during first-time setup. The readiness checkbox is a faculty attestation,
   not automatic proof that every phone has installed trust. Remove the profile when no longer needed.
5. The live **Attendance** QR opens in a separate large display, with no cropping. The same
   display has a Join Wi-Fi tab. Students scan the live QR, complete capture, then scan a fresh QR.
   Collection ends five minutes after actual start. Intake, the certificate setup page and the
   app-owned hotspot stop automatically, even during modal editing or slow central sync.
   Completed MATCH plus fresh QR preselects draft PRESENT and updates the summary. The roster
   refresh preserves open decision dropdowns. Review exceptions, enter headcount and open
   **Approve Final Attendance**. Its cross-check dialog lets you recount/edit headcount, review
   suggested students, and explicitly approve once every mark/case is resolved. A remaining
   discrepancy requires a reason; headcount never determines an individual's identity.

Native appearance follows Qt's Windows system color-scheme signal; the student/classroom web
pages follow `prefers-color-scheme`. Readiness checkboxes have explicit visible outlines. Camera
prompts, side arrows and blink-eye guidance overlay the preview. The fresh-QR rear scanner
offers 1–4× digital crop zoom, applied both to preview and decoder pixels. It requests a
high-resolution rear stream where supported; browser/device capabilities still limit detail.
The graphics do not perform liveness inference. Reduced-motion settings disable the eye animation.

The real Windows hotspot start → detected `192.168.137.1`/24 → stop/restore test passed on this
laptop. Full phone trust/camera/face/QR accuracy remains a consenting-device validation task.
The shared root lasts three years; laptop leaves last 90 days and renew online without changing
phone trust. If the hotspot IP changes or a leaf expires while offline, connect the laptop once
and reauthorize. Replacing the shared root requires reinstalling trust on phones. Back up the
central database and its encryption key together; never share the root private key with laptops.

AttendX leaves an existing externally owned hotspot unchanged. Some drivers require a usable
connection profile to start tethering. If Windows asks for firewall access, authorize this
executable for the private classroom network; a scoped administrator rule may be needed for
hotspot-only ports 9442/9443. No global firewall, Tailscale or unrelated network routes are changed.

Class times no longer contain attendance-open/close fields. Faculty may start during the class
or through class end + five minutes, inclusive. A 17:10 class permits a start through 17:15;
a start at 17:14 closes at 17:19. An unlocked running app reminds faculty at class end if no
session was started. Windows notification delivery also depends on OS notification settings.

Students require no Tailscale, central account cookies, student password or offline credential
to use the classroom site. Phones only capture frames, display timed instructions and decode QR
codes; all face/pose/blink/identity inference runs on the laptop. Collection fails closed if
hotspot, trusted HTTPS, grant, class, challenge, pipeline or template validity is unavailable.
Manual attendance remains available in the faculty roster.

## Real-phone demonstration still required

1. Complete central setup/enrollment/CC/admin approval using synthetic academics and consenting faces.
2. Provision the faculty app online and confirm all roster members, including pending/un-enrolled students.
3. Disconnect central connectivity. Establish hotspot/trusted phone HTTPS as above.
4. Check the automatically detected class/period and use the guided Start flow. Display Join Wi-Fi,
   then the rotating Attendance QR. Collection lasts five minutes from actual start and rejects late intake.
5. Student scans initial deep link once, enters roll, completes randomized live instructions.
   On MATCH, release the front camera and scan a fresh classroom QR with the rear camera.
6. Confirm the phone says **Awaiting faculty confirmation**. It must not claim final attendance.
7. Test a pending enrollment, a different consenting face, frozen photo, late/replayed QR and
   repeated submission. Each failure stays UNMARKED or creates a consolidated review case.
8. Faculty physically reviews exceptions, explicitly marks every student, closes collection,
   enters headcount and clicks **Approve Final Attendance**. Explain headcount discrepancies.
9. Quit through the tray menu and reopen. Unlock the cached profile; the approved roster and
   unsynced event must remain. Restore central internet and synchronize; retry without duplicates.
10. Test an audited amendment and re-enrollment version update through CC/admin again.

Also verify iOS Safari and Android Chrome permission handling, front-to-rear camera switching,
TLS while phones have no mobile internet, Windows notifications, closing-hour lock during an
open dialog, hotspot ownership restoration, CPU throughput and simultaneous student load.
These device tests have not been claimed as passing.

## Shut down and rollback

The window close button minimizes to tray. Use tray **Quit AttendX Faculty** to exit. Lock/end
of day stops intake, clears challenges, locks the UI, stops only an app-owned hotspot, and
preserves approved/outbox records. Background authorized upload may continue while locked.
After-hours override is explicit faculty control; verify it again for each teaching day.

For rollback, leave V2 stopped and use the unchanged V1 container/volume/private 8443 endpoint.
Source rollback ref: `codex/attendx-v1-rollback-6f67b26`. Never point V1 code at a migrated V2
database. V2 schema downgrade is deliberately blocked; restore a consistent DB/key backup if
rolling back an actual migrated database. Backups must protect both databases and encryption keys.
