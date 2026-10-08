/** Local ingestion transport; admitted publications enter the release-scoped data provider. */
export type LocalImportStatus =
  | "uploading" | "queued" | "profiling" | "needs_input" | "processing"
  | "validating" | "publishing" | "succeeded" | "no_change" | "failed"
  | "cancel_requested" | "cancelled" | "recovering";
export interface LocalImportFile {
  id: string; name: string; size: number; sha256: string; role?: string; format?: string;
}
export interface LocalImportQA {
  code: string; status: "pass" | "limited" | "block"; message: string;
  metrics?: Record<string, unknown>;
}
export interface ImportOutcome {
  version: 'import-outcome-v1'; task_mode: string; phase: string; terminal_for_task_mode: boolean;
  execution: {status: string; raw_exit_code: number | null};
  validation: {status: string; receipt_status: string; reason?: string | null; scope: string; revision?: string | null; qa_run_count: number; check_count: number; checks_passed: number};
  goal_coverage: {status?: string; requested_goals_satisfied: boolean | null; original_goal_satisfied: boolean; [key: string]: unknown};
  attention?: {kind: string; title: string; description: string; review_required: boolean} | null;
  publication: {status: string}; official_identity: {status: string};
  active_blockers: {id: string; code: string; category: string; owner: string; message: string; status: string}[];
  historical_blockers: Record<string, unknown>[];
  actions: Record<'add_files' | 'submit' | 'retry' | 'cancel' | 'view_evidence', boolean>;
  action_reasons: Record<string, string | null>;
  counts: {scope: string; full_runs: number; sample_runs: number; qa_checks: number; unknown_conversion_steps: number; unknown_qa_steps: number};
  source_limits: unknown[]; limitations: string[]; unverified_capabilities: string[];
}
export function importAction(job: LocalImportJob, action: keyof ImportOutcome['actions']): boolean {
  if (job.outcome) return job.outcome.actions[action];
  // Read compatibility only for an older backend without the versioned contract.
  if (action === 'view_evidence') return true;
  if (action === 'retry') return ['failed', 'cancelled'].includes(job.status);
  if (action === 'cancel') return !IMPORT_TERMINAL.has(job.status) && !['publishing', 'cancel_requested'].includes(job.status);
  return IMPORT_EDITABLE.has(job.status);
}
/** Presentation only: host permissions remain authoritative; review precedes a new run. */
export function importSuggestedAction(job: LocalImportJob, action: keyof ImportOutcome['actions']): boolean {
  return importAction(job, action) && !(job.outcome?.attention?.review_required && ['add_files', 'submit', 'retry'].includes(action));
}
export function importOutcomeLabel(job: LocalImportJob): string {
  if (job.outcome?.attention) return job.outcome.attention.title;
  return ({candidate_verified: 'Verified · not published', candidate_partial: 'Partial candidate', engineering_required: 'System update required', publication_waiting: 'Awaiting publication conditions', evidence_invalid: 'Evidence needs review', historical_unconfirmed: 'Historical validation · needs review'} as Record<string,string>)[job.outcome?.phase ?? ''] ?? job.status.replaceAll('_', ' ');
}
export interface LocalImportAgentStatus {
  outcome?: ImportOutcome;
  status: string;
  phase: string;
  model_calls: number;
  tool_calls: number;
  correction_count: number;
  blocker_summary?: { active_count?: number; historical_count?: number; scope_issue_count: number | null; engineering_count: number; blockers: {code: string; owner: string}[]; unmet_goals: string[] | null; goal_satisfied: boolean | null; count_scope: string };
  investigation?: { version: string; state: 'continuing' | 'replan' | 'stalled'; meaningful_events: number;
    tools_without_progress: number; unresolved_count: number; last_progress_at: string | null } | null;
  repair?: { original_goal: string; requested_context: string; target_satisfied: boolean;
    current_blocker?: string | null; route?: string; operation?: string;
    diagnostic_attempts: { purpose: string; status: string }[]; limitations: string[] } | null;
  checks?: { sample_runs: number; full_runs: number; qa_checks: number;
    qa_passed?: number; qa_failed?: number; qa_blocked?: number;
    qa_running?: number; qa_interrupted?: number; qa_unclassified?: number };
  latest_steps: { kind: string; phase: string; status: string; summary: string; at: string }[];
}
export interface LocalImportJob {
  outcome?: ImportOutcome;
  id: string; label: string; status: LocalImportStatus; stage: string; message: string;
  created_at: string; updated_at: string; files: LocalImportFile[];
  events: { at: string; stage: string; message: string }[];
  source_id?: string; profile_id?: string; batch_id?: string; release_id?: string;
  result?: Record<string, unknown> | null; qa?: LocalImportQA[];
  questions?: (string | { message?: string; question?: string; [key: string]: unknown })[];
  error?: string | { code?: string; message: string; details?: unknown } | null; attempt: number;
  agent?: LocalImportAgentStatus | null;
}
export interface LocalImportHealth {
  status: string; mode: "local-test";
  worker: { alive: boolean; heartbeat_at: string | null; active_job_id: string | null };
  capabilities: unknown;
}
export interface LocalImportStorage {
  managed: boolean; measured_at?: string; measurement_scope: string;
  estimated?: boolean; truncated?: boolean; docker_bytes: number | null;
  shared_bytes?: number; exclusive_raw_bytes?: number; referenced_raw_bytes?: number;
  unregistered_bytes?: number | null; budget_bytes?: number;
  groups: Record<string, { logical_bytes: number; allocated_bytes: number; unknown_sizes: number; count: number }>;
  resources?: { id: string; kind: string; state: string; logical_bytes: number | null;
    allocated_bytes: number | null; retention_reason: string | null; restore_available: boolean }[];
}
export interface LocalImportSource {
  source_id: string; batch_id: string; job_id: string; summary: Record<string, unknown>;
  [key: string]: unknown;
}
export interface LocalImportCatalog {
  release_id: string | null; sources: LocalImportSource[];
}
export interface LocalImportAdvice {
  summary: string; questions: string[]; draft_profile: Record<string, unknown> | null;
  model: string; execution_allowed: false;
}
export const IMPORT_FILE_LIMIT = 512 * 1024 * 1024;
export const IMPORT_JOB_LIMIT = 1024 * 1024 * 1024;
export const IMPORT_FILE_COUNT = 12;
export const IMPORT_TERMINAL = new Set<LocalImportStatus>(["succeeded", "no_change", "failed", "cancelled"]);
export const IMPORT_EDITABLE = new Set<LocalImportStatus>(["uploading", "needs_input"]);

export function validateImportFiles(files: Pick<File, "name" | "size">[], existing: LocalImportFile[] = []) {
  if (!files.length) throw Error("Choose at least one data file or supporting document.");
  if (files.length + existing.length > IMPORT_FILE_COUNT) throw Error("A bundle can contain at most 12 files.");
  if (files.some(file => !file.size || file.size > IMPORT_FILE_LIMIT)) throw Error("Each file must be non-empty and at most 512 MiB.");
  if (files.reduce((n, file) => n + file.size, 0) + existing.reduce((n, file) => n + file.size, 0) > IMPORT_JOB_LIMIT)
    throw Error("A complete bundle can contain at most 1 GiB.");
  const names = [...existing.map(file => file.name), ...files.map(file => file.name)];
  if (new Set(names).size !== names.length) throw Error("Use unique filenames within a bundle; remove duplicate selections.");
  if (files.some(file => !/^[^/\\\x00-\x1f]{1,180}$/.test(file.name))) throw Error("Use filenames of 1–180 characters without directory separators.");
}
