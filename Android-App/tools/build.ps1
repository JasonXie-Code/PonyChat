param(
    [switch]$Offline,
    [string[]]$Tasks = @(':app:assembleRelease')
)

$ErrorActionPreference = 'Stop'
$projectDir = Split-Path $PSScriptRoot -Parent
$toolRoot = 'P:\Tools'
$buildEnvironment = @{
    JAVA_HOME = Join-Path $toolRoot 'jdk-17'
    GRADLE_USER_HOME = Join-Path $toolRoot 'gradle-home'
    TEMP = Join-Path $toolRoot 'gradle-tmp'
    TMP = Join-Path $toolRoot 'gradle-tmp'
}
$previousEnvironment = @{}
foreach ($name in $buildEnvironment.Keys) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, 'Process')
}
try {
    foreach ($name in $buildEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $buildEnvironment[$name], 'Process')
    }
    if (-not (Test-Path -LiteralPath (Join-Path $env:JAVA_HOME 'bin\java.exe'))) {
        throw 'P:\Tools\jdk-17 is required.'
    }
    New-Item -ItemType Directory -Force -Path $env:TEMP | Out-Null
    Push-Location $projectDir
    try {
        $gradleArguments = @('--no-daemon', '--console=plain')
        if ($Offline) { $gradleArguments += '--offline' }
        & .\gradlew.bat @gradleArguments @Tasks
        if ($LASTEXITCODE -ne 0) { throw "Gradle failed with exit code $LASTEXITCODE" }
    } finally {
        Pop-Location
    }
} finally {
    foreach ($name in $previousEnvironment.Keys) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], 'Process')
    }
}
