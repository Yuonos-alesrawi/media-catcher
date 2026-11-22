@echo off
rem Builds MediaCatcher-Setup-<version>.exe  (needs internet; Inno Setup 6.3+ for the last step)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0build.ps1" %*
if errorlevel 1 (
  echo.
  echo BUILD FAILED - see the message above.
  pause
  exit /b 1
)
echo.
pause
