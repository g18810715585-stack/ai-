const manifestText = document.querySelector("#manifestText");
const patchText = document.querySelector("#patchText");
const resultText = document.querySelector("#resultText");
const rawText = document.querySelector("#rawText");
const statusEl = document.querySelector("#status");
const tableNameInput = document.querySelector("#configTableName");
const configDirInput = document.querySelector("#configDir");
const planningFeishuUrlInput = document.querySelector("#planningFeishuUrl");
const aiStatusText = document.querySelector("#aiStatusText");
const aiProviderSelect = document.querySelector("#aiProvider");

const aiProviderDefaults = {
  chatgpt: {
    label: "ChatGPT",
    provider: "chatgpt",
    api_key_env: "BASEAI_API_KEY",
    base_url_env: "BASEAI_BASE_URL",
    model_env: "CHATGPT_MODEL",
    default_base_url: "https://baseai.rivergame.net/v1",
    default_model: "gpt-5.5"
  },
  gemini: {
    label: "Gemini",
    provider: "gemini",
    api_key_env: "BASEAI_API_KEY",
    base_url_env: "BASEAI_BASE_URL",
    model_env: "GEMINI_MODEL",
    default_base_url: "https://baseai.rivergame.net/v1",
    default_model: "gemini-3.1-pro-preview"
  },
  claude: {
    label: "Claude",
    provider: "claude",
    api_key_env: "BASEAI_API_KEY",
    base_url_env: "BASEAI_BASE_URL",
    model_env: "CLAUDE_MODEL",
    default_base_url: "https://baseai.rivergame.net/v1",
    default_model: "claude-opus-4-8"
  },
  deepseek_v4_pro: {
    label: "DeepSeek",
    provider: "deepseek_v4_pro",
    api_key_env: "BASEAI_API_KEY",
    base_url_env: "BASEAI_BASE_URL",
    model_env: "DEEPSEEK_MODEL",
    default_base_url: "https://baseai.rivergame.net/v1",
    default_model: "deepseek-v4-pro"
  }
};

const sampleManifest = {
  project: "sample-pack",
  mode: "supervised_write",
  schema_path: "config/example.schema.json",
  run_root: ".runs",
  planning_sources: [
    {
      id: "uploaded-planning",
      kind: "local_excel",
      path: "fixtures/sample-planning.xlsx",
      role: "planning"
    }
  ],
  config_tables: {
    shop_pack_config: {
      path: "fixtures/sample-config.xlsx",
      sheet: "shop_pack_config"
    }
  },
  config_roots: [
    {
      path: "fixtures",
      recursive: false
    }
  ],
  habit_store: ".knowledge/habits.jsonl",
  ai: {
    provider: "chatgpt",
    api_key_env: "BASEAI_API_KEY",
    base_url_env: "BASEAI_BASE_URL",
    model_env: "CHATGPT_MODEL",
    default_base_url: "https://baseai.rivergame.net/v1",
    default_model: "gpt-5.5"
  }
};

let lastPatch = null;
let latestSchemaPath = localStorage.getItem("aiMetaAgent.latestSchemaPath") || "";
let draftMode = localStorage.getItem("aiMetaAgent.draftMode") || "stub";
let aiProvider = localStorage.getItem("aiMetaAgent.aiProvider") || "chatgpt";
let latestAiStatus = null;

const rememberedFields = [
  ["configDir", configDirInput],
  ["targetTable", tableNameInput],
  ["planningFeishuUrl", planningFeishuUrlInput]
];

function setStatus(text, state = "") {
  statusEl.textContent = text;
  statusEl.className = `status ${state}`.trim();
}

function setDraftMode(mode) {
  draftMode = mode === "real" ? "real" : "stub";
  localStorage.setItem("aiMetaAgent.draftMode", draftMode);
  for (const button of document.querySelectorAll("[data-ai-mode]")) {
    button.classList.toggle("active", button.dataset.aiMode === draftMode);
  }
}

function setAiProvider(provider) {
  aiProvider = aiProviderDefaults[provider] ? provider : "chatgpt";
  aiProviderSelect.value = aiProvider;
  localStorage.setItem("aiMetaAgent.aiProvider", aiProvider);
  latestAiStatus = null;
  loadAiStatus();
}

