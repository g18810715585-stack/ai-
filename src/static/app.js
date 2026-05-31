const manifestText = document.querySelector("#manifestText");
const patchText = document.querySelector("#patchText");
const resultText = document.querySelector("#resultText");
const rawText = document.querySelector("#rawText");
const statusEl = document.querySelector("#status");
const configDirInput = document.querySelector("#configDir");
const planningFeishuUrlInput = document.querySelector("#planningFeishuUrl");
const aiStatusText = document.querySelector("#aiStatusText");
const aiProviderSelect = document.querySelector("#aiProvider");
const targetTablesSummary = document.querySelector("#targetTablesSummary");
const targetDialog = document.querySelector("#targetDialog");
const tableSearchInput = document.querySelector("#tableSearch");
const tableList = document.querySelector("#tableList");
const commonTablesInput = document.querySelector("#commonTablesInput");

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
      id: "sample-planning",
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
  target_tables: ["shop_pack_config"],
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
let latestSchemaPath = localStorage.getItem(storageKey("latestSchemaPath")) || "";
let draftMode = localStorage.getItem(storageKey("draftMode")) || "stub";
let aiProvider = localStorage.getItem(storageKey("aiProvider")) || "chatgpt";
let latestAiStatus = null;
let tableOptions = [];
let serverCommonTables = [];
let selectedTargetTables = readJsonStorage("targetTables", []);
let pendingTargetSelection = new Set();

const rememberedFields = [
  ["configDir", configDirInput],
  ["planningFeishuUrl", planningFeishuUrlInput]
];

function storageKey(name) {
  return `aiMetaAgent.${name}`;
}

function readJsonStorage(name, fallback) {
  try {
    const value = localStorage.getItem(storageKey(name));
    return value ? JSON.parse(value) : fallback;
  } catch {
    return fallback;
  }
}

