@echo off
setlocal

cd /d "%~dp0"

if not exist ".runs" mkdir ".runs"

set "PANEL_URL=http://127.0.0.1:4321"
set "HEALTH_URL=http://127.0.0.1:4321/api/health"
set "NODE_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
if not exist "%NODE_EXE%" set "NODE_EXE=node"

call :check_health
if not errorlevel 1 goto open_existing

echo Starting AI Meta Agent panel...
echo.
echo Keep this window open while using the panel.
echo Closing this window will stop http://127.0.0.1:4321.
echo.

"%NODE_EXE%" src\cli.mjs server --port 4321 --open
set "EXIT_CODE=%errorlevel%"

echo.
echo AI Meta Agent panel stopped. Exit code: %EXIT_CODE%
pause
exit /b %EXIT_CODE%

:open_existing
start "" "%PANEL_URL%"
exit /b 0

:check_health
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri '%HEALTH_URL%' -TimeoutSec 1; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }"
exit /b %errorlevel%
