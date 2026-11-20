@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Project Kira - Auto Updater

set "REPO_URL=https://github.com/alizesta/Kira.git"
set "BRANCH=new-main"

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

rem Save any local edits to tracked files in stash without touching .venv, .env, settings, or databases.
git diff --quiet >nul 2>&1
if errorlevel 1 (
  echo [*] Backing up local tracked changes to git stash...
  git stash push -m "kira-auto-update-backup" >nul 2>&1
)

echo [3/4] Updating files to latest origin/%BRANCH%...
git checkout -f -B "%BRANCH%" "origin/%BRANCH%"
if errorlevel 1 goto :git_fail

if exist ".venv\Scripts\python.exe" (
  if exist "requirements.txt" (
    echo [4/4] Checking Python dependencies...
    .venv\Scripts\python.exe -m pip install --disable-pip-version-check -q -r requirements.txt
    if errorlevel 1 (
      echo [WARNING] Could not update some Python packages. Continuing...
    )
  )
  .venv\Scripts\python.exe -m compileall -q kira
) else (
  echo [4/4] Virtual environment .venv not found; skipping dependency check.
)

echo.
echo [OK] Kira is now up to date!
git log -1 --oneline
echo.
pause
exit /b 0

:git_fail
echo.
echo [ERROR] Update failed. Check your internet connection and GitHub access.
pause
exit /b 1
