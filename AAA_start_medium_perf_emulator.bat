@echo off
setlocal

set "EMU=%LOCALAPPDATA%\Android\Sdk\emulator\emulator.exe"

if not exist "%EMU%" (
    echo [X] Android emulator not found: %EMU% >&2
    exit /b 1
)

start "Medium Phone API 36.1 - Performance" /high "%EMU%" ^
    -avd Medium_Phone_API_36.1 ^
    -no-snapshot-load ^
    -no-snapshot-save ^
    -no-boot-anim ^
    -cores 16 ^
    -memory 16384 ^
    -gpu host ^
    -use-host-vulkan ^
    -netfast ^
    -cache-size 512 ^
    -accel on ^
    -qemu -smp 16

timeout /t 5 /nobreak >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Process emulator,qemu-system-x86_64 -ErrorAction SilentlyContinue | ForEach-Object { try { $_.PriorityClass = 'High' } catch {} }"

echo [OK] Medium_Phone_API_36.1 started with high-performance emulator options.
