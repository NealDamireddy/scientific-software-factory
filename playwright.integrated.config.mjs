import { defineConfig } from "playwright/test";

const baseURL = "http://127.0.0.1:4196";

export default defineConfig({
  testDir: "./tests/integrated",
  timeout: 100000,
  use: { baseURL, serviceWorkers: "block" },
  webServer: {
    command: "lab-factory/.venv/bin/python lab-factory/scripts/serve_portal.py --temporary --port 4196",
    url: baseURL + "/api/session",
    gracefulShutdown: { signal: "SIGINT", timeout: 5000 },
  },
});
