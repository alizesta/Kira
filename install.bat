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
rem pip 23.1 introduced the dry-run resolver report used by install_deps.py.
python -c "import pip,sys; v=tuple(int(x) for x in pip.__version__.split('.')[:2]); sys.exit(0 if v >= (23,1) else 1)" >nul 2>nul
if errorlevel 1 (
  echo Updating pip only because the dependency resolver preflight requires pip 23.1 or newer...
  python -m pip install --upgrade "pip>=23.1,<27" --retries 10 --timeout 60
  if errorlevel 1 goto netfail
)

echo.
echo [DEPENDENCY LOCK] Preparing uv and generating reproducible Windows locks...
if defined KIRA_PYPI_INDEX (
  python -m pip install --upgrade uv --index-url "%KIRA_PYPI_INDEX%" --retries 10 --timeout 60
) else (
  python -m pip install --upgrade uv --retries 10 --timeout 60
)
if errorlevel 1 goto netfail
if not exist ".venv\Scripts\uv.exe" (
  echo ERROR: uv installation completed without creating .venv\Scripts\uv.exe.
  goto netfail
)
".venv\Scripts\uv.exe" --version
if errorlevel 1 goto netfail
python scripts\generate_dependency_locks.py --uv ".venv\Scripts\uv.exe"
if errorlevel 1 (
  echo ERROR: Reproducible dependency lock generation failed. Package installation was not started.
  goto netfail
)
echo [DEPENDENCY LOCK] Core locks are verified; optional locks are generated where resolvable.

echo.
echo [1/6] Resolving and installing core Kira dependencies...
python install_deps.py requirements.txt --constraints constraints.txt
if errorlevel 1 goto netfail

echo.
echo [2/6] Installing optional system and document integrations...
python install_deps.py requirements-system-optional.txt --constraints constraints.txt
if errorlevel 1 (
  echo WARNING: Optional system integrations are unavailable.
  set "SYSTEM_SETUP_FAILED=1"
)

echo.
echo [3/6] Installing optional local OCR Python dependencies...
python install_deps.py requirements-ocr.txt --constraints constraints.txt
if errorlevel 1 (
  echo WARNING: Python OCR dependencies are unavailable; other Kira features remain available.
  set "OCR_SETUP_FAILED=1"
)
python -m kira.vision_ocr --status
if errorlevel 1 set "OCR_RUNTIME_SETUP_FAILED=1"

echo.
echo [4/6] Installing optional microphone and audio dependencies as one group...
if exist voice_failed.txt del voice_failed.txt
python install_deps.py requirements-audio.txt --constraints constraints.txt
if errorlevel 1 (
  echo WARNING: Optional audio dependencies are unavailable.
  set "AUDIO_SETUP_FAILED=1"
)

echo.
echo [5/6] Installing local Persian STT/TTS and downloading their models...
echo Installing only Shenava INT8 for offline speech recognition.
.venv\Scripts\python.exe scripts\setup_local_voice.py --install --prepare-models
if errorlevel 1 (
  echo WARNING: Local voice setup reported an error. Kira core installation will continue.
  set "VOICE_SETUP_FAILED=1"
)

echo.
echo [6/6] Checking optional Ollama local runtime and model setup...
python -m kira.setup_manager --interactive
if errorlevel 1 (
  echo WARNING: Ollama setup is incomplete. Kira core installation remains available.
  set "OLLAMA_SETUP_FAILED=1"
)

:install_done
echo.
echo ============================================================
echo                    KIRA SETUP FINISHED
echo ============================================================
echo Data folder: %KIRA_DATA_DIR%
echo Future updates will reuse this folder automatically.
if defined VOICE_SETUP_FAILED echo WARNING: Local voice setup needs attention.
if defined AUDIO_SETUP_FAILED echo WARNING: Optional audio dependencies need attention.
if defined OCR_SETUP_FAILED echo WARNING: OCR Python dependencies need attention; other Vision features remain available.
if defined OCR_RUNTIME_SETUP_FAILED echo WARNING: Native OCR runtime or required language data is incomplete; other Vision features remain available.
if defined SYSTEM_SETUP_FAILED echo WARNING: Optional system integrations need attention.
if defined OLLAMA_SETUP_FAILED echo WARNING: Local Ollama setup needs attention; rerun python -m kira.setup_manager --interactive.
echo OCR native engine and language data are detected, not silently installed.
echo Persian OCR requires the Tesseract fas language pack; English requires eng.
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
