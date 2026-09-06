param([switch]$Local, [int]$Port = 8021)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
while (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue) {
    $Port++
    if ($Port -gt 8099) { throw "No free local demo port in the supported range." }
}
if ($Local) {
    if (!(Test-Path ".venv/Scripts/python.exe")) {
        python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Virtual environment creation failed." }
    }
    if (!(Test-Path ".venv/Scripts/uv.exe")) {
        & ./.venv/Scripts/python.exe -m pip install uv==0.12.10
        if ($LASTEXITCODE -ne 0) { throw "uv installation failed." }
    }
    & ./.venv/Scripts/uv.exe sync --frozen
    if ($LASTEXITCODE -ne 0) { throw "Dependency synchronization failed." }
    $env:WEB_PORT = "$Port"
    $env:GITHUB_MODE = "mock"
    $env:MCP_URL = ""
    New-Item -ItemType Directory -Force "artifacts/local" | Out-Null
    $process = Start-Process -FilePath (Resolve-Path ".venv/Scripts/python.exe") `
        -ArgumentList @("-m", "issue_agent.api") -WorkingDirectory (Get-Location) `
        -WindowStyle Hidden -PassThru -RedirectStandardOutput "artifacts/local/web.stdout.log" `
        -RedirectStandardError "artifacts/local/web.stderr.log"
    Write-Output "Local process ID: $($process.Id)"
} else {
    $env:DEMO_PORT = "$Port"
    docker compose up -d --build --wait
    if ($LASTEXITCODE -ne 0) { throw "Docker Compose startup failed." }
}
Write-Output "http://127.0.0.1:$Port"
