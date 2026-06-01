import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  createProject,
  listProjects,
  projectManifestPatch,
  projectRunRoot,
  readProject,
  recordWorkflowRun,
  updateProject
} from "../../src/projects.mjs";

test("projects can be created, listed, read, and updated", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ai-meta-agent-projects-"));
  const project = createProject(dir, {
    name: "航海节兑换店",
    inputs: { config_dir: "C:\\TopHero\\Meta", run_instruction: "活动ID新建", target_tables: ["activity"] }
  });

  assert.match(project.project_id, /^[a-z0-9][a-z0-9_-]{5,79}$/);
  assert.equal(project.name, "航海节兑换店");
  assert.equal(readProject(dir, project.project_id).inputs.config_dir, "C:\\TopHero\\Meta");
  assert.equal(readProject(dir, project.project_id).inputs.run_instruction, "活动ID新建");

  const updated = updateProject(dir, project.project_id, {
    inputs: { target_tables: ["activity", "active_shop"] },
    ui: { last_tab: "patch" }
  });
  assert.deepEqual(updated.inputs.target_tables, ["activity", "active_shop"]);
  assert.equal(updated.ui.last_tab, "patch");

  const listed = listProjects(dir);
  assert.equal(listed.length, 1);
  assert.equal(listed[0].project_id, project.project_id);
  assert.deepEqual(listed[0].input_summary.target_tables, ["activity", "active_shop"]);
  assert.equal(listed[0].input_summary.run_instruction, "活动ID新建");
});

test("project manifest patch redirects run root into the project workspace", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ai-meta-agent-project-run-"));
  const project = createProject(dir, { name: "积分任务" });
  const manifest = projectManifestPatch(dir, project.project_id, {
    project: "sample-pack",
    run_root: ".runs",
    schema_path: "schema.json"
  });

  assert.equal(manifest.project, "积分任务");
  assert.equal(manifest.run_root, projectRunRoot(dir, project.project_id));
  assert.ok(manifest.run_root.endsWith(path.join(".runs", "projects", project.project_id, "runs")));
});

test("workflow run records latest step data and keeps history", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ai-meta-agent-project-record-"));
  const project = createProject(dir, { name: "礼包活动" });
  const runDir = path.join(dir, ".runs", "projects", project.project_id, "runs", "draft-20260601T010000Z");
  const patchPath = path.join(runDir, "patch.json");
  fs.mkdirSync(runDir, { recursive: true });
  fs.writeFileSync(patchPath, JSON.stringify({ patch_id: "p1", project: "礼包活动", operations: [] }), "utf8");

  const recorded = recordWorkflowRun(dir, project.project_id, "draft", {
    result: {
      status: 0,
      stdout: JSON.stringify({ run_dir: runDir, patch: patchPath })
    },
    artifact: {
      patch: { patch_id: "p1", project: "礼包活动", operations: [] },
      draftDiagnostics: { status: "empty" }
    },
    payload: {
      stub: true,
      manifest: {
        config_roots: [{ path: "C:\\TopHero\\Meta", recursive: true }],
        run_instruction: "本次礼包奖励组新建",
        target_tables: ["activity"],
        ai: { provider: "chatgpt" }
      }
    }
  });

  assert.equal(recorded.steps.draft.summary.operation_count, 0);
  assert.equal(recorded.steps.draft.paths.patch, patchPath);
  assert.equal(recorded.steps.draft.data.patch.patch_id, "p1");
  assert.equal(recorded.inputs.config_dir, "C:\\TopHero\\Meta");
  assert.equal(recorded.inputs.run_instruction, "本次礼包奖励组新建");
  assert.deepEqual(recorded.inputs.target_tables, ["activity"]);
  assert.equal(recorded.history[0].step, "draft");
});
