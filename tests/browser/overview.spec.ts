import { test, expect } from "@playwright/test";
import { readFile } from "node:fs/promises";
test("official snapshot interactions, boundary map, filters, export and agent transport", async ({
  page,
}) => {
  // Transport fixture keeps routine UI regression tests free of paid API calls.
  await page.route("**/api/agent", async (route) =>
    route.fulfill({
      contentType: "application/x-ndjson",
      body:
        [
          {
            type: "message",
            text: "NSW recorded 18,711 crashes in 2023 and 18,939 in 2024: a 1.22% change.",
            simulated: false,
          },
          {
            type: "evidence",
            evidence: {
              id: "E1",
              title: "E1 · Project snapshot evidence",
              description: "UI transport test fixture",
              result: {
                source: "NSW",
                baseline: 18711,
                current: 18939,
                difference: 228,
                percentChange: 1.22,
              },
            },
          },
          { type: "done", model: "test-transport" },
        ]
          .map((e) => JSON.stringify(e))
          .join("\n") + "\n",
    }),
  );
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(`${m.text()} ${m.location().url}`);
  });
  const badRequests: string[] = [];
  page.on("response", (r) => {
    if (r.status() >= 400) badRequests.push(`${r.status()} ${r.url()}`);
  });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");
  await page.getByRole("combobox", { name: "Data source" }).selectOption("NSW");
  await expect(page.locator(".metric-value").first()).toHaveText("92,082");
  await expect(page.locator(".maplibregl-canvas")).toBeVisible();
  await expect(page.locator(".map-marker")).toHaveCount(0);
  await expect
    .poll(() =>
      page.evaluate(() =>
        performance
          .getEntriesByType("resource")
          .some((r) => r.name.includes("maplibre-gl-worker.mjs")),
      ),
    )
    .toBeTruthy();
  const canvas = page.locator(".maplibregl-canvas");
  const mapBounds = await canvas.boundingBox();
  if (!mapBounds) throw new Error("Map canvas is not visible");
  // Select the interior of the fitted NSW boundary as the panel resizes.
  const regionPosition = {
    x: mapBounds.width * 0.48,
    y: mapBounds.height * 0.45,
  };
  // GeoJSON worker loading can finish after the canvas appears. Re-enter the
  // polygon once rendered, instead of assuming a mounted canvas is interactive.
  await expect(async () => {
    await canvas.hover({ position: { x: regionPosition.x + 3, y: regionPosition.y } });
    await canvas.hover({ position: regionPosition });
    await expect(page.locator(".map-readout")).toBeVisible({ timeout: 500 });
  }).toPass({ timeout: 6000 });
  await expect(page.locator(".spatial-panel")).toContainText(
    /Recorded crashes · LGA/i,
  );
  const severityChart = page.locator(".severity-panel .chart");
  const severityBounds = await severityChart.boundingBox();
  if (!severityBounds) throw new Error("Severity chart is not visible");
  // The third of five categories is centred in the plot, excluding axis margins.
  await severityChart.hover({
    position: {
      x: 132 + (severityBounds.width - 132 - 62) * 0.15,
      y: 12 + (severityBounds.height - 12 - 30) * 0.5,
    },
  });
  await expect(page.locator(".severity-panel")).toContainText("26,115");
  await page.screenshot({ path: "artifacts/severity-hover.png" });
  await page.getByRole("button", { name: "Zoom in", exact: true }).click();
  await page.getByRole("button", { name: "Reset map view" }).click();
  await page.getByRole("button", { name: "Monthly", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Monthly", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await page.getByRole("button", { name: "Trend chart evidence" }).click();
  await expect(page.getByRole("dialog")).toContainText("2020-01");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Yearly", exact: true }).click();
  await page.getByRole("button", { name: "Yearly", exact: true }).click();
  await expect(
    page.getByRole("button", { name: "Export", exact: true }),
  ).toBeEnabled();
  await page.getByRole("combobox", { name: "Data source" }).selectOption("VIC");
  await expect(page.locator(".metric-value").first()).toHaveText("72,170");
  await expect(page.locator(".maplibregl-canvas")).toBeVisible();
  await expect(page.locator(".map-marker")).toHaveCount(0);
  await page.getByRole("combobox", { name: "Data source" }).selectOption("QLD");
  await expect(page.locator(".metric-value").first()).toHaveText("66,624");
  await page.getByRole("combobox", { name: "Data source" }).selectOption("NSW");
  await page.getByRole("button", { name: "2020 – 2024", exact: true }).click();
  await page.getByRole("button", { name: "2024", exact: true }).click();
  await page.getByRole("button", { name: "Apply period" }).click();
  await expect(page.locator(".metric-value").first()).toHaveText("18,939");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const file = await download;
  expect(file.suggestedFilename()).toContain("SNAPSHOT-NSW-2024");
  const payload = JSON.parse(await readFile((await file.path())!, "utf8"));
  expect(payload.demo).toBe(false);
  expect(payload.overview.meta.batchId).toBe(
    "bcc5da57-25f2-41ec-9925-bef421b02671",
  );
  expect(payload.overview.meta.datasetVersion).toBe("official-v1");
  expect(payload.overview.data.crashes.value).toBe(18939);
  expect(payload.timeSeries.data).toHaveLength(1);
  expect(payload.severity.meta.availability).toBe("unsupported");
  expect(payload.severity.data).toEqual([]);
  await page.getByRole("button", { name: "2024 – 2024", exact: true }).click();
  await page.getByRole("button", { name: "2025 · no data" }).click();
  await page.getByRole("button", { name: "Apply period" }).click();
  await expect(page.locator(".metric-value").first()).toHaveText("—");
  await expect(page.locator(".spatial-panel")).toContainText(
    /unavailable|no data|boundar/i,
  );
  await expect(page.locator(".map-marker")).toHaveCount(0);
  await page.getByRole("button", { name: "Reset dates" }).click();
  await page.getByRole("button", { name: "Ask AI", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText(
    "ARSIA Assistant",
  );
  await page.getByRole("textbox", { name: "Message ARSIA assistant" }).fill("Compare 2024 with 2023");
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.locator(".chat-message.assistant")).toContainText("1.22%");
  await expect(page.locator(".chat-message.assistant")).toContainText("NSW");
  await expect(page.locator(".chat-message.assistant")).toContainText("18,711");
  await expect(page.locator(".chat-message.assistant")).toContainText("18,939");
  await page.locator(".agent-evidence summary").click();
  await page
    .getByRole("button", {
      name: /snapshot|project evidence|verified.*evidence/i,
    })
    .click();
  await expect(
    page.getByRole("heading", {
      name: /snapshot|project evidence|verified.*evidence/i,
    }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toContainText(
    "ARSIA Assistant",
  );
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(errors).toEqual([]);
  expect(badRequests).toEqual([]);
  await page.screenshot({
    path: "artifacts/overview-1440.png",
    fullPage: true,
  });
});
test("navigation, metadata-only imports, settings and unavailable reports", async ({
  page,
}) => {
  await page.goto("/data");
  await expect(page.locator(".dataset-card")).toHaveCount(3);
  await page.getByRole("link", { name: "Imports", exact: true }).click();
  await page.getByLabel("Import files").setInputFiles({
    name: "uploaded-crashes.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("id,date\n1,2024-01-01"),
  });
  await expect(page.locator(".file-list")).toContainText(
    "uploaded-crashes.csv",
  );
  await page.getByRole("button", { name: "Preview import steps" }).click();
  await expect(page.locator(".job-state")).toContainText("needs input");
  await expect(page.locator(".job-state")).toContainText("not connected");
  await page
    .getByRole("button", { name: "Remove uploaded-crashes.csv" })
    .click();
  await expect(
    page.getByRole("button", { name: "Preview import steps" }),
  ).toBeDisabled();
  await page.getByRole("link", { name: "Reports", exact: true }).click();
  await expect(
    page.getByText("Saved report authoring is not connected yet.", {
      exact: false,
    }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("Not connected");
  await page.keyboard.press("Escape");
  await page.getByRole("link", { name: "Analytics", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Analytics", exact: true }),
  ).toBeVisible();
});

test("a failed source request clears old counts, disables export and recovers without demo fallback", async ({
  page,
}) => {
  await page.goto("/");
  await page.getByRole("combobox", { name: "Data source" }).selectOption("NSW");
  await expect(page.locator(".metric-value").first()).toHaveText("92,082");
  await page.route("**/api/data/overview?**", async (route) => {
    if (new URL(route.request().url()).searchParams.get("source") === "VIC") {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({ error: "Test snapshot unavailable" }),
      });
    } else {
      await route.continue();
    }
  });
  await page.getByRole("combobox", { name: "Data source" }).selectOption("VIC");
  await expect(page.locator(".error-banner")).toContainText(
    "snapshot could not be loaded",
  );
  await expect(page.locator(".metric-value")).toHaveText(["—", "—", "—", "—"]);
  await expect(page.locator(".dashboard-body")).not.toContainText("92,082");
  await expect(page.locator(".dashboard-body")).not.toContainText("10,180");
  await expect(
    page.getByRole("button", { name: "Export", exact: true }),
  ).toBeDisabled();
  await page.unroute("**/api/data/overview?**");
  await page.getByRole("combobox", { name: "Data source" }).selectOption("QLD");
  await expect(page.locator(".metric-value").first()).toHaveText("66,624");
  await expect(page.locator(".error-banner")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Export", exact: true }),
  ).toBeEnabled();
});

for (const width of [1280, 768, 390])
  test(`responsive ${width}px, keyboard and reduced motion`, async ({
    page,
  }) => {
    await page.setViewportSize({ width, height: 1000 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await expect(page.locator(".metric-by-source").first()).toContainText(
      "92,082",
    );
    await expect(
      page.getByRole("button", { name: "Explore NSW" }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.keyboard.press("Tab");
    await expect(
      page.getByRole("link", { name: "Skip to content" }),
    ).toBeFocused();
    await page.keyboard.press("Tab");
    await expect(
      page.getByRole("button", { name: /Crash records/ }),
    ).toHaveCount(0);
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({
      path: `artifacts/overview-${width}.png`,
      fullPage: true,
    });
    await expect(
      page.getByRole("button", { name: "Switch to light theme" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Switch to light theme" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.getByRole("button", { name: "Ask AI", exact: true }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page.screenshot({ path: `artifacts/agent-${width}.png` });
    await page.keyboard.press("Escape");
  });

test("local-only resources, chart tooltip and preserved map canvas", async ({
  page,
}) => {
  const remote: string[] = [];
  await page.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.hostname !== "127.0.0.1" && url.hostname !== "localhost") {
      remote.push(url.href);
      return route.abort();
    }
    return route.continue();
  });
  await page.goto("/");
  await page.getByRole("combobox", { name: "Data source" }).selectOption("NSW");
  await expect(page.locator(".maplibregl-canvas")).toBeVisible();
  await expect(page.locator(".map-marker")).toHaveCount(0);
  await page
    .locator(".trend-panel .chart")
    .hover({ position: { x: 120, y: 90 } });
  await expect(page.locator(".trend-panel")).toContainText(/crashes/i);
  await expect(page.locator(".trend-panel")).not.toContainText("Demo crashes");
  await page
    .locator(".maplibregl-canvas")
    .evaluate((el) => el.setAttribute("data-instance-check", "original"));
  await page.getByRole("combobox", { name: "Data source" }).selectOption("VIC");
  await expect(page.locator(".maplibregl-canvas")).toBeVisible();
  await expect(page.locator(".map-marker")).toHaveCount(0);
  await expect(page.locator(".maplibregl-canvas")).toHaveAttribute(
    "data-instance-check",
    "original",
  );
  expect(remote).toEqual([]);
});
test("WebGL unavailable shows a usable local boundary fallback", async ({
  page,
}) => {
  await page.addInitScript(
    `const nativeGetContext=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(type,...args){return type.includes('webgl')?null:nativeGetContext.call(this,type,...args)};`,
  );
  await page.goto("/");
  await expect(page.locator(".fallback-note")).toContainText(
    "WebGL unavailable",
  );
  await expect(page.locator(".map-fallback path")).toHaveCount(9);
  await expect(
    page.getByRole("button", { name: "Zoom in", exact: true }),
  ).toBeDisabled();
  await page
    .getByRole("button", { name: "Select New South Wales", exact: true })
    .focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("combobox", { name: "Data source" })).toHaveValue(
    "NSW",
  );
  await expect(page.locator(".map-fallback path")).toHaveCount(129);
});

test("All country coverage, unavailable state feedback and animated drilldown", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(page.getByRole("combobox", { name: "Data source" })).toHaveValue(
    "All",
  );
  await expect(page.getByRole("button", { name: "Explore NSW" })).toBeVisible();
  await expect(page.locator(".metric-by-source").first()).toContainText(
    "92,082",
  );
  await expect(page.locator(".metric-by-source").first()).toContainText(
    "72,170",
  );
  await expect(page.locator(".metric-by-source").first()).toContainText(
    "66,624",
  );
  await expect(page.locator('[aria-label^="Explore "]')).toHaveCount(3);
  await expect(
    page.getByText("Road safety overview", { exact: true }),
  ).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "v1.0", exact: true }),
  ).toHaveCount(0);
  await expect(
    page.locator(
      ".insight-bar,.records-panel,.site-footer,.chart-subtitle,.spatial-panel .panel-footer",
    ),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "WA: no data for this period" })
    .click();
  await expect(page.getByRole("combobox", { name: "Data source" })).toHaveValue(
    "All",
  );
  await expect(page.locator(".map-readout")).toContainText("No data");
  await page
    .locator(".maplibregl-canvas")
    .evaluate((el) => el.setAttribute("data-instance-check", "country"));
  const start = await page.locator(".maplibregl-canvas").screenshot();
  await page.getByRole("button", { name: "Explore NSW" }).click();
  await expect(page.getByRole("combobox", { name: "Data source" })).toHaveValue(
    "NSW",
  );
  await expect(page.locator(".maplibregl-canvas")).toBeVisible();
  await expect(page.locator(".map-marker")).toHaveCount(0);
  await expect(page.locator(".maplibregl-canvas")).toHaveAttribute(
    "data-instance-check",
    "country",
  );
  await expect(page.locator(".metric-value").first()).toHaveText("92,082");
  expect(
    Buffer.compare(
      start,
      await page.locator(".maplibregl-canvas").screenshot(),
    ),
  ).not.toBe(0);
  await page.getByRole("combobox", { name: "Data source" }).selectOption("All");
  await expect(page.getByRole("button", { name: "Explore QLD" })).toBeVisible();
  await page.getByRole("button", { name: "Explore QLD" }).click();
  await expect(page.locator(".metric-value").first()).toHaveText("66,624");
  expect(errors).toEqual([]);
});

test("theme defaults to dark, persists after reload and preserves the map canvas", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.goto("/");

  const root = page.locator("html");
  const canvas = page.locator(".maplibregl-canvas");
  await expect(root).toHaveAttribute("data-theme", "dark");
  await expect(root).toHaveClass(/\bdark\b/);
  await expect(root).not.toHaveClass(/\blight\b/);
  await expect(
    page.getByRole("button", { name: "Switch to light theme", exact: true }),
  ).toBeVisible();
  await page.getByRole("combobox", { name: "Data source" }).selectOption("QLD");
  await expect(page.locator(".maplibregl-canvas")).toBeVisible();
  await expect(page.locator(".map-marker")).toHaveCount(0);
  await canvas.evaluate((element) =>
    element.setAttribute("data-theme-instance", "before-light"),
  );
  const darkBackground = await page
    .locator("body")
    .evaluate((element) => getComputedStyle(element).backgroundColor);

  await page.getByRole("button", { name: "Switch to light theme" }).click();
  await expect(root).toHaveAttribute("data-theme", "light");
  await expect(root).toHaveClass(/\blight\b/);
  await expect(root).not.toHaveClass(/\bdark\b/);
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("arsia-theme")))
    .toBe("light");
  await expect
    .poll(() =>
      page
        .locator("body")
        .evaluate((element) => getComputedStyle(element).backgroundColor),
    )
    .not.toBe(darkBackground);
  await expect(canvas).toHaveAttribute("data-theme-instance", "before-light");
  await expect(page.getByRole("combobox", { name: "Data source" })).toHaveValue(
    "QLD",
  );
  await expect(page.locator(".metric-value").first()).toHaveText("66,624");
  await page.getByRole("button", { name: "Settings", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("Light theme");
  await page.keyboard.press("Escape");

  await page.reload();
  await expect(root).toHaveAttribute("data-theme", "light");
  await expect(root).toHaveClass(/\blight\b/);
  await expect(
    page.getByRole("button", { name: "Switch to dark theme", exact: true }),
  ).toBeVisible();
  await expect(canvas).toBeVisible();
  await canvas.evaluate((element) =>
    element.setAttribute("data-theme-instance", "after-reload"),
  );
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(root).toHaveAttribute("data-theme", "dark");
  await expect(root).toHaveClass(/\bdark\b/);
  await expect(root).not.toHaveClass(/\blight\b/);
  await expect
    .poll(() => page.evaluate(() => localStorage.getItem("arsia-theme")))
    .toBe("dark");
  await expect(canvas).toHaveAttribute("data-theme-instance", "after-reload");
  await expect
    .poll(() =>
      page
        .locator("body")
        .evaluate((element) => getComputedStyle(element).backgroundColor),
    )
    .toBe(darkBackground);
  expect(errors).toEqual([]);
});

test("theme remains usable when local storage is unavailable", async ({
  page,
}) => {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.addInitScript(() => {
    Object.defineProperty(window, "localStorage", {
      configurable: true,
      get() {
        throw new DOMException("Storage is unavailable", "SecurityError");
      },
    });
  });
  await page.goto("/");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "Switch to light theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.getByRole("button", { name: "Switch to dark theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  expect(errors).toEqual([]);
});

test("official Overview, Analytics and Data snapshots remain readable in both themes and on mobile", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const [path, name] of [
      ["/", "overview"],
      ["/analytics", "analytics"],
      ["/data", "data"],
    ]) {
      await page.goto(path);
      if (name === "overview")
        await expect(page.locator(".metric-by-source").first()).toContainText(
          "92,082",
        );
      if (name === "analytics")
        await expect(page.getByTestId("analytics-total")).toHaveText("92,082");
      if (name === "data")
        await expect(page.locator(".dataset-card")).toHaveCount(3);
      await page.evaluate(() => document.fonts.ready.then(() => undefined));
      for (const theme of ["dark", "light"]) {
        if ((await page.locator("html").getAttribute("data-theme")) !== theme) {
          await page
            .getByRole("button", {
              name: `Switch to ${theme} theme`,
              exact: true,
            })
            .click();
        }
        await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
        await expect
          .poll(() =>
            page
              .locator("body")
              .evaluate((element) => getComputedStyle(element).color),
          )
          .toBe(theme === "light" ? "rgb(28, 41, 33)" : "rgb(243, 245, 244)");
        await page.evaluate(
          () =>
            new Promise<void>((resolve) =>
              requestAnimationFrame(() =>
                requestAnimationFrame(() => resolve()),
              ),
            ),
        );
        expect(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
        ).toBe(true);
        if (name === "data") {
          await expect
            .poll(() =>
              page
                .locator(".dataset-card .button-link")
                .first()
                .evaluate((element) => getComputedStyle(element).color),
            )
            .toBe(theme === "light" ? "rgb(28, 41, 33)" : "rgb(243, 245, 244)");
          const contrast = await page
            .locator(".dataset-card")
            .first()
            .evaluate((card) => {
              const luminance = (color: string) => {
                const channels = (color.match(/[\d.]+/g) || [])
                  .slice(0, 3)
                  .map((value) => {
                    const channel = Number(value) / 255;
                    return channel <= 0.04045
                      ? channel / 12.92
                      : ((channel + 0.055) / 1.055) ** 2.4;
                  });
                return (
                  channels[0] * 0.2126 +
                  channels[1] * 0.7152 +
                  channels[2] * 0.0722
                );
              };
              const background = luminance(
                getComputedStyle(card).backgroundColor,
              );
              return ["h2", "dd", ".button-link"].map((selector) => {
                const node = card.querySelector(selector)!;
                const text = luminance(getComputedStyle(node).color);
                return {
                  selector,
                  ratio:
                    (Math.max(text, background) + 0.05) /
                    (Math.min(text, background) + 0.05),
                };
              });
            });
          for (const item of contrast)
            expect(
              item.ratio,
              `${theme} Data ${item.selector} contrast`,
            ).toBeGreaterThanOrEqual(4.5);
        }
        await page.screenshot({
          path: `artifacts/official-${name}-${theme}-${width}.png`,
          fullPage: true,
          animations: "disabled",
        });
      }
    }
  }
});

