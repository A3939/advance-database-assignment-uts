import { test, expect, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import type { Filters, Source } from "../../src/services/contracts";

const errors = new WeakMap<Page, string[]>();
const filters = (
  source: Source = "NSW",
  from = "2020-01-01",
  to = "2024-12-31",
): Filters => ({
  source,
  dateRange: { from, to },
  datasetVersion: "official-v1",
  batchId: "bcc5da57-25f2-41ec-9925-bef421b02671",
});
// Golden values from the verified official reader receipt, not production calculations.
const nswYearly = [
  {
    period: "2020",
    crashes: 18764,
    fatalCrashes: 264,
    livesLost: 284,
    casualties: 16169,
  },
  {
    period: "2021",
    crashes: 17413,
    fatalCrashes: 260,
    livesLost: 275,
    casualties: 14448,
  },
  {
    period: "2022",
    crashes: 18255,
    fatalCrashes: 263,
    livesLost: 281,
    casualties: 14840,
  },
  {
    period: "2023",
    crashes: 18711,
    fatalCrashes: 303,
    livesLost: 340,
    casualties: 16379,
  },
  {
    period: "2024",
    crashes: 18939,
    fatalCrashes: 298,
    livesLost: 327,
    casualties: 16318,
  },
];
const nswSeverity = [1388, 15483, 26115, 29507, 19589];
const qldHalfYear = {
  crashes: 7030,
  previousCrashes: 6662,
  yoyPct: ((7030 - 6662) / 6662) * 100,
};
const formatted = (value: number) => value.toLocaleString("en-AU");
const article = (page: Page, heading: string) =>
  page
    .getByRole("article")
    .filter({ has: page.getByRole("heading", { name: heading, exact: true }) });
const dataTable = (page: Page) =>
  page.getByRole("table", {
    name: "Source-specific published aggregates. Select a column header to sort.",
    exact: true,
  });

async function openAnalytics(page: Page) {
  await page.goto("/analytics");
  await expect(
    page.getByRole("heading", { name: "Analytics", exact: true }),
  ).toBeVisible();
  await expect(page.getByTestId("analytics-total")).toHaveText("92,082");
}

async function selectPeriod(page: Page, from: string, to: string) {
  await page.getByRole("button", { name: /^Analysis period:/ }).click();
  await page.getByLabel("Start month", { exact: true }).fill(from);
  await page.getByLabel("End month", { exact: true }).fill(to);
  await page.getByRole("button", { name: "Apply period", exact: true }).click();
}

test.beforeEach(async ({ page }) => {
  const messages: string[] = [];
  errors.set(page, messages);
  page.on("pageerror", (error) => messages.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") messages.push(message.text());
  });
  await page.emulateMedia({ reducedMotion: "reduce" });
});

test.afterEach(async ({ page }) => {
  expect(errors.get(page), "No browser runtime or console errors").toEqual([]);
});

