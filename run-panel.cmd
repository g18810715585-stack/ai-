@echo off
setlocal

cd /d "%~dp0"

set "NODE_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
if not exist "%NODE_EXE%" set "NODE_EXE=node"

"%NODE_EXE%" src\cli.mjs server --port 4321
set "EXIT_CODE=%errorlevel%"

echo.
echo AI Meta Agent panel stopped. Exit code: %EXIT_CODE%
echo Keep this window open while using the panel. If it closed unexpectedly, copy the error above.
pause
exit /b %EXIT_CODE%
