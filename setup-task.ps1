# Register the collector as a startup task (the "service"). Run once.
$dir = 'C:\Users\shmuelstav\poultrix_bot\svc'
$action = New-ScheduledTaskAction -Execute 'pythonw' -Argument "$dir\collector.py"
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType S4U -RunLevel Limited
Register-ScheduledTask -TaskName 'PoultrixCollector' -Action $action -Trigger $trigger -Principal $principal -Force
Start-ScheduledTask -TaskName 'PoultrixCollector'
Write-Output 'PoultrixCollector task registered + started'
