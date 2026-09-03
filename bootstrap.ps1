# One-time server bootstrap for poultrix-watch (collector + warehouse + API).
$ErrorActionPreference = 'Stop'
$base = 'C:\Users\shmuelstav\poultrix_bot'
$svc  = "$base\svc"
$repo = 'https://github.com/shmuelstav2/poultrix-watch.git'

New-Item -ItemType Directory -Force -Path $base | Out-Null
if (-not (Test-Path "$svc\.git")) {
  if (Test-Path $svc) { Rename-Item $svc "$base\svc_old_$(Get-Date -Format yyyyMMddHHmmss)" }
  git clone $repo $svc
}
Set-Location $svc
git reset --hard origin/main --quiet
git pull --quiet
Write-Output ("repo at " + (git rev-parse HEAD))

# python deps for the API
python -m pip install --quiet --disable-pip-version-check fastapi uvicorn 2>&1 | Out-Null
Write-Output "deps installed"

# API key (generate once, gitignored)
if (-not (Test-Path "$svc\api_key.txt")) {
  ([guid]::NewGuid().ToString('N')) | Out-File "$svc\api_key.txt" -Encoding ascii -NoNewline
}
Write-Output ("API key: " + (Get-Content "$svc\api_key.txt"))

# open Windows firewall for the API port (needs admin; ignored otherwise)
New-NetFirewallRule -DisplayName 'PoultrixAPI 8000' -Direction Inbound -Protocol TCP `
  -LocalPort 8000 -Action Allow -ErrorAction SilentlyContinue | Out-Null

# every-minute polling deploy + watchdog task
$action = New-ScheduledTaskAction -Execute 'powershell' `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$svc\check_deploy.ps1`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
  -RepetitionInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
Register-ScheduledTask -TaskName 'PoultrixDeploy' -Action $action -Trigger $trigger -Principal $principal -Force | Out-Null
Start-ScheduledTask -TaskName 'PoultrixDeploy'
Write-Output 'PoultrixDeploy task registered + started'

# (re)start both services now
Get-CimInstance Win32_Process -Filter "name='python.exe' OR name='pythonw.exe'" |
  Where-Object { $_.CommandLine -like '*collector.py*' -or $_.CommandLine -like '*uvicorn*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep 2
Start-Process pythonw -ArgumentList "$svc\collector.py" -WindowStyle Hidden
Start-Process python -ArgumentList "-m uvicorn api:app --host 0.0.0.0 --port 8000" -WorkingDirectory $svc -WindowStyle Hidden
Start-Sleep 6
$col = try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765 -TimeoutSec 5).Content } catch { 'DOWN' }
$api = try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/health -TimeoutSec 5).Content } catch { 'DOWN' }
Write-Output ("bootstrap done; collector=$col ; api=$api")
