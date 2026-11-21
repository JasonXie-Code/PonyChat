param(
    [int]$MaxWorkers = 4,
    [ValidateSet("modelscope", "huggingface")]
    [string]$Source = "modelscope",
    [switch]$BaseOnly,
    [switch]$SkipBase,
    [switch]$SkipDesign,
    [switch]$SkipCustom
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

$Python = Join-Path $Root ".venv-qwen3tts\Scripts\python.exe"
$Hf = Join-Path $Root ".venv-qwen3tts\Scripts\hf.exe"
$ModelScope = Join-Path $Root ".venv-qwen3tts\Scripts\modelscope.exe"

if (-not (Test-Path $Python)) {
    python -m venv --system-site-packages ".venv-qwen3tts"
}

& $Python -m pip install -U pip wheel setuptools
& $Python -m pip install faster-qwen3-tts==0.2.6 qwen-tts==0.1.1 redis python-multipart hf_xet modelscope

if ($Source -eq "huggingface" -and -not (Test-Path $Hf)) {
    throw "hf.exe was not installed into .venv-qwen3tts"
}
if ($Source -eq "modelscope" -and -not (Test-Path $ModelScope)) {
    throw "modelscope.exe was not installed into .venv-qwen3tts"
}

$Models = @()
if (-not $SkipBase) {
    $Models += @{
        Repo = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
        Dir = "models\Qwen3-TTS-12Hz-1.7B-Base"
    }
}
if (-not $BaseOnly -and -not $SkipDesign) {
    $Models += @{
        Repo = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
        Dir = "models\Qwen3-TTS-12Hz-1.7B-VoiceDesign"
    }
}
if (-not $BaseOnly -and -not $SkipCustom) {
    $Models += @{
        Repo = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"
        Dir = "models\Qwen3-TTS-12Hz-1.7B-CustomVoice"
    }
}

New-Item -ItemType Directory -Force "models" | Out-Null

foreach ($Model in $Models) {
    Write-Host "Downloading $($Model.Repo) -> $($Model.Dir) via $Source"
    if ($Source -eq "modelscope") {
        & $ModelScope download --model $Model.Repo --local_dir $Model.Dir --max-workers $MaxWorkers
    } else {
        & $Hf download $Model.Repo --local-dir $Model.Dir --max-workers $MaxWorkers
    }
}

Write-Host "Qwen3TTS model download complete."
