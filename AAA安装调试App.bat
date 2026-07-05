@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

:: ── 绿色部署（不暂停，完成后直接进入安装调试）─────────────────────────
call "%~dp0Backend\scripts\launch\AAA_deploy_portable.bat" --no-pause

:: ── 仓库根（与本 bat 同目录 = PonyChat 根目录，含 misc\tools；与 deploy 的 PROJECT_ROOT 一致）──
set "REPO=%~dp0"

:: ── 查找便携 Python ────────────────────────────────────────────────────
:: 查找顺序：P:\Tools（全局工具盘）→ misc\tools（旧版项目内嵌）→ misc\tools 子目录
set "PYTHON_EXE="
if exist "P:\Tools\python\python.exe" (
    set "PYTHON_EXE=P:\Tools\python\python.exe"
) else if exist "%REPO%misc\tools\python\python.exe" (
    set "PYTHON_EXE=%REPO%misc\tools\python\python.exe"
) else (
    for /d %%D in ("%REPO%misc\tools\python\python-3.*") do (
        if not defined PYTHON_EXE (
            if exist "%%D\python.exe" set "PYTHON_EXE=%%D\python.exe"
        )
    )
)
if not defined PYTHON_EXE (
    echo [X] Python not found. Checked: P:\Tools\python\python.exe, %REPO%misc\tools\python\python.exe >&2
    exit /b 1
)

:: ── 安装调试 App ───────────────────────────────────────────────────────
set "SCRIPT=%REPO%Backend\scripts\launch\AAA_install_debug_app.py"
if not exist "%SCRIPT%" (
    echo [X] Script not found: %SCRIPT% >&2
    exit /b 1
)
"%PYTHON_EXE%" "%SCRIPT%" %*
exit /b %ERRORLEVEL%
