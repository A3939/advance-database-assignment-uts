/** UI-only contract test: mocked durable progress, no model execution or publication. */
import { test, expect } from '@playwright/test';
import { mkdir } from 'node:fs/promises';
import { SNAPSHOT_CATALOG } from '../../src/services/catalog-contracts';
import type { LocalImportJob } from '../../src/services/imports-contracts';

test('automatic import progress exposes real counters and revisions while full evidence loads on demand', async ({ page }) => {
  const at = new Date().toISOString();
  const job: LocalImportJob = {
    id: 'ef8c079c-10fd-40f3-ace2-c8a7e281fb12', label: 'Automatic progress UI fixture', status: 'processing', stage: 'agent', message: 'Investigating source evidence and validating an adapter', created_at: at, updated_at: at, attempt: 1, files: [], events: [],
    agent: { status: 'investigating', phase: 'sample_running', model_calls: 6, tool_calls: 12, correction_count: 2, checks: { sample_runs: 2, full_runs: 0, qa_checks: 1 }, latest_steps: [{ kind: 'tool', phase: 'sample_running', status: 'running', summary: 'Testing the transformation on a sample of the uploaded files.', at }] },
  };
  let evidenceRequests = 0;
  await page.route('**/api/data/catalog*', route => route.fulfill({ json: SNAPSHOT_CATALOG }));
  await page.route('**/api/imports/**', async route => {
    expect(route.request().method()).toBe('GET');
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/health')) return route.fulfill({ json: { status: 'ok', mode: 'local-test', worker: { alive: true }, capabilities: {} } });
    if (path.endsWith('/catalog')) return route.fulfill({ json: { release_id: null, sources: [] } });
    if (path.endsWith('/jobs')) return route.fulfill({ json: { jobs: [job] } });
    if (path.endsWith('/evidence')) {
      evidenceRequests++;
      return route.fulfill({ json: { job: { ...job, result: { source: { title: 'Synthetic progress evidence' } } }, agent: { steps: [{ id: 1, name: 'write_adapter', status: 'succeeded', arguments: { code: 'def adapt(ctx):\n    return []', reason: 'Synthetic UI fixture only.' } }] } } });
    }
    return route.fulfill({ json: job });
  });
  await page.goto('/imports');
  await page.getByRole('button', { name: /Automatic progress UI fixture/ }).click();
  const progress = page.getByRole('region', { name: 'Automatic import progress' });
  await expect(progress.getByRole('heading', { name: 'Testing a sample', exact: true })).toBeVisible();
  await expect(progress.getByText('Automatic revisions', { exact: true }).locator('..')).toHaveText('Automatic revisions2');
  await expect(progress.getByText('Sample runs', { exact: true }).locator('..')).toHaveText('Sample runs2');
  await expect(progress.getByText('Testing the transformation on a sample of the uploaded files.', { exact: true })).toBeVisible();
  await expect(page.getByText('write_adapter', { exact: true })).toHaveCount(0);
  expect(evidenceRequests).toBe(0);
  job.agent!.phase = 'full_qa'; job.agent!.correction_count = 3; job.agent!.checks = {
    sample_runs: 3, full_runs: 1, qa_checks: 4, qa_passed: 1, qa_failed: 1, qa_blocked: 1, qa_running: 1, qa_interrupted: 0, qa_unclassified: 0,
  };
  job.agent!.latest_steps = [{ kind: 'tool', phase: 'full_qa', status: 'running', summary: 'Checking every admitted record against the source definitions.', at }];
  job.updated_at = new Date(Date.now() + 1000).toISOString();
  await expect(progress.getByRole('heading', { name: 'Checking the complete result', exact: true })).toBeVisible();
  await expect(progress.getByText('Automatic revisions', { exact: true }).locator('..')).toHaveText('Automatic revisions3');
  await expect(progress.locator('[aria-current=step]')).toHaveText('Full checks');
  await expect(progress.getByText('Quality checks', { exact: true }).locator('..')).toHaveText('Quality checks4');
  await expect(progress.getByLabel('Quality check outcomes')).toHaveText('Quality checks: 1 passed, 1 failed, 1 blocked, 1 running, 0 stopped.');
  job.agent!.investigation = { version: 'scoped-issue-progress-v1', state: 'replan', meaningful_events: 3, tools_without_progress: 20, unresolved_count: 2, last_progress_at: at };
  job.updated_at = new Date(Date.now() + 1500).toISOString();
  await expect(progress.getByLabel('Investigation progress')).toContainText('2 unresolved checks · 20 actions without verified progress.');
  await expect(progress.getByLabel('Investigation progress')).toContainText('Last verified progress:');
  await expect(progress.getByLabel('Investigation progress')).toContainText('different diagnostic approach');
  expect(evidenceRequests).toBe(0);
  await mkdir('output/playwright', { recursive: true });
  await page.getByRole('heading', { name: 'From source files to evidence.' }).click();
  await page.screenshot({ path: 'output/playwright/import-issue-progress-desktop.png', fullPage: true });
  job.status = 'needs_input'; job.agent!.phase = 'needs_input'; job.agent!.investigation.state = 'stalled';
  job.updated_at = new Date(Date.now() + 1800).toISOString();
  await expect(progress.getByRole('heading', { name: 'Investigation needs review', exact: true })).toBeVisible();
  await expect(progress.getByText('Answer the question below or add the missing file to continue.', { exact: false })).toHaveCount(0);
  job.status = 'processing';
  job.agent!.phase = 'waiting_for_model';
  job.updated_at = new Date(Date.now() + 2000).toISOString();
  await expect(progress.getByRole('heading', { name: 'Waiting for the model service', exact: true })).toBeVisible();
  await expect(progress.getByText('Automatic revisions', { exact: true }).locator('..')).toHaveText('Automatic revisions3');
  await page.getByRole('button', { name: 'View evidence', exact: true }).click();
  await expect(page.getByRole('tab', { name: 'Sources', exact: true })).toHaveAttribute('aria-selected', 'true');
  await expect(page.getByText('Synthetic progress evidence', { exact: true })).toBeVisible();
  await page.getByRole('tab', { name: 'Sources', exact: true }).focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('tab', { name: 'Quality checks', exact: true })).toHaveAttribute('aria-selected', 'true');
  await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('tab', { name: 'Code versions', exact: true })).toHaveAttribute('aria-selected', 'true');
  await page.getByText('Transformation record 1 · succeeded', { exact: true }).click();
  await expect(page.getByRole('tabpanel')).toContainText('def adapt(ctx)');
  expect(evidenceRequests).toBe(1);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('heading', { name: 'From source files to evidence.' }).click();
  await page.screenshot({ path: 'output/playwright/import-issue-progress-mobile.png', fullPage: true });
});
