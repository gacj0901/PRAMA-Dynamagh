import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/browser", workers: 1,
  use: { baseURL: "http://127.0.0.1:4179", channel: "msedge", headless: true },
  webServer: { command: "npm run dev -- --host 127.0.0.1 --port 4179", url: "http://127.0.0.1:4179", reuseExistingServer: false },
});
