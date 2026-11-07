@echo off
setlocal
cd /d "%~dp0"
title Project Kira
if not exist .venv\Scripts\python.exe (
  echo ERROR: Setup has not been completed.
  echo Run install.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m kira.main
if errorlevel 1 (
  echo.
  echo Kira stopped because of an error. Copy this error text and send it.
  pause
)
