@echo off
setlocal EnableExtensions
title Kira - Move Ollama Models to A Drive

if not exist "A:\" (
  echo ERROR: Drive A: is not available.
  pause
  exit /b 1
)

set "TARGET=A:\Project KIRA\Kira Attachments\ollama\models"
if defined OLLAMA_MODELS (
  set "SOURCE=%OLLAMA_MODELS%"
) else (
  set "SOURCE=%USERPROFILE%\.ollama\models"
)

echo ============================================================
echo       Kira - Ollama Model Storage
echo ============================================================
echo.
echo Target:
echo   %TARGET%
echo.
echo Current model folder:
echo   %SOURCE%
echo.
echo This script will:
echo   1. Copy existing Ollama models to the A: drive (source is kept).
echo   2. Set the user-level OLLAMA_MODELS variable to the A: drive.
echo   3. Leave the original folder untouched.
echo.
echo IMPORTANT: Quit Ollama from the system tray before continuing.
echo The new path takes effect after Ollama is started again.
echo.
choice /C YN /N /M "Continue? [Y/N] "
if errorlevel 2 exit /b 0

if /I not "%SOURCE%"=="%TARGET%" if exist "%SOURCE%\" (
  echo.
  echo Copying existing model files. No source files will be deleted...
  if not exist "%TARGET%" mkdir "%TARGET%"
  robocopy "%SOURCE%" "%TARGET%" /E /COPY:DAT /DCOPY:DAT /R:1 /W:1
  if errorlevel 8 (
    echo.
    echo ERROR: Model copy failed. OLLAMA_MODELS was not changed.
    echo The original model folder remains untouched.
    pause
    exit /b 1
  )
) else (
  if not exist "%TARGET%" mkdir "%TARGET%"
)

echo.
echo Setting OLLAMA_MODELS for this Windows user...
setx OLLAMA_MODELS "%TARGET%" >nul
if errorlevel 1 (
  echo ERROR: Could not save the user environment variable.
  pause
  exit /b 1
)
echo.
echo SUCCESS.
echo OLLAMA_MODELS is now:
echo   %TARGET%
echo.
echo Now:
echo   1. Quit Ollama completely from its system tray icon.
echo   2. Start Ollama again from the Start menu.
echo   3. Run "ollama list" and check that your models appear.
echo.
echo If Ollama Desktop has a separate "Model location" setting,
echo set it to the same target folder before restarting Ollama.
echo The original model folder was NOT deleted.
pause
exit /b 0
