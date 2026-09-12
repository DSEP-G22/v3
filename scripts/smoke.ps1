$ErrorActionPreference = 'Stop'
$base = if ($env:BASE) { $env:BASE } else { 'http://localhost:8080' }
Invoke-WebRequest -UseBasicParsing "$base/healthz" | Out-Null
Write-Host 'ok  edge /healthz'
