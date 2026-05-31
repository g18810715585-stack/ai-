@echo off
setlocal

cd /d "%~dp0"

if not exist ".runs" mkdir ".runs"

set "PANEL_URL=http://127.0.0.1:4321"
set "NODE_EXE=%USERPROFILE%\.cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
if not exist "%NODE_EXE%" set "NODE_EXE=node"

call :check_panel
if not errorlevel 1 goto open_existing

call :cleanup_stale_pid

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

:check_panel
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$base='%PANEL_URL%';" ^
  "$health=Invoke-RestMethod -Uri ($base + '/api/health') -TimeoutSec 2;" ^
  "$tables=Invoke-RestMethod -Uri ($base + '/api/table-options') -TimeoutSec 2;" ^
  "$html=(Invoke-WebRequest -UseBasicParsing -Uri $base -TimeoutSec 2).Content;" ^
  "$app=(Invoke-WebRequest -UseBasicParsing -Uri ($base + '/app.js') -TimeoutSec 2).Content;" ^
  "$invalidCount = @($tables.tables | Where-Object { $_.name -notmatch '^[A-Za-z][A-Za-z0-9_]*$' }).Count;" ^
  "$firstCommon = @($tables.tables | Where-Object { $_.is_common } | Select-Object -First 1)[0];" ^
  "if (-not $health.ok) { throw 'health failed' }" ^
  "if (($tables.table_count -as [int]) -lt 1) { throw 'table-options missing' }" ^
  "if ($invalidCount -gt 0) { throw 'table-options has invalid names' }" ^
  "if (-not $firstCommon -or $firstCommon.frequency_tier -ne 'core') { throw 'table-options tier order failed' }" ^
  "if (-not ($html.Contains('targetDialog') -and $html.Contains('experienceDialog') -and $html.Contains('relationsBtn') -and $html.Contains('relationsTab') -and $html.Contains('diagnosticsTab') -and $html.Contains('teachBtn') -and $html.Contains('saveExperienceBtn') -and $html.Contains('openExperienceDialog') -and $html.Contains('experienceSummaryText') -and $html.Contains('activityPlanBtn') -and $html.Contains('planTab') -and $html.Contains('confirmationsTab') -and $html.Contains('internal-manifest') -and ($html.IndexOf('manifest-field') -lt 0))) { throw 'panel html is stale' }" ^
  "if (-not ($app.Contains('serverCommonTables') -and $app.Contains('tablePresetVersion') -and $app.Contains('tableTierLabels') -and $app.Contains('compactRelationshipMap') -and $app.Contains('compactDraftDiagnostics') -and $app.Contains('compactConfigPlan') -and $app.Contains('compactExperienceSummary') -and $app.Contains('loadSavedExperiences') -and $app.Contains('setActionBusy'))) { throw 'app.js is stale' }" ^
  "exit 0"
exit /b %errorlevel%

:cleanup_stale_pid
set "PID_FILE=.runs\panel-4321.pid"
if not exist "%PID_FILE%" exit /b 0
set /p PANEL_PID=<"%PID_FILE%"
if not "%PANEL_PID%"=="" taskkill /PID %PANEL_PID% /F >nul 2>nul
del "%PID_FILE%" >nul 2>nul
exit /b 0
