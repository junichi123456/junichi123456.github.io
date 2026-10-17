# Register a task that runs run_yakkun.bat at logon (run once).
#   powershell -ExecutionPolicy Bypass -File install_yakkun_task.ps1
#   remove: add -Remove
param([switch]$Remove)
$name = 'PokechampYakkunFetch'
if ($Remove) { Unregister-ScheduledTask -TaskName $name -Confirm:$false; Write-Host 'removed'; exit }
$bat = Join-Path $PSScriptRoot 'run_yakkun.bat'
New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot '..\logs\study\yakkun') | Out-Null
$action = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$set = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $set -Force | Out-Null
Write-Host "registered: $name (runs 90 seconds after logon)"
