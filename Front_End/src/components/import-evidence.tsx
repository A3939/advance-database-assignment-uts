import { useRef, useState } from 'react';
import styles from './imports.module.css';

const object = (value: unknown): Record<string, unknown> => value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const records = (value: unknown) => Array.isArray(value) ? value.map(object) : [];
export function sourceForEvidence(data: Record<string, unknown>) {
  const candidate = object(data.candidate), job = object(data.job), result = object(job.result);
  const researchSource = object(candidate.source);
  if (Object.values(researchSource).some(value => value !== null && value !== undefined && value !== '')) return researchSource;
  const proposed = records(object(data.agent).steps).findLast(step => step.name === 'set_source_contract');
  return object(result.source_contract || object(result.evidence).source_contract || result.source || object(proposed?.arguments).contract);
}
export function qualityForEvidence(data: Record<string, unknown>) {
  const job = object(data.job), candidate = object(data.candidate), result = object(job.result);
  if (candidate.receipt_status === 'verified_current') return records(candidate.qa);
  const qa = records(job.qa);
  return qa.length ? qa : records(result.qa);
}
const tabs = ['Sources', 'Quality checks', 'Code versions', 'Full record'] as const;
type EvidenceTab = typeof tabs[number];

/** The complete record is fetched only after the user explicitly requests evidence. */
export function ImportEvidence({ data }: { data: Record<string, unknown> }) {
  const [tab, setTab] = useState<EvidenceTab>('Sources');
  const tablist = useRef<HTMLDivElement>(null);
  const candidate = object(data.candidate), outcome = object(data.outcome);
  const job = object(data.job), steps = records(object(data.agent).steps);
  const sourceSteps = steps.filter(step => /source|document|registry/.test(String(step.name)));
  const codeSteps = steps.filter(step => ['write_adapter', 'patch_adapter', 'read_adapter', 'run_python'].includes(String(step.name)));
  const qualitySteps = steps.filter(step => ['validate_candidate', 'inspect_run', 'prepare_and_validate_research'].includes(String(step.name)));
  const source = sourceForEvidence(data);
  const sourceInfo = object(source.source || source), coverage = object(sourceInfo.coverage), definitions = object(source.definitions);
  const sourceValues = [['Source', sourceInfo.title || sourceInfo.source_name || sourceInfo.name || job.source_id], ['Publisher', sourceInfo.publisher], ['Jurisdiction', sourceInfo.jurisdiction], ['Coverage', coverage.from && coverage.to ? `${coverage.from} → ${coverage.to}` : undefined]].filter((row): row is [string, string] => typeof row[1] === 'string');
  const quality = qualityForEvidence(data);
  return <>
    <div ref={tablist} className={styles.evidenceTabs} role="tablist" aria-label="Execution evidence sections" onKeyDown={event => { const index = tabs.indexOf(tab); const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : -1; if (next >= 0) { event.preventDefault(); setTab(tabs[next]); tablist.current?.querySelectorAll('button')[next]?.focus(); } }}>{tabs.map(label => <button key={label} type="button" role="tab" tabIndex={tab === label ? 0 : -1} aria-selected={tab === label} id={`import-evidence-${label.replaceAll(' ', '-')}`} aria-controls="import-evidence-panel" onClick={() => setTab(label)}>{label}</button>)}</div>
    <div role="tabpanel" id="import-evidence-panel" aria-labelledby={`import-evidence-${tab.replaceAll(' ', '-')}`}>
      {tab === 'Sources' && <>{Object.values(object(candidate.source)).some(value => value != null) && <p className={styles.note}>Research candidate source context · official identity is not established by candidate QA.</p>}{!!records(candidate.inputs).length && <details><summary>Input evidence and hashes</summary><pre>{JSON.stringify(candidate.inputs, null, 2)}</pre></details>}{!!sourceValues.length && <dl className={styles.identity}>{sourceValues.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{value}</dd></div>)}</dl>}{!!Object.keys(definitions).length && <details><summary>Recorded metric definitions</summary><pre tabIndex={0}>{JSON.stringify(definitions, null, 2)}</pre></details>}{!!Object.keys(source).length && <details><summary>Source context and evidence references</summary><pre tabIndex={0}>{JSON.stringify(source, null, 2)}</pre></details>}{sourceSteps.length ? sourceSteps.map((step, index) => <details key={String(step.id || index)}><summary>Source investigation {index + 1} · {String(step.status)}</summary><pre tabIndex={0}>{JSON.stringify(step, null, 2)}</pre></details>) : !Object.keys(source).length && <p className={styles.note}>No source evidence has been recorded yet.</p>}</>}
      {tab === 'Quality checks' && <><p className={styles.note}>Receipt: {String(candidate.receipt_status || 'not supplied')} · {quality.length} checks in this result. QA run counts are reported separately for the current attempt.</p>{!!candidate.quality_report && <details><summary>Row dispositions and reconciliation</summary><pre>{JSON.stringify(candidate.quality_report, null, 2)}</pre></details>}{!!Object.keys(object(candidate.goal_coverage)).length && <details><summary>Requested goal coverage and source limitations</summary><pre>{JSON.stringify(candidate.goal_coverage, null, 2)}</pre></details>}{!!records(outcome.historical_blockers).length && <details><summary>Historical issues · resolution and applicability</summary><pre>{JSON.stringify(outcome.historical_blockers, null, 2)}</pre></details>}{!!records(candidate.historical_qa).length && <details><summary>Historical QA · not current revalidation</summary><pre>{JSON.stringify(candidate.historical_qa, null, 2)}</pre></details>}{quality.length ? <ul className={styles.qa}>{quality.map((check, index) => <li key={String(check.code || index)}><span className={styles.badge} data-status={String(check.status)}>{String(check.status)}</span><div><strong>{String(check.code)}</strong><p>{String(check.message)}</p>{!!check.metrics && <details><summary>Check values</summary><pre tabIndex={0}>{JSON.stringify(check.metrics, null, 2)}</pre></details>}</div></li>)}</ul> : <p className={styles.note}>No final quality result is recorded yet. Earlier validation attempts appear below.</p>}{qualitySteps.map((step, index) => <details key={String(step.id || index)}><summary>Validation {index + 1} · {String(step.status)}</summary><pre tabIndex={0}>{JSON.stringify(step, null, 2)}</pre></details>)}</>}
      {tab === 'Code versions' && (codeSteps.length ? codeSteps.map((step, index) => { const args = object(step.arguments), output = object(step.result); const code = args.code || output.code; return <details key={String(step.id || index)}><summary>Transformation record {index + 1} · {String(step.status)}</summary>{typeof args.reason === 'string' && <p className={styles.note}>{args.reason}</p>}{typeof code === 'string' ? <pre tabIndex={0}><code>{code}</code></pre> : typeof args.old === 'string' && typeof args.new === 'string' ? <><p className={styles.note}>Replaced code</p><pre tabIndex={0}><code>{args.old}</code></pre><p className={styles.note}>Revised code</p><pre tabIndex={0}><code>{args.new}</code></pre></> : <p className={styles.note}>The recorded operation did not include a complete code listing.</p>}<details><summary>Execution details</summary><pre tabIndex={0}>{JSON.stringify(step, null, 2)}</pre></details></details>; }) : <p className={styles.note}>No generated transformation is recorded for this job.</p>)}
      {tab === 'Full record' && <pre tabIndex={0}>{JSON.stringify(data, null, 2)}</pre>}
    </div>
  </>;
}
