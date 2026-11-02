@echo off
cd /d "%~dp0"
title JARVIS V6 Installer
py install.py
if errorlevel 1 (
  echo.
  echo Installation failed. Copy the error above.
  pause
  exit /b 1
)
echo.
echo JARVIS V6 is ready on your Desktop.
pause
