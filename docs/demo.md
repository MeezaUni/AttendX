# Demonstration script (about 10 minutes)

Prerequisites: the container is running (`.\scripts\attendx.ps1 status`), Tailscale Serve is
on, the laptop and the phone are signed in to the same tailnet, and an admin account exists.

## Optional: synthetic data mode

```powershell
.\scripts\attendx.ps1 seed-demo
```

This creates section **DEMO-5A**, six fictional courses, three fictional faculty, a weekly
timetable (with a break slot on Wednesday period 4), twelve synthetic students `DEMO5A01…12`
with one-time passwords (printed once), and ten days of synthetic past attendance
(`method = synthetic`). **No face data is created.** The UI shows a demo-mode banner when
`ATTENDX_DEMO_MODE=true`. Use the synthetic data for the reports part only; the live demo
below uses a real, consenting person (you).

## Live demo

| # | Step | Where | Expected |
|---|---|---|---|
| 1 | Admin signs in | laptop `https://…ts.net:8443` | dashboard with server time in the institutional timezone |
| 2 | Create a section and a course | *Courses & sections* | listed |
| 3 | Create a student (yourself) | *Students → Add student* | one-time password shown once |
| 4 | Enroll the face | student page → consent → *Live capture* (laptop webcam) or *Allow self-enrollment* (then enroll on the phone and approve) | "Face enrolled and approved" |
| 5 | Configure an attendance window | *Attendance → Extra session* for now, or *Open 10 min* on today's class | status **open** |
| 6 | Open AttendX on the phone | phone browser, same HTTPS address | login page |
| 7 | Student signs in and sets a password | phone | *Today's classes*, the open class shows **Mark attendance** |
| 8 | Start verification | phone → *Open camera* (allow the camera) | live oval and guidance |
| 9 | Random challenge appears | phone | e.g. "Turn LEFT → Return to CENTRE → Blink TWICE" |
| 10 | Complete it | phone | steps tick off; "Verifying…" |
| 11 | Face verified | phone | **Attendance recorded** |
| 12 | Admin sees the record | laptop *Attendance → Roster* (refreshes every 5 s) | present, method face, time, score |
| 13 | Duplicate prevented | phone → *Mark attendance* again (or reload) | "attendance is already recorded" |
| 14 | Outside-window attempt rejected | admin *Close now*, then the student tries | "attendance window has closed" |
| 15 | Export CSV | *Reports → Attendance CSV* | CSV with the record |
| 16 | (Optional) impostor | a second consenting person tries on your account | NON-MATCH or ABSTAIN, not marked |

Talking points: 1:1 verification only; the server owns every decision; random challenges;
frames are not stored; MATCH / NON-MATCH / ABSTAIN with abstention; provisional thresholds and
the validation procedure; active-liveness limitations (video replay, deepfakes).

## Device checklist (record the results)

- [ ] Android Chrome: camera permission prompt, preview, challenge, result
- [ ] iOS Safari: same
- [ ] MATCH recorded for the enrolled person (attempts used: __)
- [ ] Impostor not marked (decision: __)
- [ ] Still photo held up to the camera → rejected by liveness
- [ ] Window closed → rejected
