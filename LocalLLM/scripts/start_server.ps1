# start_server.ps1 - 启动 llama.cpp server
# 用法：
#   .\scripts\start_server.ps1              # 默认：多模态 + GPU
#   .\scripts\start_server.ps1 -NoMmproj   # 禁用视觉编码器（纯文本，省 ~1 GB 显存）
#   .\scripts\start_server.ps1 -CPU         # 强制纯 CPU（n_gpu_layers 0）

param(
    [switch]$NoMmproj,
    [switch]$CPU
)

$ErrorActionPreference = "Stop"
$Root   = "$PSScriptRoot\.."

# 清理旧进程，防止显存叠加占用
$expectedBin = [IO.Path]::GetFullPath("$Root\server\bin\llama-server.exe")
$old = Get-Process -Name "llama-server" -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $expectedBin }
if ($old) {
    Write-Host "检测到旧进程（$($old.Count) 个），正在终止..." -ForegroundColor Yellow
    $old | Stop-Process -Force
    $deadline = (Get-Date).AddSeconds(10)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process -Name "llama-server" -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 500
    }
    Write-Host "旧进程已清理" -ForegroundColor Green
}
$Cfg    = Get-Content "$Root\server\config.json" -Raw -Encoding UTF8 | ConvertFrom-Json
$Bin    = "$Root\server\bin\llama-server.exe"
$LogDir = "$Root\logs"

if (-not (Test-Path $Bin)) {
    Write-Host "未找到 llama-server.exe，请先运行：.\scripts\setup.ps1" -ForegroundColor Red
    exit 1
}

$ModelPath = "$Root\$($Cfg.model)"
if (-not (Test-Path $ModelPath)) {
    Write-Host "未找到模型文件：$ModelPath" -ForegroundColor Red
    exit 1
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$argList = @(
    "--host",           $Cfg.host,
    "--port",           [string]$Cfg.port,
    "--model",          $ModelPath,
    "--alias",          $Cfg.alias,
    "--jinja",
    "--n-predict",      [string]$Cfg.n_predict,
    "--reasoning-budget", [string]$Cfg.reasoning_budget,
    "--ctx-size",       [string]$Cfg.n_ctx,
    "--n-gpu-layers",   [string](if ($CPU) { 0 } else { $Cfg.n_gpu_layers }),
    "--batch-size",     [string]$Cfg.n_batch,
    "--threads",        [string]$Cfg.n_threads,
    "--parallel",       [string]$Cfg.parallel,
    "--flash-attn",     "auto",
    "--cache-type-k",   "q8_0",
    "--cache-type-v",   "q8_0",
    "--log-file",       "$LogDir\server.log"
)

if ($Cfg.cont_batching) { $argList += "--cont-batching" }

if (-not $NoMmproj -and $Cfg.mmproj) {
    $MmprojPath = "$Root\$($Cfg.mmproj)"
    if (Test-Path $MmprojPath) {
        $argList += "--mmproj"
        $argList += $MmprojPath
        Write-Host "多模态视觉已启用（mmproj）" -ForegroundColor Cyan
    } else {
        Write-Host "mmproj 文件不存在，以纯文本模式启动" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "=== LocalLLM Server ===" -ForegroundColor Cyan
Write-Host "版本  : b8638 (llama.cpp)"
Write-Host "模型  : $($Cfg.model)"
Write-Host "地址  : http://$($Cfg.host):$($Cfg.port)"
Write-Host "日志  : logs\server.log"
Write-Host "按 Ctrl+C 停止服务"
Write-Host ""

& $Bin @argList
