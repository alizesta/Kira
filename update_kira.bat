@echo off
rem Execute from a stable temporary copy so Git can replace this updater safely.
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
title Project Kira - Incremental Updater

set "REPO_URL=https://github.com/alizesta/Kira.git"
set "BRANCH=new-main"
set "KIRA_NO_PAUSE=1"
set "NEEDS_INSTALL=0"
set "KIRA_INSTALL_PATH_FILE=%LOCALAPPDATA%\ProjectKira\install_path.txt"
if exist "%KIRA_INSTALL_PATH_FILE%" set /p "KIRA_DATA_DIR="<"%KIRA_INSTALL_PATH_FILE%"
if not defined KIRA_DATA_DIR if exist "A:\Project KIRA\Kira Attachments" set "KIRA_DATA_DIR=A:\Project KIRA\Kira Attachments"
if not defined KIRA_DATA_DIR set "KIRA_DATA_DIR=%LOCALAPPDATA%\Kira"

where git >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Git is not installed or not in PATH.
  echo Install Git for Windows from https://git-scm.com/download/win
  pause
  exit /b 1
)

echo ============================================
echo   Project Kira - Incremental Update
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
  if errorlevel 1 git remote add origin "%REPO_URL%"
)

echo [1/4] Fetching new commits from origin/%BRANCH%...
git fetch --no-tags origin "+refs/heads/%BRANCH%:refs/remotes/origin/%BRANCH%"
if errorlevel 1 goto :git_fail

git show-ref --verify --quiet "refs/heads/%BRANCH%"
if errorlevel 1 (
  set "NEEDS_INSTALL=1"
  echo [FILES] First checkout: downloading the complete project once.
) else (
  echo [FILES] Files changed since your installed revision:
  git diff --name-status "%BRANCH%" "origin/%BRANCH%"
  rem Only setup/dependency changes trigger install.bat.
  for /f "delims=" %%F in ('git diff --name-only "%BRANCH%" "origin/%BRANCH%"') do (
    echo %%F| findstr /I /R /C:"^requirements.*\.txt$" >nul && set "NEEDS_INSTALL=1"
    if /I "%%F"=="install.bat" set "NEEDS_INSTALL=1"
    if /I "%%F"=="install_deps.py" set "NEEDS_INSTALL=1"
    if /I "%%F"=="scripts/setup_local_voice.py" set "NEEDS_INSTALL=1"
    if /I "%%F"=="scripts/setup_local_chat_model.py" set "NEEDS_INSTALL=1"
    if /I "%%F"=="pyproject.toml" set "NEEDS_INSTALL=1"
  )
)

echo.
echo [2/4] Preserving local tracked edits...
git diff --quiet >nul 2>&1
set "WORKTREE_DIRTY=%ERRORLEVEL%"
git diff --cached --quiet >nul 2>&1
if errorlevel 1 set "WORKTREE_DIRTY=1"
if "%WORKTREE_DIRTY%"=="1" (
  git stash push -m "kira-auto-update-backup"
  if errorlevel 1 goto :git_fail
)

echo [3/4] Downloading only changed project files...
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
echo [LATEST] Installed revision:
git log -1 --format="  %%h  %%cs  %%s"

if "%NEEDS_INSTALL%"=="1" (
  echo.
  echo [4/4] Setup files changed. Running dependency/model setup...
  call install.bat
  if errorlevel 1 goto :install_fail
) else (
  echo.
  echo [4/4] No dependency, setup, or model files changed.
  echo [SKIP] Skipping install.bat, package scans, model checks, downloads, compileall, and full test suite.
)

echo.
echo [OK] Incremental update completed.
echo Only files changed on origin/%BRANCH% were applied; unchanged dependencies and models were left untouched.
echo.
pause
exit /b 0

:local_ahead
echo.
echo [ERROR] Local branch %BRANCH% contains commits not present on GitHub.
echo No local commits were overwritten. Back up or push those commits, then retry.
pause
exit /b 1

:install_fail
echo.
echo [ERROR] Kira files were updated, but dependency/model setup failed.
pause
exit /b 1

:git_fail
echo.
echo [ERROR] Update failed. Check internet connection and GitHub access.
pause
exit /b 1
