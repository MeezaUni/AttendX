<#
.SYNOPSIS
  AttendX helper for Windows: Docker lifecycle and Tailscale Serve (tailnet-only HTTPS).
.EXAMPLE
  .\scripts\attendx.ps1 up          # build (if needed) and start the container
  .\scripts\attendx.ps1 serve       # expose https://<machine>.<tailnet>.ts.net:8443 to the tailnet
  .\scripts\attendx.ps1 status      # container, health and Tailscale Serve status
  .\scripts\attendx.ps1 create-admin admin
#>
param(
  [Parameter(Position = 0)][ValidateSet("up", "up-cpu", "down", "restart", "logs", "status", "serve", "unserve", "create-admin", "seed-demo", "backup")]
  [string]$Command = "status",
  [Parameter(Position = 1)][string]$Arg = ""
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (($Command -in @("up", "up-cpu")) -and (Test-Path (Join-Path $Root "docker-compose.v2.yml"))) {
  throw "This V2 checkout must not rebuild the V1 container/volume. Use docker compose --env-file .env.v2 -f docker-compose.v2.yml up -d --build. Check out the V1 rollback branch before rebuilding V1."
}
$Port = if ($env:ATTENDX_PORT) { $env:ATTENDX_PORT } else { "8470" }
$HttpsPort = if ($env:ATTENDX_HTTPS_PORT) { $env:ATTENDX_HTTPS_PORT } else { "8443" }
Push-Location $Root
try {
  switch ($Command) {
    "up"      { docker compose up -d --build }
    "up-cpu"  { docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d --build }
    "down"    { docker compose down }
    "restart" { docker compose restart attendx }
    "logs"    { docker compose logs -f --tail 200 attendx }
    "status"  {
      docker compose ps
      try { (Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$Port/api/health" -TimeoutSec 5).Content } catch { Write-Warning "health check failed: $_" }
      tailscale serve status
    }
    # Serve only (NOT Funnel): reachable from devices on your tailnet, never from the internet.
    "serve"   { tailscale serve --bg --https=$HttpsPort "http://127.0.0.1:$Port"; tailscale serve status }
    "unserve" { tailscale serve --https=$HttpsPort off; tailscale serve status }
    "create-admin" {
      if (-not $Arg) { throw "usage: attendx.ps1 create-admin <username>" }
      docker compose exec attendx attendx create-admin --username $Arg
    }
    "seed-demo" { docker compose exec -e ATTENDX_DEMO_MODE=true attendx attendx seed-demo }
    "backup" {
      $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
      New-Item -ItemType Directory -Force "$Root\backups" | Out-Null
      docker run --rm -v attendx-data:/data:ro -v "${Root}\backups:/backup" python:3.12-slim `
        python -c "import sqlite3,shutil; s=sqlite3.connect('/data/attendx.db'); d=sqlite3.connect('/backup/attendx-$stamp.db'); s.backup(d); d.close(); shutil.copy('/data/template.key','/backup/template-$stamp.key')"
      Write-Host "Backup written to backups\ (contains biometric templates and their key: keep it private)"
    }
  }
} finally { Pop-Location }