test("Analytics follows Overview and resolves All to an explicit NSW selection including AI context", async ({
  page,
}) => {
  // Only the HTTP transport is stubbed; tool arithmetic is covered separately.
  await page.route("**/api/agent", async (route) =>
    route.fulfill({
      contentType: "application/x-ndjson",
      body:
        [
          {
            type: "message",
            text: "NSW: 92,082 recorded crashes in the selected project snapshot.",
            simulated: false,
          },
          { type: "done", model: "test-transport" },
        ]
          .map((e) => JSON.stringify(e))
          .join("\n") + "\n",
    }),
  );
  await page.goto("/");
  await expect(page.getByRole("combobox", { name: "Data source" })).toHaveValue(
    "All",
  );
  const navigation = page.getByRole("navigation", { name: "Main navigation" });
  expect(
    (await navigation.getByRole("link").allTextContents()).slice(0, 2),
  ).toEqual(["Overview", "Analytics"]);
  await navigation
    .getByRole("link", { name: "Analytics", exact: true })
    .click();
  await expect(page).toHaveURL(/\/analytics$/);
  await expect(page.getByTestId("analytics-total")).toHaveText("92,082");
  await expect(
    page.getByRole("button", { name: "NSW", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    page.getByRole("button", { name: "VIC", exact: true }),
  ).toHaveAttribute("aria-pressed", "false");
  await page.getByRole("button", { name: "Ask AI", exact: true }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).not.toContainText("CURRENT CONTEXT");
  await expect(dialog).toContainText("ARSIA Assistant");
  await dialog
    .getByRole("button", { name: /Understand the data/ })
    .click();
  await expect(dialog.getByText(/NSW.*92,082 recorded crashes/)).toBeVisible();
  await expect(dialog).not.toContainText("national total");
});

test("source and half-year filters reconcile totals and compare matching months in the same source", async ({
  page,
}) => {
  await openAnalytics(page);
  await page.getByRole("button", { name: "VIC", exact: true }).click();
  await expect(page.getByTestId("analytics-total")).toHaveText("72,170");
  await page.getByRole("button", { name: "QLD", exact: true }).click();
  await expect(page.getByTestId("analytics-total")).toHaveText("66,624");

  await selectPeriod(page, "2024-01", "2024-06");
  await expect(page.getByTestId("analytics-total")).toHaveText(
    formatted(qldHalfYear.crashes),
  );
  const comparison = article(page, "Year-on-year change");
  const current = qldHalfYear;
  await expect(comparison).toContainText("2024 vs 2023");
  await expect(comparison).toContainText(
    `${current.yoyPct! > 0 ? "+" : ""}${current.yoyPct!.toFixed(1)}%`,
  );
  await expect(comparison).toContainText(formatted(current.previousCrashes!));
  await expect(comparison).toContainText("Jan–Jun · 6 matched months");
  await page
    .getByRole("button", { name: "Year-on-year definition", exact: true })
    .click();
  await expect(page.getByRole("dialog")).toContainText(
    `2023: ${formatted(current.previousCrashes!)}`,
  );
  await expect(page.getByRole("dialog")).toContainText(
    `2024: ${formatted(current.crashes!)}`,
  );
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "Ask AI", exact: true }).click();
  await page.route("**/api/agent", route => route.fulfill({contentType: "application/x-ndjson", body: JSON.stringify({type:"done",model:"transport-test"}) + "\n"}));
  const pendingContext = page.waitForRequest("**/api/agent");
  await page.getByRole("textbox", {name:"Message ARSIA assistant"}).fill("Summarise this selection");
  await page.getByRole("button", {name:"Send message"}).click();
  expect((await pendingContext).postDataJSON().context.filters).toMatchObject({source:"QLD", dateRange:{from:"2024-01-01",to:"2024-06-30"}, datasetVersion:"official-v1"});
});

test("heatmap supports keyboard inspection, click selection and analysis of one month", async ({
  page,
}) => {
  await openAnalytics(page);
  const heatmap = article(page, "Monthly distribution");
  const january = heatmap.getByRole("button", {
    name: /^Jan 2024: \d[\d,]* crashes$/,
  });
  const february = heatmap.getByRole("button", {
    name: /^Feb 2024: \d[\d,]* crashes$/,
  });
  await january.focus();
  await page.keyboard.press("ArrowRight");
  await expect(february).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(february).toHaveAttribute("aria-pressed", "true");
  await expect(heatmap).toContainText("Feb 2024");
  await expect(
    heatmap.getByRole("button", { name: "Clear inspected month" }),
  ).toBeVisible();
  const march = { crashes: 1601 };
  const marchCell = heatmap.getByRole("button", {
    name: `Mar 2024: ${formatted(march.crashes!)} crashes`,
    exact: true,
  });
  await marchCell.click();
  await expect(marchCell).toHaveAttribute("aria-pressed", "true");
  await expect(february).toHaveAttribute("aria-pressed", "false");
  await heatmap
    .getByRole("button", { name: "Analyze this month", exact: true })
    .click();
  await expect(page.getByTestId("analytics-total")).toHaveText(
    formatted(march.crashes!),
  );
  await expect(
    page.getByRole("button", {
      name: "Analysis period: Mar 2024 – Mar 2024",
      exact: true,
    }),
  ).toBeVisible();
  await expect(article(page, "Year-on-year change")).toContainText(
    "Mar–Mar · 1 matched months",
  );
  await expect(
    article(page, "Monthly distribution").getByRole("button", {
      name: "Feb 2024: no observation",
      exact: true,
    }),
  ).toBeVisible();
  await expect(dataTable(page).getByRole("row")).toHaveCount(2);
});

