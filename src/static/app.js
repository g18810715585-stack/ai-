const manifestText = document.querySelector("#manifestText");
const patchText = document.querySelector("#patchText");
const diagnosticsText = document.querySelector("#diagnosticsText");
const relationsText = document.querySelector("#relationsText");
const planText = document.querySelector("#planText");
const confirmationsText = document.querySelector("#confirmationsText");
const resultText = document.querySelector("#resultText");
const recordText = document.querySelector("#recordText");
const rawText = document.querySelector("#rawText");
const statusEl = document.querySelector("#status");
const configDirInput = document.querySelector("#configDir");
const planningFeishuUrlInput = document.querySelector("#planningFeishuUrl");
const itemBaseFeishuUrlInput = document.querySelector("#itemBaseFeishuUrl");
const experienceText = document.querySelector("#experienceText");
const experienceSummaryText = document.querySelector("#experienceSummaryText");
const saveExperienceBtn = document.querySelector("#saveExperienceBtn");
const aiStatusText = document.querySelector("#aiStatusText");
const aiProviderSelect = document.querySelector("#aiProvider");
const targetTablesSummary = document.querySelector("#targetTablesSummary");
const targetDialog = document.querySelector("#targetDialog");
const tableSearchInput = document.querySelector("#tableSearch");
const tableList = document.querySelector("#tableList");
const commonTablesInput = document.querySelector("#commonTablesInput");
const experienceDialog = document.querySelector("#experienceDialog");
const experienceSearchInput = document.querySelector("#experienceSearch");
const experienceList = document.querySelector("#experienceList");
const experienceEditText = document.querySelector("#experienceEditText");
const experienceMeta = document.querySelector("#experienceMeta");
const updateExperienceBtn = document.querySelector("#updateExperienceBtn");
const deleteExperienceBtn = document.querySelector("#deleteExperienceBtn");
const caseCorrectionText = document.querySelector("#caseCorrectionText");
const saveCaseReviewBtn = document.querySelector("#saveCaseReviewBtn");
const tablePresetVersion = "meta-doc-excel-local-learning-v2";
const tableTierRanks = { core: 0, high: 1, medium: 2, low: 3 };
const tableTierLabels = { core: "核心", high: "高频", medium: "中频", low: "低频" };

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
let serverCommonTableMeta = new Map();
resetStoredTablesWhenPresetChanges();
let selectedTargetTables = readJsonStorage("targetTables", []);
let pendingTargetSelection = new Set();
let latestExperienceSummary = null;
let savedExperiences = [];
let selectedExperienceId = "";
let lastApplyResult = null;
let lastConfigurationRecord = null;

const rememberedFields = [
  ["configDir", configDirInput],
  ["planningFeishuUrl", planningFeishuUrlInput],
  ["itemBaseFeishuUrl", itemBaseFeishuUrlInput],
  ["experienceText", experienceText],
  ["experienceSummaryText", experienceSummaryText]
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

function resetStoredTablesWhenPresetChanges() {
  if (localStorage.getItem(storageKey("tablePresetVersion")) === tablePresetVersion) return;
  localStorage.removeItem(storageKey("targetTables"));
  localStorage.removeItem(storageKey("commonTables"));
  localStorage.setItem(storageKey("tablePresetVersion"), tablePresetVersion);
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
  statusEl.dataset.state = state || "idle";
}

// Only the clicked workflow button stays enabled while a long backend action runs.
function setActionBusy(button, label, busy) {
  if (!button) return;
  const actionButtons = Array.from(document.querySelectorAll(".actions button, .experience-actions button, .history-actions button, .record-actions button"));
  if (busy) {
    button.dataset.originalText = button.dataset.originalText || button.textContent;
    button.textContent = `正在${label}...`;
    button.classList.add("running");
    button.setAttribute("aria-busy", "true");
    for (const actionButton of actionButtons) {
      actionButton.disabled = actionButton !== button;
    }
    return;
  }
  button.textContent = button.dataset.originalText || label;
  button.classList.remove("running");
  button.removeAttribute("aria-busy");
  for (const actionButton of actionButtons) {
    actionButton.disabled = false;
  }
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
    if (isConfigTableName(name) && !seen.has(name)) {
      seen.add(name);
      result.push(name);
    }
  }
  return result;
}

function isConfigTableName(name) {
  return /^[A-Za-z][A-Za-z0-9_]*$/.test(String(name || ""));
}

