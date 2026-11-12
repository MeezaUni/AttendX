# Updated faculty app: quick test

Use the **AttendX Faculty** shortcut on this laptop's desktop. It opens the updated executable
with the repository's model directory configured. The underlying file remains
`dist/faculty/AttendXFaculty/AttendXFaculty.exe`; keep the full directory together.

**Testing after 18:00:** the app's default closing time is 18:00. Sign-in now shows a clear
after-hours notice and asks whether you are authorized to continue today. Choose **Yes** if
authorized; otherwise Cancel preserves your entered details. You can also select the outlined
after-hours checkbox directly on Sign in & sync. This avoids the former immediate login/lock
loop. The choice expires the next institution-local day; timetable windows still apply.

1. In **Sign in & sync**, enter the faculty credentials and your existing local PIN/passphrase.
   Set central URL to `https://YOUR-LAPTOP.YOUR-TAILNET.ts.net:10000`, leave CA bundle blank, and click
   **Provision or reauthorize online** once. This upgrades the existing profile to the common
   AttendX classroom certificate. It preserves saved rosters and unsynced records.
2. In **Attendance**, check the automatically detected course, section and period. Press
   **Start attendance · 5 minutes**, then **Start**. The app probes Windows and prepares the
   hotspot and secure classroom services. You do not enter a period, IP or certificate path.
3. For first-time phone setup, click **Show Wi-Fi QR and phone setup**. The **Join Wi-Fi** tab
   shows the Wi-Fi QR and password. The **Phone setup · once** tab supplies the profile/camera
   instructions. Alternatively install the common profile beforehand from the student's portal.
   Each phone installs/trusts it once for this AttendX deployment, not for every class/faculty.
4. After the phone's trusted HTTPS camera check works, confirm readiness in the Start dialog
   and start collection. On later starts that confirmation is remembered for the same CA.
   The full attendance QR is shown in a separate window. Students join Wi-Fi, scan the
   attendance QR, enter roll/capture, then scan a fresh QR after a successful verification.
5. A successful face match plus the fresh QR shows **MATCH · QR complete** in the roster and
   preselects **PRESENT** as a draft. Faculty choices are preserved. Dropdowns remain open while
   counts refresh. Match alone, before the second QR, does not mark attendance.
6. At five minutes, classroom intake and the app-owned hotspot stop automatically. Resolve
   exceptions and enter physical headcount. **Approve Final Attendance** opens a cross-check:
   recount/edit the number, review suggested students, and return to their decision dropdown.
   Final approval requires all decisions and resolved cases; any remaining count discrepancy
   needs an explanation. Approved records stay local until synchronization succeeds.

The app and student website follow the system light/dark setting. Phone instructions now appear
over the camera, with directional arrows and blinking-eye guidance. After a match, the rear-camera
QR scanner offers **1–4× zoom**; increase it when scanning from the back of the room. Digital zoom
enlarges the decoder crop but cannot recover detail absent from the camera image.

The attendance timer starts after laptop setup is ready. A class ending 17:10 allows starts
through 17:15; a start at 17:14 closes at 17:19. The running unlocked app reminds faculty at
class end if no attendance was started. If no class is available, check timetable/current time.
If the period already has a session (including your earlier test), open that saved roster;
the app preserves it instead of creating duplicate attendance. Do not delete the faculty profile.

First-time iPhone trust still requires the phone owner's Settings actions. Windows may ask to
allow the app on the private classroom network. Offline classes use no public attendance proxy.
The laptop must provision/renew online initially; ordinary prepared classroom sessions work offline.
