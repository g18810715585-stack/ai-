const manifestText = document.querySelector("#manifestText");
const patchText = document.querySelector("#patchText");
const resultText = document.querySelector("#resultText");
const rawText = document.querySelector("#rawText");
const statusEl = document.querySelector("#status");
const tableNameInput = document.querySelector("#configTableName");

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
    provider: "baseai",
    api_key_env: "BASEAI_API_KEY",
    base_url_env: "BASEAI_BASE_URL",
    model_env: "BASEAI_MODEL",
    default_base_url: "https://baseai.rivergame.net/v1",
    default_model: "gpt-5.5"
  }
};

let lastPatch = null;

function setStatus(text, state = "") {
  statusEl.textContent = text;
  statusEl.className = `status ${state}`.trim();
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
  const files = [];
  const planning = document.querySelector("#planningFile").files[0];
  const config = document.querySelector("#configFile").files[0];
  const configDir = document.querySelector("#configDir").value.trim();
  if (configDir) {
    manifest.config_roots = [{ path: configDir, recursive: true }];
  }
  if (planning) {
    files.push({ role: "planning", name: planning.name, base64: await readFileAsBase64(planning) });
  }
  if (config) {
    files.push({ role: `config:${tableNameInput.value.trim() || "shop_pack_config"}`, name: config.name, base64: await readFileAsBase64(config) });
  }
  return { manifest, files };
}

async function callApi(route, payload) {
  setStatus("处理中", "busy");
  const response = await fetch(route, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
  const data = await response.json();
  rawText.textContent = JSON.stringify(data, null, 2);
  if (!response.ok) {
    setStatus("出错", "error");
    showTab("raw");
    throw new Error(data.error || data.stderr || "请求失败");
  }
  setStatus("就绪");
  return data;
}

function parseStdout(data) {
  try {
    return JSON.parse(data.stdout || "{}");
  } catch {
    return {};
  }
}

document.querySelector("#loadSample").addEventListener("click", () => {
  manifestText.value = JSON.stringify(sampleManifest, null, 2);
});

document.querySelector("#analyzeBtn").addEventListener("click", async () => {
  const payload = await buildPayload();
  const data = await callApi("/api/analyze", payload);
  resultText.textContent = JSON.stringify(parseStdout(data), null, 2);
  showTab("result");
});

document.querySelector("#draftBtn").addEventListener("click", async () => {
  const payload = await buildPayload();
  payload.stub = true;
  const data = await callApi("/api/draft", payload);
  if (data.artifact?.patch) {
    lastPatch = data.artifact.patch;
    patchText.value = JSON.stringify(lastPatch, null, 2);
  }
  resultText.textContent = JSON.stringify(parseStdout(data), null, 2);
  showTab("patch");
});

document.querySelector("#applyBtn").addEventListener("click", async () => {
  const payload = await buildPayload();
  payload.patch = JSON.parse(patchText.value || JSON.stringify(lastPatch || {}));
  const data = await callApi("/api/apply", payload);
  resultText.textContent = JSON.stringify(data.artifact || parseStdout(data), null, 2);
  showTab("result");
});

document.querySelector("#learnBtn").addEventListener("click", async () => {
  const payload = await buildPayload();
  payload.patch = JSON.parse(patchText.value || JSON.stringify(lastPatch || {}));
  payload.decision = "accepted";
  payload.note = "从本地面板确认通过";
  const data = await callApi("/api/learn", payload);
  resultText.textContent = JSON.stringify(parseStdout(data), null, 2);
  showTab("result");
});

for (const button of document.querySelectorAll(".tab")) {
  button.addEventListener("click", () => showTab(button.dataset.tab));
}

manifestText.value = JSON.stringify(sampleManifest, null, 2);
