import { defineConfig } from "playwright/test";

const baseURL = "http://127.0.0.1:4190";
const executablePath = process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE;

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  use: {
    baseURL,
    launchOptions: executablePath ? { executablePath } : {},
  },
  webServer: {
    command: "python3 -m http.server 4190 --bind 127.0.0.1 --directory out",
    url: baseURL,
  },
});
