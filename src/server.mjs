import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

import { aiRuntimeStatus, loadDotEnv } from "./env.mjs";

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
  res.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify(payload, null, 2));
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

function materializeRequest(projectRoot, payload) {
  const uploadRoot = path.join(projectRoot, ".runs", `upload-${Date.now()}-${crypto.randomBytes(3).toString("hex")}`);
  fs.mkdirSync(uploadRoot, { recursive: true });
  const manifest = payload.manifest || {};
  if (payload.useLatestSchema) {
    const latestSchema = latestSchemaDraft(projectRoot);
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
  const env = { ...process.env };
  env.PYTHONPATH = env.PYTHONPATH ? `${projectRoot}${path.delimiter}${env.PYTHONPATH}` : projectRoot;
  const result = spawnSync(python, ["-m", "ai_meta_agent.cli", "--base-dir", projectRoot, ...args], {
    cwd: projectRoot,
    env,
    encoding: "utf8"
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

function latestSchemaDraft(projectRoot) {
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

function latestSchemaScan(projectRoot) {
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

function loadCommonTables(projectRoot) {
  const candidates = [
    path.join(projectRoot, ".knowledge", "common-tables.json"),
    path.join(projectRoot, "config", "common-tables.json")
  ];
  for (const filePath of candidates) {
    const data = maybeReadJson(filePath);
    if (!data) continue;
    if (Array.isArray(data)) return data.map((name) => String(name)).filter(Boolean);
    if (Array.isArray(data.tables)) return data.tables.map((item) => String(item?.name || item)).filter(Boolean);
  }
  return [];
}

function tableOptions(projectRoot) {
  const schemaPath = latestSchemaDraft(projectRoot);
  const scanPath = latestSchemaScan(projectRoot);
  const schema = maybeReadJson(schemaPath);
  const scan = maybeReadJson(scanPath);
  const commonTables = loadCommonTables(projectRoot);
  const commonSet = new Set(commonTables);
  const sourceByName = new Map();
  for (const [name, table] of Object.entries(scan?.tables || {})) {
    sourceByName.set(name, table);
  }
  const names = new Set([
    ...Object.keys(schema?.tables || {}),
    ...Object.keys(scan?.tables || {}),
    ...loadCommonTables(projectRoot)
  ]);
  const tables = [...names].sort((left, right) => left.localeCompare(right)).map((name) => {
    const schemaTable = schema?.tables?.[name] || {};
    const scanTable = sourceByName.get(name) || {};
    const fields = schemaTable.fields || scanTable.fields || {};
    const isCommon = commonSet.has(name);
    return {
      name,
      sheet: schemaTable.sheet || scanTable.sheet || name,
      source_file: scanTable.source_file || null,
      source: scanTable.source_file ? null : isCommon ? "常用表" : null,
      is_common: isCommon,
      primary_key: schemaTable.primary_key || scanTable.primary_key || [],
      field_count: Object.keys(fields).length
    };
  });
  return {
    schema_path: schemaPath,
    scan_path: scanPath,
    table_count: tables.length,
    common_tables: commonTables,
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
  if (parsed.result) artifact.result = maybeReadJson(parsed.result);
  if (parsed.schema_draft) artifact.schemaDraft = summarizeSchemaDraft(parsed.schema_draft);
  if (parsed.report) artifact.schemaScan = summarizeSchemaScan(parsed.report);
  if (parsed.run_dir) {
    artifact.analysis = summarizeAnalysis(path.join(parsed.run_dir, "analysis.json"));
    artifact.diff = maybeReadJson(path.join(parsed.run_dir, "diff.json"));
    artifact.validation = maybeReadJson(path.join(parsed.run_dir, "validation.json"));
    artifact.rollback = maybeReadJson(path.join(parsed.run_dir, "rollback-patch.json"));
  }
  return Object.keys(artifact).some((key) => artifact[key]) ? artifact : null;
}

async function handleApi(req, res, projectRoot) {
  const url = new URL(req.url, "http://127.0.0.1");
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
    const schemaPath = latestSchemaDraft(projectRoot);
    if (!schemaPath) {
      sendJson(res, 404, { error: "no schema scan found" });
      return;
    }
    const schema = summarizeSchemaDraft(schemaPath);
    sendJson(res, 200, { schema_path: schemaPath, schema });
    return;
  }
  if (req.method === "GET" && url.pathname === "/api/table-options") {
    sendJson(res, 200, tableOptions(projectRoot));
    return;
  }
  if (req.method !== "POST") {
    sendJson(res, 405, { error: "method not allowed" });
    return;
  }
  const payload = JSON.parse((await readBody(req)).toString("utf8") || "{}");
  const { manifestPath, uploadRoot } = materializeRequest(projectRoot, payload);
  let args;
  if (url.pathname === "/api/analyze") {
    args = ["analyze", "--manifest", manifestPath];
  } else if (url.pathname === "/api/schema-scan") {
    args = ["schema-scan", "--manifest", manifestPath];
  } else if (url.pathname === "/api/draft") {
    args = ["draft", "--manifest", manifestPath, ...(payload.stub === false ? [] : ["--stub"])];
  } else if (url.pathname === "/api/apply") {
    const patchPath = path.join(uploadRoot, "patch.json");
    fs.writeFileSync(patchPath, JSON.stringify(payload.patch || {}, null, 2), "utf8");
    args = ["apply", "--manifest", manifestPath, "--patch", patchPath];
  } else if (url.pathname === "/api/learn") {
    const patchPath = path.join(uploadRoot, "patch.json");
    fs.writeFileSync(patchPath, JSON.stringify(payload.patch || {}, null, 2), "utf8");
    args = ["learn", "--manifest", manifestPath, "--patch", patchPath, "--decision", payload.decision || "accepted", "--note", payload.note || ""];
  } else {
    sendJson(res, 404, { error: "unknown api route" });
    return;
  }
  const result = runCore(projectRoot, args);
  sendJson(res, result.status === 0 ? 200 : 500, { ...result, artifact: collectArtifact(result) });
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
