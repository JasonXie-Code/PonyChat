@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=P:\Tools\python\python.exe"
if not exist "%PYTHON_EXE%" (
    echo [X] Python not found: .venv\Scripts\python.exe or P:\Tools\python\python.exe >&2
    exit /b 1
)
set "SCRIPT=%~dp0scripts\ops\root_launcher.py"
if not exist "%SCRIPT%" (
    echo [X] Launcher not found: %SCRIPT% >&2
    exit /b 1
)
"%PYTHON_EXE%" "%SCRIPT%" backend %*
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" if "%~1"=="" pause
exit /b %RESULT%
