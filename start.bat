@echo off
setlocal
cd /d "%~dp0"
title TubeDrop

if not exist ".venv\Scripts\python.exe" (
  echo Setting up TubeDrop for the first time. This takes about a minute...
  python -m venv .venv || goto :nopython
  ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :installfailed
)

".venv\Scripts\python.exe" run.py %*
if errorlevel 1 pause
goto :eof

:nopython
echo.
echo Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/
echo Tick "Add Python to PATH" during install, then run start.bat again.
pause
exit /b 1

:installfailed
echo.
echo Installing the required packages failed. Check your internet connection and run start.bat again.
pause
exit /b 1
