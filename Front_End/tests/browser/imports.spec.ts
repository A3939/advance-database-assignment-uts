/** Real isolated LOCAL TEST integration; no dashboard routes, model calls or mocked job states. */
import { test, expect, type Page } from "@playwright/test";
import { readFileSync, mkdirSync } from "node:fs";
import { resolve } from "node:path";

const profile = { ...JSON.parse(readFileSync(resolve("pipeline/examples/wa-profile.json"), "utf8")), source_id: "browser_fixture", source_name: "Browser regression fixture", publisher: "Synthetic local test", source_evidence: "Fictional records created only to verify the local imports workflow." };
const crashes = "EVENT_ID,OCCURRED_ON,OUTCOME,DEATHS,INJURIES,UNIT_TOTAL\nB1,2023-06-15,Fatal,1,2,1\nB2,2024-01-01,Injury,0,1,1\n";
const units = "EVENT_ID,UNIT_ID,KIND\nB1,U1,Car\nB2,U1,Bicycle\n";
const file = (name: string, text: string) => ({ name, mimeType: "text/csv", buffer: Buffer.from(text) });
const selectedJob = (page: Page) => page.getByRole("region", { name: "Selected job", exact: true });
async function open(page: Page) {
  await page.goto("/imports");
  await expect(page.getByRole("heading", { name: "From source files to evidence." })).toBeVisible();
  await expect(page.getByText("Worker online · one heavy job at a time")).toBeVisible({ timeout: 15000 });
}
async function enterProfile(page: Page) {
  await page.getByText("Advanced: reviewed manual profile (optional)", { exact: true }).click();
  await page.getByLabel("Mapping profile (JSON)", { exact: true }).fill(JSON.stringify(profile, null, 2));
  await page.getByLabel("I reviewed this mapping against the source documentation. Unknown facts remain unknown.").check();
}

test.describe.serial("isolated real local imports", () => {
  test.setTimeout(120000);
  test("real uploads pause for missing resources, resume, publish and persist with evidence", async ({ page }) => {
    const errors: string[] = []; page.on("pageerror", error => errors.push(error.message));
    await open(page);
    const label = `Browser fixture ${Date.now()}`;
    await page.getByLabel("Import name", { exact: true }).fill(label);
    await page.getByLabel("Import data files", { exact: true }).setInputFiles(file("wa-events.csv", crashes));
    await enterProfile(page);
    await page.getByRole("button", { name: "Upload & run", exact: true }).click();
    await expect(selectedJob(page).getByRole("heading", { name: "Information needed" })).toBeVisible();
    await expect(selectedJob(page).getByText(/Upload the missing resources: wa-units.csv/).first()).toBeVisible();
    await page.getByLabel("Import data files", { exact: true }).setInputFiles(file("wa-units.csv", units));
    await page.getByRole("button", { name: "Add files & resume", exact: true }).click();
    await expect(selectedJob(page).getByRole("heading", { name: "Published LOCAL TEST result" })).toBeVisible();
    await expect(selectedJob(page).getByText("browser_fixture", { exact: true })).toBeVisible();
    await expect(selectedJob(page).getByText("QA07_LOCATION", { exact: true })).toBeVisible();
    await expect(selectedJob(page).getByRole("table")).toContainText("2024");
    await page.getByRole("button", { name: "View evidence", exact: true }).click();
    await expect(selectedJob(page).getByRole("heading", { name: "Local execution evidence" })).toBeVisible();
    const downloadPromise = page.waitForEvent("download");
    await page.getByRole("button", { name: "Download JSON", exact: true }).click();
    const download = await downloadPromise; expect(download.suggestedFilename()).toMatch(/^local-test-.*-evidence\.json$/);
    await page.reload();
    await page.getByRole("button", { name: new RegExp(label) }).click();
    await expect(selectedJob(page).getByRole("heading", { name: "Published LOCAL TEST result" })).toBeVisible();
    const catalog = page.getByRole("region", { name: "Local publication catalog", exact: true });
    await catalog.locator("article").filter({ has: page.getByRole("heading", { name: "browser_fixture", exact: true }) }).getByRole("button", { name: /Read local result/ }).click();
    await expect(catalog.getByRole("heading", { name: "browser_fixture · LOCAL TEST result" })).toBeVisible();
    mkdirSync(resolve("output/playwright"), { recursive: true });
    await page.getByRole("heading", { name: "From source files to evidence." }).click();
    await page.screenshot({ path: resolve("output/playwright/imports-local-desktop.png"), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: resolve("output/playwright/imports-local-mobile.png"), fullPage: true });
    expect(errors).toEqual([]);
  });
  test("a failed candidate retains the previous local source publication", async ({ page, request, baseURL }) => {
    const origin = new URL(baseURL!).origin;
    const before = await request.get("/api/imports/catalog", { headers: { Origin: origin } });
    expect(before.ok()).toBe(true);
    const initial = await before.json();
    const previous = initial.sources.find((source: { source_id: string }) => source.source_id === "browser_fixture");
    expect(previous).toBeTruthy();
    await open(page);
    await page.getByLabel("Import name", { exact: true }).fill(`Browser duplicate-key failure ${Date.now()}`);
    const invalid = crashes + "B1,2024-07-01,Injury,0,1,1\n";
    await page.getByLabel("Import data files", { exact: true }).setInputFiles([file("wa-events.csv", invalid), file("wa-units.csv", units)]);
    await enterProfile(page);
    await page.getByRole("button", { name: "Upload & run", exact: true }).click();
    await expect(selectedJob(page).getByRole("button", { name: "Retry job", exact: true })).toBeVisible();
    await expect(selectedJob(page).locator('[data-status="failed"]')).toBeVisible();
    const after = await request.get("/api/imports/catalog", { headers: { Origin: origin } });
    const current = await after.json();
    expect(current.sources.find((source: { source_id: string }) => source.source_id === "browser_fixture").batch_id).toBe(previous.batch_id);
    await expect(selectedJob(page).getByRole("heading", { name: "Published LOCAL TEST result" })).toHaveCount(0);
  });
  test("an unsubmitted upload can be cancelled and explicitly retried", async ({ page, request, baseURL }) => {
    const origin = new URL(baseURL!).origin;
    const label = `Browser cancel fixture ${Date.now()}`;
    const created = await request.post("/api/imports/jobs", { headers: { Origin: origin }, data: { label, request_id: crypto.randomUUID() } });
    expect(created.ok()).toBe(true);
    const job = await created.json();
    const uploaded = await request.put(`/api/imports/jobs/${job.id}/files?filename=wa-events.csv`, { headers: { Origin: origin, "Content-Type": "application/octet-stream" }, data: Buffer.from(crashes) });
    expect(uploaded.ok()).toBe(true);
    await open(page);
    await page.getByRole("button", { name: new RegExp(label) }).click();
    await selectedJob(page).getByRole("button", { name: "Cancel job", exact: true }).click();
    await expect(selectedJob(page).getByText("cancelled", { exact: true }).first()).toBeVisible();
    await selectedJob(page).getByRole("button", { name: "Retry job", exact: true }).click();
    await expect(selectedJob(page).getByRole("heading", { name: "Information needed" })).toBeVisible();
    await expect(selectedJob(page).getByRole("heading", { name: "Published LOCAL TEST result" })).toHaveCount(0);
  });
});

