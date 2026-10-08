/** Opt-in actual model/real official source run, with no manual mapping or mocked routes. */
import { test, expect } from '@playwright/test';
import { readFileSync, mkdirSync, writeFileSync } from 'node:fs';
import { resolve, extname } from 'node:path';
import type { LocalImportJob } from '../../src/services/imports-contracts';
import { coverageMonthRange } from '../../src/services/catalog-contracts';

const state = process.env.ARSIA_LIVE_IMPORT_STATE;
test('real upload continues after browser closes and publishes a traceable release', async ({ page, request, context }) => {
  test.skip(!state, 'Explicit ARSIA_LIVE_IMPORT_STATE enables actual model calls and local publication');
  test.setTimeout(65 * 60 * 1000);
  const manifest = JSON.parse(readFileSync(resolve('artifacts/autonomous-imports/source-downloads/source-cases.json'), 'utf8'));
  const selected = manifest.cases[state!];
  expect(selected).toBeTruthy();
  const uploads = Array.isArray(selected.upload) ? selected.upload : [selected.upload];
  const beforeCatalog = process.env.ARSIA_LIVE_EXPECT_NO_CHANGE === '1'
    ? await (await request.get('/api/imports/catalog', { headers: { Origin: 'http://127.0.0.1:3100' } })).json() : undefined;
  let created: LocalImportJob;
  if (process.env.ARSIA_LIVE_JOB_ID) {
    const response = await request.get(`/api/imports/jobs/${process.env.ARSIA_LIVE_JOB_ID}`, { headers: { Origin: 'http://127.0.0.1:3100' } });
    expect(response.ok()).toBe(true); created = await response.json();
  } else {
  await page.goto('/imports');
  await expect(page.getByText('Worker online · one heavy job at a time')).toBeVisible({ timeout: 20000 });
  await page.getByLabel('Import name', { exact: true }).fill(`Autonomous real ${state} ${new Date().toISOString()}`);
  await page.getByLabel('Import data files', { exact: true }).setInputFiles(uploads.map((file: { name: string; path: string }, index:number) => ({
    name: process.env.ARSIA_LIVE_RENAME_UPLOADS === '1' ? `dataset-part-${index+1}${extname(file.name)}` : file.name,
    mimeType: 'application/octet-stream', buffer: readFileSync(file.path),
  })));
  const creation = page.waitForResponse(response => response.url().endsWith('/api/imports/jobs') && response.request().method() === 'POST');
  await page.getByRole('button', { name: 'Upload & run', exact: true }).click();
  created = await (await creation).json();
  await expect(page.getByRole('region', { name: 'Selected job', exact: true })).toContainText(/queued|processing|profiling|Investigating/i, { timeout: 120000 });
  }
  const folder = resolve(`artifacts/autonomous-imports/live-${state!.toLowerCase()}/${created.id}`);
  mkdirSync(folder, { recursive: true });
  writeFileSync(resolve(folder, 'job.json'), JSON.stringify({ job_id: created.id, started_at: new Date().toISOString() }, null, 2));
  await page.close();
  let previous = '';
  let job: LocalImportJob = created;
  await expect.poll(async () => {
    const response = await request.get(`/api/imports/jobs/${created.id}`, { headers: { Origin: 'http://127.0.0.1:3100' } });
    expect(response.ok()).toBe(true);
    job = await response.json();
    const progress = `${job.status}: ${job.stage}: ${job.message}`;
    if (progress !== previous) { console.log(progress); previous = progress; }
    return ['succeeded', 'no_change', 'needs_input', 'failed', 'cancelled'].includes(job.status);
  }, { timeout: 60 * 60 * 1000, intervals: [5000, 10000] }).toBe(true);
  writeFileSync(resolve(folder, 'result.json'), JSON.stringify(job, null, 2));
  const evidence = await request.get(`/api/imports/jobs/${created.id}/evidence`, { headers: { Origin: 'http://127.0.0.1:3100' } });
  writeFileSync(resolve(folder, 'evidence.json'), JSON.stringify(await evidence.json(), null, 2));
  const reopened = await context.newPage();
  await reopened.goto('/imports');
  await reopened.getByRole('button', { name: new RegExp(created.label.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) }).click();
  mkdirSync(resolve('output/playwright'), { recursive: true });
  await reopened.screenshot({ path: resolve(`output/playwright/autonomous-${state!.toLowerCase()}.png`), fullPage: true });
  if (process.env.ARSIA_LIVE_EXPECT_BLOCKED === '1') {
    expect(job.status).toBe('needs_input');
    expect(job.release_id).toBeFalsy();
  } else {
    expect(['succeeded', 'no_change'], JSON.stringify(job.error)).toContain(job.status);
    if (beforeCatalog) {
      expect(job.status).toBe('no_change');
      expect(job.release_id).toBe(beforeCatalog.release_id);
      const afterCatalog = await (await request.get('/api/imports/catalog', { headers: { Origin: 'http://127.0.0.1:3100' } })).json();
      const identities = (catalog:{sources:{source_id:string;batch_id:string}[]}) => Object.fromEntries(catalog.sources.map(s=>[s.source_id,s.batch_id]));
      expect(afterCatalog.release_id).toBe(beforeCatalog.release_id);
      expect(identities(afterCatalog)).toEqual(identities(beforeCatalog));
      writeFileSync(resolve(folder,'no-change.json'),JSON.stringify({passed:true,before:beforeCatalog,after:afterCatalog},null,2));
    }
    expect(job.release_id).toBeTruthy();
    if (!job.result || !job.source_id || !job.release_id) throw Error('A successful publication must retain its result and identities.');
    const result = job.result as { admission: { status: string }; coverage: { from: string; to: string }; summary: { crash_count: number | null } };
    expect(result.admission.status).toBe('admitted');
    const source = ({official_nsw:'NSW',official_vic:'VIC',official_qld:'QLD'} as Record<string,string>)[job.source_id] || job.source_id;
    const query=new URLSearchParams({source,datasetVersion:'local-integrated-v1',batchId:job.release_id,releaseId:job.release_id,...coverageMonthRange(result.coverage)});
    await reopened.goto(`/?${query}`);
    await expect(reopened.getByRole('combobox', { name: 'Data source' })).toContainText(source);
    await expect(reopened.locator('.metric-value').first()).toHaveText(result.summary.crash_count === null ? '—' : result.summary.crash_count.toLocaleString('en-AU'), { timeout: 30000 });
  }
});
