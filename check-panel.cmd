@echo off
setlocal

cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop';" ^
  "$base='http://127.0.0.1:4321';" ^
  "try {" ^
  "  $health=Invoke-RestMethod -Uri ($base + '/api/health') -TimeoutSec 10;" ^
  "  $projects=Invoke-RestMethod -Uri ($base + '/api/projects') -TimeoutSec 10;" ^
  "  $tables=Invoke-RestMethod -Uri ($base + '/api/table-options') -TimeoutSec 10;" ^
  "  $html=(Invoke-WebRequest -UseBasicParsing -Uri $base -TimeoutSec 10).Content;" ^
  "  $appResp=Invoke-WebRequest -UseBasicParsing -Uri ($base + '/app.js') -TimeoutSec 10;" ^
  "  $app=$appResp.Content;" ^
  "  $appReady = $app.Contains('serverCommonTables') -and $app.Contains('tablePresetVersion') -and $app.Contains('tableTierLabels') -and $app.Contains('compactRelationshipMap') -and $app.Contains('compactItemResolution') -and $app.Contains('compactDraftDiagnostics') -and $app.Contains('compactConfigPlan') -and $app.Contains('compactExperienceSummary') -and $app.Contains('renderExperienceConflicts') -and $app.Contains('experienceConflicts') -and $app.Contains('compactConfigurationRecord') -and $app.Contains('applyCurrentPatch') -and $app.Contains('loadSavedExperiences') -and $app.Contains('setActionBusy') -and $app.Contains('activeProjectId') -and $app.Contains('loadProject') -and $app.Contains('renderProjectStepStatus');" ^
  "  $invalidCount = @($tables.tables | Where-Object { $_.name -notmatch '^[A-Za-z][A-Za-z0-9_]*$' }).Count;" ^
  "  $firstCommon = @($tables.tables | Where-Object { $_.is_common } | Select-Object -First 1)[0];" ^
  "  $tierOrderOk = $firstCommon -and ($firstCommon.frequency_tier -eq 'core');" ^
  "  $htmlReady = $html.Contains('targetDialog') -and $html.Contains('experienceDialog') -and $html.Contains('experience-launch') -and $html.Contains('experienceConflictPanel') -and $html.Contains('projectSelect') -and $html.Contains('newProjectBtn') -and $html.Contains('projectStepStatus') -and $html.Contains('itemBaseFeishuUrl') -and $html.Contains('relationsBtn') -and $html.Contains('relationsTab') -and $html.Contains('diagnosticsTab') -and $html.Contains('recordTab') -and $html.Contains('recordText') -and $html.Contains('overwriteBtn') -and $html.Contains('caseCorrectionText') -and $html.Contains('saveCaseReviewBtn') -and $html.Contains('teachBtn') -and $html.Contains('saveExperienceBtn') -and $html.Contains('openExperienceDialog') -and $html.Contains('experienceSummaryText') -and $html.Contains('activityPlanBtn') -and $html.Contains('planTab') -and $html.Contains('confirmationsTab') -and $html.Contains('internal-manifest') -and ($html.IndexOf('manifest-field') -lt 0);" ^
  "  $projectsReady = ($projects.ok -eq $true);" ^
  "  $ok = $health.ok -and $projectsReady -and (($tables.table_count -as [int]) -gt 0) -and ($invalidCount -eq 0) -and $htmlReady -and $appReady -and $tierOrderOk;" ^
  "  [pscustomobject]@{ reachable=$true; ok=$ok; pid=$health.pid; projectsReady=$projectsReady; projectCount=@($projects.projects).Count; tableCount=$tables.table_count; commonCount=$tables.common_tables.Count; invalidNameCount=$invalidCount; firstCommon=$firstCommon.name; firstTier=$firstCommon.frequency_tier; tierOrderOk=$tierOrderOk; htmlReady=$htmlReady; appReady=$appReady; cacheControl=$appResp.Headers['Cache-Control'] } | ConvertTo-Json -Compress | Write-Host;" ^
  "  if ($ok) { exit 0 } else { exit 1 }" ^
  "} catch {" ^
  "  [pscustomobject]@{ reachable=$false; ok=$false; error=$_.Exception.Message } | ConvertTo-Json -Compress | Write-Host;" ^
  "  exit 1" ^
  "}"
