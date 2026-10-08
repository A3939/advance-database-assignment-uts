import { test, expect, type APIRequestContext } from "@playwright/test";
import { DEFAULT_FILTERS } from "../../src/services/config";
import type { Study } from "../../src/services/studio-contracts";
const filters = {
  ...DEFAULT_FILTERS,
  source: "NSW",
  dateRange: { from: "2024-01-01", to: "2024-12-31" },
};
async function create(request: APIRequestContext, title: string) {
  const r = await request.post("/api/studio", {
    data: {
      kind: "analytics",
      title: `Validation · ${title}`,
      question: "Crashes over time",
      granularity: "monthly",
      context: { filters, metric: "crashes", notes: "", references: "" },
    },
  });
  expect(r.ok()).toBeTruthy();
  return (await r.json()) as Study;
}
async function archive(request: APIRequestContext, id: string) {
  const s = await (await request.get(`/api/studio/${id}`)).json();
  await request.patch(`/api/studio/${id}`, {
    data: { type: "archive", archived: true, revision: s.revision },
  });
}

test("Studio saves findings, edits reports, retains scope history and exports real server results", async ({
  page,
  request,
}) => {
  const s = await create(request, "research workflow");
  try {
    await page.goto(`/studio?study=${s.id}`);
    await expect(
      page.getByRole("textbox", { name: "Study title" }),
    ).toHaveValue(s.title);
    await expect(
      page.getByRole("img", { name: "crashes over time" }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Add to report", exact: true })
      .first()
      .click();
    await page.getByRole("tab", { name: "Report", exact: true }).click();
    await expect(
      page.getByRole("img", { name: "crashes over time" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "+ Text", exact: true }).click();
    const text = page.getByRole("textbox", {
      name: "Report block text",
      exact: true,
    });
    await text.fill(
      "Counts describe the project snapshot, not exposure-adjusted risk.",
    );
    await text.blur();
    await expect(
      page.getByRole("status").filter({ hasText: "Saved" }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Move block up", exact: true })
      .last()
      .click();
    await page.getByRole("tab", { name: "Explore", exact: true }).click();
    await page
      .getByRole("button", { name: "Save finding", exact: true })
      .first()
      .click();
    await expect(page.getByRole("tab", { name: /Findings/ })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await page
      .getByRole("textbox", { name: "Finding title" })
      .fill("Recorded monthly counts retained with evidence");
    await page.getByRole("textbox", { name: "Finding title" }).blur();
    await expect(
      page.getByRole("status").filter({ hasText: "Saved" }),
    ).toBeVisible();
    await page
      .getByRole("button", { name: "Add to report", exact: true })
      .click();
    await page
      .getByRole("button", { name: "NSW · 2024-01 – 2024-12", exact: true })
      .click();
    await page.getByLabel("From", { exact: true }).fill("2023-01");
    await page
      .getByRole("button", { name: "Save context", exact: true })
      .click();
    await expect(
      page.getByRole("button", {
        name: "NSW · 2023-01 – 2024-12",
        exact: true,
      }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Close research panel" }).click();
    await page.reload();
    await page.getByRole("tab", { name: "Report", exact: true }).click();
    await expect(
      page.getByText("Recorded monthly counts retained with evidence", {
        exact: true,
      }),
    ).toBeVisible();
    const state = (await (
      await request.get(`/api/studio/${s.id}`)
    ).json()) as Study;
    expect(state.runs).toHaveLength(1);
    expect(state.runs[0].context.filters.dateRange.from).toBe("2024-01-01");
    expect(state.context.filters.dateRange.from).toBe("2023-01-01");
    expect(state.findings[0].edits.length).toBeGreaterThan(0);
    expect(state.report).toHaveLength(3);
    const download = page.waitForEvent("download");
    await page
      .getByRole("button", { name: "Export study", exact: true })
      .click();
    expect((await download).suggestedFilename()).toMatch(/\.zip$/);
    await page.getByRole("button", { name: "Research history" }).click();
    await expect(
      page.getByText("Before context change", { exact: true }),
    ).toBeVisible();
    await page.getByRole("button", { name: "View", exact: true }).click();
    await expect(
      page.getByText("Viewing saved history · read only"),
    ).toBeVisible();
  } finally {
    await archive(request, s.id);
  }
});

test("Studio reports save failures as Unsaved and retries without losing local edits", async ({
  page,
  request,
}) => {
  const s = await create(request, "save failure");
  try {
    await page.goto(`/studio?study=${s.id}`);
    await expect(
      page.getByRole("textbox", { name: "Study title" }),
    ).toHaveValue(s.title);
    await page.route(`**/api/studio/${s.id}`, async (route) => {
      if (route.request().method() === "PATCH")
        await route.fulfill({
          status: 503,
          contentType: "application/json",
          body: JSON.stringify({ error: "Storage unavailable for validation" }),
        });
      else await route.continue();
    });
    await page
      .getByRole("textbox", { name: "Study title" })
      .fill("Locally retained edit");
    await page.getByRole("textbox", { name: "Study title" }).blur();
    await expect(
      page.getByRole("status").filter({ hasText: "Unsaved" }),
    ).toBeVisible();
    await expect(
      page.getByRole("alert").filter({ hasText: "Storage unavailable" }),
    ).toBeVisible();
    expect(
      (await (await request.get(`/api/studio/${s.id}`)).json()).title,
    ).toBe(s.title);
    await page.unroute(`**/api/studio/${s.id}`);
    await page.getByRole("button", { name: "Retry save", exact: true }).click();
    await expect(
      page.getByRole("status").filter({ hasText: "Saved" }),
    ).toBeVisible();
    await page.reload();
    await expect(
      page.getByRole("textbox", { name: "Study title" }),
    ).toHaveValue("Locally retained edit");
  } finally {
    await archive(request, s.id);
  }
});

test("Studio keeps draft across panels, themes, mobile refresh and unrelated page filters", async ({
  page,
  request,
}) => {
  const s = await create(request, "context isolation");
  try {
    await page.goto(`/studio?study=${s.id}`);
    await page
      .getByRole("textbox", { name: "Research question", exact: true })
      .fill("Continue with the matching months");
    await page
      .getByRole("textbox", { name: "Research question", exact: true })
      .blur();
    await expect(
      page.getByRole("status").filter({ hasText: "Saved" }),
    ).toBeVisible();
    await page.getByRole("button", { name: "Assistant", exact: true }).click();
    await expect(
      page.getByRole("textbox", { name: "Research question", exact: true }),
    ).toHaveValue("Continue with the matching months");
    await page.getByRole("button", { name: "Context", exact: true }).click();
    await page.getByRole("button", { name: "Close research panel" }).click();
    await expect(
      page.getByRole("textbox", { name: "Research question", exact: true }),
    ).toHaveValue("Continue with the matching months");
    await page.goto(
      "/?source=QLD&from=2022-01-01&to=2022-12-31&datasetVersion=official-v1&batchId=" +
        DEFAULT_FILTERS.batchId,
    );
    await page.getByRole("link", { name: "Studio", exact: true }).click();
    await expect(
      page.getByRole("textbox", { name: "Study title" }),
    ).toHaveValue(s.title);
    await expect(
      page.getByRole("button", {
        name: "NSW · 2024-01 – 2024-12",
        exact: true,
      }),
    ).toBeVisible();
    for (const width of [1440, 1280, 820, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      await page.reload();
      await expect(
        page.getByRole("textbox", { name: "Study title" }),
      ).toHaveValue(s.title);
      expect(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      ).toBe(true);
      await page
        .getByRole("button", { name: "Assistant", exact: true })
        .click();
      await expect(
        page.getByRole("textbox", { name: "Research question", exact: true }),
      ).toBeVisible();
      await page.getByRole("button", { name: "Close research panel" }).click();
    }
    await page.getByRole("button", { name: /Switch to .* theme/ }).click();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
    ).toBe(true);
    await page
      .getByRole("tab", { name: "Findings", exact: true })
      .press("Enter");
    await expect(
      page.getByRole("heading", { name: "Findings", exact: true }),
    ).toBeVisible();
  } finally {
    await archive(request, s.id);
  }
});

test("Studio rejects forged result references and redirects the old empty Reports route", async ({
  page,
  request,
}) => {
  const s = await create(request, "reference boundary");
  try {
    const response = await request.patch(`/api/studio/${s.id}`, {
      data: {
        type: "block_add",
        kind: "evidence",
        runId: s.runs[0].id,
        refId: "invented",
        revision: s.revision,
      },
    });
    expect(response.status()).toBe(400);
    const forged = await request.post("/api/studio", {
      data: { transferId: "not-a-server-receipt", answer: "Fake result" },
    });
    expect(forged.status()).toBe(400);
    await page.goto("/reports");
    await expect(page).toHaveURL(/\/studio/);
    await expect(
      page.getByRole("link", { name: "Studio", exact: true }),
    ).toBeVisible();
  } finally {
    await archive(request, s.id);
  }
});
