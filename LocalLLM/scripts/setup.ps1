# setup.ps1 - 下载 llama.cpp server 二进制及 CUDA 运行时到 server/bin/
# 用法：.\scripts\setup.ps1 [-Version b8638] [-CudaVer 12.4]
# 两个 zip 都会解压到 server\bin\，实现项目完全自包含。

param(
    [string]$Version = "b8638",
    [string]$CudaVer = "12.4",
    [string]$DestDir = "$PSScriptRoot\..\server\bin"
)

$ErrorActionPreference = "Stop"
$BaseUrl  = "https://github.com/ggerganov/llama.cpp/releases/download"
$BinZip   = "llama-$Version-bin-win-cuda-$CudaVer-x64.zip"
$CudaZip  = "cudart-llama-bin-win-cuda-$CudaVer-x64.zip"

Write-Host "=== LocalLLM - 下载 llama.cpp server ===" -ForegroundColor Cyan
Write-Host "版本       : $Version"
Write-Host "CUDA       : $CudaVer"
Write-Host "目标目录   : $DestDir"
Write-Host ""

New-Item -ItemType Directory -Force -Path $DestDir | Out-Null

function Download-And-Extract {
    param([string]$FileName)
    $Url    = "$BaseUrl/$Version/$FileName"
    $TmpZip = "$env:TEMP\$FileName"

    if (Test-Path $TmpZip) {
        Write-Host "  已有缓存 $TmpZip，跳过下载" -ForegroundColor Yellow
    } else {
        Write-Host "  下载 $FileName  ($Url) ..." -ForegroundColor Cyan
        Invoke-WebRequest -Uri $Url -OutFile $TmpZip -UseBasicParsing
    }
    Write-Host "  解压 $FileName ..."
    Expand-Archive -Path $TmpZip -DestinationPath $DestDir -Force
}

# 1. 主二进制（llama-server.exe 等）
if (Test-Path "$DestDir\llama-server.exe") {
    Write-Host "llama-server.exe 已存在，跳过主二进制下载。" -ForegroundColor Yellow
} else {
    Download-And-Extract $BinZip
}

# 2. CUDA 运行时 DLL（使项目无需依赖系统 CUDA 安装）
$cudadll = Get-ChildItem $DestDir -Filter "cudart64_*.dll" -ErrorAction SilentlyContinue
if ($cudadll) {
    Write-Host "CUDA 运行时 DLL 已存在，跳过。" -ForegroundColor Yellow
} else {
    Download-And-Extract $CudaZip
}

# 验证
if (Test-Path "$DestDir\llama-server.exe") {
    $ver = & "$DestDir\llama-server.exe" --version 2>&1 | Select-Object -First 1
    Write-Host ""
    Write-Host "完成！版本信息：$ver" -ForegroundColor Green
    Write-Host "启动服务：  .\scripts\start_server.ps1" -ForegroundColor White
} else {
    Write-Error "解压后未找到 llama-server.exe，请检查下载内容。"
}
