@echo off
setlocal
cd /d "%~dp0"
rem --- Keep Kira data, speech models and runtime caches on the dedicated A: drive.
if exist "A:\" (
  set "KIRA_DATA_DIR=A:\Project KIRA\Kira Attachments"
) else (
  set "KIRA_DATA_DIR=%LOCALAPPDATA%\Kira"
  echo WARNING: Drive A: is unavailable. Kira data will use %KIRA_DATA_DIR%.
)
set "HF_HOME=%KIRA_DATA_DIR%\huggingface"
set "HUGGINGFACE_HUB_CACHE=%KIRA_DATA_DIR%\huggingface\hub"
set "HF_HUB_CACHE=%KIRA_DATA_DIR%\huggingface\hub"
set "TRANSFORMERS_CACHE=%KIRA_DATA_DIR%\huggingface\hub"
set "TORCH_HOME=%KIRA_DATA_DIR%\cache\torch"
set "XDG_CACHE_HOME=%KIRA_DATA_DIR%\cache"
set "PIP_CACHE_DIR=%KIRA_DATA_DIR%\cache\pip"
if not exist "%KIRA_DATA_DIR%" mkdir "%KIRA_DATA_DIR%"
if not exist "%HF_HOME%" mkdir "%HF_HOME%"

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
