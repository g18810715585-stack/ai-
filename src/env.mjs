import fs from "node:fs";
import path from "node:path";

export const AI_PROVIDERS = {
  baseai: {
    id: "baseai",
    label: "公司 BI",
    apiKeyEnv: "BASEAI_API_KEY",
    baseUrlEnv: "BASEAI_BASE_URL",
    modelEnv: "BASEAI_MODEL",
    defaultBaseUrl: "https://baseai.rivergame.net/v1",
    defaultModel: "gpt-5.5"
  },
  deepseek_v4_pro: {
    id: "deepseek_v4_pro",
    label: "DeepSeek V4 Pro",
    apiKeyEnv: "DEEPSEEK_API_KEY",
    baseUrlEnv: "DEEPSEEK_BASE_URL",
    modelEnv: "DEEPSEEK_MODEL",
    defaultBaseUrl: "https://api.deepseek.com",
    defaultModel: "deepseek-v4-pro"
  }
};

const PROVIDER_ALIASES = new Map([
  ["baseai", "baseai"],
  ["base_ai", "baseai"],
  ["company_bi", "baseai"],
  ["deepseek", "deepseek_v4_pro"],
  ["deepseekv4pro", "deepseek_v4_pro"],
  ["deepseek_v4", "deepseek_v4_pro"],
  ["deepseek-v4-pro", "deepseek_v4_pro"],
  ["deepseek_v4_pro", "deepseek_v4_pro"]
]);

function unquoteValue(value) {
  const trimmed = value.trim();
  if (trimmed.length < 2) return trimmed;
  const quote = trimmed[0];
  if ((quote !== "\"" && quote !== "'") || trimmed.at(-1) !== quote) return trimmed;
  const inner = trimmed.slice(1, -1);
  if (quote === "'") return inner;
  return inner
    .replaceAll("\\n", "\n")
    .replaceAll("\\r", "\r")
    .replaceAll("\\t", "\t")
    .replaceAll("\\\"", "\"")
    .replaceAll("\\\\", "\\");
}

function stripInlineComment(value) {
  let inSingle = false;
  let inDouble = false;
  for (let index = 0; index < value.length; index += 1) {
    const char = value[index];
    const previous = value[index - 1];
    if (char === "'" && !inDouble) inSingle = !inSingle;
    if (char === "\"" && !inSingle && previous !== "\\") inDouble = !inDouble;
    if (char === "#" && !inSingle && !inDouble && /\s/.test(previous || "")) {
      return value.slice(0, index).trimEnd();
    }
  }
  return value;
}

export function parseDotEnv(text) {
  const values = {};
  for (const rawLine of text.split(/\r?\n/)) {
    let line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    if (line.startsWith("export ")) line = line.slice("export ".length).trimStart();
    const match = line.match(/^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!match) continue;
    values[match[1]] = unquoteValue(stripInlineComment(match[2]));
  }
  return values;
}

export function loadDotEnv(projectRoot, env = process.env) {
  const envPath = path.join(projectRoot, ".env");
  if (!fs.existsSync(envPath)) {
    return { path: envPath, loaded: [], skipped: [], found: false };
  }
  const parsed = parseDotEnv(fs.readFileSync(envPath, "utf8"));
  const loaded = [];
  const skipped = [];
  for (const [key, value] of Object.entries(parsed)) {
    if (Object.prototype.hasOwnProperty.call(env, key)) {
      skipped.push(key);
      continue;
    }
    env[key] = value;
    loaded.push(key);
  }
  return { path: envPath, loaded, skipped, found: true };
}

export function normalizeAiProvider(value) {
  const raw = String(value || "baseai").trim().toLowerCase().replaceAll("-", "_");
  return PROVIDER_ALIASES.get(raw) || "baseai";
}

export function aiRuntimeStatus(env = process.env, settings = {}) {
  const providerId = normalizeAiProvider(settings.provider);
  const provider = AI_PROVIDERS[providerId];
  const apiKeyEnv = settings.api_key_env || settings.apiKeyEnv || provider.apiKeyEnv;
  const baseUrlEnv = settings.base_url_env || settings.baseUrlEnv || provider.baseUrlEnv;
  const modelEnv = settings.model_env || settings.modelEnv || provider.modelEnv;
  const defaultBaseUrl = settings.default_base_url || settings.defaultBaseUrl || provider.defaultBaseUrl;
  const defaultModel = settings.default_model || settings.defaultModel || provider.defaultModel;
  return {
    provider: providerId,
    provider_label: provider.label,
    api_key_env: apiKeyEnv,
    api_key_configured: Boolean(env[apiKeyEnv]),
    base_url_env: baseUrlEnv,
    base_url: env[baseUrlEnv] || defaultBaseUrl,
    model_env: modelEnv,
    model: env[modelEnv] || defaultModel
  };
}
