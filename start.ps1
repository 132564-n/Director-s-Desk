$ErrorActionPreference = "Stop"

# Windows PowerShell 5 can fail in Start-Process when a parent environment
# contains both Path and PATH. Recreate the process-level entry once.
$processPath = $env:Path
Remove-Item Env:PATH -ErrorAction SilentlyContinue
$env:Path = $processPath

$projectRoot = $PSScriptRoot
$pythonPath = Join-Path $projectRoot ".venv\Scripts\python.exe"
$webRoot = Join-Path $projectRoot "web"
$logRoot = Join-Path $projectRoot "data\logs"

if (-not (Test-Path -LiteralPath $pythonPath)) {
    throw "Python virtual environment was not found. See README.md."
}
if (-not (Test-Path -LiteralPath (Join-Path $webRoot ".next"))) {
    throw "Frontend production build was not found. Run npm run build in web."
}

New-Item -ItemType Directory -Path $logRoot -Force | Out-Null

function Test-Endpoint([string] $uri) {
    try {
        $response = Invoke-WebRequest -Uri $uri -UseBasicParsing -TimeoutSec 2
        return $response.StatusCode -eq 200
    }
    catch {
        return $false
    }
}

if (-not (Test-Endpoint "http://127.0.0.1:8000/health")) {
    Start-Process `
        -FilePath $pythonPath `
        -ArgumentList @("-m", "uvicorn", "server.director_workbench.api:app", "--host", "127.0.0.1", "--port", "8000") `
        -WorkingDirectory $projectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logRoot "api.out.log") `
        -RedirectStandardError (Join-Path $logRoot "api.err.log")
}

if (-not (Test-Endpoint "http://127.0.0.1:3000")) {
    $npmPath = (Get-Command npm.cmd).Source
    $env:NEXT_TELEMETRY_DISABLED = "1"
    Start-Process `
        -FilePath $npmPath `
        -ArgumentList @("run", "start", "--", "-p", "3000") `
        -WorkingDirectory $webRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logRoot "web.out.log") `
        -RedirectStandardError (Join-Path $logRoot "web.err.log")
}

for ($attempt = 0; $attempt -lt 20; $attempt++) {
    if ((Test-Endpoint "http://127.0.0.1:8000/health") -and (Test-Endpoint "http://127.0.0.1:3000")) {
        Write-Output "AI Director Workbench is running: http://127.0.0.1:3000"
        exit 0
    }
    Start-Sleep -Milliseconds 500
}

throw "Services did not start in time. Check data\logs."
