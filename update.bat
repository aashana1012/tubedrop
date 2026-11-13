@echo off
setlocal
cd /d "%~dp0"
title TubeDrop - update download engine

if not exist ".venv\Scripts\python.exe" (
  echo TubeDrop is not set up yet. Run start.bat first.
  pause
  exit /b 1
)

echo Updating the download engine (yt-dlp)...
".venv\Scripts\python.exe" -m pip install --upgrade "yt-dlp[default]"
echo.
echo Done. Close TubeDrop if it is open, then run start.bat again.
pause
