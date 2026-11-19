<# : AttendX - start everything (batch launcher + PowerShell). Double-click to run.
@echo off
setlocal
set "ATTENDX_START_FILE=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& ([ScriptBlock]::Create([IO.File]::ReadAllText($env:ATTENDX_START_FILE))) %*"
set "RC=%ERRORLEVEL%"
for %%A in (%*) do if /I "%%~A"=="-NoPrompt" exit /b %RC%
echo.
pause
exit /b %RC%
#>
# ---------------------------------------------------------------------------------------------
# Starts and checks everything AttendX needs on this laptop, fixing what is down:
#   1. Docker Desktop   2. AttendX central server + test inbox   3. Tailscale connection
#   4. Public portal (Tailscale Funnel on port 10000)   5. outside reachability check
#   6. opens the admin portal and test inbox, and optionally the faculty app.
# Safe to run any time; it only starts what is not already running.
# ---------------------------------------------------------------------------------------------
param([switch]$NoBrowser, [switch]$NoPrompt)
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"
$Repo = Split-Path -Parent (Split-Path -Parent $env:ATTENDX_START_FILE)
$Port = 10000
$Local = "http://127.0.0.1:8480"
$Compose = @("--project-name", "attendx-v2", "--env-file", (Join-Path $Repo ".env.v2"), "-f", (Join-Path $Repo "docker-compose.v2.yml"))
$DockerExe = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"
$ok = @{}

function Step($n, $msg) { Write-Host ""; Write-Host "[$n/6] $msg" -ForegroundColor Cyan }
function Good($msg) { Write-Host "      OK  $msg" -ForegroundColor Green }
function Warn($msg) { Write-Host "      !!  $msg" -ForegroundColor Yellow }
function Info($msg) { Write-Host "          $msg" }
function Docker-Ready { & docker info *> $null; return ($LASTEXITCODE -eq 0) }
function Health {
    try { return Invoke-RestMethod "$Local/api/health" -TimeoutSec 5 } catch { return $null }
}
function Pause-Retry($msg) {
    Write-Host "      $msg" -ForegroundColor Yellow
    if ($NoPrompt) { return $false }
    return ((Read-Host "      Press Enter to retry, or type S to skip") -notmatch "^[sS]")
}

$portalUrl = ""
$envFile = Join-Path $Repo ".env.v2"
if (Test-Path $envFile) {
    $line = Get-Content $envFile | Where-Object { $_ -like "ATTENDX_V2_PORTAL_URL=*" } | Select-Object -First 1
    if ($line) { $portalUrl = $line.Substring("ATTENDX_V2_PORTAL_URL=".Length) }
}
$publicHost = if ($portalUrl) { ([Uri]$portalUrl).Host } else { "" }

Write-Host ""
Write-Host "  Starting AttendX" -ForegroundColor White
Write-Host "  ----------------"
Info "Repository: $Repo"

# ---------------------------------------------------------------- 1. Docker
Step 1 "Docker Desktop"
if (-not (Docker-Ready)) {
    if (-not (Get-Process "Docker Desktop" -ErrorAction SilentlyContinue)) {
        Info "starting Docker Desktop..."
        Start-Process $DockerExe
    }
    Info "waiting for Docker to be ready (up to 4 minutes)..."
    $deadline = (Get-Date).AddMinutes(4)
    while (-not (Docker-Ready) -and (Get-Date) -lt $deadline) { Start-Sleep 4 }
}
if (Docker-Ready) { Good "Docker is running"; $ok.docker = $true } else { Warn "Docker did not start. Open Docker Desktop and run this again."; exit 1 }

# ---------------------------------------------------------------- 2. AttendX server
Step 2 "AttendX central server and test inbox"
& docker compose @Compose up -d --no-build 2>&1 | ForEach-Object { Info $_.ToString().Trim() }
if ($LASTEXITCODE -ne 0) {
    Warn "AttendX containers could not start. Check Docker Desktop and the messages above, then run this again."
    exit 1
}
Info "waiting for the server and face models to load..."
$h = $null
for ($i = 0; $i -lt 60 -and -not ($h -and $h.status -eq "ok"); $i++) { $h = Health; if (-not ($h -and $h.status -eq "ok")) { Start-Sleep 3 } }
if ($h -and $h.status -eq "ok") {
    Good "server healthy on $Local (face models on $($h.face_engine.device))"; $ok.server = $true
} else {
    Warn "server is not healthy. Logs: docker compose --env-file .env.v2 -f docker-compose.v2.yml logs central"
}

