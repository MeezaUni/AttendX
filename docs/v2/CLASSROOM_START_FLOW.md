# Simplified offline classroom flow — 4 November 2026

The user requests one Start flow, automatic class/period selection from laptop time and
assigned timetable, automatic laptop hotspot/TLS preparation, Wi-Fi QR/password display,
uncropped attendance QR, and automatic network shutdown when five-minute collection ends.
The user explicitly kept offline/hotspot-only attendance after discussing online alternatives.

Further steering: use one shared AttendX classroom CA so phones do not need a new profile
for each faculty laptop. The central signing key stays encrypted in the central database;
each authorized faculty device generates its own private key and sends only a signed CSR.
Issuance is limited to current teaching devices and private hotspot IPv4 SANs. Initial online
provisioning downloads the laptop certificate; ordinary class starts reuse it offline. A changed
hotspot IP or expired leaf needs one online renewal. Root rotation requires phone trust again.
Legacy per-laptop roots require online migration, rather than silent reuse after upgrading.
Students can install the common profile from their central dashboard before coming to class.

Implementation: show the detected eligible meeting (current class preferred over a previous
class's grace period). Faculty only chooses between genuinely overlapping eligible meetings.
Start opens a dialog and probes support automatically. Its primary action prepares an owned
hotspot, discovers its real adapter address, reuses or creates matching TLS material and
starts local services. No manual IP/certificate-path/probe/listener controls in the normal flow.

First use requires the phone's own certificate installation/trust and camera check. The app
cannot grant iOS trust remotely. A hotspot-only HTTP setup page serves only public CA/profile
downloads and instructions, never attendance, credentials or images; the camera stays HTTPS.
First-use setup precedes the five-minute timer. A clearly labelled faculty confirmation enables
the same dialog's Start attendance action. Later starts reuse that CA and its recorded faculty
attestation. New phones can reopen the setup instructions. No browser-security bypass.

Connection display separates Wi-Fi QR (password underneath), first-time phone setup and the
live attendance QR. QR widgets fit their available square and a large presentation dialog
keeps the entire quiet border visible. Normal controls use readable colours and fewer actions.
At timeout or manual close, local intake and the app-owned hotspot stop; saved roster/review,
approval and durable outbox remain available. Privacy lock/shutdown also clean up late starts.

Plan: failing tests for detected period/priority, setup-only HTTP boundaries, certificate reuse,
setup failure cleanup/cancellation, no timer before readiness, auto-stop, QR fit and default
control visibility; implement shared runtime/workflow/UI; full backend/frontend/packaging
verification; scoped review; deploy only V2; keep faculty profile/unsynced records and V1.