function normalizeCommonTableDetails(values) {
  const result = [];
  const seen = new Set();
  for (const item of values || []) {
    const name = String(item?.name || item?.sheet || item?.key || item || "").trim();
    if (!isConfigTableName(name) || seen.has(name)) continue;
    seen.add(name);
    result.push({
      name,
      frequency_tier: String(item?.frequency_tier || item?.frequencyTier || "").trim().toLowerCase(),
      priority: Number.isFinite(Number(item?.priority)) ? Number(item.priority) : 0,
      activity_tags: Array.isArray(item?.activity_tags)
        ? item.activity_tags.map(String).filter(Boolean)
        : Array.isArray(item?.activityTags)
          ? item.activityTags.map(String).filter(Boolean)
          : []
    });
  }
  return result;
}

function tableMeta(name) {
  return serverCommonTableMeta.get(name) || {};
}

function tableTier(table) {
  const meta = tableMeta(table.name || table);
  const tier = String(table.frequency_tier || table.frequencyTier || meta.frequency_tier || "").toLowerCase();
  return Object.hasOwn(tableTierRanks, tier) ? tier : "";
}

function tablePriority(table) {
  const meta = tableMeta(table.name || table);
  const priority = Number(table.priority ?? meta.priority ?? 0);
  return Number.isFinite(priority) ? priority : 0;
}

