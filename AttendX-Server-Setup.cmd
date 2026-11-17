<# : AttendX central server setup (batch launcher + PowerShell). Double-click to run.
@echo off
setlocal
set "ATTENDX_SETUP_FILE=%~f0"
powershell -NoProfile -ExecutionPolicy Bypass -Command "& ([ScriptBlock]::Create([IO.File]::ReadAllText($env:ATTENDX_SETUP_FILE))) %*"
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
#>
# ---------------------------------------------------------------------------------------------
# AttendX V2 central server setup for a fresh Windows 10/11 laptop. One file does everything:
#   Git, Python, WSL 2, Docker Desktop and (optionally) Tailscale  ->  clone AttendX  ->  models
#   ->  .env.v2  ->  build and start the server (GPU or CPU)  ->  first admin  ->  Tailscale Funnel.
# The faculty Windows app is separate: download it from the GitHub release.
# Safe to run again: finished steps are skipped. Continues automatically after a required restart.
# Options: -RepoDir <path>  -Port <funnel https port>  -NoTailscale  -DryRun  -Yes
# ---------------------------------------------------------------------------------------------
param(
    [string]$RepoDir = "C:\AttendX",
    [int]$Port = 10000,
    [switch]$NoTailscale,
    [switch]$DryRun,
    [switch]$Yes,
    [switch]$Resumed
)
# Cmdlet errors stop the script; native tools (py, docker, wsl, winget) report through
# $LASTEXITCODE instead, because Windows PowerShell 5.1 turns their stderr text into errors.
$ErrorActionPreference = "Continue"
$PSDefaultParameterValues["*:ErrorAction"] = "Stop"
$ProgressPreference = "SilentlyContinue"
$RepoUrl = "https://github.com/MeezaUni/AttendX"
$StateDir = Join-Path $env:ProgramData "AttendXSetup"
$StateFile = Join-Path $StateDir "state.json"
$SelfFile = $env:ATTENDX_SETUP_FILE
$DockerExe = "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe"

function Say($msg, $color = "Cyan") { Write-Host ""; Write-Host "==> $msg" -ForegroundColor $color }
function Info($msg) { Write-Host "    $msg" }
function Warn($msg) { Write-Host "    ! $msg" -ForegroundColor Yellow }
function Fail($msg) { Write-Host ""; Write-Host "SETUP STOPPED: $msg" -ForegroundColor Red; exit 1 }
function Ask($q, $default = "y") {
    if ($Yes) { return $true }
    $a = Read-Host "    $q [$(if ($default -eq 'y') {'Y/n'} else {'y/N'})]"
    if ([string]::IsNullOrWhiteSpace($a)) { $a = $default }
    return $a.Trim().ToLower().StartsWith("y")
}
function Run($desc, [scriptblock]$action) {
    if ($DryRun) { Info "[dry run] would: $desc"; return }
    Info $desc; & $action
}
function Have($cmd) { [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }
function Refresh-Path {
    $m = [Environment]::GetEnvironmentVariable("Path", "Machine"); $u = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$m;$u"
    foreach ($p in @("$env:ProgramFiles\Docker\Docker\resources\bin", "$env:ProgramFiles\Git\cmd", "$env:ProgramFiles\Tailscale")) {
        if ((Test-Path $p) -and ($env:Path -notlike "*$p*")) { $env:Path += ";$p" }
    }
}
function Resume-After-Restart($why) {
    if (-not $DryRun) {
        New-Item -ItemType Directory -Force $StateDir | Out-Null
        @{ repoDir = $RepoDir; port = $Port; noTailscale = [bool]$NoTailscale } | ConvertTo-Json | Set-Content -Encoding utf8 $StateFile
        if ($SelfFile) {
            Set-ItemProperty "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce" -Name "AttendXServerSetup" -Value "cmd /c `"`"$SelfFile`" -Resumed`""
        }
    }
    Say "$why Windows needs a restart. Setup continues automatically after you sign in again." "Yellow"
    if (Ask "Restart now?" "y") { if (-not $DryRun) { Restart-Computer -Force } }
    exit 0
}
function Has-NvidiaGpu {
    if (Have "nvidia-smi") { & nvidia-smi -L 2>$null | Out-Null; return ($LASTEXITCODE -eq 0) }
    return [bool](Get-CimInstance Win32_VideoController | Where-Object { $_.Name -like "*NVIDIA*" })
}
function Find-Python {
    # Any Python 3.9+ can run scripts\fetch_models.py (standard library only).
    foreach ($c in @(@("py", "-3.12"), @("py", "-3"), @("python"))) {
        if (-not (Have $c[0])) { continue }
        $exe = $c[0]; $pre = @($c | Select-Object -Skip 1)
        $v = & $exe @pre -c "import sys; print(int(sys.version_info >= (3, 9)))" 2>$null
        if ($LASTEXITCODE -eq 0 -and "$v".Trim() -eq "1") { return ,$c }
    }
    return $null
}
function Winget-Install($id, $name, $probe) {
    Refresh-Path
    if (& $probe) { Info "$name already installed"; return }
    Run "install $name (winget $id)" {
        winget install --id $id -e --silent --accept-package-agreements --accept-source-agreements --disable-interactivity
        if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne -1978335189) { Fail "winget could not install $name (exit $LASTEXITCODE)." }
    }
    Refresh-Path
}
function Docker-Ready { Refresh-Path; if (-not (Have "docker")) { return $false }; & docker info *> $null; return ($LASTEXITCODE -eq 0) }

