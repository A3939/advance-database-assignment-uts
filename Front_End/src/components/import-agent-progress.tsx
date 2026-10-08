import { CheckCircle2, Loader2, PauseCircle } from 'lucide-react';
import type { LocalImportAgentStatus } from '@/services/imports-contracts';
import styles from './imports.module.css';

const phases: Record<string, { title: string; description: string; group: number }> = {
  candidate_verified: { title: 'Research candidate verified · Not published', description: 'The requested candidate checks are complete. No further input is required for this validation task.', group: 3 },
  candidate_partial: { title: 'Partial candidate retained', description: 'Rule QA is recorded, but requested goals remain unmet. Review the specific gaps.', group: -1 },
  engineering_required: { title: 'Waiting for a system update', description: 'The requested capabilities need an implementation update. Additional uploaded definitions cannot supply those capabilities.', group: -1 },
  publication_waiting: { title: 'Candidate verified · Publication conditions pending', description: 'Candidate checks passed; publication still requires its own evidence and authority.', group: -1 },
  evidence_invalid: { title: 'Current validation cannot be confirmed', description: 'A receipt or its bindings changed or is unavailable. The retained evidence requires review; no automatic rerun has started.', group: -1 },
  historical_unconfirmed: { title: 'Historical validation retained · Current applicability unconfirmed', description: 'The receipt belongs to its recorded implementation. This is not a revalidation under the current version.', group: -1 },
  queued: { title: 'Waiting for the worker', description: 'Your files are saved. Processing starts when the current job finishes.', group: 0 },
  waiting_for_model: { title: 'Waiting for the model service', description: 'The investigation is saved. The worker will try again automatically when the service is available; you can still cancel this job.', group: -1 },
  inspecting: { title: 'Inspecting the uploaded files', description: 'Checking tables, fields and how the files relate to each other.', group: 0 },
  researching: { title: 'Checking source definitions', description: 'Reading source evidence to establish what the fields and counts mean.', group: 0 },
  preparing: { title: 'Preparing the data transformation', description: 'Building or revising the transformation for this source.', group: 1 },
  sample_running: { title: 'Testing a sample', description: 'Trying the transformation on a bounded sample before processing every record.', group: 2 },
  sample_qa: { title: 'Checking the sample result', description: 'Checking the sample against the source rules and investigating differences.', group: 2 },
  full_running: { title: 'Processing the complete dataset', description: 'Running the transformation over all admitted input records.', group: 3 },
  full_qa: { title: 'Checking the complete result', description: 'Reconciling counts, relationships and definitions before publication.', group: 3 },
  registering: { title: 'Saving the verified transformation', description: 'Recording the transformation and its evidence for reproducible future imports.', group: 4 },
  publishing: { title: 'Publishing the verified result', description: 'Adding this source to a new local release.', group: 4 },
  needs_input: { title: 'Waiting for specific information', description: 'The investigation is saved. Answer the question below or add the missing file to continue.', group: -1 },
  succeeded: { title: 'Published successfully', description: 'The verified source is saved in the recorded local release.', group: 4 },
  no_change: { title: 'The published data is already current', description: 'The checked input matches the existing publication; no replacement was needed.', group: 4 },
  cancelled: { title: 'Processing stopped', description: 'The saved investigation remains available. The published release has not changed.', group: -1 },
  failed: { title: 'Processing could not finish', description: 'Review the saved diagnostics below. The published release has not changed.', group: -1 },
};
const groups = ['Investigate', 'Prepare', 'Sample checks', 'Full checks', 'Publish'];
const stepStatus = (status: string) => ({ succeeded: 'Completed', running: 'In progress', failed: 'Needs revision', needs_evidence: 'More evidence needed', interrupted: 'Interrupted', paused: 'Waiting for information', cancelled: 'Stopped' })[status] || status.replaceAll('_', ' ');

