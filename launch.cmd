@echo off
REM One-command source bootstrap on Windows; does not install system drivers.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  where py >nul 2>nul
  if errorlevel 1 (
    echo Python 3.10 or later is required. Please install Python first.
    exit /b 1
  )
  py -3 -m venv .venv
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m pip show 5imic >nul 2>nul
if errorlevel 1 (
  ".venv\Scripts\python.exe" -m pip install .
  if errorlevel 1 exit /b 1
)
".venv\Scripts\python.exe" -m fiveimic %*
