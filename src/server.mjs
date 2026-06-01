import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

import { aiRuntimeStatus, loadDotEnv } from "./env.mjs";
import {
  createProject,
  latestProjectRunFile,
  listProjects,
  projectManifestPatch,
  readProject,
  recordWorkflowRun,
  updateProject
} from "./projects.mjs";
import { buildPythonEnv } from "./python_env.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const staticRoot = path.join(__dirname, "static");

function pythonCandidates() {
  return [
    process.env.AI_META_AGENT_PYTHON,
    path.join(os.homedir(), ".cache", "codex-runtimes", "codex-primary-runtime", "dependencies", "python", "python.exe"),
    "python",
    "python3",
    "py"
  ].filter(Boolean);
}

function resolvePython() {
  for (const candidate of pythonCandidates()) {
    const result = spawnSync(candidate, ["-c", "print('ok')"], { encoding: "utf8" });
    if (result.status === 0) return candidate;
  }
  throw new Error("No Python runtime found");
}

function sendJson(res, status, payload) {
  if (res.destroyed || res.writableEnded) return;
  try {
    res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
    res.end(JSON.stringify(payload, null, 2));
  } catch {
    // The browser or health check may have already timed out; keep the panel process alive.
  }
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => resolve(Buffer.concat(chunks)));
    req.on("error", reject);
  });
}

function contentType(filePath) {
  if (filePath.endsWith(".html")) return "text/html; charset=utf-8";
  if (filePath.endsWith(".js")) return "text/javascript; charset=utf-8";
  if (filePath.endsWith(".css")) return "text/css; charset=utf-8";
  if (filePath.endsWith(".json")) return "application/json; charset=utf-8";
  return "application/octet-stream";
}

function serveStatic(req, res) {
  const url = new URL(req.url, "http://127.0.0.1");
  const requestPath = url.pathname === "/" ? "/index.html" : url.pathname;
  const filePath = path.resolve(staticRoot, `.${requestPath}`);
  if (!filePath.startsWith(staticRoot) || !fs.existsSync(filePath)) {
    res.writeHead(404);
    res.end("Not found");
    return;
  }
  res.writeHead(200, {
    "Content-Type": contentType(filePath),
    "Cache-Control": "no-store"
  });
  fs.createReadStream(filePath).pipe(res);
}

function materializeRequest(projectRoot, payload, projectId = null) {
  const uploadRoot = path.join(projectRoot, ".runs", `upload-${Date.now()}-${crypto.randomBytes(3).toString("hex")}`);
  fs.mkdirSync(uploadRoot, { recursive: true });
  let manifest = JSON.parse(JSON.stringify(payload.manifest || {}));
  if (projectId) {
    manifest = projectManifestPatch(projectRoot, projectId, manifest);
  }
  if (payload.useLatestSchema) {
    const latestSchema = latestSchemaDraft(projectRoot, projectId);
    if (latestSchema) {
      manifest.schema_path = latestSchema;
    }
  }
  const files = payload.files || [];
  for (const file of files) {
    const safeName = path.basename(file.name || `${file.role || "upload"}.xlsx`);
    const filePath = path.join(uploadRoot, safeName);
    fs.writeFileSync(filePath, Buffer.from(file.base64 || "", "base64"));
    if (file.role === "planning") {
      manifest.planning_sources = [
        {
          id: "uploaded-planning",
          kind: "local_excel",
          path: filePath,
          role: "planning"
        }
      ];
    } else if (file.role?.startsWith("config:")) {
      const table = file.role.slice("config:".length);
      manifest.config_tables = manifest.config_tables || {};
      manifest.config_tables[table] = { ...(manifest.config_tables[table] || {}), path: filePath };
    }
  }
  const manifestPath = path.join(uploadRoot, "manifest.json");
  fs.writeFileSync(manifestPath, JSON.stringify(manifest, null, 2), "utf8");
  return { uploadRoot, manifestPath };
}

