@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

:: ── 仓库根（MBTI\MLP 的上两级 = PonyChat 根，含 misc\tools）────────────────
set "REPO=%~dp0..\..\"

:: ── 绿色部署（不暂停，完成后直接启动开发服务）─────────────────────────────
call "%REPO%Backend\scripts\launch\AAA_deploy_portable.bat" --no-pause

:: ── 查找便携 Python（与主项目共用 misc\tools\python\）────────────────────
set "PY_EXE="
if exist "%REPO%misc\tools\python\python.exe" (
  set "PY_EXE=%REPO%misc\tools\python\python.exe"
) else (
  for /d %%D in ("%REPO%misc\tools\python\python-3.*") do (
    if exist "%%D\python.exe" if not defined PY_EXE set "PY_EXE=%%D\python.exe"
  )
)

if defined PY_EXE (
  "%PY_EXE%" "%~dp0misc\start_dev.py"
) else (
  python "%~dp0misc\start_dev.py"
)
if errorlevel 1 pause
endlocal
