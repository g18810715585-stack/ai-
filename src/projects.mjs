import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";

const PROJECT_ID_RE = /^[a-z0-9][a-z0-9_-]{5,79}$/;

function nowIso() {
  return new Date().toISOString();
}

function projectsRoot(projectRoot) {
  return path.join(projectRoot, ".runs", "projects");
}

function assertProjectId(projectId) {
  if (!PROJECT_ID_RE.test(String(projectId || ""))) {
    throw new Error("invalid project id");
  }
}

function projectDir(projectRoot, projectId) {
  assertProjectId(projectId);
  return path.join(projectsRoot(projectRoot), projectId);
}

function projectPath(projectRoot, projectId) {
  return path.join(projectDir(projectRoot, projectId), "project.json");
}

function writeJson(filePath, data) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, JSON.stringify(data, null, 2), "utf8");
}

function readJson(filePath, fallback = null) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch {
    return fallback;
  }
}

function slugifyName(name) {
  const ascii = String(name || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 28);
  return ascii || "project";
}

function makeProjectId(name) {
  return `${slugifyName(name)}-${crypto.randomBytes(4).toString("hex")}`;
}

function defaultProject(projectId, name) {
  const timestamp = nowIso();
  return {
    project_id: projectId,
    name: String(name || "未命名配表项目").trim() || "未命名配表项目",
    created_at: timestamp,
    updated_at: timestamp,
    inputs: {},
    ui: {},
    steps: {},
    history: []
  };
}

function normalizeProject(project) {
  return {
    ...project,
    inputs: project.inputs || {},
    ui: project.ui || {},
    steps: project.steps || {},
    history: Array.isArray(project.history) ? project.history : []
  };
}

export function createProject(projectRoot, { name, inputs = {}, ui = {} } = {}) {
  const root = projectsRoot(projectRoot);
  fs.mkdirSync(root, { recursive: true });
  let projectId = makeProjectId(name);
  while (fs.existsSync(projectPath(projectRoot, projectId))) {
    projectId = makeProjectId(name);
  }
  const project = defaultProject(projectId, name);
  project.inputs = { ...inputs };
  project.ui = { ...ui };
  writeJson(projectPath(projectRoot, projectId), project);
  return project;
}

export function readProject(projectRoot, projectId) {
  const data = readJson(projectPath(projectRoot, projectId));
  if (!data) throw new Error(`未找到配表项目：${projectId}`);
  return normalizeProject(data);
}

export function listProjects(projectRoot) {
  const root = projectsRoot(projectRoot);
  if (!fs.existsSync(root)) return [];
  return fs.readdirSync(root, { withFileTypes: true })
    .filter((item) => item.isDirectory())
    .map((item) => {
      const data = readJson(path.join(root, item.name, "project.json"));
      if (!data?.project_id) return null;
      return normalizeProject(data);
    })
    .filter(Boolean)
    .sort((left, right) => String(right.updated_at || "").localeCompare(String(left.updated_at || "")))
    .map((project) => ({
      project_id: project.project_id,
      name: project.name,
      created_at: project.created_at,
      updated_at: project.updated_at,
      input_summary: {
        config_dir: project.inputs?.config_dir || "",
        planning_feishu_url: project.inputs?.planning_feishu_url || "",
        target_tables: project.inputs?.target_tables || []
      },
      latest_steps: Object.fromEntries(
        Object.entries(project.steps || {}).map(([step, record]) => [
          step,
          {
            updated_at: record.updated_at,
            run_dir: record.run_dir,
            summary: record.summary || {}
          }
        ])
      )
    }));
}

export function updateProject(projectRoot, projectId, patch = {}) {
  const project = readProject(projectRoot, projectId);
  if (patch.name !== undefined) {
    project.name = String(patch.name || "").trim() || project.name;
  }
  if (patch.inputs) {
    project.inputs = { ...project.inputs, ...patch.inputs };
  }
  if (patch.ui) {
    project.ui = { ...project.ui, ...patch.ui };
  }
  if (patch.steps) {
    project.steps = { ...project.steps, ...patch.steps };
  }
  project.updated_at = nowIso();
  writeJson(projectPath(projectRoot, projectId), project);
  return project;
}

