param([switch]$Start)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$interpreter = Join-Path $projectRoot '.venv\Scripts\pythonw.exe'
$supervisor = Join-Path $PSScriptRoot 'local_stack.py'
if (-not (Test-Path -LiteralPath $interpreter)) { throw 'Local Python environment is missing.' }
$taskName = 'PonyChat Local Backend Stack'
$taskUser = [Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $interpreter -Argument ('"' + $supervisor + '" supervise') -WorkingDirectory $projectRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $taskUser
$principal = New-ScheduledTaskPrincipal -UserId $taskUser -LogonType Interactive -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -Hidden -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description 'PonyChat local chat, CosyVoice, search and Server-USA reverse tunnel supervisor.' -Force | Out-Null
if ($Start) { Start-ScheduledTask -TaskName $taskName }
Get-ScheduledTask -TaskName $taskName | Select-Object TaskName,State