# ---------------------------------------------------------------- 3. Tailscale
Step 3 "Tailscale connection"
$tsUp = $false
$connectAttempted = $false
while ($true) {
    $state = ""
    try { $ts = & tailscale status --json 2>$null | ConvertFrom-Json; $state = $ts.BackendState } catch { }
    if ($state -eq "Running") {
        $tsUp = $true
        foreach ($message in $ts.Health) { Warn "Tailscale: $message" }
        break
    }
    if ($state -eq "NeedsLogin" -and $NoPrompt) {
        Warn "Tailscale needs sign-in. Open the Tailscale app and sign in, then run this again."
        break
    }
    if ($state -in @("Stopped", "NeedsLogin") -and -not $connectAttempted) {
        $connectAttempted = $true
        Info "connecting Tailscale (sign in if a login link appears)..."
        & tailscale up --timeout=20s
        continue
    }
    $reach = $false
    try { $null = Invoke-WebRequest "https://controlplane.tailscale.com/key?v=148" -UseBasicParsing -TimeoutSec 8; $reach = $true } catch { }
    if (-not $reach) {
        if (-not (Pause-Retry "Cannot reach Tailscale (college Wi-Fi may block it). Turn on NekoBox TUN mode, or connect the laptop to a phone hotspot / USB tethering.")) { break }
    } elseif (-not (Pause-Retry "Tailscale is starting or disconnected (state: $state). Open the Tailscale app and make sure it is connected.")) { break }
    $connectAttempted = $false
}
if ($tsUp) { Good "Tailscale connected"; $ok.tailscale = $true } else { Warn "Tailscale is not connected; the public portal will not work until it is." }

# ---------------------------------------------------------------- 4. Funnel
Step 4 "Public portal (Tailscale Funnel on port $Port)"
if ($tsUp) {
    $config = $null
    try {
        $rawConfig = & tailscale serve status --json 2>$null
        if ($LASTEXITCODE -eq 0) { $config = $rawConfig | ConvertFrom-Json -ErrorAction Stop }
    } catch { }
    $web = @($config.Web.PSObject.Properties | Where-Object { $_.Name -match ":${Port}$" })
    $published = @($web | Where-Object {
        $_.Value.Handlers.'/'.Proxy -eq $Local -and $config.AllowFunnel.PSObject.Properties[$_.Name].Value
    })
    if (-not $config) {
        Warn "could not read Tailscale's port configuration; leaving all routes unchanged."
    } elseif ($published.Count -gt 0) {
        Good "published: $portalUrl"; $ok.funnel = $true
    } elseif ($config.TCP.PSObject.Properties.Name -contains "$Port" -or $web.Count -gt 0) {
        Warn "port $Port is used by something else in Tailscale; not changing it."
    } else {
        Info "publishing the portal on port $Port..."
        & tailscale funnel --bg --https=$Port http://127.0.0.1:8480
        if ($LASTEXITCODE -eq 0) { Good "published: $portalUrl"; $ok.funnel = $true } else { Warn "could not publish (if Tailscale printed a link, open it to allow Funnel)." }
    }
} else { Warn "skipped (Tailscale not connected)" }