test("schema-assistance UI keeps a mocked AI draft unconfirmed until explicit review", async ({ page }) => {
  const id = "af8c079c-10fd-40f3-ace2-c8a7e281fb12";
  const timestamp = new Date().toISOString();
  const schemas = [{ filename: "wa-events.csv", format: "csv", sheet: null, columns: ["EVENT_ID", "OCCURRED_ON", "OUTCOME"] }];
  const job = { id, label: "Schema assistance UI fixture", status: "needs_input", stage: "profiling", message: "A reviewed profile is required.", created_at: timestamp, updated_at: timestamp, attempt: 1, files: [{ id: "file", name: "wa-events.csv", size: 100, sha256: "a".repeat(64) }], events: [], questions: ["What does OUTCOME mean?"], error: { code: "needs_input", message: "Supply source definitions.", details: { schemas } } };
  let sentProfile: Record<string, unknown> | undefined;
  await page.route("**/api/imports/**", async route => {
    const path = new URL(route.request().url()).pathname;
    let data: unknown;
    if (path.endsWith("/health")) data = { status: "ok", mode: "local-test", worker: { alive: true }, capabilities: {} };
    else if (path.endsWith("/catalog")) data = { release_id: null, sources: [] };
    else if (path.endsWith("/jobs")) data = { jobs: [job] };
    else if (path.endsWith("/assist")) {
      expect(route.request().postDataJSON()).toEqual({ job_id: id, source_context: "Public field dictionary: OUTCOME retains native classifications." });
      data = { summary: "The severity meanings need the published dictionary.", questions: ["Confirm each native severity meaning."], draft_profile: { ...profile, confirmed: false }, model: "test-only", execution_allowed: false };
    } else if (path.endsWith("/submit")) { sentProfile = route.request().postDataJSON().profile; data = job; }
    else data = job;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(data) });
  });
  await open(page);
  await page.getByRole("button", { name: /Schema assistance UI fixture/ }).click();
  await page.getByText("Advanced schema assistance", {exact:true}).click();
  await page.getByLabel("Public source definitions (optional)", { exact: true }).fill("Public field dictionary: OUTCOME retains native classifications.");
  await page.getByRole("button", { name: "Ask AI about this schema", exact: true }).click();
  await expect(page.getByText("Draft guidance · not approved for execution", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Use draft in mapping editor", exact: true }).click();
  expect(JSON.parse(await page.getByRole("textbox", { name: "Mapping profile (JSON)", exact: true }).inputValue()).confirmed).toBe(false);
  const confirm = page.getByLabel("I reviewed this mapping against the source documentation. Unknown facts remain unknown.");
  await expect(confirm).not.toBeChecked();
  await page.getByRole("button", { name: "Run current bundle", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "Review the source mapping" })).toBeVisible();
  expect(sentProfile).toBeUndefined();
  await confirm.check();
  await page.getByRole("button", { name: "Run current bundle", exact: true }).click();
  await expect.poll(() => sentProfile?.confirmed).toBe(true);
  await page.getByRole("button", { name: /Switch to light theme/ }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  mkdirSync(resolve("output/playwright"), { recursive: true });
  await page.getByRole("heading", { name: "From source files to evidence." }).click();
  await page.screenshot({ path: resolve("output/playwright/imports-assistance-light-mobile.png"), fullPage: true });
});