export function projectRunRoot(projectRoot, projectId) {
  const dir = path.join(projectDir(projectRoot, projectId), "runs");
  fs.mkdirSync(dir, { recursive: true });
  return dir;
}

export function latestProjectRunFile(projectRoot, projectId, pointerName, fileName) {
  const pointer = path.join(projectRunRoot(projectRoot, projectId), pointerName);
  if (!fs.existsSync(pointer)) return null;
  const value = fs.readFileSync(pointer, "utf8").trim();
  if (!value) return null;
  const candidate = fileName ? path.join(value, fileName) : value;
  return fs.existsSync(candidate) ? candidate : null;
}

export function projectManifestPatch(projectRoot, projectId, manifest) {
  const project = readProject(projectRoot, projectId);
  return {
    ...manifest,
    project: project.name,
    run_root: projectRunRoot(projectRoot, projectId)
  };
}

export function extractProjectInputs(payload = {}) {
  const manifest = payload.manifest || {};
  const planning = (manifest.planning_sources || []).find((source) => (source.role || "planning") === "planning") || {};
  const itemBase = (manifest.planning_sources || []).find((source) => source.role === "item_base") || {};
  const configRoot = (manifest.config_roots || [])[0] || {};
  return {
    config_dir: configRoot.path || "",
    planning_feishu_url: planning.url || "",
    item_base_feishu_url: itemBase.url || "",
    target_tables: manifest.target_tables || [],
    ai_provider: manifest.ai?.provider || "",
    draft_mode: payload.stub === false ? "real" : payload.draft_mode || "",
    schema_path: manifest.schema_path || ""
  };
}

export function recordWorkflowRun(projectRoot, projectId, step, { result, artifact, payload } = {}) {
  const project = readProject(projectRoot, projectId);
  const parsed = parseStdout(result?.stdout);
  const runDir = parsed.run_dir || artifact?.analysis?.run_dir || null;
  const record = {
    step,
    updated_at: nowIso(),
    run_dir: runDir,
    status: result?.status ?? null,
    paths: stepPaths(parsed),
    summary: stepSummary(step, artifact, parsed),
    data: stepData(step, artifact, parsed)
  };
  project.inputs = { ...project.inputs, ...extractProjectInputs(payload) };
  project.steps = { ...project.steps, [step]: record };
  project.history = [
    { step, updated_at: record.updated_at, run_dir: record.run_dir, status: record.status, summary: record.summary },
    ...(project.history || [])
  ].slice(0, 80);
  project.updated_at = nowIso();
  writeJson(projectPath(projectRoot, projectId), project);
  return project;
}

function parseStdout(stdout) {
  try {
    return JSON.parse(stdout || "{}");
  } catch {
    return {};
  }
}

function stepPaths(parsed) {
  return Object.fromEntries(
    Object.entries({
      run_dir: parsed.run_dir,
      report: parsed.report,
      schema_draft: parsed.schema_draft,
      relationship_map: parsed.relationship_map,
      analysis: parsed.run_dir ? path.join(parsed.run_dir, "analysis.json") : null,
      config_plan: parsed.config_plan,
      draft_table_preview: parsed.draft_table_preview,
      draft_diagnostics: parsed.draft_diagnostics,
      patch: parsed.patch,
      result: parsed.result,
      configuration_record: parsed.configuration_record,
      case_review: parsed.case_review
    }).filter(([, value]) => Boolean(value))
  );
}