# ---------------------------------------------------------------- 5. outside check
Step 5 "Checking the portal from outside (the path phones use)"
if ($ok.funnel -and $publicHost -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $check = @"
import http.client, ipaddress, json, socket, ssl, subprocess, sys, time
host, port = sys.argv[1], int(sys.argv[2])
deadline = time.monotonic() + 45
try:
    out = subprocess.run(['nslookup', host, '1.1.1.1'], capture_output=True, text=True, timeout=8).stdout.split()
except (OSError, subprocess.TimeoutExpired):
    print('FAIL'); sys.exit(1)
ips = []
for word in out:
    try:
        ip = ipaddress.IPv4Address(word)
        if ip.is_global and word != '1.1.1.1' and word not in ips: ips.append(word)
    except ipaddress.AddressValueError: pass
for attempt in range(3):
    if not ips or time.monotonic() >= deadline: break
    for ip in ips[:3]:
        remaining = deadline - time.monotonic()
        if remaining <= 0: break
        try:
            with socket.create_connection((ip, port), timeout=min(6, remaining)) as raw:
                with ssl.create_default_context().wrap_socket(raw, server_hostname=host) as s:
                    s.settimeout(max(0.1, min(6, deadline - time.monotonic())))
                    s.sendall(f'GET /api/health HTTP/1.1\r\nHost: {host}:{port}\r\nConnection: close\r\n\r\n'.encode())
                    with http.client.HTTPResponse(s) as response:
                        response.begin()
                        data = response.read(65536)
                        if response.status == 200 and json.loads(data).get('status') == 'ok':
                            print('OK'); sys.exit(0)
        except Exception: pass
    time.sleep(max(0, min(2, deadline - time.monotonic())))
print('FAIL')
sys.exit(1)
"@
    $tmp = [IO.Path]::GetTempFileName()
    try {
        Set-Content -LiteralPath $tmp -Value $check -Encoding ascii
        $result = (& python $tmp $publicHost $Port 2>$null | Select-Object -Last 1)
    } finally { Remove-Item -LiteralPath $tmp -ErrorAction SilentlyContinue }
    if ($result -eq "OK") { Good "reachable from the internet: $portalUrl"; $ok.outside = $true }
    else { Warn "not reachable from outside yet. Wait a minute and run this again; on college Wi-Fi keep NekoBox in TUN mode." }
} elseif (-not $ok.funnel) { Warn "skipped (portal not published)" }
else { Info "skipped (Python not found); open $portalUrl on your phone to check." }

# ---------------------------------------------------------------- 6. open things
Step 6 "Opening AttendX"
if (-not $NoBrowser) {
    Start-Process "$Local/login"
    Start-Process "http://127.0.0.1:8026"
    Good "opened the admin portal and the test email inbox in your browser"
}
$desktop = [Environment]::GetFolderPath("Desktop")
$apps = @(Get-ChildItem $desktop -Filter "AttendX Faculty*.lnk" -ErrorAction SilentlyContinue | Sort-Object Name)
if ($apps -and -not $NoPrompt) {
    Write-Host ""
    Write-Host "      Open a faculty app?"
    for ($i = 0; $i -lt $apps.Count; $i++) { Write-Host "        $($i + 1)) $($apps[$i].BaseName)" }
    $pick = Read-Host "      Number, or Enter to skip"
    if ($pick -match "^\d+$" -and [int]$pick -ge 1 -and [int]$pick -le $apps.Count) {
        if (Get-Process AttendXFaculty -ErrorAction SilentlyContinue) {
            Warn "a faculty app is already running (check the tray). Quit it first to switch profiles."
        } else { Start-Process $apps[[int]$pick - 1].FullName; Good "started $($apps[[int]$pick - 1].BaseName)" }
    }
}

Write-Host ""
Write-Host "  Summary" -ForegroundColor White
foreach ($k in "docker", "server", "tailscale", "funnel", "outside") {
    $label = @{ docker = "Docker"; server = "AttendX server"; tailscale = "Tailscale"; funnel = "Public portal"; outside = "Public health check" }[$k]
    if ($ok[$k]) { Write-Host ("    [OK]   {0}" -f $label) -ForegroundColor Green } else { Write-Host ("    [--]   {0}" -f $label) -ForegroundColor Yellow }
}
Write-Host ""
Info "Admin portal (this laptop): $Local"
Info "Portal for phones:          $portalUrl"
Info "Test email inbox:           http://127.0.0.1:8026"
if ($ok.docker -and $ok.server -and $ok.tailscale -and $ok.funnel -and $ok.outside) { exit 0 }
exit 1
