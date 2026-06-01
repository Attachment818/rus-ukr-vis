# Usage: cd frontend; powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
$ErrorActionPreference = 'Continue'
Set-Location -LiteralPath $PSScriptRoot

$log = Join-Path $PSScriptRoot 'dev-start.log'
Set-Content -Path $log -Value '' -Encoding UTF8

function Write-Log {
    param([string]$Message)
    $line = '[' + (Get-Date -Format 'yyyy-MM-dd HH:mm:ss') + '] ' + $Message
    Write-Host $line
    Add-Content -Path $log -Value $line -Encoding UTF8
}

Write-Log '=== frontend dev server ==='
Write-Log ('PWD: ' + (Get-Location).Path)

$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if (-not $nodeCmd) {
    Write-Log 'ERROR: node not found in PATH'
    Read-Host 'Press Enter to exit'
    exit 1
}
Write-Log ('node: ' + $nodeCmd.Source)
$nodeVer = & node -v 2>&1
Write-Log ('node -v: ' + $nodeVer)

$vitePath = Join-Path $PSScriptRoot 'node_modules\vite\bin\vite.js'
if (-not (Test-Path -LiteralPath $vitePath)) {
    Write-Log 'Running npm install...'
    & npm install
    if ($LASTEXITCODE -ne 0) {
        Write-Log ('ERROR: npm install failed, code=' + $LASTEXITCODE)
        Read-Host 'Press Enter to exit'
        exit 1
    }
}

Write-Log 'Running check-dev.cjs...'
& node (Join-Path $PSScriptRoot 'scripts\check-dev.cjs')
if ($LASTEXITCODE -ne 0) {
    Write-Log ('ERROR: check failed. See log: ' + $log)
    Read-Host 'Press Enter to exit'
    exit 1
}

Write-Log 'Starting Vite http://127.0.0.1:5173/ (Ctrl+C to stop)'
& node (Join-Path $PSScriptRoot 'scripts\dev.cjs')
$code = $LASTEXITCODE
Write-Log ('Vite exited, code=' + $code)
if ($code -ne 0) {
    Write-Log ('Full log: ' + $log)
    Read-Host 'Press Enter to exit'
    exit $code
}
