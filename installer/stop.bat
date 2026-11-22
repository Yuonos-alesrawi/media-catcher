@echo off
rem Stops Media Catcher if it is running in the background.
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -like '*MediaCatcher*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Media Catcher was stopped (if it was running).
timeout /t 2 >nul
