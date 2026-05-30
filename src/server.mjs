import { spawnSync } from "node:child_process";
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";

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
  res.writeHead(200, { "Content-Type": contentType(filePath) });
  fs.createReadStream(filePath).pipe(res);
}

function materializeRequest(projectRoot, payload) {
  const uploadRoot = path.join(projectRoot, ".runs", `upload-${Date.now()}-${crypto.randomBytes(3).toString("hex")}`);
  fs.mkdirSync(uploadRoot, { recursive: true });
  const manifest = payload.manifest || {};
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
  if (parsed.run_dir) {
    artifact.analysis = maybeReadJson(path.join(parsed.run_dir, "analysis.json"));
    artifact.diff = maybeReadJson(path.join(parsed.run_dir, "diff.json"));
    artifact.validation = maybeReadJson(path.join(parsed.run_dir, "validation.json"));
    artifact.rollback = maybeReadJson(path.join(parsed.run_dir, "rollback-patch.json"));
  }
  return Object.keys(artifact).some((key) => artifact[key]) ? artifact : null;
}

async function handleApi(req, res, projectRoot) {
  const url = new URL(req.url, "http://127.0.0.1");
  if (url.pathname === "/api/health") {
    sendJson(res, 200, { ok: true });
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

export async function startServer({ port = 4321, projectRoot, openBrowser = false }) {
  const server = http.createServer((req, res) => {
    if (req.url.startsWith("/api/")) {
      handleApi(req, res, projectRoot).catch((error) => sendJson(res, 500, { error: error.message }));
      return;
    }
    serveStatic(req, res);
  });
  await new Promise((resolve) => server.listen(port, "127.0.0.1", resolve));
  const url = `http://127.0.0.1:${port}`;
  console.log(`ai-meta-agent panel: ${url}`);
  if (openBrowser) {
    openUrl(url);
  }
}
