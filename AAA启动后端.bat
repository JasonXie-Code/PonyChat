@echo off
setlocal
cd /d "%~dp0"

:: ── 绿色部署（不暂停，完成后直接启动后端）─────────────────────────────
call "%~dp0Backend\scripts\launch\AAA_deploy_portable.bat" --no-pause

:: ── 仓库根（与本 bat 同目录 = PonyChat 根目录，含 misc\tools；与 deploy 的 PROJECT_ROOT 一致）──
set "REPO=%~dp0"

:: ── 查找共享 Python ────────────────────────────────────────────────────
set "PYTHON_EXE="
if exist "P:\Tools\python\python.exe" set "PYTHON_EXE=P:\Tools\python\python.exe"
if not defined PYTHON_EXE (
    echo [X] Python not found: P:\Tools\python\python.exe >&2
    exit /b 1
)

:: ── 启动后端 ──────────────────────────────────────────────────────────
set "SCRIPT=%REPO%Backend\scripts\launch\AAA_launch_backend.py"
if not exist "%SCRIPT%" (
    echo [X] Script not found: %SCRIPT% >&2
    exit /b 1
)
"%PYTHON_EXE%" "%SCRIPT%" %*
exit /b %ERRORLEVEL%
