@echo off
cd /d "%~dp0"
title JARVIS V6 Shortcut Repair
py install.py --shortcut-only
if errorlevel 1 (
  echo.
  echo Shortcut repair failed. Copy the error above.
)
pause
