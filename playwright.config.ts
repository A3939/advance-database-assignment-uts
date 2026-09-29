import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/browser",
  fullyParallel: false,
  workers: 1,
  timeout: 30_000,
  use: {
    baseURL: process.env.ARSIA_TEST_URL || "http://127.0.0.1:3100",
    viewport: { width: 1440, height: 1000 },
    trace: "retain-on-failure",
    channel: process.env.ARSIA_BROWSER_CHANNEL,
    launchOptions: { args: ["--enable-unsafe-swiftshader"] },
  },
  reporter: "list",
});