function runCore(projectRoot, args) {
  const python = resolvePython();
  const env = buildPythonEnv(projectRoot);
  const result = spawnSync(python, ["-m", "ai_meta_agent.cli", "--base-dir", projectRoot, ...args], {
    cwd: projectRoot,
    env,
    encoding: "utf8",
    windowsHide: true
  });
  return {
    status: result.status ?? 1,
    stdout: result.stdout,
    stderr: result.stderr
  };
}

function maybeReadJson(filePath) {
  if (!filePath || !fs.existsSync(filePath)) return null;
  return JSON.parse(fs.readFileSync(filePath, "utf8"));
}

function latestSchemaDraft(projectRoot, projectId = null) {
  if (projectId) {
    const projectSchema = latestProjectRunFile(projectRoot, projectId, "LATEST_SCHEMA_DRAFT.txt");
    if (projectSchema) return projectSchema;
  }
  const runsDir = path.join(projectRoot, ".runs");
  const pointer = path.join(runsDir, "LATEST_SCHEMA_DRAFT.txt");
  if (fs.existsSync(pointer)) {
    const value = fs.readFileSync(pointer, "utf8").trim();
    if (value && fs.existsSync(value)) return value;
  }
  if (!fs.existsSync(runsDir)) return null;
  const candidates = fs.readdirSync(runsDir, { withFileTypes: true })
    .filter((item) => item.isDirectory() && item.name.startsWith("schema-scan-"))
    .map((item) => {
      const filePath = path.join(runsDir, item.name, "schema-draft.json");
      const stat = fs.existsSync(filePath) ? fs.statSync(filePath) : null;
      return stat ? { filePath, time: stat.mtimeMs } : null;
    })
    .filter(Boolean)
    .sort((left, right) => right.time - left.time);
  return candidates[0]?.filePath || null;
}

function latestSchemaScan(projectRoot, projectId = null) {
  if (projectId) {
    const projectScan = latestProjectRunFile(projectRoot, projectId, "LATEST_SCHEMA_SCAN.txt", "schema-scan.json");
    if (projectScan) return projectScan;
  }
  const runsDir = path.join(projectRoot, ".runs");
  const pointer = path.join(runsDir, "LATEST_SCHEMA_SCAN.txt");
  if (fs.existsSync(pointer)) {
    const value = fs.readFileSync(pointer, "utf8").trim();
    const reportPath = path.join(value, "schema-scan.json");
    if (value && fs.existsSync(reportPath)) return reportPath;
  }
  if (!fs.existsSync(runsDir)) return null;
  const candidates = fs.readdirSync(runsDir, { withFileTypes: true })
    .filter((item) => item.isDirectory() && item.name.startsWith("schema-scan-"))
    .map((item) => {
      const filePath = path.join(runsDir, item.name, "schema-scan.json");
      const stat = fs.existsSync(filePath) ? fs.statSync(filePath) : null;
      return stat ? { filePath, time: stat.mtimeMs } : null;
    })
    .filter(Boolean)
    .sort((left, right) => right.time - left.time);
  return candidates[0]?.filePath || null;
}

function countBy(items, field) {
  const counts = {};
  for (const item of items || []) {
    const value = item?.[field] || "unknown";
    counts[value] = (counts[value] || 0) + 1;
  }
  return counts;
}

const TABLE_TIER_RANK = {
  core: 0,
  high: 1,
  medium: 2,
  low: 3
};

function tableTierRank(tier) {
  return TABLE_TIER_RANK[String(tier || "").toLowerCase()] ?? 99;
}

function normalizeCommonTableEntry(item) {
  if (typeof item === "string") {
    return { name: item.trim(), frequencyTier: null, priority: 0, activityTags: [] };
  }
  const name = String(item?.name || item?.sheet || item?.key || "").trim();
  const frequencyTier = String(item?.frequencyTier || item?.frequency_tier || "").trim().toLowerCase() || null;
  const priority = Number.isFinite(Number(item?.priority)) ? Number(item.priority) : 0;
  const activityTags = Array.isArray(item?.activityTags)
    ? item.activityTags.map((tag) => String(tag)).filter(Boolean)
    : Array.isArray(item?.activity_tags)
      ? item.activity_tags.map((tag) => String(tag)).filter(Boolean)
      : [];
  return { name, frequencyTier, priority, activityTags };
}

