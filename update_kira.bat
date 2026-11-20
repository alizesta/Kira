@echo off
rem Run a stable temporary copy synchronously so the visible window stays open
rem and the original updater can safely be replaced by the Git update.
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
call "%KIRA_UPDATER_TEMP%" %*
set "KIRA_UPDATER_EXIT=%ERRORLEVEL%"
del /q "%KIRA_UPDATER_TEMP%" >nul 2>&1
exit /b %KIRA_UPDATER_EXIT%

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
  echo [1/5] Connecting this folder to GitHub...
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

echo [2/5] Fetching latest updates from origin/%BRANCH%...
git fetch origin "+refs/heads/%BRANCH%:refs/remotes/origin/%BRANCH%"
if errorlevel 1 goto :git_fail

rem Resolve and report the newest commit published on the update branch.
set "REMOTE_HEAD="
for /f %%H in ('git rev-parse "origin/%BRANCH%"') do set "REMOTE_HEAD=%%H"
if not defined REMOTE_HEAD goto :git_fail
echo.
echo [LATEST] Newest commit on origin/%BRANCH%:
git log -1 --format="  %%h  %%cs  %%s" "origin/%BRANCH%"
echo [LATEST] Files changed by that commit:
git show --format= --name-status --first-parent "origin/%BRANCH%"
echo.

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

echo [3/5] Detecting and downloading changed files from the latest merged updates...
git show-ref --verify --quiet "refs/heads/%BRANCH%"
if not errorlevel 1 (
  for /f "tokens=1,2" %%A in ('git rev-list --left-right --count "%BRANCH%...origin/%BRANCH%"') do if not "%%A"=="0" goto :local_ahead
  echo [FILES] Files changed since this installation's current commit:
  git diff --name-status "%BRANCH%" "origin/%BRANCH%"
  git checkout "%BRANCH%"
  if errorlevel 1 goto :git_fail
  git merge --ff-only "origin/%BRANCH%"
  if errorlevel 1 goto :git_fail
) else (
  echo [FILES] First checkout: downloading the complete current project snapshot.
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
pause
exit /b 0

:local_ahead
echo.
echo [ERROR] Local branch %BRANCH% contains commits not present on GitHub.
echo No local commits were overwritten. Push or back them up, then run Update again.
pause
exit /b 1

:install_fail
echo.
echo [ERROR] Full setup failed. Kira was updated, but dependencies/model are not verified.
pause
exit /b 1

:verify_fail
echo.
echo [ERROR] Compilation or focused regression tests failed. This update is not verified.
pause
exit /b 1

:git_fail
echo.
echo [ERROR] Update failed. Check your internet connection and GitHub access.
pause
exit /b 1
