param(
    [switch]$RunNow
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$StackScript = Join-Path $Root "start_qwen3tts_stack.ps1"
$WatchdogLauncher = Join-Path $Root "start_qwen3tts_watchdog.vbs"
$TaskName = "PonyChat Qwen3TTS Local Stack"

if (-not (Test-Path $StackScript)) {
    throw "Missing stack script: $StackScript"
}
if (-not (Test-Path $WatchdogLauncher)) {
    throw "Missing watchdog launcher: $WatchdogLauncher"
}

$action = New-ScheduledTaskAction `
    -Execute "wscript.exe" `
    -Argument "`"$WatchdogLauncher`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -Hidden `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Description "Starts a hidden PonyChat local Qwen3TTS watchdog for the Server-USA reverse tunnel." `
    -Force | Out-Null

if ($RunNow) {
    Start-ScheduledTask -TaskName $TaskName
}

Write-Host "Registered scheduled task: $TaskName"
