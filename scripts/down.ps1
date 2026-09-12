Set-Location (Join-Path $PSScriptRoot '..')
docker compose down @args
exit $LASTEXITCODE
