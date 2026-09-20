@echo off
setlocal
cd /d "%~dp0"
set "GA_PYTHON=D:\Program\Anaconda\envs\game_assistant\python.exe"
if exist "%GA_PYTHON%" goto run
set "GA_PYTHON=python"
:run
"%GA_PYTHON%" "%~dp0app.py"
if errorlevel 1 pause
