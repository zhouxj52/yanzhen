$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
New-Item -ItemType Directory -Force -Path "$taskRoot\.cache\uv", "$taskRoot\.tmp", "$taskRoot\.cache\browsers" | Out-Null
$env:UV_CACHE_DIR = "$taskRoot\.cache\uv"
$env:UV_PYTHON_INSTALL_DIR = "$taskRoot\.cache\python"
$env:PIP_CACHE_DIR = "$taskRoot\.cache\pip"
$env:PLAYWRIGHT_BROWSERS_PATH = "$taskRoot\.cache\browsers"
$env:TEMP = "$taskRoot\.tmp"
$env:TMP = "$taskRoot\.tmp"
if (-not (Test-Path -LiteralPath "$taskRoot\.venv\Scripts\python.exe")) {
    uv venv --python 3.13 "$taskRoot\.venv"
    if ($LASTEXITCODE -ne 0) { throw '创建虚拟环境失败' }
}
uv pip sync --python "$taskRoot\.venv\Scripts\python.exe" "$taskRoot\requirements.lock"
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败' }
uv pip install --no-deps --python "$taskRoot\.venv\Scripts\python.exe" --editable "$taskRoot"
if ($LASTEXITCODE -ne 0) { throw '项目安装失败' }
& "$taskRoot\.venv\Scripts\python.exe" -m playwright install chromium
if ($LASTEXITCODE -ne 0) { throw '浏览器安装失败；接口模式仍可通过 --api-only 使用' }
Write-Host '安装完成。运行 .\scripts\start.ps1 打开 http://127.0.0.1:8765'
