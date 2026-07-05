param(
    [int]$LocalPort = 8010,
    [int]$RemotePort = 18012
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

New-Item -ItemType Directory -Force "generation_logs" | Out-Null

function Test-LocalQwen3Tts {
    try {
        $health = Invoke-RestMethod "http://127.0.0.1:$LocalPort/qwen3tts/health" -TimeoutSec 3
        return [bool]$health.ok
    } catch {
        return $false
    }
}

function Start-LocalQwen3Tts {
    $out = Join-Path $Root "generation_logs\qwen3tts_local_stdout.log"
    $err = Join-Path $Root "generation_logs\qwen3tts_local_stderr.log"
    Start-Process powershell `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $Root "start_qwen3tts_local.ps1"), "-NoBrowser", "-Port", "$LocalPort") `
        -WindowStyle Hidden `
        -RedirectStandardOutput $out `
        -RedirectStandardError $err | Out-Null
}

function Get-TunnelProcess {
    $needle = "127.0.0.1:$RemotePort:127.0.0.1:$LocalPort"
    return Get-CimInstance Win32_Process -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -eq "ssh.exe" -and $_.CommandLine -like "*$needle*" } |
        Select-Object -First 1
}

function Test-TunnelProcess {
    return [bool](Get-TunnelProcess)
}

function Stop-Qwen3TtsTunnel {
    $proc = Get-TunnelProcess
    if ($proc) {
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
}

function Test-PublicQwen3Tts {
    try {
        $health = Invoke-RestMethod "https://voice.ponychat.org/qwen3tts/health" -TimeoutSec 6
        return [bool]$health.ok
    } catch {
        return $false
    }
}

function Start-Qwen3TtsTunnel {
    $out = Join-Path $Root "generation_logs\qwen3tts_tunnel_stdout.log"
    $err = Join-Path $Root "generation_logs\qwen3tts_tunnel_stderr.log"
    Start-Process powershell `
        -ArgumentList @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", (Join-Path $Root "start_qwen3tts_tunnel.ps1"), "-RemotePort", "$RemotePort", "-LocalPort", "$LocalPort") `
        -WindowStyle Hidden `
        -RedirectStandardOutput $out `
        -RedirectStandardError $err | Out-Null
}

if (-not (Test-LocalQwen3Tts)) {
    Start-LocalQwen3Tts
    $deadline = (Get-Date).AddMinutes(8)
    do {
        Start-Sleep -Seconds 4
        if (Test-LocalQwen3Tts) { break }
    } while ((Get-Date) -lt $deadline)
}

if (-not (Test-LocalQwen3Tts)) {
    throw "Qwen3TTS did not become healthy on http://127.0.0.1:$LocalPort/qwen3tts/health"
}

$tunnelHealthy = Test-PublicQwen3Tts
if (-not $tunnelHealthy -and (Test-TunnelProcess)) {
    Stop-Qwen3TtsTunnel
    Start-Sleep -Seconds 2
}

if (-not $tunnelHealthy) {
    Start-Qwen3TtsTunnel
    $deadline = (Get-Date).AddSeconds(45)
    do {
        Start-Sleep -Seconds 3
        if (Test-PublicQwen3Tts) {
            $tunnelHealthy = $true
            break
        }
    } while ((Get-Date) -lt $deadline)
}

if ($tunnelHealthy) {
    Write-Host "PonyChat Qwen3TTS stack is running: local=$LocalPort remote=$RemotePort"
} else {
    Write-Warning "PonyChat Qwen3TTS local service is running, but public tunnel health is not ready yet."
}
