@echo off
echo ============================================
echo OPENING POLYMARKET BOT DASHBOARD
echo ============================================
echo.
echo Dashboard URL: http://localhost:5000
echo.
echo Starting browser...
echo.

start http://localhost:5000

echo.
echo Dashboard opened in your default browser!
echo.
echo IMPORTANT: Keep the Flask server running in the background.
echo If the dashboard doesn't load, run: py dashboard\api.py
echo.
pause
