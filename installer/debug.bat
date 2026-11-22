@echo off
rem Runs Media Catcher in this window so any error is visible. Close the window to stop it.
cd /d "%~dp0"
echo Starting Media Catcher (debug mode, no tray icon)...
"%~dp0python\python.exe" "%~dp0app.py" --no-tray --no-update
echo.
echo Media Catcher stopped (exit code %errorlevel%). Log file: %LOCALAPPDATA%\MediaCatcher\app.log
pause
