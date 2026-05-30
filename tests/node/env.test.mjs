import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import { aiRuntimeStatus, loadDotEnv, normalizeAiProvider, parseDotEnv } from "../../src/env.mjs";

test("parseDotEnv handles comments, exports, and quotes", () => {
  const parsed = parseDotEnv(`
# ignored
TEST_API_KEY="base-key"
export SECOND_API_KEY='deepseek-key'
DEEPSEEK_MODEL=deepseek-v4-pro # local note
`);
  assert.deepEqual(parsed, {
    TEST_API_KEY: "base-key",
    SECOND_API_KEY: "deepseek-key",
    DEEPSEEK_MODEL: "deepseek-v4-pro"
  });
});

test("loadDotEnv does not override existing process values", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "ai-meta-agent-env-"));
  fs.writeFileSync(path.join(dir, ".env"), "TEST_API_KEY=from-file\nDEEPSEEK_API_KEY=from-file\n", "utf8");
  const env = { TEST_API_KEY: "from-env" };
  const result = loadDotEnv(dir, env);
  assert.equal(result.found, true);
  assert.equal(env.TEST_API_KEY, "from-env");
  assert.equal(env.DEEPSEEK_API_KEY, "from-file");
  assert.deepEqual(result.loaded, ["DEEPSEEK_API_KEY"]);
  assert.deepEqual(result.skipped, ["TEST_API_KEY"]);
});

test("aiRuntimeStatus resolves DeepSeek V4 Pro defaults", () => {
  const status = aiRuntimeStatus({ DEEPSEEK_API_KEY: "test" }, { provider: "deepseek-v4-pro" });
  assert.equal(normalizeAiProvider("deepseek-v4-pro"), "deepseek_v4_pro");
  assert.equal(status.provider, "deepseek_v4_pro");
  assert.equal(status.provider_label, "DeepSeek V4 Pro");
  assert.equal(status.api_key_env, "DEEPSEEK_API_KEY");
  assert.equal(status.base_url, "https://api.deepseek.com");
  assert.equal(status.model, "deepseek-v4-pro");
  assert.equal(status.api_key_configured, true);
});
