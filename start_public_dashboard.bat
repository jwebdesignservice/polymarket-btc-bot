@echo off
echo ================================================================
echo POLYMARKET BOT - PUBLIC DASHBOARD LAUNCHER
echo ================================================================
echo.
echo Starting Flask dashboard on localhost:5000...
echo Starting ngrok tunnel for public access...
echo.
echo IMPORTANT: Keep this window open while sharing the dashboard!
echo Press Ctrl+C to stop both services.
echo.
echo ================================================================
echo.

REM Start Flask in background
start /B py dashboard\api.py

REM Wait for Flask to start
timeout /t 3 /nobreak >nul

REM Start ngrok (will display public URL)
ngrok http 5000 --log=stdout
