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

title Project Kira Setup
echo =====================================
echo       Project Kira - Setup
echo =====================================
echo.

set "PY="
py -3.12 -c "import sys" >nul 2>nul && set "PY=py -3.12"
if not defined PY py -3.11 -c "import sys" >nul 2>nul && set "PY=py -3.11"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 set "PY=python"
)
if not defined PY (
  echo ERROR: Python was not found.
  echo Install Python from python.org and enable "Add Python to PATH".
  pause
  exit /b 1
)
echo Using: %PY%
%PY% --version

rem --- AI model cache is kept in the shared Kira data folder above.
echo Kira data and AI model cache: %KIRA_DATA_DIR%

set "GOOD=0"
%PY% -c "import sys; sys.exit(0 if (3,11)<=sys.version_info[:2]<=(3,12) else 1)" >nul 2>nul
if not errorlevel 1 set "GOOD=1"

rem --- keep an existing environment only if it is Python 3.11 or 3.12
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -c "import sys; sys.exit(0 if (3,11)<=sys.version_info[:2]<=(3,12) else 1)" >nul 2>nul
  if errorlevel 1 (
    echo Existing environment uses an unsuitable Python. Recreating it...
    rmdir /s /q .venv
  )
)

if not exist .venv\Scripts\python.exe (
  if "%GOOD%"=="1" (
    %PY% -m venv .venv
  ) else (
    echo.
    echo Your Python version is outside the supported range ^(3.11 or 3.12^).
    echo Downloading a private copy of Python 3.12 automatically. Please wait...
    if not exist .uvboot\Scripts\python.exe %PY% -m venv .uvboot
    .uvboot\Scripts\python.exe -m pip install --retries 10 --timeout 60 uv
    if not errorlevel 1 .uvboot\Scripts\uv.exe venv --seed --python 3.12 .venv
    if not exist .venv\Scripts\python.exe (
      echo ERROR: Could not install a supported Python 3.12 environment.
      echo Install Python 3.12 from python.org, then run install.bat again.
      goto fail
    )
  )
)
if not exist .venv\Scripts\python.exe goto fail

call .venv\Scripts\activate.bat
python --version
python -m pip install --upgrade pip --retries 10 --timeout 60

echo.
echo [1/3] Installing core packages...
python install_deps.py requirements.txt
if errorlevel 1 goto netfail

echo.
echo [2/3] Installing voice packages one by one...
if exist voice_failed.txt del voice_failed.txt
set "PKGS=Pillow sounddevice PyAudioWPatch edge-tts SpeechRecognition"
set "SKIPPED="
python -c "import sys; sys.exit(0 if sys.version_info[:2]<=(3,12) else 1)" >nul 2>nul
if errorlevel 1 (
  set "SKIPPED=1"
) else (
  set "PKGS=%PKGS% miniaudio faster-whisper"
)
for %%P in (%PKGS%) do (
  echo.
  echo --- %%P
  python -m pip install --retries 10 --timeout 60 %%P
  if errorlevel 1 echo %%P>>voice_failed.txt
)

echo.
echo =====================================
if exist voice_failed.txt (
  echo These packages FAILED to install:
  type voice_failed.txt
  echo Kira will still run. Missing packages only disable the related feature:
  echo   edge-tts = online voice ^(Windows offline voice is used instead^),
  echo   sounddevice = microphone, Pillow = sharper picture.
  echo If the error says "Failed to resolve", it is an internet or DNS problem.
  echo Fix it and run install.bat again; finished packages are skipped quickly.
) else (
  echo Setup completed successfully.
  if defined SKIPPED (
    echo Note: Python 3.12 could not be downloaded, so offline microphone and exact
    echo lip-sync were skipped. Kira uses online microphone and approximate lip-sync.
  )
)
echo.
echo [3/3] Optional local Persian voice engines
echo Qwen3-ASR and its runtime dependencies can require several GB of downloads.
echo Their Python packages will be installed in this Kira .venv.
echo Downloaded Hugging Face model files are kept in:
echo   %HF_HOME%
choice /C YN /N /M "Install local voice engines now? [Y/N] "
if errorlevel 2 goto voice_skip
if not exist requirements-voice-local.txt (
  echo ERROR: requirements-voice-local.txt was not found beside install.bat.
  echo Download the complete Kira branch archive and try again.
  goto voice_done
)
python -m pip install --retries 10 --timeout 60 -r requirements-voice-local.txt
if errorlevel 1 (
  echo Local voice engines could not be installed. Kira will continue without them.
  echo You can retry later by running:
  echo   .venv\Scripts\python.exe -m pip install -r requirements-voice-local.txt
) else (
  echo Local voice packages installed. Model weights download on first use.
)
goto voice_done
:voice_skip
echo Skipped local voice engines. You can install them later from this folder.
:voice_done
echo.
echo For local chat models, install Ollama, then run:
echo   configure_ollama_storage.bat
echo   download_model.bat
echo Restart Ollama from its tray icon after changing its model location.
echo Finally run start_kira.bat.
pause
exit /b 0

:netfail
echo.
echo DOWNLOAD FAILED. If you see "Failed to resolve" or "getaddrinfo failed",
echo this is a DNS or internet problem on this computer.
echo Try: change Windows DNS to 1.1.1.1 and 8.8.8.8, or use a VPN, then run install.bat again.
echo To test, open CMD and run:  nslookup files.pythonhosted.org
goto fail

:fail
echo.
echo SETUP FAILED. Copy the error text above and send it for troubleshooting.
pause
exit /b 1
