param(
    [ValidateSet('workbench', 'target', 'swarm')][string]$Component = 'workbench',
    [switch]$WithDemo,
    [switch]$EnableModel,
    [string]$PythonPath = '',
    [int]$Port = 0
)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$taskPython = if ($PythonPath) { $PythonPath } else { Join-Path $taskRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run scripts/bootstrap.ps1 first.' }
$env:TEMP = Join-Path $taskRoot '.tmp'
$env:TMP = $env:TEMP
$env:PYTHONIOENCODING = 'utf-8'
$env:PLAYWRIGHT_BROWSERS_PATH = Join-Path $taskRoot '.cache\browsers'
$env:YZ_ARTIFACTS_DIR = Join-Path $taskRoot '.artifacts\verifyagent-service'
if ($EnableModel) { $env:YZ_ENABLE_MODEL = '1' }
if ($Component -eq 'target') {
    if ($Port -eq 0) { $Port = 8771 }
    & $taskPython -m uvicorn examples.verifyagent.app:app --host 127.0.0.1 --port $Port
} elseif ($Component -eq 'swarm') {
    if ($Port -eq 0) { $Port = 8774 }
    $env:YZ_SWARM_PORT = [string]$Port
    & $taskPython -m yanzhen.verifyagent.swarm_server
} else {
    if ($Port -eq 0) { $Port = 8767 }
    $env:YZ_ARTIFACTS_DIR = Join-Path $taskRoot '.artifacts\verifyagent-service'
    if ($WithDemo) {
        # Public synthetic fixture identities, never production credentials.
        $env:YZ_VERIFY_ALLOWED_ORIGINS = 'http://127.0.0.1:8771'
        $env:YZ_VERIFY_SECRET_ALICE = 'fixture-alice-credential'
        $env:YZ_VERIFY_SECRET_BOB = 'fixture-bob-credential'
        $env:YZ_ENABLE_MODEL = '0'
    }
    if ($EnableModel) { $env:YZ_ENABLE_MODEL = '1' }
    Write-Host "Workbench: http://127.0.0.1:$Port/static/verifyagent.html"
    # Foreground process; Ctrl+C closes it. No detached helpers or hot reload.
    & $taskPython -m yanzhen serve --port $Port
}
exit $LASTEXITCODE