function compareTableOptions(left, right) {
  const leftRank = tableTierRanks[tableTier(left)] ?? 99;
  const rightRank = tableTierRanks[tableTier(right)] ?? 99;
  return leftRank - rightRank ||
    Number(!left.is_common) - Number(!right.is_common) ||
    tablePriority(right) - tablePriority(left) ||
    left.name.localeCompare(right.name);
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
      tableOptions.push({ name, source: "常用表", is_common: true });
    }
  }
  tableOptions.sort(compareTableOptions);
  renderTableList();
  setStatus(`已保存 ${names.length} 张常用表`, "ok");
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
  let refreshed = true;
  try {
    const response = await fetch("/api/table-options");
    if (!response.ok) throw new Error("no scan result");
    const data = await response.json();
    serverCommonTables = normalizeTableNames(data.common_tables || []);
    const commonDetails = normalizeCommonTableDetails(data.common_table_details || []);
    serverCommonTableMeta = new Map(commonDetails.map((item) => [item.name, item]));
    if (!commonTablesInput.value.trim() && serverCommonTables.length) {
      commonTablesInput.value = serverCommonTables.join("\n");
    }
    const commonSet = new Set([...serverCommonTables, ...commonTableNames()]);
    const backendTables = (data.tables || [])
      .filter((table) => isConfigTableName(table.name))
      .map((table) => ({
        name: table.name,
        source: table.source_file || table.source || "",
        field_count: table.field_count || 0,
        primary_key: table.primary_key || [],
        frequency_tier: table.frequency_tier || tableTier(table),
        priority: table.priority || tablePriority(table),
        activity_tags: table.activity_tags || [],
        is_common: Boolean(table.is_common) || commonSet.has(table.name)
      }));
    const commonOnly = [...commonSet]
      .filter((name) => !backendTables.some((table) => table.name === name))
      .map((name) => ({
        name,
        source: "常用表",
        is_common: true,
        frequency_tier: tableMeta(name).frequency_tier || "",
        priority: tableMeta(name).priority || 0,
        activity_tags: tableMeta(name).activity_tags || []
      }));
    tableOptions = [...commonOnly, ...backendTables].sort(compareTableOptions);
  } catch (error) {
    refreshed = false;
    tableOptions = fallbackTableOptionsFromManifest();
    if (!silent) {
      setStatus(`表列表未刷新：${error.message}`, "error");
    }
  }
  renderTableList();
  return refreshed;
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
      const tier = tableTier(table);
      const tierBadge = tier ? `<span class="badge tier-${escapeHtml(tier)}">${escapeHtml(tableTierLabels[tier] || tier)}</span>` : "";
      const pk = table.primary_key?.length ? `主键：${table.primary_key.join(", ")}` : "主键：待识别";
      const fields = table.field_count ? `字段：${table.field_count}` : "";
      return `
        <label class="table-option">
          <input type="checkbox" value="${escapeHtml(table.name)}" ${checked} />
          <span>
            <strong>${escapeHtml(table.name)}</strong>
            ${commonBadge}${tierBadge}
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
  setStatus("正在加载可选配置表...", "busy");
  loadTableOptions({ silent: true }).then((refreshed) => {
    tableSearchInput.focus();
    setStatus(refreshed ? "配置表选择已就绪" : "使用本地缓存配置表列表", refreshed ? "ok" : "error");
  });
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
  setStatus(`已选择 ${selectedTargetTables.length} 张目标配置表`, "ok");
}

function formatTime(value) {
  if (!value) return "未知时间";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString("zh-CN", { hour12: false });
}

function openExperienceDialog() {
  experienceDialog.hidden = false;
  experienceSearchInput.value = "";
  loadSavedExperiences().catch((error) => setStatus(`加载历史经验失败：${error.message}`, "error"));
}

function closeExperienceDialog() {
  experienceDialog.hidden = true;
}

async function loadSavedExperiences() {
  const payload = await buildPayload();
  const data = await callApi("/api/experience-list", payload, { label: "加载历史经验" });
  const summary = parseStdout(data);
  savedExperiences = summary.experiences || [];
  selectedExperienceId = savedExperiences.some((item) => item.experience_id === selectedExperienceId) ? selectedExperienceId : "";
  renderExperienceList();
  if (selectedExperienceId) {
    selectExperience(selectedExperienceId);
  } else {
    clearSelectedExperience();
  }
}

function renderExperienceList() {
  const query = experienceSearchInput.value.trim().toLowerCase();
  const items = savedExperiences.filter((item) => {
    if (!query) return true;
    return `${item.title || ""} ${item.text || ""} ${item.project || ""} ${item.source || ""}`.toLowerCase().includes(query);
  });
  if (!items.length) {
    experienceList.innerHTML = '<div class="empty-state">还没有保存的经验。</div>';
    return;
  }
  experienceList.innerHTML = items
    .map((item) => {
      const active = item.experience_id === selectedExperienceId ? " active" : "";
      const counts = item.record_counts || {};
      const countText = `规则 ${counts.rules || 0} / 模板 ${counts.activity_templates || 0} / 映射 ${counts.field_mappings || 0}`;
      return `
        <button class="experience-item${active}" type="button" data-experience-id="${escapeHtml(item.experience_id)}">
          <strong>${escapeHtml(item.title || "未命名经验")}</strong>
          <small>录入：${escapeHtml(formatTime(item.created_at))}</small>
          <small>更新：${escapeHtml(formatTime(item.updated_at))} · ${escapeHtml(item.project || "default")}</small>
          <small>${escapeHtml(countText)}${item.legacy ? " · 旧记录" : ""}</small>
        </button>
      `;
    })
    .join("");
}

function selectExperience(experienceId) {
  const item = savedExperiences.find((value) => value.experience_id === experienceId);
  if (!item) {
    clearSelectedExperience();
    return;
  }
  selectedExperienceId = experienceId;
  experienceEditText.value = item.text || "";
  const counts = item.record_counts || {};
  experienceMeta.textContent = [
    `标题：${item.title || "未命名经验"}`,
    `项目：${item.project || "default"}`,
    `来源：${item.source || "未知"}`,
    `录入时间：${formatTime(item.created_at)}`,
    `更新时间：${formatTime(item.updated_at)}`,
    `结构化记录：规则 ${counts.rules || 0}，模板 ${counts.activity_templates || 0}，字段映射 ${counts.field_mappings || 0}`,
  ].join("\n");
  updateExperienceBtn.disabled = !experienceEditText.value.trim();
  deleteExperienceBtn.disabled = false;
  renderExperienceList();
}

function clearSelectedExperience() {
  selectedExperienceId = "";
  experienceEditText.value = "";
  experienceMeta.textContent = "请选择一条经验。";
  updateExperienceBtn.disabled = true;
  deleteExperienceBtn.disabled = true;
}

async function updateSelectedExperience() {
  if (!selectedExperienceId) throw new Error("请先选择一条经验");
  const text = experienceEditText.value.trim();
  if (!text) throw new Error("经验内容不能为空");
  const payload = await buildPayload();
  payload.experience_id = selectedExperienceId;
  payload.experience_text = text;
  const data = await callApi("/api/experience-update", payload, { label: "保存经验修改" });
  resultText.textContent = JSON.stringify(parseStdout(data), null, 2);
  await loadSavedExperiences();
  selectExperience(selectedExperienceId);
  showTab("result");
}

async function deleteSelectedExperience() {
  if (!selectedExperienceId) throw new Error("请先选择一条经验");
  const item = savedExperiences.find((value) => value.experience_id === selectedExperienceId);
  if (!window.confirm(`确定删除这条经验吗？\n${item?.title || selectedExperienceId}`)) return;
  const payload = await buildPayload();
  payload.experience_id = selectedExperienceId;
  const data = await callApi("/api/experience-delete", payload, { label: "删除经验" });
  resultText.textContent = JSON.stringify(parseStdout(data), null, 2);
  selectedExperienceId = "";
  await loadSavedExperiences();
  showTab("result");
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
  const itemBaseFeishuUrl = itemBaseFeishuUrlInput.value.trim();
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
  let planningSources = Array.isArray(manifest.planning_sources) ? [...manifest.planning_sources] : [];
  if (planningFeishuUrl) {
    planningSources = [
      {
        id: "feishu-planning",
        kind: "feishu",
        url: planningFeishuUrl,
        range: "A1:ZZ1000",
        role: "planning"
      }
    ];
  }
  planningSources = planningSources.filter((source) => source.id !== "feishu-value-table");
  if (itemBaseFeishuUrl) {
    planningSources.push({
      id: "feishu-value-table",
      kind: "feishu",
      url: itemBaseFeishuUrl,
      range: "A1:AZ3000",
      role: "item_base"
    });
  }
  manifest.planning_sources = planningSources;
  return { manifest, files: [], useLatestSchema: Boolean(latestSchemaPath) };
}

function ensureTargetTablesSelected() {
  if (!selectedTargetTables.length) {
    throw new Error("请先点击“选择配置表”，勾选本次活动的主要关联表");
  }
}

function ensurePlanningSource(manifest) {
  if (planningFeishuUrlInput.value.trim()) return;
  if (Array.isArray(manifest.planning_sources) && manifest.planning_sources.some((source) => (source.role || "planning") === "planning")) return;
  throw new Error("请先填写飞书规划链接，或在 Manifest 里配置 planning_sources");
}

async function callApi(route, payload, { label = "处理" } = {}) {
  setStatus(`正在${label}...`, "busy");
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
    setStatus(`${label}失败`, "error");
    showTab("raw");
    throw new Error(data.error || data.stderr || "请求失败");
  }
  setStatus(`${label}完成`, "ok");
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

function compactConfigurationRecord(data) {
  const artifact = data.artifact || {};
  const result = artifact.result || parseStdout(data);
  const record = artifact.configurationRecord || result.configuration_record || null;
  return {
    summary: {
      write_mode: result.write_mode || record?.write_mode || "preview",
      operation_count: record?.operation_count || result.operation_results?.length || 0,
      target_tables: record?.target_tables || [],
      validation_summary: record?.validation_summary || null,
      previews: result.previews || record?.previews || {},
      backups: result.backups || record?.backups || {},
      written_files: result.written_files || record?.written_files || {}
    },
    tables: (record?.tables || []).map((table) => ({
      table: table.table,
      operation_count: table.operation_count,
      affected_rows: table.affected_rows,
      operations: (table.operations || []).map((operation) => ({
        op: operation.op,
        affected_rows: operation.affected_rows,
        reason: operation.reason,
        confidence: operation.confidence,
        risk_level: operation.risk_level,
        set: operation.set,
        rows: operation.rows
      }))
    })),
    record
  };
}

function renderConfigurationRecord(data) {
  const artifact = data.artifact || {};
  lastApplyResult = artifact.result || parseStdout(data);
  lastConfigurationRecord = artifact.configurationRecord || lastApplyResult.configuration_record || null;
  recordText.textContent = JSON.stringify(compactConfigurationRecord(data), null, 2);
  saveCaseReviewBtn.disabled = !lastConfigurationRecord || !caseCorrectionText.value.trim();
}

function compactRelationshipMap(data) {
  const map = data.artifact?.relationshipMap || data.relationship_map || {};
  const relations = (map.relations || []).slice(0, 80).map((relation) => ({
    from: `${relation.from_table}.${relation.from_field}`,
    to: `${relation.to_table}.${relation.to_field}`,
    to_field_kind: relation.to_field_kind,
    type: relation.relation_type,
    confidence: relation.confidence,
    risk: relation.risk,
    hop: relation.hop,
    evidence: relation.evidence
  }));
  return {
    summary: map.summary || parseStdout(data),
    target_tables: map.target_tables || [],
    recommended_tables: map.recommended_tables || [],
    ai_review: map.ai_review || null,
    relations,
    diagnostics: {
      missing_refs: (map.diagnostics?.missing_refs || []).slice(0, 40),
      errors: map.diagnostics?.errors || []
    }
  };
}

function compactItemResolution(data) {
  const resolution = data.artifact?.planningItemResolution || data.artifact?.analysis?.planning_item_resolution || {};
  return {
    enabled: Boolean(resolution.enabled),
    summary: resolution.summary || {},
    matches: (resolution.matches || []).slice(0, 30),
    missing: (resolution.missing || []).slice(0, 20),
    warnings: resolution.warnings || []
  };
}

function compactDraftDiagnostics(data) {
  return data.artifact?.draftDiagnostics || null;
}

function compactConfigPlan(data) {
  return data.artifact?.configPlan || data.config_plan || null;
}

function compactExperienceSummary(data) {
  return data.artifact?.experienceSummary || data.experience_summary || null;
}

function renderExperienceSummary(data) {
  const summary = compactExperienceSummary(data);
  if (!summary) return null;
  latestExperienceSummary = summary;
  experienceSummaryText.value = summary.review_text || "";
  saveRememberedInputs();
  saveExperienceBtn.disabled = !experienceSummaryText.value.trim();
  resultText.textContent = JSON.stringify(
    {
      mode: summary.mode,
      summary_title: summary.summary_title,
      questions: summary.questions || [],
      risk_notes: summary.risk_notes || [],
      ai_error: summary.ai_error || null,
      records_preview: summary.records_preview || null
    },
    null,
    2
  );
  return summary;
}

function renderPlanArtifact(data) {
  const plan = compactConfigPlan(data);
  if (!plan) return null;
  planText.textContent = formatConfigPlan(plan);
  confirmationsText.textContent = formatConfirmations(plan);
  return plan;
}

function formatConfigPlan(plan) {
  if (!plan) return "暂无配表计划。";
  const lines = [];
  lines.push("配表计划");
  lines.push("");
  lines.push(`活动模板：${plan.activity_type || "未识别"}`);
  lines.push(`置信度：${formatConfidence(plan.confidence)}`);
  if (plan.relation_chain?.length) {
    lines.push(`推荐链路：${plan.relation_chain.join(" -> ")}`);
  }
  appendList(lines, "建议补选配置表", plan.recommended_target_tables);
  appendList(lines, "本次完整建议表", plan.all_recommended_tables);
  appendList(lines, "自动纳入生成范围", plan.auto_included_target_tables);
  appendRequiredFields(lines, plan.required_fields);
  appendMatchedMappings(lines, plan.matched_field_mappings);
  appendMatchedRules(lines, plan.matched_rules);
  appendSimilarCases(lines, plan.similar_cases);
  appendList(lines, "缺失信息", plan.missing_information);
  appendList(lines, "下一步", plan.next_steps || defaultPlanNextSteps(plan));
  if (plan.safety) {
    lines.push("安全边界");
    lines.push(`- ${plan.safety}`);
  }
  return lines.join("\n").trim();
}

function formatConfirmations(plan) {
  const confirmations = plan?.pending_confirmations || [];
  if (!confirmations.length) {
    return "暂无待确认字段。高风险和低置信字段仍会在生成草案时继续进入审核。";
  }
  const lines = ["待确认字段", ""];
  for (const item of confirmations) {
    const aliases = item.source_aliases?.length ? item.source_aliases.join(" / ") : "未命名规划字段";
    lines.push(`- ${aliases} -> ${item.target_table || "?"}.${item.target_field || "?"}`);
    lines.push(`  置信度：${formatConfidence(item.confidence)}；原因：${item.reason || "需要人工确认"}`);
  }
  return lines.join("\n");
}

function formatDraftDiagnostics(diagnostics) {
  if (!diagnostics) return "暂无草案诊断。";
  const lines = [];
  lines.push(diagnostics.status === "empty" ? "草案没有生成配置变更" : "草案诊断");
  lines.push("");
  if (diagnostics.summary) {
    lines.push(diagnostics.summary);
    lines.push("");
  }
  appendList(lines, "原因", diagnostics.reasons);
  appendList(lines, "缺少的信息", diagnostics.missing_information);
  appendList(lines, "建议勾选的关联表", diagnostics.suggested_target_tables);
  if (diagnostics.config_plan) {
    const plan = diagnostics.config_plan;
    lines.push("配表计划摘要");
    lines.push(`- 活动模板：${plan.activity_type || "未识别"}`);
    if (plan.recommended_target_tables?.length) {
      lines.push(`- 建议补选：${plan.recommended_target_tables.join(", ")}`);
    }
    if (plan.pending_confirmations?.length) {
      lines.push(`- 待确认字段：${plan.pending_confirmations.length}`);
    }
    lines.push("");
  }
  appendFieldMappings(lines, diagnostics.suggested_field_mappings);
  if (diagnostics.relationship_summary) {
    lines.push("关联关系摘要");
    lines.push(`- 关系数：${diagnostics.relationship_summary.relation_count || 0}`);
    lines.push(`- 高置信关系：${diagnostics.relationship_summary.high_confidence_count || 0}`);
    if (diagnostics.relationship_summary.recommended_tables?.length) {
      lines.push(`- 推荐表：${diagnostics.relationship_summary.recommended_tables.join(", ")}`);
    }
    lines.push("");
  }
  appendList(lines, "下一步", diagnostics.next_steps);
  appendList(lines, "自动纳入生成范围", diagnostics.auto_included_target_tables);
  if (diagnostics.ai_review && !diagnostics.ai_review.error) {
    lines.push("AI 诊断");
    lines.push(JSON.stringify(diagnostics.ai_review, null, 2));
    lines.push("");
  }
  if (diagnostics.ai_review?.error) {
    lines.push("AI 诊断未完成");
    lines.push(`- ${diagnostics.ai_review.error}`);
    lines.push("");
  }
  if (diagnostics.ai_reason) {
    lines.push("AI 原始判断摘要");
    lines.push(diagnostics.ai_reason);
  }
  return lines.join("\n");
}

function appendRequiredFields(lines, requiredFields) {
  const entries = Object.entries(requiredFields || {});
  if (!entries.length) return;
  lines.push("模板必填字段");
  for (const [table, fields] of entries.slice(0, 10)) {
    lines.push(`- ${table}: ${(fields || []).join(", ")}`);
  }
  lines.push("");
}

function appendMatchedMappings(lines, mappings) {
  if (!mappings?.length) return;
  lines.push("命中的字段映射");
  for (const mapping of mappings.slice(0, 12)) {
    const aliases = mapping.matched_aliases?.length ? mapping.matched_aliases.join(" / ") : (mapping.source_aliases || []).slice(0, 3).join(" / ");
    lines.push(`- ${aliases || "规划字段"} -> ${mapping.target_table}.${mapping.target_field}（${formatConfidence(mapping.confidence)}）`);
  }
  lines.push("");
}

function appendMatchedRules(lines, rules) {
  if (!rules?.length) return;
  lines.push("命中的个人规则");
  for (const rule of rules.slice(0, 8)) {
    lines.push(`- ${rule.title || rule.text || rule.rule_id}（${formatConfidence(rule.match_score || rule.confidence)}）`);
  }
  lines.push("");
}

function appendSimilarCases(lines, cases) {
  if (!cases?.length) return;
  lines.push("相似历史案例");
  for (const item of cases.slice(0, 6)) {
    lines.push(`- ${item.patch_id || item.case_id}: ${item.decision || "case"}，${item.operation_count || 0} 个操作`);
  }
  lines.push("");
}

function formatConfidence(value) {
  const number = Number(value || 0);
  if (!Number.isFinite(number) || number <= 0) return "待确认";
  return `${Math.round(number * 100)}%`;
}

function defaultPlanNextSteps(plan) {
  const steps = [];
  if (plan?.recommended_target_tables?.length) steps.push("把建议补选配置表加入本次目标表后重新分析关联关系。");
  if (plan?.missing_information?.length) steps.push("补充缺失信息或写入一条经验规则。");
  if (!steps.length) steps.push("确认配表计划后生成待审核草案。");
  return steps;
}

function appendList(lines, title, values) {
  if (!values?.length) return;
  lines.push(title);
  for (const value of values) {
    lines.push(`- ${value}`);
  }
  lines.push("");
}

function appendFieldMappings(lines, mappings) {
  if (!mappings?.length) return;
  lines.push("建议优先补充的字段映射");
  for (const mapping of mappings.slice(0, 12)) {
    lines.push(`- ${mapping.target_table}`);
    if (mapping.primary_key?.length) lines.push(`  主键：${mapping.primary_key.join(", ")}`);
    if (mapping.fields_to_map_first?.length) lines.push(`  字段：${mapping.fields_to_map_first.join(", ")}`);
  }
  lines.push("");
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

async function runAction(event, action) {
  const button = event.currentTarget;
  const label = button?.dataset.originalText || button?.textContent?.trim() || "处理";
  setActionBusy(button, label, true);
  try {
    await action(label);
  } catch (error) {
    setStatus(`${label}失败：${error.message}`, "error");
  } finally {
    setActionBusy(button, label, false);
    saveExperienceBtn.disabled = !experienceSummaryText.value.trim();
    const hasSelectedExperience = Boolean(selectedExperienceId);
    updateExperienceBtn.disabled = !hasSelectedExperience || !experienceEditText.value.trim();
    deleteExperienceBtn.disabled = !hasSelectedExperience;
    saveCaseReviewBtn.disabled = !lastConfigurationRecord || !caseCorrectionText.value.trim();
  }
}

for (const [, input] of rememberedFields) {
  input.addEventListener("input", saveRememberedInputs);
  input.addEventListener("change", saveRememberedInputs);
}

experienceSummaryText.addEventListener("input", () => {
  saveExperienceBtn.disabled = !experienceSummaryText.value.trim();
});

caseCorrectionText.addEventListener("input", () => {
  saveCaseReviewBtn.disabled = !lastConfigurationRecord || !caseCorrectionText.value.trim();
});

document.querySelector("#loadSample").addEventListener("click", () => {
  latestSchemaPath = "";
  localStorage.removeItem(storageKey("latestSchemaPath"));
  selectedTargetTables = ["shop_pack_config"];
  writeJsonStorage("targetTables", selectedTargetTables);
  manifestText.value = JSON.stringify(sampleManifest, null, 2);
  updateTargetSummary();
  setStatus("示例已加载", "ok");
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
  setStatus("已清空待选配置表", "ok");
});
document.querySelector("#refreshTableOptions").addEventListener("click", async () => {
  setStatus("正在刷新配置表列表...", "busy");
  const refreshed = await loadTableOptions();
  if (refreshed) setStatus("配置表列表已刷新", "ok");
});
document.querySelector("#saveCommonTables").addEventListener("click", saveCommonTables);
document.querySelector("#selectCommonTables").addEventListener("click", () => {
  for (const name of commonTableNames()) {
    pendingTargetSelection.add(name);
  }
  renderTableList();
  setStatus("已勾选常用表", "ok");
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
document.querySelector("#openExperienceDialog").addEventListener("click", openExperienceDialog);
document.querySelector("#closeExperienceDialog").addEventListener("click", closeExperienceDialog);
document.querySelector("#refreshExperienceList").addEventListener("click", (event) => runAction(event, loadSavedExperiences));
experienceSearchInput.addEventListener("input", renderExperienceList);
experienceList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-experience-id]");
  if (button) selectExperience(button.dataset.experienceId);
});
experienceEditText.addEventListener("input", () => {
  updateExperienceBtn.disabled = !selectedExperienceId || !experienceEditText.value.trim();
});
updateExperienceBtn.addEventListener("click", (event) => runAction(event, updateSelectedExperience));
deleteExperienceBtn.addEventListener("click", (event) => runAction(event, deleteSelectedExperience));
experienceDialog.addEventListener("click", (event) => {
  if (event.target === experienceDialog) closeExperienceDialog();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !targetDialog.hidden) closeTargetDialog();
  if (event.key === "Escape" && !experienceDialog.hidden) closeExperienceDialog();
});

document.querySelector("#schemaScanBtn").addEventListener("click", (event) => runAction(event, async (label) => {
  const payload = await buildPayload();
  const data = await callApi("/api/schema-scan", payload, { label });
  rememberSchemaPath(data.artifact?.schemaDraft?.path || parseStdout(data).schema_draft);
  await loadTableOptions({ silent: true });
  resultText.textContent = JSON.stringify(compactSchemaResult(data), null, 2);
  showTab("result");
  if (!selectedTargetTables.length) openTargetDialog();
}));

document.querySelector("#relationsBtn").addEventListener("click", (event) => runAction(event, async (label) => {
  ensureTargetTablesSelected();
  const payload = await buildPayload();
  if (draftMode === "real") {
    const aiStatus = latestAiStatus?.ready ? latestAiStatus : await loadAiStatus();
    payload.explain = Boolean(aiStatus?.ready);
  }
  const data = await callApi("/api/relations", payload, { label });
  relationsText.textContent = JSON.stringify(compactRelationshipMap(data), null, 2);
  resultText.textContent = JSON.stringify(parseStdout(data), null, 2);
  showTab("relations");
}));

document.querySelector("#teachBtn").addEventListener("click", (event) => runAction(event, async (label) => {
  const text = experienceText.value.trim();
  if (!text) throw new Error("请先写入一条配表经验");
  const payload = await buildPayload();
  payload.experience_text = text;
  const data = await callApi("/api/experience-summary", payload, { label });
  const summary = renderExperienceSummary(data);
  showTab("result");
  if (summary?.ai_error) {
    setStatus("AI 整理失败，已生成本地整理结果", "error");
  }
}));

saveExperienceBtn.addEventListener("click", (event) => runAction(event, async (label) => {
  const text = experienceSummaryText.value.trim();
  if (!text) throw new Error("请先整理经验，或在整理结果中填写要保存的内容");
  const payload = await buildPayload();
  payload.experience_text = text;
  const data = await callApi("/api/teach", payload, { label });
  const summary = parseStdout(data);
  resultText.textContent = JSON.stringify(
    {
      store: summary.store,
      created: summary.created,
      summary_title: latestExperienceSummary?.summary_title || null,
      hint: "经验已写入本地 .knowledge，后续识别模板和生成草案会自动参考。"
    },
    null,
    2
  );
  showTab("result");
  if (!experienceDialog.hidden) await loadSavedExperiences();
}));

document.querySelector("#activityPlanBtn").addEventListener("click", (event) => runAction(event, async (label) => {
  const payload = await buildPayload();
  ensurePlanningSource(payload.manifest);
  const data = await callApi("/api/activity-plan", payload, { label });
  const plan = renderPlanArtifact(data);
  resultText.textContent = JSON.stringify(parseStdout(data), null, 2);
  showTab(plan?.pending_confirmations?.length ? "confirmations" : "plan");
}));

document.querySelector("#analyzeBtn").addEventListener("click", (event) => runAction(event, async (label) => {
  ensureTargetTablesSelected();
  const payload = await buildPayload();
  ensurePlanningSource(payload.manifest);
  const data = await callApi("/api/analyze", payload, { label });
  if (data.artifact?.relationshipMap) {
    relationsText.textContent = JSON.stringify(compactRelationshipMap(data), null, 2);
  }
  renderPlanArtifact(data);
  resultText.textContent = JSON.stringify(
    {
      summary: parseStdout(data),
      planning_item_resolution: compactItemResolution(data),
      analysis: data.artifact?.analysis || null
    },
    null,
    2
  );
  showTab("result");
}));

document.querySelector("#draftBtn").addEventListener("click", (event) => runAction(event, async (label) => {
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
  const data = await callApi("/api/draft", payload, { label });
  if (data.artifact?.patch) {
    lastPatch = data.artifact.patch;
    patchText.value = JSON.stringify(lastPatch, null, 2);
  }
  const diagnostics = compactDraftDiagnostics(data);
  if (diagnostics) {
    diagnosticsText.textContent = formatDraftDiagnostics(diagnostics);
  }
  if (data.artifact?.relationshipMap) {
    relationsText.textContent = JSON.stringify(compactRelationshipMap(data), null, 2);
  }
  renderPlanArtifact(data);
  resultText.textContent = JSON.stringify(parseStdout(data), null, 2);
  const operationCount = data.artifact?.patch?.operations?.length || 0;
  if (operationCount === 0 && diagnostics) {
    setStatus("生成草案完成：没有安全变更，已生成诊断", "ok");
    showTab("diagnostics");
  } else {
    showTab("patch");
  }
}));

async function applyCurrentPatch(writeMode, label) {
  const payload = await buildPayload();
  payload.patch = JSON.parse(patchText.value || JSON.stringify(lastPatch || {}));
  payload.write_mode = writeMode;
  const data = await callApi("/api/apply", payload, { label });
  renderConfigurationRecord(data);
  resultText.textContent = JSON.stringify(data.artifact || parseStdout(data), null, 2);
  showTab("record");
}

document.querySelector("#applyBtn").addEventListener("click", (event) => runAction(event, async (label) => {
  await applyCurrentPatch("preview", label);
}));

document.querySelector("#overwriteBtn").addEventListener("click", (event) => runAction(event, async (label) => {
  const confirmed = window.confirm("确认覆盖原表吗？工具会先生成备份、预览、diff、校验报告和回滚 patch，再写回原 Excel。");
  if (!confirmed) return;
  await applyCurrentPatch("overwrite", label);
}));

saveCaseReviewBtn.addEventListener("click", (event) => runAction(event, async (label) => {
  if (!lastApplyResult || !lastConfigurationRecord) {
    throw new Error("请先生成预览或覆盖原表，拿到本次配表记录后再复盘。");
  }
  const correction = caseCorrectionText.value.trim();
  if (!correction) throw new Error("请先填写这次配表的问题。");
  const payload = await buildPayload();
  payload.patch = JSON.parse(patchText.value || JSON.stringify(lastPatch || {}));
  payload.apply_result = lastApplyResult;
  payload.correction_text = correction;
  payload.no_ai = draftMode !== "real";
  const data = await callApi("/api/case-review", payload, { label });
  const caseReview = data.artifact?.caseReview || parseStdout(data);
  recordText.textContent = JSON.stringify(
    {
      configuration_record: lastConfigurationRecord,
      case_review: caseReview
    },
    null,
    2
  );
  resultText.textContent = JSON.stringify(caseReview, null, 2);
  setStatus("案例复盘已保存，后续相似配表会优先参考这次修正", "ok");
  showTab("record");
}));

document.querySelector("#learnBtn").addEventListener("click", (event) => runAction(event, async (label) => {
  const payload = await buildPayload();
  payload.patch = JSON.parse(patchText.value || JSON.stringify(lastPatch || {}));
  payload.decision = "accepted";
  payload.note = "从本地面板确认通过";
  const data = await callApi("/api/learn", payload, { label });
  resultText.textContent = JSON.stringify(parseStdout(data), null, 2);
  showTab("result");
}));

for (const button of document.querySelectorAll(".tab")) {
  button.addEventListener("click", () => showTab(button.dataset.tab));
}

manifestText.value = JSON.stringify(sampleManifest, null, 2);
restoreRememberedInputs();
saveExperienceBtn.disabled = !experienceSummaryText.value.trim();
saveCaseReviewBtn.disabled = true;
const storedCommonTables = readJsonStorage("commonTables", []);
commonTablesInput.value = storedCommonTables.join("\n");
applyTargetTablesToManifest();
setAiProvider(aiProvider);
setDraftMode(draftMode);
updateTargetSummary();
loadLatestSchema();
