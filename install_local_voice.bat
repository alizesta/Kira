@echo off
setlocal
cd /d "%~dp0"
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
set "HF_HOME=%LOCALAPPDATA%\Kira\huggingface"
if not exist "%HF_HOME%" mkdir "%HF_HOME%"
echo Using Python:
.venv\Scripts\python.exe --version
echo Model cache: %HF_HOME%
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