test("trend metrics, severity shares and sortable paged tables expose the same aggregate values", async ({
  page,
}) => {
  await openAnalytics(page);
  const trend = article(page, "Trend over time");
  await trend.getByRole("button", { name: "Yearly", exact: true }).click();
  for (const [key, label] of [
    ["crashes", "Crashes"],
    ["fatalCrashes", "Fatal crashes"],
    ["livesLost", "Lives lost"],
    ["casualties", "Casualties"],
  ] as const) {
    await trend.getByRole("button", { name: label, exact: true }).click();
    await expect(
      trend.getByRole("button", { name: label, exact: true }),
    ).toHaveAttribute("aria-pressed", "true");
    await expect(
      trend.getByRole("img", { name: new RegExp(`^${label} by year\\.`) }),
    ).toBeVisible();
    await trend
      .getByRole("button", { name: "View values", exact: true })
      .click();
    const dialog = page.getByRole("dialog");
    await expect(
      dialog.getByRole("heading", { name: "Trend values", exact: true }),
    ).toBeVisible();
    for (const row of nswYearly) {
      await expect(dialog).toContainText(row.period);
      await expect(dialog).toContainText(formatted(row[key]));
    }
    await page.keyboard.press("Escape");
  }
  await trend.getByRole("button", { name: "Monthly", exact: true }).click();
  const keyboardChart = trend.getByRole("img", {
    name: /^Casualties by month\./,
  });
  await keyboardChart.focus();
  await page.keyboard.press("End");
  await page.keyboard.press("Enter");
  await expect(
    article(page, "Monthly distribution").getByRole("button", {
      name: /^Dec 2024:/,
    }),
  ).toHaveAttribute("aria-pressed", "true");

  const severity = article(page, "Severity profile");
  await expect(
    severity.getByRole("img", { name: /^Severity crash counts\./ }),
  ).toBeVisible();
  await severity.getByRole("button", { name: "Share", exact: true }).click();
  await expect(
    severity.getByRole("button", { name: "Share", exact: true }),
  ).toHaveAttribute("aria-pressed", "true");
  await expect(
    severity.getByRole("img", {
      name: /^Severity shares within each source\./,
    }),
  ).toBeVisible();
  await severity
    .getByRole("button", { name: "Definitions", exact: true })
    .click();
  for (const count of nswSeverity)
    await expect(page.getByRole("dialog")).toContainText(
      `${formatted(count)} crashes · ${((count / 92082) * 100).toFixed(2)}%`,
    );
  await page.keyboard.press("Escape");
  await severity.getByRole("button", { name: "Count", exact: true }).click();
  await expect(
    severity.getByRole("img", { name: /^Severity crash counts\./ }),
  ).toBeVisible();

  const table = dataTable(page);
  await table.getByRole("button", { name: "Crashes", exact: true }).click();
  await expect(
    table.getByRole("columnheader", { name: "Crashes", exact: true }),
  ).toHaveAttribute("aria-sort", "descending");
  let values = await table
    .locator("tbody tr td:first-of-type")
    .allTextContents();
  expect(values.map((value) => Number(value.replaceAll(",", "")))).toEqual(
    nswYearly.map((row) => row.crashes).sort((a, b) => b - a),
  );
  await table.getByRole("button", { name: "Crashes", exact: true }).click();
  await expect(
    table.getByRole("columnheader", { name: "Crashes", exact: true }),
  ).toHaveAttribute("aria-sort", "ascending");
  values = await table.locator("tbody tr td:first-of-type").allTextContents();
  expect(values.map((value) => Number(value.replaceAll(",", "")))).toEqual(
    nswYearly.map((row) => row.crashes).sort((a, b) => a - b),
  );
  const dataCard = article(page, "Analysis data");
  await dataCard.getByRole("button", { name: "Months", exact: true }).click();
  await expect(table.getByRole("row")).toHaveCount(9);
  await expect(dataCard).toContainText("60 months");
  await expect(dataCard).toContainText("1 / 8");
  const firstPage = await table.locator("tbody tr th").allTextContents();
  await page
    .getByRole("button", { name: "Next data page", exact: true })
    .click();
  await expect(dataCard).toContainText("2 / 8");
  expect(await table.locator("tbody tr th").allTextContents()).not.toEqual(
    firstPage,
  );
  await page
    .getByRole("button", { name: "Previous data page", exact: true })
    .click();
  expect(await table.locator("tbody tr th").allTextContents()).toEqual(
    firstPage,
  );
});

