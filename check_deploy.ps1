# Poultrix-watch polling deployer + collector watchdog.
# Runs every minute via a scheduled task. Pulls the public repo; on a new
# commit it redeploys and restarts the collector; also restarts the collector
# if it isn't listening. Writes deploy_status.txt (read from your Mac via SSH).
$ErrorActionPreference = 'SilentlyContinue'
$dir = 'C:\Users\shmuelstav\poultrix_bot\svc'
Set-Location $dir
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

function Restart-Collector {
  Get-CimInstance Win32_Process -Filter "name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like '*collector.py*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
  Start-Sleep 1
  Start-Process pythonw -ArgumentList "$dir\collector.py" -WindowStyle Hidden
  Start-Sleep 3
}

function Test-Health {
  try { return (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765 -TimeoutSec 5).Content }
  catch { return "DOWN" }
}

# 1) pull latest
$before = (git rev-parse HEAD) 2>$null
git fetch origin main --quiet 2>$null
$after = (git rev-parse origin/main) 2>$null

$deployed = $false
if ($before -and $after -and ($before -ne $after)) {
  git reset --hard origin/main --quiet 2>$null   # ignored data files are untouched
  Restart-Collector
  $deployed = $true
}

# 2) watchdog: make sure the collector is up regardless
$health = Test-Health
if ($health -eq 'DOWN') { Restart-Collector; $health = Test-Health }

# 3) write status
if ($deployed) {
  "$stamp DEPLOYED commit=$after health=$health" | Out-File "$dir\deploy_status.txt" -Encoding utf8
}
"$stamp checked head=$after deployed=$deployed health=$health" | Out-File "$dir\last_check.txt" -Encoding utf8