function applyAiProvider(manifest) {
  const provider = aiProviderDefaults[aiProvider] || aiProviderDefaults.chatgpt;
  manifest.ai = {
    ...(manifest.ai || {}),
    provider: provider.provider,
    api_key_env: provider.api_key_env,
    base_url_env: provider.base_url_env,
    model_env: provider.model_env,
    default_base_url: provider.default_base_url,
    default_model: provider.default_model
  };
}

function showTab(name) {
  for (const button of document.querySelectorAll(".tab")) {
    button.classList.toggle("active", button.dataset.tab === name);
  }
  for (const panel of document.querySelectorAll(".tab-content")) {
    panel.classList.remove("active");
  }
  document.querySelector(`#${name}Tab`).classList.add("active");
}

function readFileAsBase64(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = String(reader.result);
      resolve(dataUrl.slice(dataUrl.indexOf(",") + 1));
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function buildPayload() {
  const manifest = JSON.parse(manifestText.value);
  applyAiProvider(manifest);
  const files = [];
  const planning = document.querySelector("#planningFile").files[0];
  const planningFeishuUrl = planningFeishuUrlInput.value.trim();
  const config = document.querySelector("#configFile").files[0];
  const configDir = configDirInput.value.trim();
  const targetTable = tableNameInput.value.trim();
  saveRememberedInputs();
  if (configDir) {
    manifest.config_roots = [{ path: configDir, recursive: true }];
  }
  if (targetTable) {
    manifest.target_tables = [targetTable];
  }
  if (planningFeishuUrl) {
    manifest.planning_sources = [
      {
        id: "feishu-planning",
        kind: "feishu",
        url: planningFeishuUrl,
        range: "A1:ZZ1000",
        role: "planning"
      }
    ];
  } else if (planning) {
    files.push({ role: "planning", name: planning.name, base64: await readFileAsBase64(planning) });
  }
  if (config) {
    files.push({ role: `config:${targetTable || "shop_pack_config"}`, name: config.name, base64: await readFileAsBase64(config) });
  }
  return { manifest, files, useLatestSchema: Boolean(latestSchemaPath) };
}

async function callApi(route, payload) {
  setStatus("处理中", "busy");
  const response = await fetch(route, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const text = await response.text();
  let data;
  try {
    data = JSON.parse(text || "{}");
  } catch {
    data = { error: text || "服务返回了非 JSON 内容" };
  }
  rawText.textContent = JSON.stringify(data, null, 2);
  if (!response.ok) {
    setStatus("出错", "error");
    showTab("raw");
    throw new Error(data.error || data.stderr || "请求失败");
  }
  setStatus("就绪");
  return data;
}

async function loadAiStatus() {
  try {
    const response = await fetch(`/api/ai-status?provider=${encodeURIComponent(aiProvider)}`);
    const data = await response.json();
    latestAiStatus = data;
    if (data.ready) {
      aiStatusText.textContent = `${data.provider_label} 已配置：${data.model} @ ${data.base_url}`;
      aiStatusText.classList.remove("error");
    } else {
      aiStatusText.textContent = `${data.provider_label} 未配置：请在 .env 中填写 ${data.api_key_env}`;
      aiStatusText.classList.add("error");
    }
    return data;
  } catch (error) {
    latestAiStatus = null;
    aiStatusText.textContent = `无法检查真实 AI 配置：${error.message}`;
    aiStatusText.classList.add("error");
    return null;
  }
}

function parseStdout(data) {
  try {
    return JSON.parse(data.stdout || "{}");
  } catch {
    return {};
  }
}

function compactSchemaResult(data) {
  const summary = parseStdout(data);
  const artifact = data.artifact || {};
  return {
    summary,
    schemaDraft: artifact.schemaDraft,
    schemaScan: artifact.schemaScan
  };
}

function rememberSchemaPath(schemaPath) {
  if (!schemaPath) return;
  latestSchemaPath = schemaPath;
  localStorage.setItem("aiMetaAgent.latestSchemaPath", schemaPath);
  try {
    const manifest = JSON.parse(manifestText.value);
    manifest.schema_path = schemaPath;
    manifestText.value = JSON.stringify(manifest, null, 2);
  } catch {
    // Leave invalid manual edits visible so the user can correct them.
  }
}

async function loadLatestSchema() {
  try {
    const response = await fetch("/api/latest-schema");
    if (!response.ok) return;
    const data = await response.json();
    rememberSchemaPath(data.schema_path);
  } catch {
    // The first run may not have a schema scan yet.
  }
}

async function runAction(action) {
  try {
    await action();
  } catch (error) {
    setStatus(`出错：${error.message}`, "error");
  }
}

function storageKey(name) {
  return `aiMetaAgent.${name}`;
}

function saveRememberedInputs() {
  for (const [name, input] of rememberedFields) {
    const value = input.value.trim();
    if (value) {
      localStorage.setItem(storageKey(name), value);
    } else {
      localStorage.removeItem(storageKey(name));
    }
  }
}

function restoreRememberedInputs() {
  for (const [name, input] of rememberedFields) {
    const value = localStorage.getItem(storageKey(name));
    if (value) {
      input.value = value;
    }
  }
}

for (const [, input] of rememberedFields) {
  input.addEventListener("input", saveRememberedInputs);
  input.addEventListener("change", saveRememberedInputs);
}

document.querySelector("#loadSample").addEventListener("click", () => {
  latestSchemaPath = "";
  localStorage.removeItem("aiMetaAgent.latestSchemaPath");
  tableNameInput.value = "shop_pack_config";
  manifestText.value = JSON.stringify(sampleManifest, null, 2);
});

for (const button of document.querySelectorAll("[data-ai-mode]")) {
  button.addEventListener("click", () => setDraftMode(button.dataset.aiMode));
}

aiProviderSelect.addEventListener("change", () => setAiProvider(aiProviderSelect.value));

document.querySelector("#schemaScanBtn").addEventListener("click", () => runAction(async () => {
  const payload = await buildPayload();
  const data = await callApi("/api/schema-scan", payload);
  rememberSchemaPath(data.artifact?.schemaDraft?.path || parseStdout(data).schema_draft);
  resultText.textContent = JSON.stringify(compactSchemaResult(data), null, 2);
  showTab("result");
}));

document.querySelector("#analyzeBtn").addEventListener("click", () => runAction(async () => {
  if (!tableNameInput.value.trim()) {
    throw new Error("请先填写目标配置表名（sheet 名）");
  }
  const payload = await buildPayload();
  const data = await callApi("/api/analyze", payload);
  resultText.textContent = JSON.stringify(parseStdout(data), null, 2);
  showTab("result");
}));

document.querySelector("#draftBtn").addEventListener("click", () => runAction(async () => {
  if (!tableNameInput.value.trim()) {
    throw new Error("请先填写目标配置表名（sheet 名）");
  }
  const payload = await buildPayload();
  if (draftMode === "real") {
    const aiStatus = latestAiStatus?.ready ? latestAiStatus : await loadAiStatus();
    if (!aiStatus?.ready) {
      throw new Error(aiStatus?.message || "真实 AI 未配置，请先在 .env 中填写对应 Key，或切回本地草案");
    }
  }
  payload.stub = draftMode !== "real";
  const data = await callApi("/api/draft", payload);
  if (data.artifact?.patch) {
    lastPatch = data.artifact.patch;
    patchText.value = JSON.stringify(lastPatch, null, 2);
  }
  resultText.textContent = JSON.stringify(parseStdout(data), null, 2);
  showTab("patch");
}));

document.querySelector("#applyBtn").addEventListener("click", () => runAction(async () => {
  const payload = await buildPayload();
  payload.patch = JSON.parse(patchText.value || JSON.stringify(lastPatch || {}));
  const data = await callApi("/api/apply", payload);
  resultText.textContent = JSON.stringify(data.artifact || parseStdout(data), null, 2);
  showTab("result");
}));

document.querySelector("#learnBtn").addEventListener("click", () => runAction(async () => {
  const payload = await buildPayload();
  payload.patch = JSON.parse(patchText.value || JSON.stringify(lastPatch || {}));
  payload.decision = "accepted";
  payload.note = "从本地面板确认通过";
  const data = await callApi("/api/learn", payload);
  resultText.textContent = JSON.stringify(parseStdout(data), null, 2);
  showTab("result");
}));

for (const button of document.querySelectorAll(".tab")) {
  button.addEventListener("click", () => showTab(button.dataset.tab));
}

manifestText.value = JSON.stringify(sampleManifest, null, 2);
setAiProvider(aiProvider);
setDraftMode(draftMode);
restoreRememberedInputs();
loadLatestSchema();
