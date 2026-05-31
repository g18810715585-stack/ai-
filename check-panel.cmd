@echo off
setlocal

cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$base='http://127.0.0.1:4321';" ^
  "try {" ^
  "  $health=Invoke-RestMethod -Uri ($base + '/api/health') -TimeoutSec 2;" ^
  "  $tables=Invoke-RestMethod -Uri ($base + '/api/table-options') -TimeoutSec 2;" ^
  "  $html=(Invoke-WebRequest -UseBasicParsing -Uri $base -TimeoutSec 2).Content;" ^
  "  $appResp=Invoke-WebRequest -UseBasicParsing -Uri ($base + '/app.js') -TimeoutSec 2;" ^
  "  $app=$appResp.Content;" ^
  "  $appReady = $app.Contains('serverCommonTables') -and $app.Contains('tablePresetVersion') -and $app.Contains('tableTierLabels') -and $app.Contains('compactRelationshipMap') -and $app.Contains('setActionBusy');" ^
  "  $invalidCount = @($tables.tables | Where-Object { $_.name -notmatch '^[A-Za-z][A-Za-z0-9_]*$' }).Count;" ^
  "  $firstCommon = @($tables.tables | Where-Object { $_.is_common } | Select-Object -First 1)[0];" ^
  "  $tierOrderOk = $firstCommon -and ($firstCommon.frequency_tier -eq 'core');" ^
  "  $htmlReady = $html.Contains('targetDialog') -and $html.Contains('relationsBtn') -and $html.Contains('relationsTab') -and $html.Contains('internal-manifest') -and ($html.IndexOf('manifest-field') -lt 0);" ^
  "  $ok = $health.ok -and (($tables.table_count -as [int]) -gt 0) -and ($invalidCount -eq 0) -and $htmlReady -and $appReady -and $tierOrderOk;" ^
  "  [pscustomobject]@{ reachable=$true; ok=$ok; pid=$health.pid; tableCount=$tables.table_count; commonCount=$tables.common_tables.Count; invalidNameCount=$invalidCount; firstCommon=$firstCommon.name; firstTier=$firstCommon.frequency_tier; tierOrderOk=$tierOrderOk; htmlReady=$htmlReady; appReady=$appReady; cacheControl=$appResp.Headers['Cache-Control'] } | ConvertTo-Json -Compress | Write-Host;" ^
  "  if ($ok) { exit 0 } else { exit 1 }" ^
  "} catch {" ^
  "  [pscustomobject]@{ reachable=$false; ok=$false; error=$_.Exception.Message } | ConvertTo-Json -Compress | Write-Host;" ^
  "  exit 1" ^
  "}"
