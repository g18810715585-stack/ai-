@echo off
setlocal

cd /d "%~dp0"

set "PID_FILE=.runs\panel-4321.pid"

if not exist "%PID_FILE%" goto stop_by_port

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

:stop_by_port
for /f "usebackq delims=" %%P in (`powershell -NoProfile -ExecutionPolicy Bypass -Command "$c=Get-NetTCPConnection -LocalPort 4321 -ErrorAction SilentlyContinue | Select-Object -First 1; if ($c) { $c.OwningProcess }"`) do set "PORT_PID=%%P"
if "%PORT_PID%"=="" exit /b 0
taskkill /PID %PORT_PID% /F >nul 2>nul
if errorlevel 1 (
  echo Port 4321 process %PORT_PID% was not running.
) else (
  echo Stopped AI Meta Agent panel port process %PORT_PID%.
)