export function ImportAgentProgress({ agent, systemBlocked = false }: { agent: LocalImportAgentStatus; systemBlocked?: boolean }) {
  const phase = agent.outcome?.attention ? {...agent.outcome.attention, group: -1} : (systemBlocked || (agent.blocker_summary?.engineering_count ?? 0) > 0) && agent.phase === 'needs_input'
    ? { title: 'Waiting for a system update', description: 'The files and investigation are saved. The required capability must be available before this import can continue.', group: -1 }
    : agent.phase === 'needs_input' && agent.investigation?.state === 'stalled'
    ? { title: 'Investigation needs review', description: 'Recent actions did not resolve the remaining checks. The investigation is saved for review before it continues.', group: -1 }
    : phases[agent.phase] || { title: 'Investigating this source', description: 'The worker is checking the evidence and recording its next steps.', group: 0 };
  const complete = ['succeeded', 'no_change', 'candidate_verified'].includes(agent.phase);
  const stopped = phase.group === -1;
  const outcome = agent.outcome;
  const candidateGoalsSatisfied = outcome?.task_mode === 'candidate_validation_only'
    && outcome.phase === 'candidate_verified' && outcome.terminal_for_task_mode === true
    && outcome.validation.receipt_status === 'verified_current' && outcome.goal_coverage.requested_goals_satisfied === true;
  return <section className={styles.agentProgress} aria-label="Automatic import progress">
    <div className={styles.progressTitle} aria-live="polite">{complete ? <CheckCircle2 size={21} /> : stopped ? <PauseCircle size={21} /> : <Loader2 size={21} className="spin" />}<div><h3>{phase.title}</h3><p>{phase.description}</p></div></div>
    <ol className={styles.phaseList} aria-label="Import stages">{groups.map((label, index) => <li key={label} aria-current={index === phase.group ? 'step' : undefined}>{label}</li>)}</ol>
    <dl className={styles.agentCounts}><div><dt>Investigation rounds</dt><dd>{agent.model_calls}</dd></div><div><dt>Actions started</dt><dd>{agent.tool_calls}</dd></div><div><dt>Automatic revisions</dt><dd>{agent.correction_count}</dd></div>{agent.checks && <><div><dt>Sample runs</dt><dd>{agent.checks.sample_runs}</dd></div><div><dt>Full-data runs</dt><dd>{agent.checks.full_runs}</dd></div><div><dt>Independent QA runs</dt><dd>{agent.checks.qa_checks}</dd></div></>}</dl>
    {outcome && <div aria-label="Candidate validation outcome">
      <p className={styles.note}>Counts: current attempt. Current QA result: {outcome.validation.check_count} checks recorded, {outcome.validation.checks_passed} passed.</p>
      {(outcome.counts.unknown_conversion_steps > 0 || outcome.counts.unknown_qa_steps > 0) && <p className={styles.note}>Historical subphase counts are unconfirmed: {outcome.counts.unknown_conversion_steps} conversion steps; {outcome.counts.unknown_qa_steps} QA steps. Known run counts above exclude these.</p>}
      <p className={styles.note}>Requested candidate goals: {outcome.goal_coverage.requested_goals_satisfied === true ? (outcome.goal_coverage.status || 'satisfied').replaceAll('_', ' ') : outcome.goal_coverage.requested_goals_satisfied === false ? 'not satisfied' : 'not confirmed'}.</p>
      <p className={styles.note}>Official identity: {outcome.official_identity.status.replaceAll('_', ' ')} · Publication: {outcome.publication.status.replaceAll('_', ' ')}.</p>
      {outcome.unverified_capabilities.includes('displayed_map') && <p className={styles.note}>Published queries / displayed map: not verified.</p>}
      {outcome.validation.reason && <p className={styles.note}>{outcome.validation.reason}</p>}
      {!outcome.active_blockers.length && <p className={styles.note}>No unresolved blockers in the current validation stage.</p>}
      {!!outcome.source_limits.length && <details><summary>Recorded source limitations ({outcome.source_limits.length})</summary><pre>{JSON.stringify(outcome.source_limits, null, 2)}</pre></details>}
      {!!outcome.historical_blockers.length && <details><summary>Historical issues · resolution and applicability ({outcome.historical_blockers.length})</summary><pre>{JSON.stringify(outcome.historical_blockers, null, 2)}</pre></details>}
    </div>}
    {agent.correction_count > 0 && <p className={styles.note}>The Agent has revised its work {agent.correction_count} {agent.correction_count === 1 ? 'time' : 'times'} as it checks the evidence. Each revised candidate must pass the required checks before publication.</p>}
    {agent.checks?.qa_passed !== undefined && <p className={styles.note} aria-label="Quality check outcomes">
      Independent QA runs: {agent.checks.qa_passed} passed, {agent.checks.qa_failed ?? 0} failed, {agent.checks.qa_blocked ?? 0} blocked, {agent.checks.qa_running ?? 0} running, {agent.checks.qa_interrupted ?? 0} stopped.
      {!!agent.checks.qa_unclassified && <> {agent.checks.qa_unclassified} have no verified outcome.</>}
    </p>}
    {agent.investigation && <div aria-label="Investigation progress">
      <p className={styles.note}>{agent.investigation.unresolved_count} unresolved scope checks · {agent.investigation.tools_without_progress} actions without verified progress.</p>
      {agent.investigation.last_progress_at && <p className={styles.note}>Last verified progress: <time dateTime={agent.investigation.last_progress_at}>{new Date(agent.investigation.last_progress_at).toLocaleTimeString()}</time></p>}
      {!complete && agent.investigation.state === 'replan' && <p className={styles.note}>The remaining checks need a different diagnostic approach. Reading more documents alone does not establish progress.</p>}
    </div>}
    {agent.blocker_summary && <div aria-label="Host blockers">
      <p className={styles.note}>{agent.blocker_summary.active_count ?? agent.blocker_summary.blockers.length} active blockers · {agent.blocker_summary.engineering_count} engineering blockers · {agent.blocker_summary.unmet_goals === null ? 'Goal coverage not evaluated' : `${agent.blocker_summary.unmet_goals.length} unmet goals`}.</p>
      {!!agent.blocker_summary.unmet_goals?.length && <p className={styles.note}>{agent.blocker_summary.unmet_goals.join(', ')}</p>}
    </div>}
    {agent.repair && <div aria-label="Repair investigation">
      <p className={styles.note}><strong>Original goal:</strong> {agent.repair.original_goal}</p>
      {agent.repair.requested_context && <p className={styles.note}>{agent.repair.requested_context}</p>}
      {agent.repair.current_blocker && <p className={styles.note}><strong>Current blocker:</strong> {agent.repair.current_blocker}</p>}
      {agent.repair.route === 'engineering' && !complete && !outcome?.attention && <p className={styles.note}>The implementation needs an isolated engineering review and independent checks before it can be used for this import.</p>}
      {!agent.repair.target_satisfied && <p className={styles.note}>{candidateGoalsSatisfied
        ? 'The requested goals for this candidate validation are satisfied. The broader original goal remains unverified. Official identity and publication require separate verification and authorization.'
        : 'The original goal is not fully verified. A published limited result does not establish the remaining capabilities.'}</p>}
      {!!agent.repair.diagnostic_attempts.length && <ul aria-label="Diagnostic attempts">{agent.repair.diagnostic_attempts.map((attempt, index) => <li key={index}>{attempt.purpose.replaceAll('_', ' ')} · {stepStatus(attempt.status)}</li>)}</ul>}
      {!!agent.repair.limitations.length && <ul aria-label="Remaining limitations">{agent.repair.limitations.map((limit, index) => <li key={index}>{limit}</li>)}</ul>}
    </div>}
    {!!agent.latest_steps.length && <ol className={styles.recentSteps} aria-label="Recent automatic actions">{agent.latest_steps.map((step, index) => <li key={`${step.at}-${index}`}><div><span>{step.summary}</span><small>{stepStatus(step.status)}</small></div><time dateTime={step.at}>{new Date(step.at).toLocaleTimeString()}</time></li>)}</ol>}
    <p className={styles.note}>These are recorded worker actions. Stages can repeat when a check calls for a revision.</p>
  </section>;
}
