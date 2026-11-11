@echo off
setlocal
cd /d "%~dp0"
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
    echo Your Python is too new for some Kira packages ^(voice, microphone^).
    echo Downloading a private copy of Python 3.12 automatically. Please wait...
    if not exist .uvboot\Scripts\python.exe %PY% -m venv .uvboot
    .uvboot\Scripts\python.exe -m pip install --retries 10 --timeout 60 uv
    if not errorlevel 1 .uvboot\Scripts\uv.exe venv --seed --python 3.12 .venv
    if not exist .venv\Scripts\python.exe (
      echo Could not download Python 3.12. Continuing with your own Python.
      %PY% -m venv .venv
    )
  )
)
if not exist .venv\Scripts\python.exe goto fail

call .venv\Scripts\activate.bat
python --version
python -m pip install --upgrade pip --retries 10 --timeout 60

echo.
echo [1/2] Installing core packages...
python install_deps.py requirements.txt
if errorlevel 1 goto netfail

echo.
echo [2/2] Installing voice packages one by one...
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
echo Next: install Ollama, run download_model.bat, then start_kira.bat.
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
