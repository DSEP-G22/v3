# Native tools write progress to stderr; with $ErrorActionPreference='Stop' Windows
# PowerShell 5.1 turns that into a terminating error, so rely on $LASTEXITCODE instead.
Set-Location (Join-Path $PSScriptRoot '..')
if (-not (Test-Path .env)) { Write-Error 'no .env: copy .env.example to .env and fill NEON_KEY'; exit 1 }
if (-not (Select-String -Path .env -Pattern '^\s*NEON_KEY\s*=\s*\S' -Quiet)) { Write-Error '.env has no NEON_KEY'; exit 1 }
docker compose up -d --build --wait @args
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host 'Lanka Link v3 is up: http://localhost:8080'
