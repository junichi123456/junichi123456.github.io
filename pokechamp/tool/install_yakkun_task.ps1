# PC起動（ログオン）時に run_yakkun.bat を自動実行するタスクを登録する。1回だけ実行すればよい。
#   PowerShell で:  powershell -ExecutionPolicy Bypass -File install_yakkun_task.ps1
#   解除:           powershell -ExecutionPolicy Bypass -File install_yakkun_task.ps1 -Remove
param([switch]$Remove)
$name = 'PokechampYakkunFetch'
if ($Remove) { Unregister-ScheduledTask -TaskName $name -Confirm:$false; Write-Host '解除しました'; exit }
$bat = Join-Path $PSScriptRoot 'run_yakkun.bat'
New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot '..\logs\study\yakkun') | Out-Null
$action = New-ScheduledTaskAction -Execute $bat -WorkingDirectory $PSScriptRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$set = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $set -Force | Out-Null
Write-Host "登録しました: $name （ログオンの90秒後に実行）"
