#!/usr/bin/env node
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

import { loadDotEnv } from "./env.mjs";
import { startServer } from "./server.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const projectRoot = path.resolve(__dirname, "..");
loadDotEnv(projectRoot);

function pythonCandidates() {
  const candidates = [];
  if (process.env.AI_META_AGENT_PYTHON) candidates.push(process.env.AI_META_AGENT_PYTHON);
  candidates.push(path.join(os.homedir(), ".cache", "codex-runtimes", "codex-primary-runtime", "dependencies", "python", "python.exe"));
  candidates.push(path.join(os.homedir(), ".cache", "codex-runtimes", "codex-primary-runtime", "dependencies", "python", "bin", "python"));
  candidates.push("python");
  candidates.push("python3");
  candidates.push("py");
  return candidates;
}

function resolvePython() {
  for (const candidate of pythonCandidates()) {
    const result = spawnSync(candidate, ["-c", "import sys; print(sys.version_info[0])"], { encoding: "utf8" });
    if (result.status === 0) return candidate;
  }
  throw new Error("No Python runtime found. Set AI_META_AGENT_PYTHON or install Python 3.11+.");
}

function runPython(args) {
  const python = resolvePython();
  const env = { ...process.env };
  env.PYTHONPATH = env.PYTHONPATH ? `${projectRoot}${path.delimiter}${env.PYTHONPATH}` : projectRoot;
  const result = spawnSync(python, ["-m", "ai_meta_agent.cli", "--base-dir", projectRoot, ...args], {
    cwd: projectRoot,
    env,
    encoding: "utf8",
    stdio: "inherit"
  });
  return result.status ?? 1;
}

function help() {
  console.log(`ai-meta-agent

Usage:
  node src/cli.mjs server [--port 4321]
  node src/cli.mjs schema-scan --manifest fixtures/sample.manifest.json
  node src/cli.mjs relations --manifest fixtures/sample.manifest.json
  node src/cli.mjs analyze --manifest fixtures/sample.manifest.json
  node src/cli.mjs draft --manifest fixtures/sample.manifest.json [--stub]
  node src/cli.mjs apply --manifest fixtures/sample.manifest.json --patch .runs/latest/patch.json
  node src/cli.mjs learn --manifest fixtures/sample.manifest.json --patch .runs/latest/patch.json --decision accepted
`);
}

async function main() {
  const [command, ...rest] = process.argv.slice(2);
  if (!command || command === "--help" || command === "-h") {
    help();
    return 0;
  }
  if (command === "server") {
    const portArg = rest.indexOf("--port");
    const port = portArg >= 0 ? Number(rest[portArg + 1]) : Number(process.env.PORT || 4321);
    await startServer({ port, projectRoot, openBrowser: rest.includes("--open") });
    return 0;
  }
  if (["analyze", "schema-scan", "relations", "draft", "apply", "learn"].includes(command)) {
    return runPython([command, ...rest]);
  }
  console.error(`Unknown command: ${command}`);
  help();
  return 1;
}

main()
  .then((code) => {
    process.exitCode = code;
  })
  .catch((error) => {
    console.error(error.message);
    process.exitCode = 1;
  });
