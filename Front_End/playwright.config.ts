import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/browser",
  // These historical suites write normal Imports/Studio or invoke real models.
  // They require migration to an explicitly verified isolated binding; ordinary
  // test:e2e (including direct filename selection) must never execute them.
  testIgnore: ["**/imports.spec.ts", "**/studio.spec.ts", "**/autonomous-live.spec.ts", "**/local-release-live.spec.ts"],
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
