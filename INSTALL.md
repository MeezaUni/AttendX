# Installing AttendX V2 on a new laptop

Step-by-step setup on a fresh Windows 10/11 laptop. For day-to-day operation, classroom
networking and the real-phone procedure, see [Operations](docs/v2/OPERATIONS.md).

AttendX has two parts. You can install both on one laptop or on separate machines:

| Part | What it is | Runs as |
|---|---|---|
| Central server | Admin, coordinator (CC) and student web portal, enrollment and sync | Docker containers |
| Faculty app | Classroom hotspot, rotating QR, face and liveness verification, approval | Windows executable |

## What is not in Git

Git holds only source code and documentation. Bring the following over separately, or recreate
them:

- `.env.v2`: local settings (step 3 creates it).
- `models/`: model weights, about 300 MB (step 2 downloads them).
- `dist/`: the built faculty application, about 4.8 GB (step 4 builds or copies it).
- The Docker volume `attendx-v2-data`: accounts, enrollments, attendance and the encryption key
  (see [Moving existing data](#moving-existing-data)).

Never commit biometric data, databases, keys or model files.

## 1. Install the prerequisites

```powershell
winget install Git.Git Docker.DockerDesktop Python.Python.3.12 OpenJS.NodeJS.LTS astral-sh.uv Tailscale.Tailscale
```

- Restart Windows, open **Docker Desktop** once and wait until it reports that it is running
  (WSL 2 backend).
- **NVIDIA GPU (recommended):** install the current NVIDIA driver. Docker GPU passthrough then
  works through WSL 2.
- **No NVIDIA GPU:** everything runs on the CPU. Use the CPU commands below. This is slower and
  room-scale CPU throughput has not been measured.
- **Tailscale** is needed only to publish the central portal outside the laptop. Phones never
  need Tailscale for classroom attendance.

## 2. Get the code and the models

```powershell
git clone https://github.com/MeezaUni/AttendX.git C:\AttendX
cd C:\AttendX
py -3.12 scripts\fetch_models.py
```

The fetcher uses only the Python standard library. It downloads SCRFD (InsightFace), AdaFace
IR-101 (Hugging Face) and MediaPipe Face Landmarker into `models\` and verifies their pinned
SHA-256 hashes. On a machine without internet access, copy `models\` from another installation,
or run `py -3.12 scripts\fetch_models.py --from-dir <folder>`.

The model weights permit **non-commercial academic use only**. See
[third-party notices](THIRD_PARTY_NOTICES.md).

## 3. Central server

Create the local settings file. Set the URL to the HTTPS address that students and faculty will
use. This address appears in invitation and password-reset emails.

```powershell
@'
ATTENDX_V2_PORTAL_URL=https://localhost:8480
ATTENDX_UNIVERSITY_EMAIL_DOMAIN=example.edu
ATTENDX_TORCH_VARIANT=cu128
'@ | Set-Content -Encoding ascii .env.v2
```

Build and start. The first build takes several minutes.

```powershell
# NVIDIA GPU
docker compose --env-file .env.v2 -f docker-compose.v2.yml up -d --build

# CPU only
docker compose --env-file .env.v2 -f docker-compose.v2.yml -f docker-compose.v2.cpu.yml up -d --build
```

Create the first administrator. You choose the password at the prompt; no credentials are
pre-created.

```powershell
docker compose --env-file .env.v2 -f docker-compose.v2.yml exec central attendx create-admin --username admin
```

Check that it is running:

```powershell
docker compose --env-file .env.v2 -f docker-compose.v2.yml ps
Invoke-RestMethod http://127.0.0.1:8480/api/health
```

| Address | Purpose |
|---|---|
| http://127.0.0.1:8480 | Central portal (bound to this laptop only) |
| http://127.0.0.1:8026 | Mailpit test inbox. Invitation emails land here; nothing is sent externally |

### Optional: reach the portal from phones

Publish only the central portal through a Tailscale Funnel on a free HTTPS port (443, 8443 or
10000). Check `tailscale serve status` first so that you do not replace an existing route, then
set `ATTENDX_V2_PORTAL_URL` in `.env.v2` to the published address and run `up -d` again.

```powershell
tailscale serve status
tailscale funnel --bg --https=10000 http://127.0.0.1:8480
```

Never publish the faculty app's classroom ports (9442/9443) through Tailscale, the campus LAN or
any public endpoint.

### Real email (optional)

Mailpit is a test catcher. Real delivery needs authorized SMTP settings (`ATTENDX_SMTP_HOST`,
`ATTENDX_SMTP_PORT`, `ATTENDX_SMTP_STARTTLS`, `ATTENDX_SMTP_USERNAME`, `ATTENDX_SMTP_PASSWORD`,
`ATTENDX_MAIL_FROM`). Keep secrets out of Git.

## 4. Faculty Windows app

### Option A: download the built app (fastest)

Download every `AttendXFaculty-v2.0.0-win64-cuda.zip.00N` part from the
[v2.0.0 release](https://github.com/MeezaUni/AttendX/releases/tag/v2.0.0) into one folder, then
join and extract them in PowerShell:

```powershell
$name = "AttendXFaculty-v2.0.0-win64-cuda.zip"
$out = [IO.File]::Create("$PWD\$name")
Get-ChildItem "$name.0*" | Sort-Object Name | ForEach-Object { $in = [IO.File]::OpenRead($_.FullName); $in.CopyTo($out); $in.Close() }
$out.Close()
Expand-Archive $name -DestinationPath C:\AttendXFaculty
C:\AttendXFaculty\AttendXFaculty\AttendXFaculty.exe
```

The release zip already contains the `models` folder beside the executable, so no
`--models-dir` is needed. Add `--device cpu` on laptops without an NVIDIA GPU.

Alternatively, copy the **entire** `dist\faculty\AttendXFaculty` folder (including
`_internal\`) and the `models\` folder from an existing installation. Then run:

```powershell
.\dist\faculty\AttendXFaculty\AttendXFaculty.exe --models-dir C:\AttendX\models

# Without an NVIDIA GPU
.\dist\faculty\AttendXFaculty\AttendXFaculty.exe --device cpu --models-dir C:\AttendX\models

# Diagnostic: loads the models and rejects a blank frame (not an accuracy test)
.\dist\faculty\AttendXFaculty\AttendXFaculty.exe --check-models --models-dir C:\AttendX\models
```

### Option B: build from source (Python 3.12)

```powershell
uv venv --python 3.12 backend\.venv
uv pip install --python backend\.venv\Scripts\python.exe -e "backend[dev,desktop]"

# CUDA build of PyTorch (skip on CPU-only laptops; install the CPU wheel instead)
uv pip install --python backend\.venv\Scripts\python.exe torch --index-url https://download.pytorch.org/whl/cu128

cd frontend
npm ci
npm run build
cd ..

backend\.venv\Scripts\python.exe scripts\build_faculty.py
```

The output is `dist\faculty\AttendXFaculty\AttendXFaculty.exe`. The tested package versions are
recorded in `backend\requirements-windows.lock.txt`. You can create a desktop shortcut to the
executable with the `--models-dir` argument above.

### First launch

1. In the central portal (as admin), create sections and courses, the timetable, a faculty
   account and its teaching and CC assignments. See
   [Operations: academic setup](docs/v2/OPERATIONS.md#academic-setup-and-enrollment).
2. In the faculty app's **Sign in & sync** tab, enter the central HTTPS URL, the faculty
   username and password, and a new local PIN or passphrase. Click
   **Provision or reauthorize online** once. This downloads the authorized roster and prepares
   the classroom certificate.
3. After provisioning, classes work offline. Each student phone installs and trusts the AttendX
   classroom certificate once per deployment (from the student portal, or the
   **Phone setup · once** QR).
4. If Windows asks, allow the app on the private network used by the classroom hotspot.

Faculty data is stored in `%LOCALAPPDATA%\AttendXFaculty` and encrypted for the current Windows
user. Do not copy it between users or laptops, and never delete it while approved attendance is
still waiting to sync. Provision fresh on each laptop.

## 5. Verify the installation (optional)

```powershell
cd backend
.venv\Scripts\python.exe -m pytest -q
cd ..\frontend
npm test
cd ..
backend\.venv\Scripts\python.exe scripts\verify_offline_demo.py
```

Expected result on the reference laptop: 199 backend tests passed and 1 skipped (the skipped
test needs a consented real-face folder). The offline demo uses an isolated synthetic process
and touches no deployed data.

## Moving existing data

The central database and its encryption key live together in the Docker volume
`attendx-v2-data`. Always move them together.

```powershell
# Old laptop: stop the server, then back up the volume to the current folder
docker compose --env-file .env.v2 -f docker-compose.v2.yml stop
docker run --rm -v attendx-v2-data:/data -v ${PWD}:/backup alpine tar czf /backup/attendx-v2-data.tgz -C /data .

# New laptop: restore before the first start
docker volume create attendx-v2-data
docker run --rm -v attendx-v2-data:/data -v ${PWD}:/backup alpine tar xzf /backup/attendx-v2-data.tgz -C /data
```

Keep backups private: they contain encrypted biometric templates and account data.

## Stop, start and update

```powershell
docker compose --env-file .env.v2 -f docker-compose.v2.yml stop     # stop (data kept)
docker compose --env-file .env.v2 -f docker-compose.v2.yml start    # start again

git pull
docker compose --env-file .env.v2 -f docker-compose.v2.yml up -d --build   # update central
```

Database migrations run automatically at start-up. Close the faculty app from its tray menu
(**Quit AttendX Faculty**); the window close button only minimizes it.

## Troubleshooting

| Problem | What to do |
|---|---|
| `could not select device driver "nvidia"` | Update the NVIDIA driver and Docker Desktop, or use the CPU compose command |
| Port 8480 or 8026 already in use | Stop the other service, or change the left-hand port in `docker-compose.v2.yml` |
| Model download fails | Check internet access to github.com, huggingface.co and storage.googleapis.com, or copy `models\` manually |
| Faculty app cannot load models | Pass the correct `--models-dir`; add `--device cpu` if CUDA is unavailable |
| Phone shows a certificate warning | Install and fully trust the AttendX classroom profile; do not bypass the warning |
| Invitation link points to the wrong address | Fix `ATTENDX_V2_PORTAL_URL` in `.env.v2`, run `up -d`, then resend the invitation |
