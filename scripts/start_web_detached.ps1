param(
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 8080
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonExe = Join-Path $projectRoot ".venv\Scripts\python.exe"
$logDir = Join-Path $projectRoot "outputs\web"
$stdoutLog = Join-Path $logDir "uvicorn_stdout.log"
$stderrLog = Join-Path $logDir "uvicorn_stderr.log"

if (-not (Test-Path $pythonExe)) {
    throw "Missing venv Python at $pythonExe"
}

New-Item -ItemType Directory -Path $logDir -Force | Out-Null

# Clear any existing listener on the selected port.
$existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if ($existing) {
    $existing | Select-Object -ExpandProperty OwningProcess -Unique | ForEach-Object {
        if ($_ -gt 4) {
            Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue
        }
    }
}

$args = @(
    "-m", "uvicorn",
    "web.app:app",
    "--host", $HostAddress,
    "--port", "$Port"
)

$proc = Start-Process -FilePath $pythonExe `
    -ArgumentList $args `
    -WorkingDirectory $projectRoot `
    -RedirectStandardOutput $stdoutLog `
    -RedirectStandardError $stderrLog `
    -PassThru

Write-Host "Started web server PID=$($proc.Id) at http://$HostAddress`:$Port"
Write-Host "Logs:"
Write-Host "  $stdoutLog"
Write-Host "  $stderrLog"