function loadCommonTableEntries(projectRoot) {
  const candidates = [
    path.join(projectRoot, ".knowledge", "common-tables.json"),
    path.join(projectRoot, "config", "common-tables.json")
  ];
  for (const filePath of candidates) {
    const data = maybeReadJson(filePath);
    if (!data) continue;
    const rawTables = Array.isArray(data) ? data : data.tables;
    if (Array.isArray(rawTables)) {
      return rawTables
        .map(normalizeCommonTableEntry)
        .filter((item) => isConfigTableName(item.name))
        .sort((left, right) =>
          tableTierRank(left.frequencyTier) - tableTierRank(right.frequencyTier) ||
          right.priority - left.priority ||
          left.name.localeCompare(right.name)
        );
    }
  }
  return [];
}

function isConfigTableName(name) {
  return /^[A-Za-z][A-Za-z0-9_]*$/.test(String(name || ""));
}

function tableOptions(projectRoot, projectId = null) {
  const schemaPath = latestSchemaDraft(projectRoot, projectId);
  const scanPath = latestSchemaScan(projectRoot, projectId);
  const schema = maybeReadJson(schemaPath);
  const scan = maybeReadJson(scanPath);
  const commonEntries = loadCommonTableEntries(projectRoot);
  const commonTables = commonEntries.map((item) => item.name);
  const commonSet = new Set(commonTables);
  const commonByName = new Map(commonEntries.map((item) => [item.name, item]));
  const sourceByName = new Map();
  for (const [name, table] of Object.entries(scan?.tables || {})) {
    sourceByName.set(name, table);
  }
  const names = new Set([
    ...Object.keys(schema?.tables || {}),
    ...Object.keys(scan?.tables || {}),
    ...commonTables
  ]);
  const tables = [...names].filter(isConfigTableName).map((name) => {
    const schemaTable = schema?.tables?.[name] || {};
    const scanTable = sourceByName.get(name) || {};
    const fields = schemaTable.fields || scanTable.fields || {};
    const isCommon = commonSet.has(name);
    const commonEntry = commonByName.get(name);
    return {
      name,
      sheet: schemaTable.sheet || scanTable.sheet || name,
      source_file: scanTable.source_file || null,
      source: scanTable.source_file ? null : isCommon ? "常用表" : null,
      is_common: isCommon,
      frequency_tier: commonEntry?.frequencyTier || null,
      priority: commonEntry?.priority || 0,
      tier_rank: tableTierRank(commonEntry?.frequencyTier),
      activity_tags: commonEntry?.activityTags || [],
      primary_key: schemaTable.primary_key || scanTable.primary_key || [],
      field_count: Object.keys(fields).length
    };
  }).sort((left, right) =>
    left.tier_rank - right.tier_rank ||
    Number(!left.is_common) - Number(!right.is_common) ||
    right.priority - left.priority ||
    left.name.localeCompare(right.name)
  );
  return {
    schema_path: schemaPath,
    scan_path: scanPath,
    table_count: tables.length,
    common_tables: commonTables.filter(isConfigTableName),
    common_table_details: commonEntries,
    tables
  };
}

function summarizeSchemaDraft(filePath) {
  const data = maybeReadJson(filePath);
  if (!data) return null;
  const tableNames = Object.keys(data.tables || {}).sort();
  return {
    path: filePath,
    version: data.version,
    table_count: tableNames.length,
    tables: tableNames.slice(0, 100),
    omitted_tables: Math.max(0, tableNames.length - 100),
    risk: data.risk
  };
}

