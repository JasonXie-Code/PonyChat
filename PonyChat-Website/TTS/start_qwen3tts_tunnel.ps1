param(
    [int]$RemotePort = 18012,
    [int]$LocalPort = 8010,
    [int]$RestartDelaySeconds = 5,
    [int]$ExistingTunnelSleepSeconds = 30
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$Mutex = $null
$MutexCreated = $false

$ServerHost = "154.17.23.237"
$ServerUser = "root"
$ServerSshPort = 22
$KeyCandidates = @(
    $env:PONYCHAT_VOICE_SSH_KEY,
    (Join-Path (Split-Path -Parent $Root) "ServerKeys\DMIT - 154.17.23.237\Server-USA-id_rsa\id_rsa.pem"),
    "P:\ServerKeys\DMIT - 154.17.23.237\Server-USA-id_rsa\id_rsa.pem"
) | Where-Object { $_ }
$Key = $KeyCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $Key) {
    throw "SSH key not found. Tried: $($KeyCandidates -join ', ')"
}

function Test-LocalListener {
    $listener = Get-NetTCPConnection -LocalAddress 127.0.0.1 -LocalPort $LocalPort -State Listen -ErrorAction SilentlyContinue |
        Select-Object -First 1
    return [bool]$listener
}

$env:HTTP_PROXY = ""
$env:HTTPS_PROXY = ""
$env:ALL_PROXY = ""
$env:http_proxy = ""
$env:https_proxy = ""
$env:all_proxy = ""
$env:NO_PROXY = "*"
$env:no_proxy = "*"

$Forward = "127.0.0.1:{0}:127.0.0.1:{1}" -f $RemotePort, $LocalPort

function Test-ExistingTunnelProcess {
    $existing = Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "ssh.exe" -and $_.CommandLine -like "*$Forward*" } |
        Select-Object -First 1
    return [bool]$existing
}

$Mutex = New-Object System.Threading.Mutex($true, "Global\PonyChatQwen3TTSTunnel", [ref]$MutexCreated)
if (-not $MutexCreated) {
    Write-Host "$(Get-Date -Format s) Qwen3TTS reverse tunnel supervisor is already running. Exiting duplicate."
    exit 0
}

try {
    while ($true) {
        if (-not (Test-LocalListener)) {
            Write-Warning "$(Get-Date -Format s) Qwen3TTS is not listening on http://127.0.0.1:$LocalPort/qwen3tts/. Retrying in $RestartDelaySeconds seconds."
            Start-Sleep -Seconds $RestartDelaySeconds
            continue
        }

        if (Test-ExistingTunnelProcess) {
            Write-Host "$(Get-Date -Format s) Qwen3TTS reverse tunnel ssh is already running. Exiting duplicate supervisor."
            exit 0
        }

        $started = Get-Date
        Write-Host "$(Get-Date -Format s) Opening reverse tunnel: Server-USA 127.0.0.1:$RemotePort -> local 127.0.0.1:$LocalPort"

        ssh -F none `
            -i $Key `
            -p $ServerSshPort `
            -o BatchMode=yes `
            -o RequestTTY=no `
            -o IdentitiesOnly=yes `
            -o ExitOnForwardFailure=yes `
            -o ConnectTimeout=25 `
            -o StrictHostKeyChecking=accept-new `
            -o ServerAliveInterval=15 `
            -o ServerAliveCountMax=4 `
            -n `
            -N `
            -R $Forward `
            "$ServerUser@$ServerHost"

        $exitCode = $LASTEXITCODE
        $elapsed = [int]((Get-Date) - $started).TotalSeconds
        Write-Warning "$(Get-Date -Format s) Qwen3TTS reverse tunnel exited code=$exitCode after ${elapsed}s. Restarting in $RestartDelaySeconds seconds."
        Start-Sleep -Seconds $RestartDelaySeconds
    }
} finally {
    if ($Mutex) {
        $Mutex.ReleaseMutex() | Out-Null
        $Mutex.Dispose()
    }
}
