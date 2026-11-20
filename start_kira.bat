@echo off
setlocal EnableExtensions
cd /d "%~dp0"

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
if not exist "%KIRA_DATA_DIR%\logs" mkdir "%KIRA_DATA_DIR%\logs"
set "KIRA_LAUNCH_LOG=%KIRA_DATA_DIR%\logs\launcher.log"

if not exist ".venv\Scripts\pythonw.exe" (
  >>"%KIRA_LAUNCH_LOG%" echo [%date% %time%] ERROR: pythonw.exe missing. Run install.bat again.
  exit /b 1
)

rem Keep the launcher log bounded; the in-app Logs tab also receives live output.
powershell -NoProfile -Command "$p=$env:KIRA_LAUNCH_LOG; if ((Test-Path -LiteralPath $p) -and (Get-Item -LiteralPath $p).Length -gt 5242880) { Move-Item -LiteralPath $p -Destination ($p + '.1') -Force }" >nul 2>&1
>>"%KIRA_LAUNCH_LOG%" echo.
>>"%KIRA_LAUNCH_LOG%" echo ===== Kira started %date% %time% =====

rem pythonw prevents a persistent console window; redirected streams preserve diagnostics.
".venv\Scripts\pythonw.exe" -m kira.main >>"%KIRA_LAUNCH_LOG%" 2>&1