function writeJsonStorage(name, value) {
  localStorage.setItem(storageKey(name), JSON.stringify(value));
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function setStatus(text, state = "") {
  statusEl.textContent = text;
  statusEl.className = `status ${state}`.trim();
}

function setDraftMode(mode) {
  draftMode = mode === "real" ? "real" : "stub";
  localStorage.setItem(storageKey("draftMode"), draftMode);
  for (const button of document.querySelectorAll("[data-ai-mode]")) {
    button.classList.toggle("active", button.dataset.aiMode === draftMode);
  }
}

function setAiProvider(provider) {
  aiProvider = aiProviderDefaults[provider] ? provider : "chatgpt";
  aiProviderSelect.value = aiProvider;
  localStorage.setItem(storageKey("aiProvider"), aiProvider);
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

function normalizeTableNames(values) {
  const result = [];
  const seen = new Set();
  for (const value of values || []) {
    const name = String(value || "").trim();
    if (name && !seen.has(name)) {
      seen.add(name);
      result.push(name);
    }
  }
  return result;
}

function parseTableListText(text) {
  return normalizeTableNames(String(text || "").split(/[\n,，;；]+/));
}

function commonTableNames() {
  return parseTableListText(commonTablesInput.value);
}

function saveCommonTables() {
  const names = commonTableNames();
  commonTablesInput.value = names.join("\n");
  writeJsonStorage("commonTables", names);
  for (const name of names) {
    if (!tableOptions.some((table) => table.name === name)) {
      tableOptions.push({ name, source: "common" });
    }
  }
  tableOptions.sort((left, right) => left.name.localeCompare(right.name));
  renderTableList();
}

function selectedTableOrder() {
  const optionNames = tableOptions.map((item) => item.name);
  const ordered = optionNames.filter((name) => pendingTargetSelection.has(name));
  for (const name of pendingTargetSelection) {
    if (!ordered.includes(name)) ordered.push(name);
  }
  return ordered;
}

function updateTargetSummary() {
  if (!selectedTargetTables.length) {
    targetTablesSummary.textContent = "尚未选择。请先扫描配置目录，再选择本次活动的主要关联表。";
    targetTablesSummary.classList.add("empty");
    return;
  }
  targetTablesSummary.classList.remove("empty");
  targetTablesSummary.innerHTML = selectedTargetTables
    .map((name) => `<span class="target-chip">${escapeHtml(name)}</span>`)
    .join("");
}

function applyTargetTablesToManifest() {
  try {
    const manifest = JSON.parse(manifestText.value);
    if (selectedTargetTables.length) {
      manifest.target_tables = selectedTargetTables;
    } else {
      delete manifest.target_tables;
    }
    manifestText.value = JSON.stringify(manifest, null, 2);
  } catch {
    // Keep the user's manual manifest edits visible.
  }
}

function syncTargetsFromManifest() {
  try {
    const manifest = JSON.parse(manifestText.value);
    selectedTargetTables = normalizeTableNames(manifest.target_tables || selectedTargetTables);
    writeJsonStorage("targetTables", selectedTargetTables);
    updateTargetSummary();
  } catch {
    updateTargetSummary();
  }
}

function fallbackTableOptionsFromManifest() {
  try {
    const manifest = JSON.parse(manifestText.value);
    const names = [
      ...Object.keys(manifest.config_tables || {}),
      ...(manifest.target_tables || []),
      ...commonTableNames()
    ];
    return normalizeTableNames(names).map((name) => ({ name, source: "manifest" }));
  } catch {
    return commonTableNames().map((name) => ({ name, source: "common" }));
  }
}

async function loadTableOptions({ silent = false } = {}) {
  try {
    const response = await fetch("/api/table-options");
    if (!response.ok) throw new Error("no scan result");
    const data = await response.json();
    serverCommonTables = normalizeTableNames(data.common_tables || []);
    if (!commonTablesInput.value.trim() && serverCommonTables.length) {
      commonTablesInput.value = serverCommonTables.join("\n");
    }
    const commonSet = new Set([...serverCommonTables, ...commonTableNames()]);
    const backendTables = (data.tables || []).map((table) => ({
      name: table.name,
      source: table.source_file || table.source || "",
      field_count: table.field_count || 0,
      primary_key: table.primary_key || [],
      is_common: Boolean(table.is_common) || commonSet.has(table.name)
    }));
    const commonOnly = [...commonSet]
      .filter((name) => !backendTables.some((table) => table.name === name))
      .map((name) => ({ name, source: "常用表", is_common: true }));
    tableOptions = [...commonOnly, ...backendTables].sort((left, right) => left.name.localeCompare(right.name));
  } catch (error) {
    tableOptions = fallbackTableOptionsFromManifest();
    if (!silent) {
      setStatus(`表列表未刷新：${error.message}`, "error");
    }
  }
  renderTableList();
}

function renderTableList() {
  const query = tableSearchInput.value.trim().toLowerCase();
  const common = new Set([...serverCommonTables, ...commonTableNames()]);
  const options = tableOptions.filter((table) => {
    if (!query) return true;
    return `${table.name} ${table.source || ""}`.toLowerCase().includes(query);
  });

  if (!options.length) {
    tableList.innerHTML = `
      <div class="empty-state">
        还没有可选表。先点“扫描配置目录”，或者在“常用表列表”里粘贴 sheet 名后保存。
      </div>
    `;
    return;
  }

  tableList.innerHTML = options
    .map((table) => {
      const checked = pendingTargetSelection.has(table.name) ? "checked" : "";
      const commonBadge = common.has(table.name) || table.is_common ? '<span class="badge">常用</span>' : "";
      const pk = table.primary_key?.length ? `主键：${table.primary_key.join(", ")}` : "主键：待识别";
      const fields = table.field_count ? `字段：${table.field_count}` : "";
      return `
        <label class="table-option">
          <input type="checkbox" value="${escapeHtml(table.name)}" ${checked} />
          <span>
            <strong>${escapeHtml(table.name)}</strong>
            ${commonBadge}
            <small>${escapeHtml([pk, fields].filter(Boolean).join(" · "))}</small>
            ${table.source ? `<small>${escapeHtml(table.source)}</small>` : ""}
          </span>
        </label>
      `;
    })
    .join("");
}

function openTargetDialog() {
  pendingTargetSelection = new Set(selectedTargetTables);
  tableSearchInput.value = "";
  commonTablesInput.value = readJsonStorage("commonTables", []).join("\n");
  targetDialog.hidden = false;
  loadTableOptions({ silent: true }).then(() => tableSearchInput.focus());
}

function closeTargetDialog() {
  targetDialog.hidden = true;
}

function saveTargetSelection() {
  selectedTargetTables = selectedTableOrder();
  writeJsonStorage("targetTables", selectedTargetTables);
  updateTargetSummary();
  applyTargetTablesToManifest();
  closeTargetDialog();
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
    if (value) input.value = value;
  }
}

async function buildPayload() {
  const manifest = JSON.parse(manifestText.value);
  applyAiProvider(manifest);
  const planningFeishuUrl = planningFeishuUrlInput.value.trim();
  const configDir = configDirInput.value.trim();
  saveRememberedInputs();

  if (configDir) {
    manifest.config_roots = [{ path: configDir, recursive: true }];
  }
  if (selectedTargetTables.length) {
    manifest.target_tables = selectedTargetTables;
  } else {
    delete manifest.target_tables;
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
  }
  return { manifest, files: [], useLatestSchema: Boolean(latestSchemaPath) };
}

function ensureTargetTablesSelected() {
  if (!selectedTargetTables.length) {
    throw new Error("请先点击“选择配置表”，勾选本次活动的主要关联表");
  }
}

function ensurePlanningSource(manifest) {
  if (planningFeishuUrlInput.value.trim()) return;
  if (Array.isArray(manifest.planning_sources) && manifest.planning_sources.length) return;
  throw new Error("请先填写飞书规划链接，或在 Manifest 里配置 planning_sources");
}

async function callApi(route, payload) {
  setStatus("处理中...", "busy");
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
  localStorage.setItem(storageKey("latestSchemaPath"), schemaPath);
  try {
    const manifest = JSON.parse(manifestText.value);
    manifest.schema_path = schemaPath;
    manifestText.value = JSON.stringify(manifest, null, 2);
  } catch {
    // Keep invalid manual edits visible so the user can correct them.
  }
}

async function loadLatestSchema() {
  try {
    const response = await fetch("/api/latest-schema");
    if (!response.ok) return;
    const data = await response.json();
    rememberSchemaPath(data.schema_path);
    await loadTableOptions({ silent: true });
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

for (const [, input] of rememberedFields) {
  input.addEventListener("input", saveRememberedInputs);
  input.addEventListener("change", saveRememberedInputs);
}

document.querySelector("#loadSample").addEventListener("click", () => {
  latestSchemaPath = "";
  localStorage.removeItem(storageKey("latestSchemaPath"));
  selectedTargetTables = ["shop_pack_config"];
  writeJsonStorage("targetTables", selectedTargetTables);
  manifestText.value = JSON.stringify(sampleManifest, null, 2);
  updateTargetSummary();
});

for (const button of document.querySelectorAll("[data-ai-mode]")) {
  button.addEventListener("click", () => setDraftMode(button.dataset.aiMode));
}

aiProviderSelect.addEventListener("change", () => setAiProvider(aiProviderSelect.value));
manifestText.addEventListener("change", syncTargetsFromManifest);

document.querySelector("#openTargetDialog").addEventListener("click", openTargetDialog);
document.querySelector("#closeTargetDialog").addEventListener("click", closeTargetDialog);
document.querySelector("#cancelTargetSelection").addEventListener("click", closeTargetDialog);
document.querySelector("#saveTargetSelection").addEventListener("click", saveTargetSelection);
document.querySelector("#clearTargetSelection").addEventListener("click", () => {
  pendingTargetSelection.clear();
  renderTableList();
});
document.querySelector("#refreshTableOptions").addEventListener("click", () => loadTableOptions());
document.querySelector("#saveCommonTables").addEventListener("click", saveCommonTables);
document.querySelector("#selectCommonTables").addEventListener("click", () => {
  for (const name of commonTableNames()) {
    pendingTargetSelection.add(name);
  }
  renderTableList();
});
tableSearchInput.addEventListener("input", renderTableList);
tableList.addEventListener("change", (event) => {
  const checkbox = event.target;
  if (!(checkbox instanceof HTMLInputElement) || checkbox.type !== "checkbox") return;
  if (checkbox.checked) {
    pendingTargetSelection.add(checkbox.value);
  } else {
    pendingTargetSelection.delete(checkbox.value);
  }
});
targetDialog.addEventListener("click", (event) => {
  if (event.target === targetDialog) closeTargetDialog();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !targetDialog.hidden) closeTargetDialog();
});

document.querySelector("#schemaScanBtn").addEventListener("click", () => runAction(async () => {
  const payload = await buildPayload();
  const data = await callApi("/api/schema-scan", payload);
  rememberSchemaPath(data.artifact?.schemaDraft?.path || parseStdout(data).schema_draft);
  await loadTableOptions({ silent: true });
  resultText.textContent = JSON.stringify(compactSchemaResult(data), null, 2);
  showTab("result");
  if (!selectedTargetTables.length) openTargetDialog();
}));

document.querySelector("#analyzeBtn").addEventListener("click", () => runAction(async () => {
  ensureTargetTablesSelected();
  const payload = await buildPayload();
  ensurePlanningSource(payload.manifest);
  const data = await callApi("/api/analyze", payload);
  resultText.textContent = JSON.stringify(parseStdout(data), null, 2);
  showTab("result");
}));

document.querySelector("#draftBtn").addEventListener("click", () => runAction(async () => {
  ensureTargetTablesSelected();
  const payload = await buildPayload();
  ensurePlanningSource(payload.manifest);
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
restoreRememberedInputs();
const storedCommonTables = readJsonStorage("commonTables", []);
commonTablesInput.value = storedCommonTables.join("\n");
if (!selectedTargetTables.length) {
  selectedTargetTables = normalizeTableNames(sampleManifest.target_tables);
}
applyTargetTablesToManifest();
setAiProvider(aiProvider);
setDraftMode(draftMode);
updateTargetSummary();
loadLatestSchema();
