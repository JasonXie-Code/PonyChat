@echo off
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_qwen3tts_tunnel.ps1" %*
pause
