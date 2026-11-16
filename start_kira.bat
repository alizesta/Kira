@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Project Kira

rem Use the exact data folder saved by install.bat.
set "KIRA_INSTALL_PATH_FILE=%LOCALAPPDATA%\ProjectKira\install_path.txt"
if exist "%KIRA_INSTALL_PATH_FILE%" set /p "KIRA_DATA_DIR="<"%KIRA_INSTALL_PATH_FILE%"
if not defined KIRA_DATA_DIR (
  if exist "A:\Project KIRA\Kira Attachments" (
    set "KIRA_DATA_DIR=A:\Project KIRA\Kira Attachments"
  ) else (
    set "KIRA_DATA_DIR=%LOCALAPPDATA%\Kira"
  )
)
if not exist "%KIRA_DATA_DIR%" mkdir "%KIRA_DATA_DIR%"
set "HF_HOME=%KIRA_DATA_DIR%\huggingface"
set "HUGGINGFACE_HUB_CACHE=%KIRA_DATA_DIR%\huggingface\hub"
set "HF_HUB_CACHE=%KIRA_DATA_DIR%\huggingface\hub"
set "TORCH_HOME=%KIRA_DATA_DIR%\cache\torch"
set "XDG_CACHE_HOME=%KIRA_DATA_DIR%\cache"
set "PIP_CACHE_DIR=%KIRA_DATA_DIR%\cache\pip"
if not exist "%HF_HOME%" mkdir "%HF_HOME%"

if not exist .venv\Scripts\python.exe (
  echo ERROR: Setup has not been completed. Run install.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m kira.main
if errorlevel 1 (
  echo.
  echo Kira stopped because of an error. Copy this error text and send it.
  pause
)
