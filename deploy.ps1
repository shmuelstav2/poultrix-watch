# Poultrix-watch deploy: pull latest, restart the collector.
# Run on the server:  powershell -ExecutionPolicy Bypass -File deploy.ps1
$ErrorActionPreference = 'Stop'
$dir = 'C:\Users\shmuelstav\poultrix_bot\svc'
Set-Location $dir

Write-Output '== git pull =='
git pull

Write-Output '== restart collector =='
Get-CimInstance Win32_Process -Filter "name='pythonw.exe'" |
  Where-Object { $_.CommandLine -like '*collector.py*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Output "killed PID $($_.ProcessId)" }
Start-Sleep 1
Start-Process pythonw -ArgumentList "$dir\collector.py" -WindowStyle Hidden
Start-Sleep 3

Write-Output '== health =='
try { (Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8765).Content }
catch { Write-Output "health check FAILED: $_" }
