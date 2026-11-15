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

title Kira - Local Persian Voice Setup
echo ==========================================
echo       Kira - Local Persian Voice Setup
echo ==========================================
echo.
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: Kira virtual environment was not found.
  echo Run install.bat first, then run this file again.
  pause
  exit /b 1
)
echo Using Python:
.venv\Scripts\python.exe --version
echo Kira data and model cache: %KIRA_DATA_DIR%
echo.
echo This installs packages and downloads the Qwen ASR model.
echo The first download can be several GB. Keep this window open.
echo.
.venv\Scripts\python.exe scripts\setup_local_voice.py --install --prepare-models
if errorlevel 1 (
  echo.
  echo SETUP FAILED. Copy the error above for diagnosis.
) else (
  echo.
  echo Local voice packages and model files are ready.
  echo Open Kira - Settings - Sound and Microphone.
  echo Use Check Status, Load Qwen and Test Persian Voice.
)
pause