function summarizeSchemaScan(filePath) {
  const data = maybeReadJson(filePath);
  if (!data) return null;
  const tables = Object.entries(data.tables || {}).sort(([left], [right]) => left.localeCompare(right));
  const duplicates = Object.entries(data.duplicates || {}).sort(([left], [right]) => left.localeCompare(right));
  return {
    path: filePath,
    roots: data.roots || [],
    table_count: data.table_count || tables.length,
    duplicate_count: duplicates.length,
    duplicates: Object.fromEntries(duplicates.slice(0, 20)),
    omitted_duplicates: Math.max(0, duplicates.length - 20),
    reference_candidate_count: (data.reference_candidates || []).length,
    skipped_count: (data.skipped_sheets || []).length,
    skipped_by_reason: countBy(data.skipped_sheets, "reason"),
    errors: data.errors || [],
    tables: tables.slice(0, 80).map(([name, table]) => ({
      name,
      sheet: table.sheet,
      source_file: table.source_file,
      primary_key: table.primary_key || [],
      field_count: Object.keys(table.fields || {}).length
    })),
    omitted_tables: Math.max(0, tables.length - 80)
  };
}

function summarizeAnalysis(filePath) {
  const data = maybeReadJson(filePath);
  if (!data) return null;
  const schemaTables = Object.keys(data.schema?.tables || {}).sort();
  const discovery = data.config_discovery || {};
  return {
    path: filePath,
    run_dir: data.run_dir,
    project: data.manifest?.project,
    schema_path: data.manifest?.schema_path,
    target_tables: data.manifest?.target_tables || [],
    schema_table_count: schemaTables.length,
    schema_tables: schemaTables.slice(0, 80),
    omitted_schema_tables: Math.max(0, schemaTables.length - 80),
    workbook_count: (data.workbooks || []).length,
    workbooks: (data.workbooks || []).map((workbook) => ({
      source_id: workbook.source_id,
      path: workbook.path,
      sheet_count: (workbook.sheets || []).length,
      sheets: (workbook.sheets || []).slice(0, 20).map((sheet) => ({
        name: sheet.name,
        max_row: sheet.max_row,
        max_column: sheet.max_column,
        header_row: sheet.header_row,
        headers: (sheet.headers || []).filter(Boolean).slice(0, 40)
      }))
    })),
    source_errors: data.source_errors || [],
    config_discovery: {
      roots: discovery.roots || [],
      matched_count: Object.keys(discovery.matched || {}).length,
      unmatched_count: (discovery.unmatched_tables || []).length,
      unmatched_tables: (discovery.unmatched_tables || []).slice(0, 80),
      skipped_count: (discovery.skipped_sheets || []).length,
      error_count: (discovery.errors || []).length,
      errors: discovery.errors || []
    },
    relationship_map: data.relationship_map ? {
      relation_count: data.relationship_map.summary?.relation_count || 0,
      recommended_tables: data.relationship_map.recommended_tables || [],
      error_count: data.relationship_map.summary?.error_count || 0
    } : null,
    planning_item_resolution: data.planning_item_resolution ? {
      enabled: Boolean(data.planning_item_resolution.enabled),
      summary: data.planning_item_resolution.summary || {},
      matches: (data.planning_item_resolution.matches || []).slice(0, 40),
      missing: (data.planning_item_resolution.missing || []).slice(0, 20),
      warnings: data.planning_item_resolution.warnings || []
    } : null,
    matched_habit_count: (data.matched_habits || []).length
  };
}

