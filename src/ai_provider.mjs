import { AI_PROVIDERS, normalizeAiProvider } from "./env.mjs";

export function aiProviderSettings(provider = "chatgpt", env = process.env) {
  const providerId = normalizeAiProvider(provider);
  const defaults = AI_PROVIDERS[providerId];
  return {
    provider: providerId,
    label: defaults.label,
    apiKeyEnv: defaults.apiKeyEnv,
    apiKey: env[defaults.apiKeyEnv] || "",
    baseUrl: (env[defaults.baseUrlEnv] || defaults.defaultBaseUrl).replace(/\/$/, ""),
    model: env[defaults.modelEnv] || defaults.defaultModel,
    extraBody: providerId === "deepseek_v4_pro" ? { thinking: { type: "disabled" } } : {}
  };
}

export function baseAiSettings(env = process.env) {
  return aiProviderSettings("chatgpt", env);
}

export async function callAiJson(context, { provider = "chatgpt", env = process.env, fetchImpl = fetch } = {}) {
  const settings = aiProviderSettings(provider, env);
  if (!settings.apiKey) {
    throw new Error(`Missing ${settings.apiKeyEnv}`);
  }
  const response = await fetchImpl(`${settings.baseUrl}/chat/completions`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${settings.apiKey}`,
      "Content-Type": "application/json"
    },
    body: JSON.stringify({
      model: settings.model,
      messages: [
        {
          role: "system",
          content: "You are an AI meta configuration agent. Return only strict JSON."
        },
        {
          role: "user",
          content: JSON.stringify(context)
        }
      ],
      response_format: { type: "json_object" },
      temperature: 0.1,
      ...settings.extraBody
    })
  });
  if (!response.ok) {
    throw new Error(`${settings.label} request failed: ${response.status} ${await response.text()}`);
  }
  const payload = await response.json();
  return JSON.parse(payload.choices[0].message.content);
}

export async function callBaseAiJson(context, env = process.env, fetchImpl = fetch) {
  return callAiJson(context, { provider: "chatgpt", env, fetchImpl });
}