function stepSummary(step, artifact = {}, parsed = {}) {
  if (step === "schemaScan") {
    return {
      table_count: artifact.schemaScan?.table_count || artifact.schemaDraft?.table_count || 0,
      duplicate_count: artifact.schemaScan?.duplicate_count || 0,
      path: parsed.schema_draft || artifact.schemaDraft?.path || ""
    };
  }
  if (step === "relations") {
    return {
      relation_count: artifact.relationshipMap?.summary?.relation_count || 0,
      recommended_tables: artifact.relationshipMap?.recommended_tables || []
    };
  }
  if (step === "analyze") {
    return {
      target_tables: artifact.analysis?.target_tables || [],
      workbook_count: artifact.analysis?.workbook_count || 0,
      matched_count: artifact.analysis?.config_discovery?.matched_count || 0
    };
  }
  if (step === "draft") {
    return {
      operation_count: artifact.patch?.operations?.length || 0,
      status: artifact.draftDiagnostics?.status || "draft",
      table_preview_count: artifact.draftTablePreview?.table_count || 0,
      target_tables: [...new Set((artifact.patch?.operations || []).map((operation) => operation.target_table))]
    };
  }
  if (step === "applyPreview" || step === "applyOverwrite") {
    const result = artifact.result || {};
    return {
      write_mode: result.write_mode || parsed.write_mode || "",
      operation_count: result.operation_results?.length || 0,
      preview_count: Object.keys(result.previews || {}).length,
      written_count: Object.keys(result.written_files || {}).length,
      validation_summary: artifact.configurationRecord?.validation_summary || null
    };
  }
  if (step === "caseReview") {
    return {
      decision: artifact.caseReview?.decision || "",
      patch_id: artifact.caseReview?.patch_id || ""
    };
  }
  if (step === "experienceSummary") {
    return {
      summary_title: artifact.experienceSummary?.summary_title || parsed.summary_title || "",
      mode: artifact.experienceSummary?.mode || parsed.mode || "",
      conflict_count: artifact.experienceSummary?.conflicts?.length || parsed.conflict_count || 0,
      has_conflicts: Boolean(artifact.experienceSummary?.has_conflicts || parsed.has_conflicts)
    };
  }
  return { run_dir: parsed.run_dir || "" };
}

function stepData(step, artifact = {}, parsed = {}) {
  if (step === "schemaScan") {
    return { schemaDraft: artifact.schemaDraft || null, schemaScan: artifact.schemaScan || null };
  }
  if (step === "relations") {
    return { relationshipMap: compactRelationshipMap(artifact.relationshipMap || {}) };
  }
  if (step === "analyze") {
    return {
      analysis: artifact.analysis || null,
      relationshipMap: compactRelationshipMap(artifact.relationshipMap || {}),
      planningItemResolution: artifact.planningItemResolution || artifact.analysis?.planning_item_resolution || null,
      configPlan: artifact.configPlan || null
    };
  }
  if (step === "draft") {
    return {
      patch: artifact.patch || null,
      configPlan: artifact.configPlan || null,
      draftDiagnostics: artifact.draftDiagnostics || null,
      draftTablePreview: artifact.draftTablePreview || null,
      relationshipMap: compactRelationshipMap(artifact.relationshipMap || {})
    };
  }
  if (step === "applyPreview" || step === "applyOverwrite") {
    return {
      result: compactApplyResult(artifact.result || {}),
      configurationRecord: artifact.configurationRecord || null,
      diff: compactDiff(artifact.diff || {}),
      validation: artifact.validation || null,
      rollback: artifact.rollback || null
    };
  }
  if (step === "caseReview") {
    return { caseReview: artifact.caseReview || parsed };
  }
  if (step === "experienceSummary") {
    return { experienceSummary: artifact.experienceSummary || null };
  }
  return { parsed };
}

function compactRelationshipMap(map) {
  return {
    summary: map.summary || {},
    target_tables: map.target_tables || [],
    recommended_tables: map.recommended_tables || [],
    ai_review: map.ai_review || null,
    relations: (map.relations || []).slice(0, 120),
    diagnostics: {
      missing_refs: (map.diagnostics?.missing_refs || []).slice(0, 60),
      errors: map.diagnostics?.errors || []
    }
  };
}

function compactApplyResult(result) {
  return {
    patch_id: result.patch_id,
    write_mode: result.write_mode,
    operation_results: result.operation_results || [],
    previews: result.previews || {},
    backups: result.backups || {},
    written_files: result.written_files || {},
    validation: result.validation || {}
  };
}

function compactDiff(diff) {
  const compact = {};
  for (const [filePath, tables] of Object.entries(diff || {})) {
    compact[filePath] = {};
    for (const [table, value] of Object.entries(tables || {})) {
      compact[filePath][table] = {
        inserted: (value.inserted || []).slice(0, 20),
        deleted: (value.deleted || []).slice(0, 20),
        changed: (value.changed || []).slice(0, 20),
        inserted_count: (value.inserted || []).length,
        deleted_count: (value.deleted || []).length,
        changed_count: (value.changed || []).length
      };
    }
  }
  return compact;
}
