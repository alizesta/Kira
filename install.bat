@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Project Kira - One Click Setup
echo ============================================================
echo                 PROJECT KIRA - ONE CLICK SETUP
echo ============================================================
echo.

rem The install-state file survives application updates and ZIP replacement.
set "KIRA_INSTALL_STATE=%LOCALAPPDATA%\ProjectKira"
set "KIRA_INSTALL_PATH_FILE=%KIRA_INSTALL_STATE%\install_path.txt"
if not exist "%KIRA_INSTALL_STATE%" mkdir "%KIRA_INSTALL_STATE%"
if exist "%KIRA_INSTALL_PATH_FILE%" set /p "KIRA_DATA_DIR="<"%KIRA_INSTALL_PATH_FILE%"

rem Recover the data location used by older releases before asking anything.
if not defined KIRA_DATA_DIR if exist "A:\Project KIRA\Kira Attachments\settings.json" set "KIRA_DATA_DIR=A:\Project KIRA\Kira Attachments"
if not defined KIRA_DATA_DIR if exist "A:\Project KIRA\Kira Attachments\huggingface" set "KIRA_DATA_DIR=A:\Project KIRA\Kira Attachments"
if not defined KIRA_DATA_DIR if exist "%LOCALAPPDATA%\Kira\settings.json" set "KIRA_DATA_DIR=%LOCALAPPDATA%\Kira"
if not defined KIRA_DATA_DIR if exist "%LOCALAPPDATA%\Kira\huggingface" set "KIRA_DATA_DIR=%LOCALAPPDATA%\Kira"
if not defined KIRA_DATA_DIR if exist "%~dp0data\settings.json" set "KIRA_DATA_DIR=%~dp0data"

if defined KIRA_DATA_DIR goto save_data_path
if exist "A:\" (
  set "KIRA_DEFAULT_DATA_DIR=A:\Project KIRA\Kira Attachments"
) else (
  set "KIRA_DEFAULT_DATA_DIR=%LOCALAPPDATA%\ProjectKira\Data"
)
echo First installation. Choose the permanent data folder:
echo   [1] Default: %KIRA_DEFAULT_DATA_DIR%
echo   [2] Choose a custom folder
choice /C 12 /N /M "Select [1/2]: "
if errorlevel 2 goto choose_custom
set "KIRA_DATA_DIR=%KIRA_DEFAULT_DATA_DIR%"
goto save_data_path

:choose_custom
echo.
set /p "KIRA_DATA_DIR=Enter the full folder path: "
if not defined KIRA_DATA_DIR goto fail

:save_data_path
if not exist "%KIRA_DATA_DIR%" mkdir "%KIRA_DATA_DIR%"
if errorlevel 1 goto fail
powershell -NoProfile -Command "[IO.File]::WriteAllText($env:KIRA_INSTALL_PATH_FILE, $env:KIRA_DATA_DIR)"
if errorlevel 1 goto fail

set "HF_HOME=%KIRA_DATA_DIR%\huggingface"
set "HUGGINGFACE_HUB_CACHE=%KIRA_DATA_DIR%\huggingface\hub"
set "HF_HUB_CACHE=%KIRA_DATA_DIR%\huggingface\hub"
set "TORCH_HOME=%KIRA_DATA_DIR%\cache\torch"
set "XDG_CACHE_HOME=%KIRA_DATA_DIR%\cache"
set "PIP_CACHE_DIR=%KIRA_DATA_DIR%\cache\pip"
if not exist "%HF_HOME%" mkdir "%HF_HOME%"
if not exist "%KIRA_DATA_DIR%\cache" mkdir "%KIRA_DATA_DIR%\cache"
echo.
echo Kira data, settings, chats and model downloads:
echo   %KIRA_DATA_DIR%
echo This location is remembered for future updates.
echo.

rem Python 3.11/3.12 is required by the local speech runtime.
rem Reuse a compatible existing venv first; otherwise accept only a verified system interpreter.
set "PY="
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -c "import sys; sys.exit(0 if (3,11)<=sys.version_info[:2]<=(3,12) else 1)" >nul 2>nul
  if not errorlevel 1 set "PY=.venv\Scripts\python.exe"
)
if not defined PY py -3.12 -c "import sys" >nul 2>nul && set "PY=py -3.12"
if not defined PY py -3.11 -c "import sys" >nul 2>nul && set "PY=py -3.11"
if not defined PY (
  where python >nul 2>nul
  if not errorlevel 1 (
    python -c "import sys; sys.exit(0 if (3,11)<=sys.version_info[:2]<=(3,12) else 1)" >nul 2>nul
    if not errorlevel 1 set "PY=python"
  )
)
if not defined PY (
  echo Python was not found. Trying automatic Python 3.12 installation...
  where winget >nul 2>nul
  if errorlevel 1 (
    echo ERROR: Python is missing and Windows Package Manager is unavailable.
    goto fail
  )
  winget install --id Python.Python.3.12 --exact --silent --accept-package-agreements --accept-source-agreements
  if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
  if not defined PY if exist "%ProgramFiles%\Python312\python.exe" set "PY=%ProgramFiles%\Python312\python.exe"
  if not defined PY py -3.12 -c "import sys" >nul 2>nul && set "PY=py -3.12"
)
if not defined PY (
  echo ERROR: Could not install or locate Python 3.11/3.12.
  goto fail
)
echo Using: %PY%
%PY% --version
set "GOOD=0"
%PY% -c "import sys; sys.exit(0 if (3,11)<=sys.version_info[:2]<=(3,12) else 1)" >nul 2>nul
if not errorlevel 1 set "GOOD=1"

