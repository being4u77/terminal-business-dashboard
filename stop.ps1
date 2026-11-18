$ErrorActionPreference = 'Stop'
$stateFile = Join-Path $PSScriptRoot 'data\server-process.json'
if (-not (Test-Path -LiteralPath $stateFile)) { Write-Host 'No dashboard process record found.'; exit 0 }
$saved = Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
$running = Get-Process -Id $saved.pid -ErrorAction SilentlyContinue
if ($running -and $running.StartTime.ToUniversalTime().Ticks -eq [long]$saved.startTicks) {
  Stop-Process -Id $running.Id
  Write-Host 'Dashboard service stopped.'
} else { Write-Host 'The recorded process is not running; no process was stopped.' }
Remove-Item -LiteralPath $stateFile
