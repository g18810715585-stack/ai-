@echo off
setlocal

cd /d "%~dp0"

set "PID_FILE=.runs\panel-4321.pid"

if not exist "%PID_FILE%" (
  echo No AI Meta Agent panel pid file found.
  echo If the port is still open, restart Windows or close the matching node.exe process.
  exit /b 0
)

set /p PANEL_PID=<"%PID_FILE%"
if "%PANEL_PID%"=="" (
  del "%PID_FILE%" >nul 2>nul
  echo Empty pid file removed.
  exit /b 0
)

taskkill /PID %PANEL_PID% /F >nul 2>nul
if errorlevel 1 (
  echo Panel process %PANEL_PID% was not running.
) else (
  echo Stopped AI Meta Agent panel process %PANEL_PID%.
)

del "%PID_FILE%" >nul 2>nul

