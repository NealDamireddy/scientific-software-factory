import { defineConfig } from "playwright/test";

const baseURL = "http://127.0.0.1:4187";
export default defineConfig({
  testDir: "./tests/browser",
  timeout: 90000,
  use: { baseURL },
  webServer: {
    command: "python3 -m http.server 4187 --bind 127.0.0.1 --directory out",
    url: baseURL,
  },
});
