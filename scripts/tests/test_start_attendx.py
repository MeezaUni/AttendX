import os
from pathlib import Path
import subprocess
import tempfile
import unittest

LAUNCHER = Path(__file__).resolve().parents[1] / 'Start-AttendX.cmd'
HARNESS = r'''
$env:ATTENDX_START_FILE = $env:TEST_ENTRY
$global:state = if ($env:TEST_CASE -eq 'stopped') { 'Stopped' } elseif ($env:TEST_CASE -eq 'login') { 'NeedsLogin' } else { 'Running' }
function Log($s) { Add-Content -LiteralPath $env:TEST_CALLS -Value $s }
function docker {
    Log ('docker ' + ($args -join ' '))
    $global:LASTEXITCODE = if ($env:TEST_CASE -eq 'compose-fails' -and $args[0] -eq 'compose') { 17 } else { 0 }
    if ($global:LASTEXITCODE) { Write-Output 'Error: compose failed' }
}
function tailscale {
    Log ('tailscale ' + ($args -join ' '))
    $global:LASTEXITCODE = 0
    if ($args[0] -eq 'up') { $global:state = 'Running'; return }
    if ($args[0] -eq 'status') { return (@{ BackendState = $global:state; Health = @() } | ConvertTo-Json -Compress) }
    if ($args[0] -eq 'serve') {
        if ($env:TEST_CASE -eq 'bad-config') { $global:LASTEXITCODE = 1; return 'not JSON' }
        $proxy = if ($env:TEST_CASE -eq 'conflict') { 'http://127.0.0.1:9999' } else { 'http://127.0.0.1:8480' }
        if ($args -contains '--json') {
            return (@{TCP=@{'10000'=@{HTTPS=$true}}; Web=@{'mak.tailc1af96.ts.net:10000'=@{Handlers=@{'/'=@{Proxy=$proxy}}}}; AllowFunnel=@{'mak.tailc1af96.ts.net:10000'=$true}} | ConvertTo-Json -Depth 8 -Compress)
        }
        return "https://mak.tailc1af96.ts.net:10000 (Funnel on)`n|-- / proxy $proxy"
    }
    if ($args[0] -eq 'funnel') { throw 'Must not modify Funnel in these scenarios' }
}
function Invoke-RestMethod { return @{status='ok'; face_engine=@{device='cuda'}} }
function Invoke-WebRequest { return @{StatusCode=200} }
function python { $global:LASTEXITCODE=0; 'OK' }
function Start-Sleep { }
function Read-Host { throw 'Unexpected interactive prompt' }
function Start-Process { throw 'Unexpected application launch' }
& ([ScriptBlock]::Create([IO.File]::ReadAllText($env:TEST_LAUNCHER))) -NoBrowser -NoPrompt
'''


@unittest.skipUnless(os.name == 'nt', 'Windows launcher requires Windows PowerShell')
class LauncherTests(unittest.TestCase):
    def run_case(self, case):
        with tempfile.TemporaryDirectory(prefix='attendx-launcher-') as d:
            Path(d, '.env.v2').write_text('ATTENDX_V2_PORTAL_URL=https://mak.tailc1af96.ts.net:10000\n')
            env = dict(
                os.environ, TEST_LAUNCHER=str(LAUNCHER), TEST_CASE=case,
                TEST_CALLS=str(Path(d)/'calls.txt'),
                TEST_ENTRY=str(Path(d)/'scripts'/'Start-AttendX.cmd'),
            )
            result = subprocess.run(['powershell','-NoProfile','-ExecutionPolicy','Bypass','-Command',HARNESS],env=env,capture_output=True,text=True,timeout=20)
            calls = Path(env['TEST_CALLS']).read_text() if Path(env['TEST_CALLS']).exists() else ''
            return result, calls

    def test_stopped_reconnects(self):
        r,c = self.run_case('stopped')
        self.assertIn('tailscale up',c,r.stdout+r.stderr)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    def test_login_no_prompt_reports_failure(self):
        r,c = self.run_case('login')
        self.assertNotIn('tailscale up',c)
        self.assertEqual(r.returncode,1,r.stdout+r.stderr)

    def test_compose_failure_not_hidden_by_old_healthy_server(self):
        r,c = self.run_case('compose-fails')
        self.assertEqual(r.returncode,1,r.stdout+r.stderr)
        self.assertNotIn('OK  server healthy',r.stdout)

    def test_conflicting_funnel_is_untouched_and_fails(self):
        r,c = self.run_case('conflict')
        self.assertNotIn('tailscale funnel',c)
        self.assertEqual(r.returncode,1,r.stdout+r.stderr)

    def test_unreadable_funnel_is_not_overwritten(self):
        r,c = self.run_case('bad-config')
        self.assertNotIn('tailscale funnel',c)
        self.assertEqual(r.returncode,1,r.stdout+r.stderr)

    def test_existing_services_succeed_without_republishing(self):
        r,c = self.run_case('running')
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
        self.assertNotIn('tailscale funnel',c)
        self.assertNotIn('Unexpected',r.stderr)

    def test_batch_preserves_failure_and_no_prompt_skips_pause(self):
        # Stop at Compose so this exercises the real CMD wrapper without touching services.
        with tempfile.TemporaryDirectory(prefix='attendx-launcher-bin-') as d:
            Path(d, 'docker.cmd').write_bytes(
                b'@echo off\r\nif "%~1"=="info" exit /b 0\r\nexit /b 17\r\n'
            )
            env = dict(os.environ, PATH=d + os.pathsep + os.environ['PATH'])
            r = subprocess.run(
                ['cmd', '/d', '/c', str(LAUNCHER), '-NoBrowser', '-NoPrompt'],
                env=env, input='', capture_output=True, text=True, timeout=20,
            )
            self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
            self.assertIn('containers could not start', r.stdout)
            self.assertNotIn('Press any key', r.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