test("JSON export preserves official identity, matched baseline and unsupported partial severity", async ({
  page,
}) => {
  await openAnalytics(page);
  await page.getByRole("button", { name: "QLD", exact: true }).click();
  const selectedFilters = filters("QLD", "2024-01-01", "2024-06-30");
  await selectPeriod(page, "2024-01", "2024-06");
  await expect(page.getByTestId("analytics-total")).toHaveText(
    formatted(qldHalfYear.crashes),
  );
  const trend = article(page, "Trend over time");
  await trend.getByRole("button", { name: "Casualties", exact: true }).click();
  await trend.getByRole("button", { name: "Yearly", exact: true }).click();
  await expect(article(page, "Severity profile")).toContainText(
    /2020.*2024|unsupported|unavailable/i,
  );
  await expect(article(page, "Severity profile").getByRole("img")).toHaveCount(
    0,
  );
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  const download = await downloadPromise;
  expect(download.suggestedFilename()).toBe(
    "ARSIA-OFFICIAL-Analytics-QLD-2024-01-01-2024-06-30.json",
  );
  const payload = JSON.parse(await readFile((await download.path())!, "utf8"));
  expect(payload.demo).toBe(false);
  expect(payload.filters).toEqual(selectedFilters);
  expect(payload.view).toEqual({
    metric: "casualties",
    granularity: "yearly",
    severityMode: "count",
  });
  expect(payload.analysis.meta).toMatchObject({
    demo: false,
    source: "QLD",
    datasetVersion: "official-v1",
    batchId: "bcc5da57-25f2-41ec-9925-bef421b02671",
  });
  expect(payload.analysis.data.summary.total).toBe(7030);
  expect(payload.analysis.data.yearly[0].comparisonMonths).toEqual([
    1, 2, 3, 4, 5, 6,
  ]);
  expect(payload.analysis.data.yearly[0].previousCrashes).toBe(6662);
  expect(payload.analysis.data.monthly).toHaveLength(6);
  expect(payload.analysis.data.severity).toEqual([]);
  expect(payload.analysis.data.notes.join(" ")).not.toContain(
    "synthetically allocated",
  );
  expect(payload.note).not.toContain("Synthetic monthly allocation");
  expect(payload.note).toContain("no underlying crash records");
});

test("missing months and empty selections remain explicit across themes and mobile layout", async ({
  page,
}) => {
  await openAnalytics(page);
  await selectPeriod(page, "2019-01", "2020-03");
  await expect(
    page.getByText(
      "Partial coverage. Unobserved months stay empty; comparisons require matching months.",
      { exact: true },
    ),
  ).toBeVisible();
  const heatmap = article(page, "Monthly distribution");
  const missing = heatmap.getByRole("button", {
    name: "Jan 2019: no observation",
    exact: true,
  });
  await expect(missing).toHaveText("—");
  await missing.click();
  await expect(heatmap).toContainText(
    "No observation for this month in the current selection.",
  );
  await expect(
    heatmap.getByRole("button", { name: "Analyze this month", exact: true }),
  ).toHaveCount(0);
  await expect(article(page, "Year-on-year change")).toContainText(
    "A comparable baseline is unavailable.",
  );
  await selectPeriod(page, "2025-01", "2025-12");
  await expect(
    page.getByRole("heading", {
      name: "No data for this selection",
      exact: true,
    }),
  ).toBeVisible();
  await expect(
    page.getByRole("button", { name: "Export", exact: true }),
  ).toBeDisabled();
  await expect(
    page.getByRole("heading", { name: "Trend over time", exact: true }),
  ).toHaveCount(0);
  await page.getByRole("button", { name: "Reset dates", exact: true }).click();
  await expect(page.getByTestId("analytics-total")).toHaveText("92,082");

  const root = page.locator("html");
  await expect(root).toHaveAttribute("data-theme", "dark");
  const darkBackground = await page
    .locator("body")
    .evaluate((element) => getComputedStyle(element).backgroundColor);
  await page
    .getByRole("button", { name: "Switch to light theme", exact: true })
    .click();
  await expect(root).toHaveAttribute("data-theme", "light");
  await expect
    .poll(() =>
      page
        .locator("body")
        .evaluate((element) => getComputedStyle(element).backgroundColor),
    )
    .not.toBe(darkBackground);
  await expect(
    page.getByRole("img", { name: /^Crashes by month\./ }),
  ).toBeVisible();
  await page.reload();
  await expect(page.getByTestId("analytics-total")).toHaveText("92,082");
  await expect(root).toHaveAttribute("data-theme", "light");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
  await expect(
    page.getByRole("button", { name: "NSW", exact: true }),
  ).toBeVisible();
  await article(page, "Analysis data")
    .getByRole("button", { name: "Months", exact: true })
    .click();
  await expect(dataTable(page).getByRole("row")).toHaveCount(9);
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
  await page.getByRole("button", { name: "Ask AI", exact: true }).click();
  await expect(page.getByRole("dialog")).toContainText("ARSIA Assistant");
  await expect(page.locator(".agent-context")).toHaveCount(0);
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
  await page.keyboard.press("Escape");
  await page
    .getByRole("button", { name: "Switch to dark theme", exact: true })
    .click();
  await expect(root).toHaveAttribute("data-theme", "dark");
  await expect
    .poll(() =>
      page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
    )
    .toBe(true);
});
