import { defineConfig } from "playwright/test";

// Parallel checkouts can set PLAYWRIGHT_PORT so their servers do not collide.
const port = Number(process.env.PLAYWRIGHT_PORT ?? 4190);
const baseURL = `http://127.0.0.1:${port}`;
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;

export default defineConfig({
  testDir: "./e2e",
  // A stray .only must never pass CI by running a single test.
  forbidOnly: !!process.env.CI,
  timeout: 90_000,
  use: {
    baseURL,
    launchOptions: executablePath ? { executablePath } : {},
  },
  webServer: {
    command: `python3 -m http.server ${port} --bind 127.0.0.1 --directory out`,
    url: baseURL,
  },
});