function collectArtifact(result) {
  let parsed = {};
  try {
    parsed = JSON.parse(result.stdout || "{}");
  } catch {
    return null;
  }
  const artifact = {};
  if (parsed.patch) artifact.patch = maybeReadJson(parsed.patch);
  if (parsed.draft_table_preview) artifact.draftTablePreview = maybeReadJson(parsed.draft_table_preview);
  if (parsed.experience_summary) artifact.experienceSummary = maybeReadJson(parsed.experience_summary);
  if (parsed.config_plan) artifact.configPlan = maybeReadJson(parsed.config_plan);
  if (parsed.draft_diagnostics) artifact.draftDiagnostics = maybeReadJson(parsed.draft_diagnostics);
  if (parsed.result) artifact.result = maybeReadJson(parsed.result);
  if (parsed.configuration_record) artifact.configurationRecord = maybeReadJson(parsed.configuration_record);
  if (parsed.case_review) artifact.caseReview = maybeReadJson(parsed.case_review);
  if (parsed.structured_correction) artifact.structuredCorrection = maybeReadJson(parsed.structured_correction);
  if (parsed.relationship_map) artifact.relationshipMap = maybeReadJson(parsed.relationship_map);
  if (parsed.planning_item_resolution) artifact.planningItemResolution = maybeReadJson(parsed.planning_item_resolution);
  if (parsed.schema_draft) artifact.schemaDraft = summarizeSchemaDraft(parsed.schema_draft);
  if (parsed.report) artifact.schemaScan = summarizeSchemaScan(parsed.report);
  if (parsed.run_dir) {
    artifact.analysis = summarizeAnalysis(path.join(parsed.run_dir, "analysis.json"));
    artifact.relationshipMap = artifact.relationshipMap || maybeReadJson(path.join(parsed.run_dir, "relationship-map.json"));
    artifact.planningItemResolution = artifact.planningItemResolution || maybeReadJson(path.join(parsed.run_dir, "planning-item-resolution.json"));
    artifact.configPlan = artifact.configPlan || maybeReadJson(path.join(parsed.run_dir, "config-plan.json"));
    artifact.draftDiagnostics = artifact.draftDiagnostics || maybeReadJson(path.join(parsed.run_dir, "draft-diagnostics.json"));
    artifact.draftTablePreview = artifact.draftTablePreview || maybeReadJson(path.join(parsed.run_dir, "draft-table-preview.json"));
    artifact.configurationRecord = artifact.configurationRecord || maybeReadJson(path.join(parsed.run_dir, "configuration-record.json"));
    artifact.caseReview = artifact.caseReview || maybeReadJson(path.join(parsed.run_dir, "case-review.json"));
    artifact.structuredCorrection = artifact.structuredCorrection || maybeReadJson(path.join(parsed.run_dir, "structured-correction.json"));
    artifact.diff = maybeReadJson(path.join(parsed.run_dir, "diff.json"));
    artifact.validation = maybeReadJson(path.join(parsed.run_dir, "validation.json"));
    artifact.rollback = maybeReadJson(path.join(parsed.run_dir, "rollback-patch.json"));
  }
  return Object.keys(artifact).some((key) => artifact[key]) ? artifact : null;
}

