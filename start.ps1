$ErrorActionPreference = 'Stop'
$projectPath = $PSScriptRoot
$stateFile = Join-Path $projectPath 'data\server-process.json'
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) { Write-Host 'Python 3.10+ is required. Install Python, then run install.cmd.'; exit 1 }
if (-not (Test-Path -LiteralPath (Join-Path $projectPath 'data\seed.sqlite')) -or -not (Test-Path -LiteralPath (Join-Path $projectPath 'dist\client\index.html'))) {
  Write-Host 'Setup is incomplete. Run install.cmd first.'
  exit 1
}
& $pythonCommand.Source -c "import fastapi,uvicorn,websockets" 2>$null
if ($LASTEXITCODE -ne 0) { Write-Host 'Dependencies missing. Run install.cmd first.'; exit 1 }
if (Test-Path -LiteralPath $stateFile) {
  try {
    $saved = Get-Content -LiteralPath $stateFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $running = Get-Process -Id $saved.pid -ErrorAction SilentlyContinue
    if ($running -and $running.StartTime.ToUniversalTime().Ticks -eq [long]$saved.startTicks) {
      Start-Process 'http://127.0.0.1:8765/'
      Write-Host 'Dashboard is already running.'
      exit 0
    }
  } catch { }
}
try {
  $probe = [Net.Sockets.TcpClient]::new()
  $probe.Connect('127.0.0.1',8765)
  $probe.Close()
  Write-Host 'Port 8765 is already in use. Stop the other service or change the port.'
  exit 1
} catch { if ($probe) { $probe.Dispose() } }
$env:PYTHONUTF8 = '1'
$outLog = Join-Path $projectPath 'data\server-out.log'
$errLog = Join-Path $projectPath 'data\server-error.log'
$proc = Start-Process -FilePath $pythonCommand.Source -ArgumentList @('-m','uvicorn','backend.app:app','--host','127.0.0.1','--port','8765') -WorkingDirectory $projectPath -WindowStyle Hidden -PassThru -RedirectStandardOutput $outLog -RedirectStandardError $errLog
$started = $false
for ($i=0; $i -lt 30; $i++) {
  Start-Sleep -Milliseconds 500
  $proc.Refresh()
  if ($proc.HasExited) { break }
  try {
    $response = Invoke-RestMethod -Uri 'http://127.0.0.1:8765/api/meta' -TimeoutSec 1
    if ($response.synthetic -eq $true -and $response.instanceId) { $started = $true; break }
  } catch { }
}
if (-not $started -or $proc.HasExited) { Write-Host 'Unable to start. Check data\server-error.log and whether port 8765 is in use.'; exit 1 }
$record = @{ pid=$proc.Id; startTicks=$proc.StartTime.ToUniversalTime().Ticks; instanceId=$response.instanceId } | ConvertTo-Json
[IO.File]::WriteAllText($stateFile,$record,[Text.UTF8Encoding]::new($false))
Start-Process 'http://127.0.0.1:8765/'
Write-Host 'Dashboard started at http://127.0.0.1:8765/'
