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
  fs.writeFileSync(path.join(dir, ".env"), "TEST_API_KEY=from-file\nTHIRD_API_KEY=from-file\n", "utf8");
  const env = { TEST_API_KEY: "from-env" };
  const result = loadDotEnv(dir, env);
  assert.equal(result.found, true);
  assert.equal(env.TEST_API_KEY, "from-env");
  assert.equal(env.THIRD_API_KEY, "from-file");
  assert.deepEqual(result.loaded, ["THIRD_API_KEY"]);
  assert.deepEqual(result.skipped, ["TEST_API_KEY"]);
});

test("aiRuntimeStatus resolves company BI model choices", () => {
  const env = { BASEAI_API_KEY: "test" };
  const chatgpt = aiRuntimeStatus(env, { provider: "chatgpt" });
  const gemini = aiRuntimeStatus(env, { provider: "gemini" });
  const claude = aiRuntimeStatus(env, { provider: "claude" });
  const deepseek = aiRuntimeStatus(env, { provider: "deepseek-v4-pro" });
  assert.equal(normalizeAiProvider("baseai"), "chatgpt");
  assert.equal(chatgpt.provider_label, "ChatGPT");
  assert.equal(chatgpt.api_key_env, "BASEAI_API_KEY");
  assert.equal(chatgpt.model, "gpt-5.5");
  assert.equal(gemini.provider_label, "Gemini");
  assert.equal(gemini.model, "gemini-3.1-pro-preview");
  assert.equal(claude.provider_label, "Claude");
  assert.equal(claude.model, "claude-opus-4-8");
  assert.equal(deepseek.provider_label, "DeepSeek");
  assert.equal(deepseek.api_key_env, "BASEAI_API_KEY");
  assert.equal(deepseek.base_url, "https://baseai.rivergame.net/v1");
  assert.equal(deepseek.model, "deepseek-v4-pro");
  assert.equal(deepseek.api_key_configured, true);
});
