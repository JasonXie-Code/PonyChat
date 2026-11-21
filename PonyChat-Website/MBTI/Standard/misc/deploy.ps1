# [已废弃] 原 HK-CN2 时代部署脚本；现推荐使用 misc\deploy_standard_mbti_server_usa.py（基于 ssh_lib）。
#
# 构建并上传 web/dist 到服务器（OpenSSH 的 ssh/scp）
# 用法（在 MBTI/Standard 项目根目录 PowerShell）：
#   .\misc\deploy.ps1
#   .\misc\deploy.ps1 -SshTarget "root@154.17.23.237" -RemoteDir "/var/www/standard-mbti-static"
#
# 注意：本脚本依赖 $bypassPs1 中的 deploy-ssh-bypass.ps1（外部 AIOPC-Website 路径），
#       在当前 PonyChat 仓库中不可用，运行前请先确认路径正确或直接改用 deploy_standard_mbti_server_usa.py。

param(
    [string] $SshTarget = "root@154.17.23.237",
    [string] $RemoteDir = "/var/www/mbti",
    [string] $IdentityFile = ""
)

$ErrorActionPreference = "Stop"
$bypassPs1 = Join-Path $PSScriptRoot '..\..\AIOPC-Website\aiopc-platform\TheServerUSA\deploy-ssh-bypass.ps1'
. (Resolve-Path -LiteralPath $bypassPs1).Path
Initialize-DeploySshBypass
$root = Split-Path -Parent $PSScriptRoot
$web = Join-Path $root "web"

$keyPath = $null
if ($IdentityFile -ne "") {
    $keyPath =
        if ([System.IO.Path]::IsPathRooted($IdentityFile)) {
            $IdentityFile
        } else {
            Join-Path $root $IdentityFile
        }
    if (-not (Test-Path $keyPath)) {
        throw "找不到密钥文件: $keyPath"
    }
}

Push-Location $web
try {
    npm run build
} finally {
    Pop-Location
}

$dist = Join-Path $web "dist"
if (-not (Test-Path $dist)) {
    throw "未找到 web\dist，构建失败。"
}

$SshArgs = if ($null -ne $keyPath) { Get-DeploySshScpArgs $keyPath } else { Get-DeploySshScpArgsNoIdentity }
Write-Host "确保远程目录存在..."
if ($null -ne $keyPath) {
    & ssh.exe @SshArgs $SshTarget "mkdir -p $RemoteDir"
} else {
    & ssh.exe @SshArgs $SshTarget "mkdir -p $RemoteDir"
}
if ($LASTEXITCODE -ne 0) {
    throw "ssh mkdir 失败。"
}

Write-Host "上传到 ${SshTarget}:${RemoteDir}/ ..."
if ($null -ne $keyPath) {
    & scp.exe @SshArgs -r "${dist}/." "${SshTarget}:${RemoteDir}/"
} else {
    & scp.exe @SshArgs -r "${dist}/." "${SshTarget}:${RemoteDir}/"
}
if ($LASTEXITCODE -ne 0) {
    throw "scp 失败（请检查 SSH、密钥权限与服务器目录）。"
}
Write-Host "完成。若仅更新静态文件，一般无需重载 nginx。"