for (const viewport of [
  { width: 1280, height: 720 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
  { width: 2560, height: 1440 },
]) {
  test(`desktop ${viewport.width}×${viewport.height}: aligned panels fill the viewport without overflow`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.goto("/");
    await page.evaluate(() => document.fonts.ready.then(() => undefined));

    for (const source of ["All", "QLD"]) {
      await test.step(`${source} layout`, async () => {
        await page
          .getByRole("combobox", { name: "Data source" })
          .selectOption(source);
        await expect(page.locator(".dashboard-body")).toHaveAttribute(
          "aria-busy",
          "false",
        );
        await expect(page.locator(".maplibregl-canvas")).toBeVisible();
        await expect(page.locator(".trend-panel .chart canvas")).toBeVisible();
        await expect(
          page.locator(".severity-panel .chart canvas"),
        ).toBeVisible();
        if (source === "All") {
          await expect(page.locator('[aria-label^="Explore "]')).toHaveCount(3);
        } else {
          await expect(page.locator(".metric-value").first()).toHaveText(
            "66,624",
          );
          await expect(page.locator(".maplibregl-canvas")).toBeVisible();
          await expect(page.locator(".map-marker")).toHaveCount(0);
        }

        const geometry = await page.evaluate(() => {
          const bounds = (selector: string) => {
            const element = document.querySelector(selector);
            if (!element)
              throw new Error(`Missing dashboard element: ${selector}`);
            const { top, right, bottom, left, width, height } =
              element.getBoundingClientRect();
            return { top, right, bottom, left, width, height };
          };
          return {
            toolbar: bounds(".overview-toolbar"),
            topbar: bounds(".topbar"),
            metrics: bounds(".metric-grid"),
            map: bounds(".spatial-panel"),
            trend: bounds(".trend-panel"),
            severity: bounds(".severity-panel"),
            mapCanvas: bounds(".maplibregl-canvas"),
            chartStack: bounds(".chart-stack"),
            scrollWidth: Math.max(
              document.documentElement.scrollWidth,
              document.body.scrollWidth,
            ),
            scrollHeight: Math.max(
              document.documentElement.scrollHeight,
              document.body.scrollHeight,
            ),
            viewportWidth: innerWidth,
            viewportHeight: innerHeight,
            scrollTop: scrollY,
          };
        });
        expect(
          Math.abs(geometry.map.top - geometry.trend.top),
        ).toBeLessThanOrEqual(2);
        expect(
          Math.abs(geometry.map.bottom - geometry.severity.bottom),
        ).toBeLessThanOrEqual(2);
        expect(
          Math.abs(geometry.map.height - geometry.chartStack.height),
        ).toBeLessThanOrEqual(2);
        expect(geometry.trend.bottom).toBeLessThan(geometry.severity.top);
        expect(geometry.map.right).toBeLessThan(geometry.chartStack.left);
        expect(geometry.mapCanvas.height).toBeGreaterThan(180);
        expect(
          Math.abs(
            geometry.toolbar.top -
              geometry.topbar.bottom -
              (geometry.metrics.top - geometry.toolbar.bottom),
          ),
        ).toBeLessThanOrEqual(1);
        const contentBottom = Math.max(
          geometry.map.bottom,
          geometry.severity.bottom,
        );
        const bottomGap = geometry.viewportHeight - contentBottom;
        expect(bottomGap).toBeGreaterThanOrEqual(15);
        expect(bottomGap).toBeLessThanOrEqual(40);
        expect(geometry.scrollTop).toBe(0);
        expect(geometry.scrollHeight).toBeLessThanOrEqual(
          geometry.viewportHeight + 1,
        );
        expect(geometry.scrollWidth).toBeLessThanOrEqual(
          geometry.viewportWidth,
        );
        expect(geometry.map.left).toBeGreaterThanOrEqual(0);
        expect(geometry.chartStack.right).toBeLessThanOrEqual(
          geometry.viewportWidth,
        );
      });
    }
  });
}
