# Usage: cd frontend; powershell -ExecutionPolicy Bypass -File .\fix-deps.ps1
Set-Location -LiteralPath $PSScriptRoot

$nodeSrc = (Get-Command node -ErrorAction SilentlyContinue).Source
Write-Host ('Node: ' + $nodeSrc)
& node -v

npm config set cache (Join-Path $PSScriptRoot '.npm-cache') --location=project

Remove-Item -Recurse -Force (Join-Path $PSScriptRoot 'node_modules\.vite') -ErrorAction SilentlyContinue

Write-Host 'npm install...'
& npm install
if ($LASTEXITCODE -ne 0) {
    Write-Host 'ERROR: npm install failed'
    exit 1
}

# npm rebuild on npm 11 may throw ERR_INVALID_ARG_TYPE; skip if install OK
Write-Host 'skip npm rebuild (optional, often fails on npm 11)'

& node (Join-Path $PSScriptRoot 'scripts\check-dev.cjs')
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

Write-Host ''
Write-Host 'OK. Next: npm run dev'
Write-Host 'Or:  powershell -ExecutionPolicy Bypass -File .\start-dev.ps1'
