import path from "node:path";

export function buildPythonEnv(projectRoot, baseEnv = process.env) {
  const env = { ...baseEnv };
  env.PYTHONPATH = env.PYTHONPATH ? `${projectRoot}${path.delimiter}${env.PYTHONPATH}` : projectRoot;
  env.PYTHONIOENCODING = "utf-8";
  env.PYTHONUTF8 = "1";
  return env;
}
