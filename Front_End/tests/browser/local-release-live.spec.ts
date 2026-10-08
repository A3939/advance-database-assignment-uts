/** Opt-in real publication UI verification: GET requests only, without mocked transport. */
import { test, expect } from '@playwright/test';
import { mkdir, readFile } from 'node:fs/promises';
import { analysisHref, DEFAULT_VIEW } from '../../src/services/analysis-state';
import { coverageMonthRange, type DataCatalog } from '../../src/services/catalog-contracts';

const requestedSource = process.env.ARSIA_LIVE_ANALYSIS_SOURCE;
test('published source remains fixed across real Overview, Analytics, Data and saved Studio', async ({ page, request }) => {
  test.skip(!requestedSource, 'Set ARSIA_LIVE_ANALYSIS_SOURCE to inspect an already published source.');
  test.setTimeout(120000);
  await page.emulateMedia({ reducedMotion: 'reduce' });
  const release = process.env.ARSIA_LIVE_ANALYSIS_RELEASE;
  const catalogResponse = await request.get('/api/data/catalog' + (release ? `?releaseId=${release}` : ''));
  expect(catalogResponse.ok()).toBe(true);
  const catalog = await catalogResponse.json() as DataCatalog;
  expect(catalog.mode).toBe('local');
  const source = catalog.sources.find(s => s.source === requestedSource || s.sourceId === requestedSource);
  expect(source?.origin).toBe('publication');
  const filters = { source: source!.source, dateRange: coverageMonthRange(source!.coverage), datasetVersion: catalog.datasetVersion, batchId: catalog.batchId, releaseId: catalog.releaseId };
  const query = new URL(analysisHref('/', filters, DEFAULT_VIEW), 'http://localhost').search;
  const overviewResponse = await request.get('/api/data/overview' + query);
  expect(overviewResponse.ok()).toBe(true);
  const overview = await overviewResponse.json();
  expect(overview.meta.releaseId).toBe(catalog.releaseId);
  expect(overview.meta.sourceBatchId).toBe(source!.batchId);
  const oraclePath = process.env.ARSIA_LIVE_ANALYSIS_ORACLE;
  if (oraclePath) {
    const oracle = JSON.parse(await readFile(oraclePath, 'utf8'));
    for (const [metric, field] of Object.entries({ crashes: 'crash_count', fatalCrashes: 'fatal_crash_count', livesLost: 'fatalities', casualties: 'casualties' })) expect(overview.data[metric].value, `Independent oracle ${metric}`).toBe(oracle.summary[field]);
  }
  await mkdir('output/playwright', { recursive: true });
  const requests: URL[] = [];
  page.on('request', req => { const url = new URL(req.url()); if (url.pathname.startsWith('/api/data/') && !url.pathname.endsWith('/catalog')) requests.push(url); });
  await page.goto(analysisHref('/', filters, DEFAULT_VIEW));
  for (const [index, metric] of ['crashes', 'fatalCrashes', 'livesLost', 'casualties'].entries()) {
    const value = overview.data[metric].value;
    await expect(page.locator('.metric-value').nth(index)).toHaveText(value === null ? '—' : Number(value).toLocaleString('en-AU'), { timeout: 30000 });
  }
  await expect(page.getByRole('combobox', { name: 'Data source' })).toContainText(source!.source);
  await page.locator('.date-trigger').click();
  await expect(page.getByLabel('Start month')).toHaveValue(filters.dateRange.from.slice(0, 7));
  await expect(page.getByLabel('End month')).toHaveValue(filters.dateRange.to.slice(0, 7));
  await page.keyboard.press('Escape');
  await page.screenshot({ path: `output/playwright/local-release-${source!.source}-overview.png`, fullPage: true });
  await page.getByRole('link', { name: 'Analytics', exact: true }).click();
  await expect(page.getByRole('button', { name: source!.source, exact: true })).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('analytics-total')).toHaveText(overview.data.crashes.value === null ? '—' : Number(overview.data.crashes.value).toLocaleString('en-AU'), { timeout: 30000 });
  await expect(page.locator('.analytics-chart canvas').first()).toBeVisible({ timeout: 30000 });
  if (overview.data.livesLost.value === null) {
    await page.getByRole('region', { name: 'Time and change' }).getByRole('button', { name: 'Lives lost', exact: true }).click();
    await expect(page.getByRole('status').filter({ hasText: overview.data.livesLost.availability === 'unsupported' ? 'This source does not provide lives lost.' : 'Lives lost unavailable for this selection. Unknown observations are not zero.' })).toBeVisible();
    await page.getByRole('region', { name: 'Time and change' }).getByRole('button', { name: 'Crashes', exact: true }).click();
  }
  await page.screenshot({ path: `output/playwright/local-release-${source!.source}-analytics.png`, fullPage: true });
  await page.getByRole('link', { name: 'Data', exact: true }).click();
  await expect(page.getByRole('main')).toContainText(source!.title);
  const sourceCard = page.locator('.dataset-card').filter({ has: page.getByRole('heading', { name: source!.title, exact: true }) });
  await expect(sourceCard).toContainText('Local publication');
  await expect(sourceCard).toContainText(source!.batchId);
  await expect(sourceCard).toContainText(catalog.releaseId!);
  await page.screenshot({ path: `output/playwright/local-release-${source!.source}-data.png`, fullPage: true });
  expect(requests.length).toBeGreaterThan(4);
  for (const url of requests) expect(url.searchParams.get('releaseId'), url.pathname).toBe(catalog.releaseId);
  const studyId = process.env.ARSIA_LIVE_ANALYSIS_STUDY;
  if (studyId) {
    const saved = await (await request.get(`/api/studio/${studyId}`)).json();
    expect(saved.context.filters.releaseId).toBe(catalog.releaseId);
    expect(saved.context.filters.source).toBe(source!.source);
    await page.goto(analysisHref('/studio', filters, DEFAULT_VIEW) + `&study=${studyId}`);
    await expect(page.getByRole('textbox', { name: 'Study title' })).toHaveValue(saved.title);
    await expect(page.getByRole('main')).toContainText(saved.runs.at(-1).answer.slice(0, 20));
    await expect(page.getByText('Loading chart…', { exact: true })).toHaveCount(0);
  }
  await mkdir('output/playwright', { recursive: true });
  await page.screenshot({ path: `output/playwright/local-release-${source!.source}.png`, fullPage: true });
});
