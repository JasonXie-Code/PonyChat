param(
    [string]$SourceDir = "$env:TEMP\ponychat-eleeye-build\eleeye",
    [string]$NdkDir = "P:\Tools\android-sdk\ndk\26.3.11579264"
)

$ErrorActionPreference = "Stop"

$clang = Join-Path $NdkDir "toolchains\llvm\prebuilt\windows-x86_64\bin\clang++.exe"
if (-not (Test-Path -LiteralPath $clang)) {
    throw "clang++ not found at $clang"
}

$engineDir = Join-Path $SourceDir "eleeye"
if (-not (Test-Path -LiteralPath $engineDir)) {
    throw "EleEye source not found. Clone https://github.com/xqbase/eleeye to $SourceDir first."
}

$repoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$jniRoot = Join-Path $repoRoot "app\src\main\jniLibs"
$assetRoot = Join-Path $repoRoot "app\src\main\assets\eleeye"
$sources = @(
    "..\base\pipe.cpp",
    "ucci.cpp",
    "pregen.cpp",
    "position.cpp",
    "genmoves.cpp",
    "hash.cpp",
    "book.cpp",
    "movesort.cpp",
    "preeval.cpp",
    "evaluate.cpp",
    "search.cpp",
    "eleeye.cpp"
)
$targets = @{
    "arm64-v8a" = "aarch64-linux-android21"
    "armeabi-v7a" = "armv7a-linux-androideabi21"
    "x86_64" = "x86_64-linux-android21"
}

Push-Location $engineDir
try {
    foreach ($abi in $targets.Keys) {
        $outDir = Join-Path $jniRoot $abi
        New-Item -ItemType Directory -Force -Path $outDir | Out-Null
        $outFile = Join-Path $outDir "libeleeye.so"
        $args = @(
            "--target=$($targets[$abi])",
            "-static-libstdc++",
            "-DNDEBUG",
            "-O4",
            "-Wall",
            "-pie",
            "-fPIE",
            "-Wl,-s",
            "-o",
            $outFile
        ) + $sources
        & $clang @args
        if ($LASTEXITCODE -ne 0) {
            throw "EleEye build failed for $abi"
        }
    }
} finally {
    Pop-Location
}

New-Item -ItemType Directory -Force -Path $assetRoot | Out-Null
Copy-Item -LiteralPath (Join-Path $SourceDir "BOOK\BOOK.DAT") -Destination (Join-Path $assetRoot "BOOK.DAT") -Force
Get-ChildItem -Path $jniRoot -Recurse -Filter libeleeye.so | Select-Object FullName,Length
Get-Item (Join-Path $assetRoot "BOOK.DAT") | Select-Object FullName,Length
