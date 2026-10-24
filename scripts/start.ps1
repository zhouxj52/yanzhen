param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$env:TEMP = "$taskRoot\.tmp"
$env:TMP = "$taskRoot\.tmp"
$env:PLAYWRIGHT_BROWSERS_PATH = "$taskRoot\.cache\browsers"
$env:PYTHONIOENCODING = 'utf-8'
$env:YZ_PORT = "$Port"
& "$taskRoot\.venv\Scripts\python.exe" -m yanzhen serve --port $Port