if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -c "import sys; sys.exit(0 if (3,11)<=sys.version_info[:2]<=(3,12) else 1)" >nul 2>nul
  if errorlevel 1 (
    echo Recreating incompatible Python environment...
    rmdir /s /q .venv
  )
)
if not exist .venv\Scripts\python.exe (
  if "%GOOD%"=="1" (
    %PY% -m venv .venv
  ) else (
    echo Preparing a private Python 3.12 runtime...
    if not exist .uvboot\Scripts\python.exe %PY% -m venv .uvboot
    .uvboot\Scripts\python.exe -m pip install --upgrade --retries 10 --timeout 60 uv
    if not errorlevel 1 .uvboot\Scripts\uv.exe venv --seed --python 3.12 .venv
  )
)
if not exist .venv\Scripts\python.exe goto fail
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip --retries 10 --timeout 60
if errorlevel 1 goto netfail

echo.
echo [1/4] Installing core Kira dependencies...
python install_deps.py requirements.txt
if errorlevel 1 goto netfail

echo.
echo [2/4] Installing microphone and speech support...
if exist voice_failed.txt del voice_failed.txt
set "PKGS=sounddevice PyAudioWPatch miniaudio"
for %%P in (%PKGS%) do (
  echo --- %%P
  python -m pip install --upgrade --retries 10 --timeout 60 %%P
  if errorlevel 1 echo %%P>>voice_failed.txt
)

echo.
echo [3/4] Installing local Persian STT/TTS and downloading their models...
echo Qwen ASR and its dependencies may require several GB of downloads.
.venv\Scripts\python.exe scripts\setup_local_voice.py --install --prepare-models
if errorlevel 1 (
  echo WARNING: Local voice setup reported an error. Kira core installation will continue.
  set "VOICE_SETUP_FAILED=1"
)

echo.
echo [4/4] Installing/configuring Ollama and the default local chat model...
where ollama >nul 2>nul
if errorlevel 1 (
  where winget >nul 2>nul
  if errorlevel 1 (
    echo ERROR: winget is unavailable; Ollama cannot be installed automatically.
    goto fail
  )
  winget install --id Ollama.Ollama --exact --silent --accept-package-agreements --accept-source-agreements
  if exist "%LOCALAPPDATA%\Programs\Ollama\ollama.exe" set "PATH=%PATH%;%LOCALAPPDATA%\Programs\Ollama"
  if exist "%ProgramFiles%\Ollama\ollama.exe" set "PATH=%PATH%;%ProgramFiles%\Ollama"
  where ollama >nul 2>nul
  if errorlevel 1 (
    echo ERROR: Ollama was not found after its installation attempt.
    goto fail
  )
)

set "OLLAMA_TARGET=%KIRA_DATA_DIR%\ollama\models"
if not exist "%OLLAMA_TARGET%" mkdir "%OLLAMA_TARGET%"
if defined OLLAMA_MODELS (set "OLLAMA_SOURCE=%OLLAMA_MODELS%") else (set "OLLAMA_SOURCE=%USERPROFILE%\.ollama\models")
if exist "%OLLAMA_SOURCE%\" if /I not "%OLLAMA_SOURCE%"=="%OLLAMA_TARGET%" (
  echo Copying existing Ollama models. The old folder will be kept.
  robocopy "%OLLAMA_SOURCE%" "%OLLAMA_TARGET%" /E /COPY:DAT /DCOPY:DAT /R:1 /W:1
  if errorlevel 8 echo WARNING: Existing Ollama model copy failed; original files remain untouched.
)
set "OLLAMA_MODELS=%OLLAMA_TARGET%"
setx OLLAMA_MODELS "%OLLAMA_TARGET%" >nul
echo Ollama models: %OLLAMA_TARGET%
echo Restarting Ollama to apply the new storage location...
taskkill /IM ollama.exe /F >nul 2>nul
timeout /t 2 /nobreak >nul
start "" /b ollama serve
timeout /t 8 /nobreak >nul
ollama list >nul 2>nul
if errorlevel 1 (
  echo ERROR: Ollama service did not start.
  goto fail
)
if /I "%KIRA_SKIP_OLLAMA_MODEL_DOWNLOAD%"=="1" (
  echo [SKIP] Ollama model download is disabled for incremental updates.
) else (
  echo Installing the pinned, checksum-verified Qwen3.5-9B Abliterated Q4_K_M model...
  .venv\Scripts\python.exe scripts\setup_local_chat_model.py
  if errorlevel 1 goto fail
)

:install_done
echo.
echo ============================================================
echo                    KIRA SETUP FINISHED
echo ============================================================
echo Data folder: %KIRA_DATA_DIR%
echo Future updates will reuse this folder automatically.
if defined VOICE_SETUP_FAILED echo WARNING: Local voice setup needs attention.
if exist voice_failed.txt (
  echo Some optional audio packages failed:
  type voice_failed.txt
)
echo Start Kira with start_kira.vbs (no CMD window).
if not defined KIRA_NO_PAUSE pause
exit /b 0

:netfail
echo.
echo DOWNLOAD FAILED. Check internet/DNS and free disk space.
echo Run install.bat again; completed downloads will be reused.
goto fail

:fail
echo.
echo SETUP DID NOT COMPLETE. Copy the error text above for troubleshooting.
if not defined KIRA_NO_PAUSE pause
exit /b 1
