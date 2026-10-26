param([int]$Port = 8765, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) {
    throw '请先运行 scripts/bootstrap.ps1 安装项目环境。'
}
$env:TEMP = "$taskRoot\.tmp"
$env:TMP = "$taskRoot\.tmp"
$env:PLAYWRIGHT_BROWSERS_PATH = "$taskRoot\.cache\browsers"
$env:PYTHONIOENCODING = 'utf-8'
$env:YZ_PORT = "$Port"
$taskUrl = "http://127.0.0.1:$Port"
$taskReady = $false
try {
    $taskHealth = Invoke-RestMethod "$taskUrl/api/health" -TimeoutSec 2
    $taskReady = $taskHealth.status -eq 'ok' -and $taskHealth.scope -eq 'local_reimbursement_and_todomvc'
} catch {}
if (-not $taskReady) {
    if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
        throw "端口 $Port 已被其他服务占用。请使用 -Port 8766。"
    }
    $taskLogs = Join-Path $taskRoot '.artifacts'
    New-Item -ItemType Directory -Force -Path $taskLogs | Out-Null
    Start-Process -FilePath $taskPython -ArgumentList @('-m', 'yanzhen', 'serve', '--port', "$Port") -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput "$taskLogs\demo-server.out.log" -RedirectStandardError "$taskLogs\demo-server.err.log" | Out-Null
    for ($taskAttempt = 0; $taskAttempt -lt 30; $taskAttempt++) {
        Start-Sleep -Milliseconds 350
        try {
            $taskHealth = Invoke-RestMethod "$taskUrl/api/health" -TimeoutSec 1
            if ($taskHealth.status -eq 'ok' -and $taskHealth.scope -eq 'local_reimbursement_and_todomvc') {
                $taskReady = $true
                break
            }
        } catch {}
    }
}
if (-not $taskReady) { throw '演示服务启动失败，请查看 .artifacts/demo-server.err.log。' }
if (-not $NoBrowser) { Start-Process "$taskUrl/#showcase" }
Write-Host "演示已打开：$taskUrl/#showcase"
Write-Host '点击“开始真实演示”，即可观看从需求到修复验证的完整流程。'