async function handleApi(req, res, projectRoot) {
  const url = new URL(req.url, "http://127.0.0.1");
  const projectRoute = /^\/api\/projects(?:\/([^/]+))?$/.exec(url.pathname);
  if (projectRoute) {
    try {
      const projectId = projectRoute[1] ? decodeURIComponent(projectRoute[1]) : null;
      if (req.method === "GET" && !projectId) {
        sendJson(res, 200, { ok: true, projects: listProjects(projectRoot) });
        return;
      }
      if (req.method === "POST" && !projectId) {
        const payload = JSON.parse((await readBody(req)).toString("utf8") || "{}");
        const project = createProject(projectRoot, payload);
        sendJson(res, 200, { ok: true, project });
        return;
      }
      if (req.method === "GET" && projectId) {
        sendJson(res, 200, { ok: true, project: readProject(projectRoot, projectId) });
        return;
      }
      if (req.method === "PATCH" && projectId) {
        const payload = JSON.parse((await readBody(req)).toString("utf8") || "{}");
        sendJson(res, 200, { ok: true, project: updateProject(projectRoot, projectId, payload) });
        return;
      }
      sendJson(res, 405, { error: "method not allowed" });
    } catch (error) {
      sendJson(res, 400, { error: error.message });
    }
    return;
  }
  if (url.pathname === "/api/health") {
    sendJson(res, 200, { ok: true, pid: process.pid });
    return;
  }
  if (req.method === "GET" && url.pathname === "/api/ai-status") {
    const status = aiRuntimeStatus(process.env, { provider: url.searchParams.get("provider") });
    sendJson(res, 200, {
      ok: true,
      ready: status.api_key_configured,
      ...status,
      message: status.api_key_configured ? `${status.provider_label} 已配置` : `未检测到 ${status.api_key_env}`
    });
    return;
  }
  if (req.method === "GET" && url.pathname === "/api/latest-schema") {
    const schemaPath = latestSchemaDraft(projectRoot, url.searchParams.get("project_id"));
    if (!schemaPath) {
      sendJson(res, 404, { error: "no schema scan found" });
      return;
    }
    const schema = summarizeSchemaDraft(schemaPath);
    sendJson(res, 200, { schema_path: schemaPath, schema });
    return;
  }
  if (req.method === "GET" && url.pathname === "/api/table-options") {
    sendJson(res, 200, tableOptions(projectRoot, url.searchParams.get("project_id")));
    return;
  }
  if (req.method !== "POST") {
    sendJson(res, 405, { error: "method not allowed" });
    return;
  }
  const payload = JSON.parse((await readBody(req)).toString("utf8") || "{}");
  const projectId = payload.project_id || null;
  if (projectId) readProject(projectRoot, projectId);
  const { manifestPath, uploadRoot } = materializeRequest(projectRoot, payload, projectId);
  let args;
  let projectStep = null;
  if (url.pathname === "/api/analyze") {
    args = ["analyze", "--manifest", manifestPath];
    projectStep = "analyze";
  } else if (url.pathname === "/api/teach") {
    args = ["teach", "--manifest", manifestPath, "--text", payload.experience_text || "", "--source", "panel"];
  } else if (url.pathname === "/api/experience-summary") {
    args = ["experience-summary", "--manifest", manifestPath, "--text", payload.experience_text || ""];
    projectStep = "experienceSummary";
  } else if (url.pathname === "/api/experience-list") {
    args = ["experience-list", "--manifest", manifestPath];
  } else if (url.pathname === "/api/experience-update") {
    args = ["experience-update", "--manifest", manifestPath, "--experience-id", payload.experience_id || "", "--text", payload.experience_text || "", "--source", "panel"];
  } else if (url.pathname === "/api/experience-delete") {
    args = ["experience-delete", "--experience-id", payload.experience_id || ""];
  } else if (url.pathname === "/api/activity-template-list") {
    args = ["activity-template-list"];
  } else if (url.pathname === "/api/activity-template-upsert") {
    const templatePath = path.join(uploadRoot, "activity-template.json");
    fs.writeFileSync(templatePath, JSON.stringify(payload.template || {}, null, 2), "utf8");
    args = ["activity-template-upsert", "--template", templatePath];
  } else if (url.pathname === "/api/activity-template-delete") {
    args = ["activity-template-delete", "--template-id", payload.template_id || ""];
  } else if (url.pathname === "/api/field-dictionary-list") {
    args = ["field-dictionary-list", ...(payload.table ? ["--table", payload.table] : [])];
  } else if (url.pathname === "/api/field-dictionary-upsert") {
    const entryPath = path.join(uploadRoot, "field-dictionary-entry.json");
    fs.writeFileSync(entryPath, JSON.stringify(payload.entry || {}, null, 2), "utf8");
    args = ["field-dictionary-upsert", "--entry", entryPath];
  } else if (url.pathname === "/api/field-dictionary-delete") {
    args = ["field-dictionary-delete", "--dictionary-id", payload.dictionary_id || ""];
  } else if (url.pathname === "/api/field-dictionary-seed") {
    args = ["field-dictionary-seed", "--manifest", manifestPath];
  } else if (url.pathname === "/api/activity-plan") {
    args = ["plan", "--manifest", manifestPath];
    projectStep = "activityPlan";
  } else if (url.pathname === "/api/schema-scan") {
    args = ["schema-scan", "--manifest", manifestPath];
    projectStep = "schemaScan";
  } else if (url.pathname === "/api/relations") {
    args = ["relations", "--manifest", manifestPath, ...(payload.explain ? ["--explain"] : [])];
    projectStep = "relations";
  } else if (url.pathname === "/api/draft") {
    args = ["draft", "--manifest", manifestPath, ...(payload.stub === false ? [] : ["--stub"])];
    projectStep = "draft";
  } else if (url.pathname === "/api/apply") {
    const patchPath = path.join(uploadRoot, "patch.json");
    fs.writeFileSync(patchPath, JSON.stringify(payload.patch || {}, null, 2), "utf8");
    const writeMode = payload.write_mode === "overwrite" ? "overwrite" : "preview";
    args = ["apply", "--manifest", manifestPath, "--patch", patchPath, "--write-mode", writeMode];
    projectStep = writeMode === "overwrite" ? "applyOverwrite" : "applyPreview";
  } else if (url.pathname === "/api/case-review") {
    const patchPath = path.join(uploadRoot, "patch.json");
    const applyResultPath = path.join(uploadRoot, "apply-result.json");
    fs.writeFileSync(patchPath, JSON.stringify(payload.patch || {}, null, 2), "utf8");
    fs.writeFileSync(applyResultPath, JSON.stringify(payload.apply_result || {}, null, 2), "utf8");
    args = [
      "case-review",
      "--manifest",
      manifestPath,
      "--patch",
      patchPath,
      "--apply-result",
      applyResultPath,
      "--correction",
      payload.correction_text || ""
    ];
    if (payload.no_ai) args.push("--no-ai");
    projectStep = "caseReview";
  } else if (url.pathname === "/api/learn") {
    const patchPath = path.join(uploadRoot, "patch.json");
    fs.writeFileSync(patchPath, JSON.stringify(payload.patch || {}, null, 2), "utf8");
    args = ["learn", "--manifest", manifestPath, "--patch", patchPath, "--decision", payload.decision || "accepted", "--note", payload.note || ""];
    projectStep = "learn";
  } else {
    sendJson(res, 404, { error: "unknown api route" });
    return;
  }
  const result = runCore(projectRoot, args);
  const artifact = collectArtifact(result);
  let project = null;
  if (projectId && projectStep) {
    try {
      project = recordWorkflowRun(projectRoot, projectId, projectStep, { result, artifact, payload });
    } catch (error) {
      if (result.status === 0) {
        result.status = 1;
        result.stderr = `${result.stderr || ""}\nProject record failed: ${error.message}`.trim();
      }
    }
  }
  sendJson(res, result.status === 0 ? 200 : 500, { ...result, artifact, project });
}

