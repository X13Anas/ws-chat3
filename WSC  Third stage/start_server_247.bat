@echo off
title WS CHAT 24/7 AUTO-RESTART SERVER
color 0A
:SERVER_LOOP
echo =================================================================
echo        WS CHAT 24/7 LIVE SERVER RUNNER IS ACTIVE!
echo        Server Start Time: %date% %time%
echo =================================================================
python app.py
echo.
echo [WARNING] Server stopped or disconnected. Auto-restarting in 3 seconds...
timeout /t 3 /nobreak >nul
goto SERVER_LOOP
