@echo off
setlocal
title Project Kira - Model Download
set "MODEL=%~1"
if "%MODEL%"=="" set "MODEL=qwen3.5:4b"
echo This downloads the local model "%MODEL%" using Ollama (about 3.4 GB for qwen3.5:4b).
echo Internet access and Ollama are required. Use the latest Ollama version.
echo.
where ollama >nul 2>nul
if errorlevel 1 (
  echo ERROR: Ollama was not found.
  echo Install it from https://ollama.com/ and try again.
  pause
  exit /b 1
)
ollama pull %MODEL%
if errorlevel 1 (
  echo Model download failed. Check the internet connection, the model name and the Ollama installation.
  echo If Ollama says the model needs a newer version, update Ollama from https://ollama.com/download
  pause
  exit /b 1
)
echo.
echo Model download completed. Installed models:
ollama list
echo.
echo After starting Kira, open Assistant settings, press "Check connection" and make sure the model runs on the GPU.
echo (Same information in CMD:  ollama ps  -> column PROCESSOR)
pause
