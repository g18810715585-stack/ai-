@echo off
setlocal

powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $r = Invoke-WebRequest -UseBasicParsing -Uri 'http://127.0.0.1:4321/api/health' -TimeoutSec 2; Write-Host 'Panel health OK:' $r.Content; exit 0 } catch { Write-Host 'Panel is not reachable at http://127.0.0.1:4321'; exit 1 }"