function openUrl(url) {
  const command = process.platform === "win32" ? "cmd" : process.platform === "darwin" ? "open" : "xdg-open";
  const args = process.platform === "win32" ? ["/c", "start", "", url] : [url];
  const child = spawn(command, args, { detached: true, stdio: "ignore", windowsHide: true });
  child.unref();
}

function writePidFile(projectRoot, port) {
  const runsDir = path.join(projectRoot, ".runs");
  fs.mkdirSync(runsDir, { recursive: true });
  const pidFile = path.join(runsDir, `panel-${port}.pid`);
  fs.writeFileSync(pidFile, String(process.pid), "utf8");
  const cleanup = () => {
    try {
      if (fs.existsSync(pidFile) && fs.readFileSync(pidFile, "utf8").trim() === String(process.pid)) {
        fs.unlinkSync(pidFile);
      }
    } catch {
      // Best-effort cleanup only.
    }
  };
  process.once("exit", cleanup);
  process.once("SIGINT", () => {
    cleanup();
    process.exit(0);
  });
  process.once("SIGTERM", () => {
    cleanup();
    process.exit(0);
  });
}

export async function startServer({ port = 4321, projectRoot, openBrowser = false }) {
  loadDotEnv(projectRoot);
  const server = http.createServer((req, res) => {
    res.on("error", () => {
      // Best-effort response only; aborted local checks should not crash the panel.
    });
    if (req.url.startsWith("/api/")) {
      handleApi(req, res, projectRoot).catch((error) => sendJson(res, 500, { error: error.message }));
      return;
    }
    serveStatic(req, res);
  });
  await new Promise((resolve) => server.listen(port, "127.0.0.1", resolve));
  writePidFile(projectRoot, port);
  const url = `http://127.0.0.1:${port}`;
  console.log(`ai-meta-agent panel: ${url}`);
  if (openBrowser) {
    openUrl(url);
  }
  await new Promise((resolve) => server.once("close", resolve));
}
