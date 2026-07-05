@echo off
setlocal
REM cd to repo root (same level as misc/, Backend/, Android-App/)
cd /d "%~dp0..\..\.."

set "REPO=%~dp0..\..\..\"
set "PYEXE="
if exist "P:\Tools\python\python.exe"          set "PYEXE=P:\Tools\python\python.exe"
if not defined PYEXE if exist "%REPO%misc\tools\python\python.exe" set "PYEXE=%REPO%misc\tools\python\python.exe"

if not defined PYEXE (
    echo [X] Python not found. Checked: P:\Tools\python\python.exe, %REPO%misc\tools\python\python.exe
    exit /b 1
)

"%PYEXE%" "scripts\ops\deploy_portable.py" %*
exit /b %ERRORLEVEL%
