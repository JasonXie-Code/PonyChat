param(
    [int]$IntervalSeconds = 60
)

$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$StackScript = Join-Path $Root "start_qwen3tts_stack.ps1"
$LogDir = Join-Path $Root "generation_logs"
$Log = Join-Path $LogDir "qwen3tts_watchdog.log"
$Mutex = $null
$MutexCreated = $false

New-Item -ItemType Directory -Force $LogDir | Out-Null

function Write-WatchdogLog {
    param([string]$Message)
    $line = "$(Get-Date -Format s) $Message"
    Add-Content -Path $Log -Value $line -Encoding UTF8
}

if (-not (Test-Path $StackScript)) {
    Write-WatchdogLog "missing stack script: $StackScript"
    exit 1
}

$Mutex = New-Object System.Threading.Mutex($true, "Global\PonyChatQwen3TTSWatchdog", [ref]$MutexCreated)
if (-not $MutexCreated) {
    Write-WatchdogLog "watchdog already running; exiting duplicate"
    exit 0
}

try {
    Write-WatchdogLog "watchdog started interval=${IntervalSeconds}s"

    while ($true) {
        try {
            $output = & $StackScript 2>&1 | Out-String
            $trimmed = $output.Trim()
            if ($trimmed) {
                foreach ($line in ($trimmed -split "\r?\n")) {
                    Write-WatchdogLog "stack: $line"
                }
            }
            if (-not $?) {
                Write-WatchdogLog "stack check reported failure"
            }
        } catch {
            Write-WatchdogLog "stack check exception: $($_.Exception.Message)"
        }

        Start-Sleep -Seconds ([Math]::Max(10, $IntervalSeconds))
    }
} finally {
    if ($Mutex) {
        $Mutex.ReleaseMutex() | Out-Null
        $Mutex.Dispose()
    }
}
