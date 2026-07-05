@echo off
chcp 65001 >nul
cd /d "%~dp0"
title PonyChat Main/frontend

if not exist "node_modules\" (
    echo [frontend] 首次运行：正在执行 npm install ...
    call npm install
    if errorlevel 1 (
        echo [frontend] 依赖安装失败，请确认已安装 Node.js 且 npm 可用。
        pause
        exit /b 1
    )
)

echo [frontend] 启动 Vite 开发服务器，浏览器可访问终端中提示的地址；按 Ctrl+C 停止。
call npm run dev
