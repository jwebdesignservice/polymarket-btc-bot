@echo off
cd /d "C:\Users\Jack\Desktop\AI Website\htdocs\Websites\Project Manager\polymarket-bot"

:loop
echo [%date% %time%] Starting bot...
py -u watchdog.py
echo [%date% %time%] Bot stopped, restarting in 5 seconds...
timeout /t 5 /nobreak
goto loop
