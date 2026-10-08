/** Synthetic UI fixture only: this does not establish any source CRS or import acceptance. */
import { test, expect } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import { SNAPSHOT_CATALOG, LOCAL_VERSION } from '../../src/services/catalog-contracts';
import { createPublishedProvider } from '../../src/server/published-data';
import { createOfficialProvider, loadOfficialSnapshot } from '../../src/server/official-data';
import type { publicationRead } from '../../src/server/data-catalog';

const release = 'aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa', source = 'synthetic_geography_fixture';
const catalog = { ...SNAPSHOT_CATALOG, mode: 'local' as const, releaseId: release, batchId: release, datasetVersion: LOCAL_VERSION, coverage: { from: '2025-01-01', to: '2025-12-31' }, sources: [{ source, sourceId: source, title: 'Synthetic coordinate UI fixture', jurisdiction: 'SA', publisher: 'Synthetic browser fixture', batchId: 'bbbbbbbb-1111-4111-8111-bbbbbbbbbbbb', origin: 'publication' as const, coverage: { from: '2025-01-01', to: '2025-12-31' }, capabilities: { monthly: true, severity: false, geography: true, units: false }, definitions: {}, limitations: ['Synthetic fixture; no evidence of real SA admission.'] }] };

for (const fallback of [false, true]) test(`trusted rounded-cell UI ${fallback ? 'SVG fallback' : 'WebGL'} preserves partial coverage without region drilldown`, async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  if (fallback) await page.addInitScript(`const original=HTMLCanvasElement.prototype.getContext;HTMLCanvasElement.prototype.getContext=function(type,...args){return type.includes('webgl')?null:original.call(this,type,...args)};`);
  const counts = { crash_count: 6, fatal_crash_count: null, fatalities: null, casualties: null };
  const read = (async (_path: string, q: Record<string, string>) => ({ release_id: release, batch_id: catalog.sources[0].batchId, source_id: source, availability: 'available', coverage: { ...catalog.coverage, complete: true }, summary: counts, monthly: [{ year: 2025, month: 1, ...counts }], yearly: [{ year: 2025, ...counts }], severity: [], geography: { status: 'available', precision_degrees: 0.1, cells: [{ longitude: 138.6, latitude: -34.9, crash_count: 2 }, { longitude: 139.1, latitude: -35.1, crash_count: 1 }], total_cells: 3, returned_cells: 2, truncated: true, located_crash_count: 5, unlocated_crash_count: 1 }, requested: q })) as typeof publicationRead;
  const provider = createPublishedProvider(catalog, createOfficialProvider(await loadOfficialSnapshot()), read);
  const queryURLs: URL[] = [];
  await page.route('**/api/data/**', async route => {
    const url = new URL(route.request().url()), p = url.searchParams, report = url.pathname.split('/').at(-1);
    if (report === 'catalog') return route.fulfill({ json: catalog });
    queryURLs.push(url);
    const f = { source: p.get('source')!, dateRange: { from: p.get('from')!, to: p.get('to')! }, datasetVersion: LOCAL_VERSION, batchId: release, releaseId: release };
    const data = report === 'overview' ? await provider.getOverview(f) : report === 'timeseries' ? await provider.getTimeSeries(f, 'yearly') : report === 'severity' ? await provider.getSeverityDistribution(f) : report === 'metadata' ? await provider.getDatasetMetadata() : await provider.getMapData(f);
    return route.fulfill({ json: data });
  });
  await page.goto(`/?source=${source}&from=2025-01-01&to=2025-12-31&datasetVersion=${LOCAL_VERSION}&batchId=${release}&releaseId=${release}`);
  const map = page.getByRole('region', { name: 'Trusted coordinate aggregates' });
  await expect(map).toBeVisible();
  await expect(map).toContainText('0.1° coordinate cells');
  await expect(map).toContainText('5 crashes with trusted coordinates · 1 without.');
  await expect(map).toContainText('Showing 2 of 3 cells. Other cells are not shown.');
  await expect(map.getByRole('combobox')).toHaveCount(0);
  await expect(page.getByRole('combobox', { name: 'Search areas' })).toHaveCount(0);
  if (fallback) {
    await expect(map.getByRole('img', { name: 'Rounded crash coordinate grid, WebGL unavailable' })).toBeVisible();
    await expect(map.locator('circle')).toHaveCount(2);
    await expect(map.getByRole('button', { name: 'Zoom in', exact: true })).toBeDisabled();
  } else {
    await expect(map.locator('canvas')).toBeVisible();
    await map.getByRole('button', { name: 'Zoom in', exact: true }).click();
  }
  await map.getByText('View coordinate-cell values', { exact: true }).focus();
  await page.keyboard.press('Enter');
  await expect(map.getByRole('table')).toBeVisible();
  await expect(map.getByRole('cell', { name: '138.6°', exact: true })).toBeVisible();
  await expect(map.getByRole('cell', { name: '2', exact: true })).toBeVisible();
  await expect(page).not.toHaveURL(/regionId=/);
  for (const url of queryURLs) { expect(url.searchParams.get('releaseId')).toBe(release); expect(url.searchParams.has('regionId')).toBe(false); }
  await map.getByText('View coordinate-cell values', { exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  if (!fallback) await map.getByRole('button', { name: 'Reset coordinate map' }).click();
  await mkdir('output/playwright', { recursive: true });
  await page.screenshot({ path: `output/playwright/synthetic-point-grid-${fallback ? 'fallback' : 'webgl'}.png`, fullPage: true });
});
