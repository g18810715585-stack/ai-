@echo off
setlocal

cd /d "%~dp0"

set "NODE_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
if not exist "%NODE_EXE%" set "NODE_EXE=node"

if not exist ".runs" mkdir ".runs"

start "AI Meta Agent Panel Server" cmd /k ""%NODE_EXE%" src\cli.mjs server --port 4321"
timeout /t 2 /nobreak >nul
start "" "http://127.0.0.1:4321"