# ------------------------------------------------------------------ resume and elevation
if ($Resumed -and (Test-Path $StateFile)) {
    $st = Get-Content $StateFile -Raw | ConvertFrom-Json
    $RepoDir = $st.repoDir; $Port = [int]$st.port; if ($st.noTailscale) { $NoTailscale = [switch]$true }
}
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin -and -not $DryRun) {
    if (-not $SelfFile) { Fail "Run AttendX-Server-Setup.cmd by double-clicking it." }
    Write-Host "Requesting administrator rights (needed to install Docker, WSL and Tailscale)..."
    $argList = @()
    foreach ($k in $PSBoundParameters.Keys) {
        $v = $PSBoundParameters[$k]
        if ($v -is [switch]) { if ($v) { $argList += "-$k" } } else { $argList += "-$k"; $argList += "`"$v`"" }
    }
    Start-Process -FilePath $SelfFile -ArgumentList $argList -Verb RunAs
    Write-Host "Setup continues in the new administrator window."
    exit 0
}

Write-Host ""
Write-Host "  AttendX V2 - central server setup" -ForegroundColor White
Write-Host "  ---------------------------------"
$gpu = Has-NvidiaGpu
Info "Install folder: $RepoDir   NVIDIA GPU: $(if ($gpu) {'yes'} else {'no (CPU mode)'})   $(if ($DryRun) {'DRY RUN - nothing will change'})"
if ($Resumed) { Info "Continuing after restart." }
else {
    Write-Host ""
    Write-Host "  This installs Git, Python, WSL 2, Docker Desktop and optionally Tailscale, then the AttendX"
    Write-Host "  server and its models (models are licensed for non-commercial research use only)."
    Write-Host "  Running it accepts those licences. Docker Desktop is free for personal and education use."
    if (-not (Ask "Continue?" "y")) { exit 0 }
}
if (-not (Have "winget")) { Fail "winget is missing. Install 'App Installer' from the Microsoft Store, then run this again." }

# ------------------------------------------------------------------ 1. prerequisites
Say "1/6  Prerequisites"
Winget-Install "Git.Git" "Git" { Have "git" }
Winget-Install "Python.Python.3.12" "Python" { [bool](Find-Python) }
& wsl.exe --status *> $null
if ($LASTEXITCODE -ne 0) {
    Run "enable WSL 2 (needed by Docker Desktop)" { & wsl.exe --install --no-distribution }
    Resume-After-Restart "WSL 2 was enabled."
}
else { Info "WSL 2 already enabled" }
if (-not (Test-Path $DockerExe)) {
    Winget-Install "Docker.DockerDesktop" "Docker Desktop" { Test-Path $DockerExe }
    if (-not $DryRun) {
        & net localgroup docker-users "$env:USERDOMAIN\$env:USERNAME" /add *> $null
        Resume-After-Restart "Docker Desktop was installed."
    }
}
else { Info "Docker Desktop already installed" }
$useTs = $false
if (-not $NoTailscale) {
    if ((Have "tailscale") -or (Test-Path "$env:ProgramFiles\Tailscale\tailscale.exe")) {
        Info "Tailscale already installed"; $useTs = Ask "Publish the portal on the internet with Tailscale Funnel?" "y"
    }
    elseif (Ask "Install Tailscale so phones can reach the portal over the internet?" "y") {
        Winget-Install "Tailscale.Tailscale" "Tailscale" { (Have "tailscale") -or (Test-Path "$env:ProgramFiles\Tailscale\tailscale.exe") }
        $useTs = $true
    }
}

# ------------------------------------------------------------------ 2. docker
Say "2/6  Docker"
if (-not (Docker-Ready)) {
    Run "start Docker Desktop and wait (accept Docker's agreement in its window if it appears)" {
        Start-Process explorer.exe -ArgumentList "`"$DockerExe`""
        $deadline = (Get-Date).AddMinutes(8)
        while (-not (Docker-Ready)) {
            if ((Get-Date) -gt $deadline) { Fail "Docker did not start. Open Docker Desktop, finish its first-run screens, then run setup again." }
            Start-Sleep 5
        }
    }
}
Info "Docker is running"

# ------------------------------------------------------------------ 3. source and models
Say "3/6  AttendX source and models"
if (Test-Path (Join-Path $RepoDir ".git")) { Run "update $RepoDir (git pull)" { & git -C $RepoDir pull --ff-only } }
else { Run "clone $RepoUrl into $RepoDir" { & git clone "$RepoUrl.git" $RepoDir; if ($LASTEXITCODE -ne 0) { Fail "git clone failed." } } }
Run "download and verify the models (about 270 MB)" {
    $py = Find-Python; if (-not $py) { Fail "Python was not found after installation. Sign out and in, then run setup again." }
    $pre = @($py | Select-Object -Skip 1)
    & $py[0] @pre (Join-Path $RepoDir "scripts\fetch_models.py") --dest (Join-Path $RepoDir "models")
    if ($LASTEXITCODE -ne 0) { Fail "Model download failed." }
}

# ------------------------------------------------------------------ 4. tailscale sign-in
$tsHost = ""
if ($useTs) {
    Say "4/6  Tailscale"
    Refresh-Path
    Run "sign in to Tailscale (a browser window opens - sign in there)" { & tailscale up; if ($LASTEXITCODE -ne 0) { Fail "Tailscale sign-in did not complete." } }
    if (-not $DryRun) { try { $tsHost = ((& tailscale status --json | ConvertFrom-Json).Self.DNSName).TrimEnd(".") } catch { $tsHost = "" } }
}
else { Say "4/6  Tailscale (skipped)" }
$defaultUrl = if ($tsHost) { "https://${tsHost}:$Port" } elseif ($useTs) { "https://YOUR-LAPTOP.YOUR-TAILNET.ts.net:$Port" } else { "https://localhost:8480" }

# ------------------------------------------------------------------ 5. central server
Say "5/6  Central server"
$compose = @("--env-file", ".env.v2", "-f", "docker-compose.v2.yml")
if (-not $gpu) { $compose += @("-f", "docker-compose.v2.cpu.yml") }
$portalUrl = $defaultUrl
if ($DryRun -and -not (Test-Path $RepoDir)) {
    Info "[dry run] would: write .env.v2 ($portalUrl), docker compose up -d --build, create the first admin"
}
else {
    Push-Location $RepoDir
    try {
        if (-not (Test-Path ".env.v2")) {
            if (-not $Yes) { $r = Read-Host "    Portal URL students will use [$defaultUrl]"; if ($r) { $portalUrl = $r } }
            $domain = "example.edu"
            if (-not $Yes) { $r = Read-Host "    University email domain [example.edu]"; if ($r) { $domain = $r } }
            Run "write .env.v2" {
                "ATTENDX_V2_PORTAL_URL=$portalUrl", "ATTENDX_UNIVERSITY_EMAIL_DOMAIN=$domain",
                "ATTENDX_TORCH_VARIANT=$(if ($gpu) {'cu128'} else {'cpu'})" | Set-Content -Encoding ascii ".env.v2"
            }
        }
        else {
            Info ".env.v2 already exists (kept)"
            $line = Get-Content ".env.v2" | Where-Object { $_ -like "ATTENDX_V2_PORTAL_URL=*" } | Select-Object -First 1
            if ($line) { $portalUrl = $line.Substring("ATTENDX_V2_PORTAL_URL=".Length) }
        }
        Run "build and start the server (the first build takes several minutes)" {
            & docker compose @compose up -d --build
            if ($LASTEXITCODE -ne 0) { Fail "docker compose failed." }
        }
        if (-not $DryRun) {
            $h = $null
            for ($i = 0; $i -lt 60; $i++) {
                try { $h = Invoke-RestMethod http://127.0.0.1:8480/api/health -TimeoutSec 5; if ($h.status -eq "ok") { break } } catch { }
                Start-Sleep 5
            }
            if (-not $h -or $h.status -ne "ok") { Fail "The server did not become healthy. Check: docker compose $($compose -join ' ') logs central" }
            Info "Server healthy: http://127.0.0.1:8480 (face engine on $($h.face_engine.device))"
            if (-not $h.admin_configured) {
                Say "Create the first administrator" "Yellow"
                $u = Read-Host "    Admin username [admin]"; if (-not $u) { $u = "admin" }
                Info "Type the password at the prompts (8+ characters, letters plus numbers or symbols)."
                do {
                    & docker compose @compose exec central attendx create-admin --username $u
                    $ok = $LASTEXITCODE -eq 0
                    if (-not $ok) { Warn "That did not work (see the message above). Try again." }
                } until ($ok)
            }
            else { Info "An administrator already exists" }
        }
    }
    finally { Pop-Location }
}

# ------------------------------------------------------------------ 6. publish
Say "6/6  Publish the portal"
if ($useTs) {
    $status = if ($DryRun) { "" } else { (& tailscale serve status 2>$null) -join "`n" }
    if ($status -match "(?m):$Port\b[^\n]*\n\|--\s*/\s*proxy\s+http://127\.0\.0\.1:8480") { Info "Already published on port $Port" }
    elseif ($status -match ":$Port\b") { Warn "Tailscale port $Port is used by something else. Rerun with -Port 8443 (or 443) and update .env.v2." }
    else {
        Run "tailscale funnel --bg --https=$Port http://127.0.0.1:8480" {
            & tailscale funnel --bg --https=$Port http://127.0.0.1:8480
            if ($LASTEXITCODE -ne 0) { Warn "Funnel was not enabled. If Tailscale printed a link, open it to allow Funnel for this tailnet, then run setup again." }
        }
    }
}
else { Info "Skipped (portal stays on this laptop only)" }

if (-not $DryRun -and (Test-Path $StateFile)) { Remove-Item $StateFile -Force }
Say "Done" "Green"
Info "Portal on this laptop:   http://127.0.0.1:8480"
Info "Portal for students:     $portalUrl"
Info "Test email inbox:        http://127.0.0.1:8026"
Info "Faculty app:             download it from $RepoUrl/releases (separate install)"
Info "Keep this laptop awake with Docker running while people use the portal."
