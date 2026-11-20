@echo off
rem Run a stable copy: this updater replaces itself when it checks out new-main.
rem The first (bootstrap) process launches the temporary copy in a separate console,
rem then exits before Git can overwrite the original .bat file.
if /I "%KIRA_UPDATER_BOOTSTRAPPED%"=="1" goto :updater_run
set "KIRA_UPDATER_BOOTSTRAPPED=1"
set "KIRA_UPDATER_ORIGINAL_DIR=%~dp0"
set "KIRA_UPDATER_TEMP=%TEMP%\KiraUpdater_%RANDOM%_%RANDOM%.bat"
copy /y "%~f0" "%KIRA_UPDATER_TEMP%" >nul
if errorlevel 1 (
  echo [ERROR] Could not create a stable temporary copy of the updater.
  pause
  exit /b 1
)
start "Project Kira Updater" "%ComSpec%" /d /c ""%KIRA_UPDATER_TEMP%" %*"
exit /b 0

:updater_run
setlocal EnableExtensions
cd /d "%KIRA_UPDATER_ORIGINAL_DIR%"
title Project Kira - Auto Updater

set "REPO_URL=https://github.com/alizesta/Kira.git"
set "BRANCH=new-main"
set "KIRA_NO_PAUSE=1"
set "KIRA_INSTALL_PATH_FILE=%LOCALAPPDATA%\ProjectKira\install_path.txt"
if exist "%KIRA_INSTALL_PATH_FILE%" set /p "KIRA_DATA_DIR="<"%KIRA_INSTALL_PATH_FILE%"
if not defined KIRA_DATA_DIR if exist "A:\Project KIRA\Kira Attachments" set "KIRA_DATA_DIR=A:\Project KIRA\Kira Attachments"
if not defined KIRA_DATA_DIR set "KIRA_DATA_DIR=%LOCALAPPDATA%\Kira"
rem install.bat detects and copies the user's existing Ollama store before switching it to Kira's data folder.

where git >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Git is not installed or not in PATH.
  echo Please install Git for Windows from https://git-scm.com/download/win
  pause
  exit /b 1
)

echo ============================================
echo   Project Kira - Auto Update ^(%BRANCH%^)
echo ============================================
echo.

if not exist ".git" (
  echo [1/4] Connecting this folder to GitHub...
  git init
  if errorlevel 1 goto :git_fail
  git remote add origin "%REPO_URL%"
  if errorlevel 1 goto :git_fail
) else (
  git remote get-url origin >nul 2>&1
  if errorlevel 1 (
    git remote add origin "%REPO_URL%"
  )
)

echo [2/4] Fetching latest updates from origin/%BRANCH%...
git fetch origin "%BRANCH%"
if errorlevel 1 goto :git_fail

rem Preserve local tracked edits, including staged changes, before replacing program files.
git diff --quiet >nul 2>&1
set "WORKTREE_DIRTY=%ERRORLEVEL%"
git diff --cached --quiet >nul 2>&1
if errorlevel 1 set "WORKTREE_DIRTY=1"
if "%WORKTREE_DIRTY%"=="1" (
  echo [*] Backing up local tracked changes to git stash...
  git stash push -m "kira-auto-update-backup"
  if errorlevel 1 goto :git_fail
)

echo [3/5] Updating files to latest origin/%BRANCH%...
git show-ref --verify --quiet "refs/heads/%BRANCH%"
if not errorlevel 1 (
  for /f "tokens=1,2" %%A in ('git rev-list --left-right --count "%BRANCH%...origin/%BRANCH%"') do if not "%%A"=="0" goto :local_ahead
  git checkout "%BRANCH%"
  if errorlevel 1 goto :git_fail
  git merge --ff-only "origin/%BRANCH%"
  if errorlevel 1 goto :git_fail
) else (
  git checkout -b "%BRANCH%" "origin/%BRANCH%"
  if errorlevel 1 goto :git_fail
)

echo.
echo [4/5] Installing/updating all Kira dependencies, local speech engines and the verified uncensored model...
call install.bat
if errorlevel 1 goto :install_fail

echo.
echo [5/5] Compiling and running focused regression tests...
.venv\Scripts\python.exe -m compileall -q kira scripts
if errorlevel 1 goto :verify_fail
.venv\Scripts\python.exe -m unittest tests.test_brain_quality tests.test_router_routes tests.test_routes tests.test_local_chat_model_setup tests.test_installer_scripts
if errorlevel 1 goto :verify_fail

echo.
echo [OK] Kira updated, dependencies installed, local Qwen Abliterated model verified, and focused tests passed.
git log -1 --oneline
echo.
if not defined KIRA_NO_PAUSE pause
exit /b 0

:local_ahead
echo.
echo [ERROR] Local branch %BRANCH% contains commits not present on GitHub.
echo No local commits were overwritten. Push or back them up, then run Update again.
if not defined KIRA_NO_PAUSE pause
exit /b 1

:install_fail
echo.
echo [ERROR] Full setup failed. Kira was updated, but dependencies/model are not verified.
if not defined KIRA_NO_PAUSE pause
exit /b 1

:verify_fail
echo.
echo [ERROR] Compilation or focused regression tests failed. This update is not verified.
if not defined KIRA_NO_PAUSE pause
exit /b 1

:git_fail
echo.
echo [ERROR] Update failed. Check your internet connection and GitHub access.
if not defined KIRA_NO_PAUSE pause
exit /b 1
