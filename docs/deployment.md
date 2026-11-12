# Deployment: Windows + Docker + Tailscale Serve

Target: a Windows 10/11 laptop runs AttendX; phones on the same **tailnet** open it over HTTPS.
Nothing is exposed to the public internet.

```
phone ──HTTPS──▶ https://<machine>.<tailnet>.ts.net:8443  (Tailscale Serve, tailnet only)
                 └─▶ http://127.0.0.1:8470  (Docker port, loopback only) ─▶ container :8000
```

## Verified on the development laptop (2026-11-03)

| Item | Result |
|---|---|
| Docker Desktop 29.8 (WSL2), Compose v5.6 | OK; dedicated project `attendx`, container `attendx`, volume `attendx-data` |
| GPU passthrough | `docker run --gpus all … nvidia-smi` sees the RTX 4060; the container's AdaFace runs on `cuda` |
| Image | `attendx:local`, 4.45 GB (CUDA torch); contains **no** database, key or model files (checked) |
| Health over HTTPS | `https://YOUR-LAPTOP.YOUR-TAILNET.ts.net:8443/api/health` → 200, valid certificate, all three models loaded |
| Cookies over HTTPS | `attendx_session`: Secure, HttpOnly, SameSite=Strict |
| Browser camera on the HTTPS origin | Desktop Chromium (fake camera): secure context, `getUserMedia` 640×480, MediaPipe guide running |
| Verification path through Tailscale → Docker | Challenge → 30 frames → server liveness: 115 ms round trip |
| Existing Tailscale config | The pre-existing Serve/**Funnel** on port 443 (`→ 127.0.0.1:8000`, another project) was left unchanged; AttendX's 8443 handler is "tailnet only" (`AllowFunnel` lists only `:443`) |
| Phone camera with a real person | **Not verified by the developer. Run the checklist in `demo.md`.** |

## 1. Prerequisites

1. **Docker Desktop** with the WSL2 backend. For GPU: a recent NVIDIA driver on Windows
   (`docker run --rm --gpus all python:3.12-slim nvidia-smi` must list the GPU).
2. **Tailscale** for Windows on the laptop, signed in. In the admin console
   (login.tailscale.com → DNS) enable **MagicDNS** and **HTTPS Certificates**.
3. **Tailscale** app on the phone, signed in to the **same tailnet**.
4. Python 3.12 (only for `scripts/fetch_models.py`; `py -3.12` or uv).

## 2. Install and start

```powershell
cd C:\path\to\AttendX
copy .env.example .env               # timezone, device, demo mode
py -3.12 scripts\fetch_models.py     # ~280 MB into .\models, SHA-256 verified
.\scripts\attendx.ps1 up             # = docker compose up -d --build   (CPU only: up-cpu)
.\scripts\attendx.ps1 status         # container + /api/health + tailscale serve status
.\scripts\attendx.ps1 create-admin admin   # prompts for the password inside the container
```

The first build downloads about 3 GB (CUDA PyTorch). Later builds reuse the cached layers.

## 3. Tailnet-only HTTPS (Tailscale Serve)

```powershell
.\scripts\attendx.ps1 serve
# = tailscale serve --bg --https=8443 http://127.0.0.1:8470
tailscale serve status
```

Expected output includes:

```
https://<machine>.<tailnet>.ts.net:8443 (tailnet only)
|-- / proxy http://127.0.0.1:8470
```

Use the URL shown by Tailscale Serve for your laptop, for example
`https://YOUR-LAPTOP.YOUR-TAILNET.ts.net:8443/`.

* Do **not** run `tailscale funnel` for this port. Funnel would publish AttendX on the internet.
* Port 8443 is used because 443 on this machine already serves another project through Funnel.
  If 443 is free on your machine you may use `--https=443`.
* The Serve configuration persists across reboots. Remove it with `.\scripts\attendx.ps1 unserve`.

Phones must have the Tailscale VPN switched **on**. Without it the hostname does not resolve
and nothing is reachable.

## 4. Everyday operations

| Task | Command |
|---|---|
| Start / update after code changes | `.\scripts\attendx.ps1 up` |
| Stop (data kept) | `.\scripts\attendx.ps1 down` |
| Restart | `.\scripts\attendx.ps1 restart` |
| Logs | `.\scripts\attendx.ps1 logs` |
| Status / health | `.\scripts\attendx.ps1 status` |
| Reset an admin password | `docker compose exec attendx attendx create-admin --username admin --reset` |
| Synthetic demo data | set `ATTENDX_DEMO_MODE=true` in `.env`, `up`, then `.\scripts\attendx.ps1 seed-demo` |
| Backup DB + template key | `.\scripts\attendx.ps1 backup` (writes `backups\`; keep it private) |
| Delete **all** data | `docker compose down; docker volume rm attendx-data` (irreversible) |

## 5. Running natively on Windows (fallback)

Use this if Docker GPU passthrough misbehaves, or for development:

```powershell
cd backend
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe torch --index-url https://download.pytorch.org/whl/cu128
uv pip install --python .venv\Scripts\python.exe -e .
cd ..\frontend; npm ci; npm run build; cd ..\backend
.venv\Scripts\attendx.exe create-admin --username admin
.venv\Scripts\attendx.exe serve --port 8470      # Tailscale Serve config is the same
```

Native mode uses `.\data` (database and key) and `.\models`. Stop the container first, because
both use port 8470.

## 6. Troubleshooting

| Symptom | Fix |
|---|---|
| Phone: "site can't be reached" | Tailscale on the phone is off or on another account/tailnet; check `tailscale status` on the laptop lists the phone. |
| Certificate warning / HTTPS fails | Enable HTTPS Certificates in the Tailscale admin console; run `tailscale cert <machine>.<tailnet>.ts.net` once on the laptop. |
| Camera button shows "needs a secure connection" | Open the `https://…ts.net:8443` address, not an IP or `http://`. |
| "Camera permission was denied" | Android Chrome: lock icon → Permissions → Camera → Allow. iOS: Settings → Safari → Camera → Allow (or aA → Website Settings). |
| Sign-in works on the laptop but not via `http://127.0.0.1:8470` | Expected: cookies are `Secure`. Use the HTTPS address, or set `ATTENDX_COOKIE_SECURE=false` for local HTTP development only. |
| `/api/health` shows a face-engine error | Models missing → run `scripts\fetch_models.py`; `libEGL` errors → rebuild the image; GPU errors → `up-cpu` or `ATTENDX_DEVICE=cpu`. |
| Port 8470 in use | Set `ATTENDX_PORT` in `.env`, run `up`, then `tailscale serve --bg --https=8443 http://127.0.0.1:<port>`. |
| Times look wrong | Check `ATTENDX_TIMEZONE` (IANA name). Attendance windows are evaluated on the server clock only; phone clocks are ignored. |
| "attendance window has closed" during a demo | Admin → *Attendance* → *Open 10 min*, or create an *Extra session*. |
| Verification keeps ABSTAINing | Improve light, remove mask or glasses, re-enroll in the same lighting; then validate thresholds (`thresholds.md`). |
| Health check `unhealthy` in the first minute | Models load at start-up (`start-period` 90 s); wait, then check `logs`. |
