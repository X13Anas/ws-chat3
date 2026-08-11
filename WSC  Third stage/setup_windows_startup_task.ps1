# Windows Task Scheduler 24/7 Auto-Start Setup Script
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$PSScriptRoot\start_server_247.bat`""
$trigger = New-ScheduledTaskTrigger -AtStartup
$principal = New-ScheduledTaskPrincipal -UserId "NT AUTHORITY\SYSTEM" -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName "WSChat247Server" -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force
Write-Host "✅ WS Chat 24/7 Task registered successfully! Server will start automatically on PC boot." -ForegroundColor Green
