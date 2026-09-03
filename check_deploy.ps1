# Poultrix-watch polling deployer + watchdog for BOTH services.
# Runs every minute via a scheduled task. Pulls the public repo; on a new commit
# redeploys and restarts the collector (127.0.0.1:8765) and the API (0.0.0.0:8000);
# also restarts either if it isn't listening. Writes deploy_status.txt.
$ErrorActionPreference = 'SilentlyContinue'
$dir = 'C:\Users\shmuelstav\poultrix_bot\svc'
Set-Location $dir
$stamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'

function Stop-ByCmd($match) {
  Get-CimInstance Win32_Process -Filter "name='python.exe' OR name='pythonw.exe'" |
    Where-Object { $_.CommandLine -like "*$match*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
}
function Start-Collector { Start-Process pythonw -ArgumentList "$dir\collector.py" -WindowStyle Hidden }
function Start-Api {
  Start-Process python -ArgumentList "-m uvicorn api:app --host 0.0.0.0 --port 8000" `
    -WorkingDirectory $dir -WindowStyle Hidden
}
function Test-Port($url) { try { (Invoke-WebRequest -UseBasicParsing $url -TimeoutSec 5) | Out-Null; return $true } catch { return $false } }

# 1) pull latest
$before = (git rev-parse HEAD) 2>$null
git fetch origin main --quiet 2>$null
$after = (git rev-parse origin/main) 2>$null
$deployed = $false
if ($before -and $after -and ($before -ne $after)) {
  git reset --hard origin/main --quiet 2>$null
  Stop-ByCmd 'collector.py'; Stop-ByCmd 'uvicorn'
  Start-Sleep 2; Start-Collector; Start-Api; Start-Sleep 4
  $deployed = $true
}

# 2) watchdog both services
if (-not (Test-Port 'http://127.0.0.1:8765')) { Start-Collector; Start-Sleep 3 }
if (-not (Test-Port 'http://127.0.0.1:8000/health')) { Start-Api; Start-Sleep 4 }

# 2b) watchdog the Cloudflare tunnel; record the current public URL
if (-not (Get-Process cloudflared -ErrorAction SilentlyContinue)) {
  Start-ScheduledTask -TaskName 'PoultrixTunnel' -ErrorAction SilentlyContinue
  Start-Sleep 12
}
$turl = (Get-Content "$dir\cloudflared.log" -ErrorAction SilentlyContinue |
         Select-String -Pattern 'https://[a-z0-9-]+\.trycloudflare\.com' |
         ForEach-Object { $_.Matches.Value } | Select-Object -Last 1)
if ($turl) { $turl | Out-File "$dir\tunnel_url.txt" -Encoding utf8 -NoNewline }

$col = if (Test-Port 'http://127.0.0.1:8765') { 'up' } else { 'DOWN' }
$api = if (Test-Port 'http://127.0.0.1:8000/health') { 'up' } else { 'DOWN' }

# 3) status
if ($deployed) {
  "$stamp DEPLOYED commit=$after collector=$col api=$api" | Out-File "$dir\deploy_status.txt" -Encoding utf8
}
"$stamp checked head=$after deployed=$deployed collector=$col api=$api" | Out-File "$dir\last_check.txt" -Encoding utf8
