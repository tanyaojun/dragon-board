@echo off
chcp 65001 >nul
title Stock Data System

echo ========================================
echo   Start Stock Data System
echo ========================================
echo.

:: Start proxy server (in subdirectory)
echo [1/2] Starting proxy server (port 3000)...
start "Proxy Server" cmd /k "cd /d D:\dragon-board\proxy-server && node server.js"

:: Wait 3 seconds
timeout /t 3 /nobreak >nul

:: Start frontend (in main directory)
echo [2/2] Starting frontend (port 5173)...
start "Frontend" cmd /k "cd /d D:\dragon-board && npm run dev"

:: Open browsers
timeout /t 5 /nobreak >nul
start http://localhost:3000
start http://localhost:5173

echo.
echo ? Startup complete!
echo   Proxy Server: http://localhost:3000
echo   Frontend: http://localhost:5173
echo.
pause