param(
    [int]$Port = 8010,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Join-Path $Root ".venv-qwen3tts\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    python -m venv --system-site-packages ".venv-qwen3tts"
    & $Python -m pip install -U pip wheel setuptools
    & $Python -m pip install faster-qwen3-tts==0.2.6 qwen-tts==0.1.1 redis python-multipart hf_xet modelscope
}

$Existing = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
$Url = "http://127.0.0.1:$Port/qwen3tts/"
if ($Existing) {
    Write-Host "Qwen3TTS already appears to be listening on $Url (PID $($Existing.OwningProcess))."
    if (-not $NoBrowser) {
        Start-Process $Url
    }
    exit 0
}

New-Item -ItemType Directory -Force "generation_logs" | Out-Null

if (-not $env:QWEN_TTS_QUEUE_BACKEND) { $env:QWEN_TTS_QUEUE_BACKEND = "memory" }
if (-not $env:QWEN_TTS_WORKER_ENABLED) { $env:QWEN_TTS_WORKER_ENABLED = "1" }
if (-not $env:QWEN_TTS_WARMUP) { $env:QWEN_TTS_WARMUP = "0" }
if (-not $env:QWEN_TTS_DEVICE) { $env:QWEN_TTS_DEVICE = "cuda" }
if (-not $env:QWEN_TTS_SINGLE_MODEL_MODE) { $env:QWEN_TTS_SINGLE_MODEL_MODE = "0" }
if (-not $env:QWEN_TTS_PRELOAD_MODELS) { $env:QWEN_TTS_PRELOAD_MODELS = "clone,design,custom" }
if (-not $env:QWEN_TTS_PRELOAD_STRICT) { $env:QWEN_TTS_PRELOAD_STRICT = "1" }
if (-not $env:PYTORCH_CUDA_ALLOC_CONF) { $env:PYTORCH_CUDA_ALLOC_CONF = "expandable_segments:True" }

Write-Host "Starting PonyChat Qwen3TTS at $Url"
Write-Host "Queue backend: $env:QWEN_TTS_QUEUE_BACKEND"
Write-Host "Warmup: $env:QWEN_TTS_WARMUP"
Write-Host "Single model mode: $env:QWEN_TTS_SINGLE_MODEL_MODE"
Write-Host "Preload models: $env:QWEN_TTS_PRELOAD_MODELS"

if (-not $NoBrowser) {
    Start-Process $Url
}

& $Python -m uvicorn app_fast:app --host 127.0.0.1 --port $Port
