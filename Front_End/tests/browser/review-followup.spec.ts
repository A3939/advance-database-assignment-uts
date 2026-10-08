import { test, expect } from "@playwright/test";
const batch = "bcc5da57-25f2-41ec-9925-bef421b02671";
const scope = (path: string, from = "2024-01-01", to = "2024-12-31") => `${path}?source=NSW&from=${from}&to=${to}&batchId=${batch}&datasetVersion=official-v1`;
test.beforeEach(async ({ page }) => { await page.emulateMedia({ reducedMotion: "reduce" }); });

for (const path of ["/", "/analytics"]) {
  test(`${path}: typed invalid months cannot Apply or produce a non-restorable URL`, async ({ page }) => {
    const requests: string[] = [];
    page.on("request", request => { if (request.url().includes("/api/data/")) requests.push(request.url()); });
    await page.goto(scope(path));
    if (path === "/") await page.locator(".date-trigger").click();
    else await page.getByRole("button", {name:/^Analysis period:/}).click();
    const original = page.url();
    const from = page.getByLabel("Start month", {exact:true});
    const to = page.getByLabel("End month", {exact:true});
    const apply = page.getByRole("button",{name:"Apply period",exact:true});
    await from.fill("2018-01"); await to.fill("2020-02");
    expect(await from.evaluate((node: HTMLInputElement) => node.validity.rangeUnderflow)).toBe(true);
    await expect(apply).toBeDisabled();
    await expect(page.getByText("Choose months from Jan 2019 to Dec 2026.",{exact:true})).toBeVisible();
    expect(page.url()).toBe(original);
    await from.fill("2019-01"); await to.fill("2027-01");
    await expect(apply).toBeDisabled();
    await expect(page.getByText("Choose months from Jan 2019 to Dec 2026.",{exact:true})).toBeVisible();
    await from.fill("2020-03"); await to.fill("2020-02");
    await expect(apply).toBeDisabled();
    await expect(page.getByText("Start month must not follow end month.",{exact:true})).toBeVisible();
    await from.fill("");
    await expect(apply).toBeDisabled();
    await expect(page.getByText("Choose both a start and an end month.",{exact:true})).toBeVisible();
    expect(requests.some(url => url.includes("from=2018") || url.includes("to=2027"))).toBe(false);
    await from.fill("2019-01"); await to.fill("2020-02");
    await expect(apply).toBeEnabled(); await apply.click();
    await expect(page).toHaveURL(/from=2019-01-01/);
    await expect(page).toHaveURL(/to=2020-02-29/);
    await page.reload();
    await expect(page.getByText("Open supported snapshot",{exact:true})).toHaveCount(0);
    if (path === "/") await expect(page.locator(".metric-value").first()).not.toHaveText("—");
    else await expect(page.getByTestId("analytics-total")).not.toHaveText("—");
  });
}

test("390px touch heatmap statuses have distinct visible labels and patterns",async ({page})=>{
  await page.setViewportSize({width:390,height:844});
  // Inject null/zero to exercise admitted-count states without changing files or business data.
  await page.route("**/api/data/overview?**", async route => {
    const response=await route.fetch(); const body=await response.json();
    body.data.crashes.value=null; body.data.crashes.availability="unknown";
    await route.fulfill({response,json:body});
  });
  await page.route("**/api/data/timeseries?**",async route=>{
    const response=await route.fetch(); const body=await response.json();
    body.data=body.data.map((row: {period:string;crashes:number|null})=>row.period==="2020-01"?{...row,crashes:0}:row.period==="2020-02"?{...row,crashes:null}:row);
    await route.fulfill({response,json:body});
  });
  await page.goto(scope("/analytics","2019-12-01","2020-02-29"));
  const missing=page.getByRole("button",{name:"Dec 2019: No coverage",exact:true});
  const zero=page.getByRole("button",{name:"Jan 2020: 0 crashes",exact:true});
  const unknown=page.getByRole("button",{name:"Feb 2020: Unknown count",exact:true});
  const outside=page.getByRole("button",{name:"Mar 2020: Not in selected period",exact:true});
  await expect(missing).toHaveText("N/C"); await expect(zero).toHaveText("0");
  await expect(unknown).toHaveText("?"); await expect(outside).toHaveText("Out");
  expect(await missing.evaluate(node=>getComputedStyle(node).backgroundImage)).toContain("repeating-linear-gradient");
  expect(await outside.evaluate(node=>getComputedStyle(node).borderStyle)).toBe("dashed");
  expect(await unknown.evaluate(node=>getComputedStyle(node).borderStyle)).toBe("dotted");
  const legend=page.getByLabel("Monthly observation states",{exact:true});
  await expect(legend).toContainText("Not selected"); await expect(legend).toContainText("No coverage");
  await expect(legend).toContainText("Unknown count"); await expect(legend).toContainText("Recorded zero");
  await missing.click(); await expect(page.getByText("No coverage for this month.",{exact:true})).toBeVisible();
  await page.waitForLoadState("networkidle");
  await page.screenshot({path:"output/playwright/review-followup-heatmap-states-mobile.png",fullPage:true});
});

test("map legend matches integer bands and omits empty intervals for a small maximum",async ({page})=>{
  let maximum=10;
  // Scale fixture isolates legend boundaries; no snapshot writes are made.
  await page.route("**/api/data/map?**",async route=>{
    const response=await route.fetch(); const body=await response.json();
    body.data.regions=body.data.regions.map((row: {count:number},index:number)=>({...row,count:index===0?maximum:0}));
    await route.fulfill({response,json:body});
  });
  await page.goto(scope("/"));
  const bins=page.locator(".map-legend i[data-band]");
  await expect(bins).toHaveCount(7);
  expect(await bins.evaluateAll(nodes=>nodes.map(node=>node.getAttribute("title")))).toEqual([
    "1–1 recorded crashes", "2–2 recorded crashes", "3–4 recorded crashes", "5–5 recorded crashes",
    "6–7 recorded crashes", "8–8 recorded crashes", "9–10 recorded crashes",
  ]);
  maximum=1;
  await page.getByLabel("Data source",{exact:true}).click();
  await page.getByRole("option", { name: "VIC", exact: true }).click();
  await expect(bins).toHaveCount(1);
  await expect(bins.first()).toHaveAttribute("data-band","7");
  await expect(bins.first()).toHaveAttribute("title","1–1 recorded crashes");
});
