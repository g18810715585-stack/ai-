export function baseAiSettings(env = process.env) {
  return {
    apiKey: env.BASEAI_API_KEY || "",
    baseUrl: (env.BASEAI_BASE_URL || "https://baseai.rivergame.net/v1").replace(/\/$/, ""),
    model: env.BASEAI_MODEL || "gpt-5.5"
  };
}

export async function callBaseAiJson(context, env = process.env, fetchImpl = fetch) {
  const settings = baseAiSettings(env);
  if (!settings.apiKey) {
    throw new Error("Missing BASEAI_API_KEY");
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
      temperature: 0.1
    })
  });
  if (!response.ok) {
    throw new Error(`BaseAI request failed: ${response.status} ${await response.text()}`);
  }
  const payload = await response.json();
  return JSON.parse(payload.choices[0].message.content);
}
