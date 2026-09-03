# One-time server bootstrap for poultrix-watch.
# Clones the public repo into the svc folder, registers a 1-minute polling
# deploy task, and starts the collector. Safe to re-run.
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

# every-minute polling deploy task (also watchdogs the collector)
$action = New-ScheduledTaskAction -Execute 'powershell' `
  -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$svc\check_deploy.ps1`""
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
  -RepetitionInterval (New-TimeSpan -Minutes 1)
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
Register-ScheduledTask -TaskName 'PoultrixDeploy' -Action $action -Trigger $trigger -Principal $principal -Force
Start-ScheduledTask -TaskName 'PoultrixDeploy'
Write-Output 'PoultrixDeploy task registered + started'

# start the collector now
Get-CimInstance Win32_Process -Filter "name='pythonw.exe'" |
  Where-Object { $_.CommandLine -like '*collector.py*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Start-Sleep 1
Start-Process pythonw -ArgumentList "$svc\collector.py" -WindowStyle Hidden
Start-Sleep 3
$health = try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765 -TimeoutSec 5).Content } catch { 'DOWN' }
Write-Output ("bootstrap done; collector health = $health")
