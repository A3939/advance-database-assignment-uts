/** Local, durable request coordination. No prompts, credentials or source rows. */
import { DatabaseSync } from 'node:sqlite';
import { mkdirSync, existsSync, lstatSync, chmodSync, openSync, closeSync } from 'node:fs';
import { join } from 'node:path';

export const MODEL_COORDINATION = { version: 1, concurrentRequests: 2, concurrentImports: 1 } as const;
export type Usage = { input_tokens: number; output_tokens: number; input_tokens_details?: { cached_tokens?: number } };
export const validModelUsage = (usage: Usage | undefined): usage is Usage => Boolean(usage && Number.isSafeInteger(usage.input_tokens) && usage.input_tokens >= 0 && Number.isSafeInteger(usage.output_tokens) && usage.output_tokens >= 0);
export class ModelBudgetError extends Error {
  status = 429;
  constructor(public code: 'MODEL_BUSY' | 'MODEL_TASK_LIMIT' | 'MODEL_USAGE_UNKNOWN', message: string) { super(message); if (code === 'MODEL_USAGE_UNKNOWN') this.status = 409; }
}
export type TaskBudget = { taskId: string; surface: string; maxRequests: number; requestTimeoutMs: number };
export const budgetRoot = () => join(process.cwd(), 'artifacts/model-routing');
const safeId = (value: string) => /^[A-Za-z0-9_.:-]{1,200}$/.test(value);
const taskLimits: Record<string, [number, number]> = {
  ask: [12, 240000], studio: [36, 240000], 'imports-assist': [2, 240000],
  'imports-agent': [120, 600000], 'imports-codex': [120, 600000],
};
export function taskBudget(surface: string, taskId: string): TaskBudget {
  const limits = taskLimits[surface];
  if (!limits || !safeId(taskId)) throw Error('Invalid local model task identity');
  return { taskId, surface, maxRequests: limits[0], requestTimeoutMs: limits[1] };
}
export class ModelBudget {
  db: DatabaseSync;
  constructor(root = budgetRoot(), readonly = false) {
    const path = join(root, 'usage.sqlite');
    if (!readonly) mkdirSync(root, { recursive: true, mode: 0o700 });
    if (lstatSync(root).isSymbolicLink() || existsSync(path) && (lstatSync(path).isSymbolicLink() || lstatSync(path).mode & 0o077))
      throw Error('Private local model ledger required');
    if (!readonly) {
      try { closeSync(openSync(path, "wx", 0o600)); } catch (error) { if ((error as NodeJS.ErrnoException).code !== "EEXIST") throw error; }
    }
    this.db = new DatabaseSync(path, { readOnly: readonly });
    this.db.exec('PRAGMA busy_timeout=5000');
    if (!readonly) {
      chmodSync(path, 0o600);
      this.db.exec(`CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,surface TEXT NOT NULL,max_requests INTEGER NOT NULL,timeout_ms INTEGER NOT NULL,created_at INTEGER NOT NULL,last_stop TEXT);
        CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY,task_id TEXT NOT NULL,started_at INTEGER NOT NULL,deadline INTEGER NOT NULL,status TEXT NOT NULL,input_tokens INTEGER,output_tokens INTEGER,cached_tokens INTEGER,finished_at INTEGER);
        CREATE INDEX IF NOT EXISTS request_task ON requests(task_id);
        CREATE INDEX IF NOT EXISTS request_active ON requests(status,deadline);`);
    }
  }
  close() { this.db.close(); }
  start(task: TaskBudget, id: string, now = Date.now()) {
    if (!safeId(id) || !safeId(task.taskId) || !taskLimits[task.surface] ||
        task.maxRequests !== taskLimits[task.surface][0] || task.requestTimeoutMs !== taskLimits[task.surface][1])
      throw Error('Invalid local model budget');
    let refusal: ModelBudgetError | undefined;
    this.db.exec('BEGIN IMMEDIATE');
    try {
      // A dead process retains its lease until the authoritative request wall
      // limit. Recovery never erases its request count or pretends usage is 0.
      this.db.prepare("UPDATE requests SET status='interrupted',finished_at=? WHERE status='pending' AND deadline<=?").run(now, now);
      this.db.prepare('INSERT OR IGNORE INTO tasks VALUES(?,?,?,?,?,NULL)').run(task.taskId, task.surface, task.maxRequests, task.requestTimeoutMs, now);
      const saved = this.db.prepare('SELECT surface,max_requests,timeout_ms FROM tasks WHERE id=?').get(task.taskId) as {surface:string;max_requests:number;timeout_ms:number};
      if (saved.surface !== task.surface || saved.max_requests !== task.maxRequests || saved.timeout_ms !== task.requestTimeoutMs)
        throw Error('A persisted task budget cannot be replaced');
      if (this.db.prepare('SELECT 1 FROM requests WHERE id=?').get(id)) throw Error('Model request identity was already used');
      const calls = (this.db.prepare('SELECT count(*) AS n FROM requests WHERE task_id=?').get(task.taskId) as {n:number}).n;
      const active = (this.db.prepare("SELECT count(*) AS n FROM requests WHERE status='pending'").get() as {n:number}).n;
      const imports = (this.db.prepare("SELECT count(*) AS n FROM requests r JOIN tasks t ON t.id=r.task_id WHERE r.status='pending' AND t.surface LIKE 'imports-%'").get() as {n:number}).n;
      // A new Studio run must not conceal an earlier ended request with unknown usage.
      // Active requests retain their normal concurrency lease; this gate applies after settlement or expiry.
      const unknownStudio = task.surface === 'studio' && Boolean(this.db.prepare("SELECT 1 FROM requests r JOIN tasks t ON t.id=r.task_id WHERE t.surface='studio' AND r.status!='pending' AND (r.input_tokens IS NULL OR r.output_tokens IS NULL) LIMIT 1").get());
      if (unknownStudio) refusal = new ModelBudgetError('MODEL_USAGE_UNKNOWN', 'Studio model usage is unknown for an earlier request. New Studio model calls are stopped until that receipt is reviewed; creating another study or retry does not clear it. Saved research and deterministic exports remain available.');
      else if (calls >= task.maxRequests) refusal = new ModelBudgetError('MODEL_TASK_LIMIT', 'This task reached its cumulative model request limit, including earlier attempts. Start a new task to use a new budget.');
      else if (active >= MODEL_COORDINATION.concurrentRequests || task.surface.startsWith('imports-') && imports >= MODEL_COORDINATION.concurrentImports)
        refusal = new ModelBudgetError('MODEL_BUSY', 'The shared local model service is busy. Wait for an active request to finish.');
      if (refusal) this.db.prepare('UPDATE tasks SET last_stop=? WHERE id=?').run(refusal.code, task.taskId);
      else this.db.prepare("INSERT INTO requests VALUES(?,?,?,?,'pending',NULL,NULL,NULL,NULL)").run(id, task.taskId, now, now + task.requestTimeoutMs);
      this.db.exec('COMMIT');
    } catch (error) { this.db.exec('ROLLBACK'); throw error; }
    if (refusal) throw refusal;
  }
  finish(taskId: string, id: string, status: string, usage?: Usage, now = Date.now()) {
    const valid = validModelUsage(usage);
    const cached = valid ? usage.input_tokens_details?.cached_tokens : undefined;
    this.db.prepare(`UPDATE requests SET status=?,input_tokens=?,output_tokens=?,cached_tokens=?,finished_at=?
      WHERE id=? AND task_id=? AND status IN ('pending','interrupted')`).run(
      ['completed','failed','cancelled'].includes(status) ? status : 'failed',
      valid ? usage.input_tokens : null, valid ? usage.output_tokens : null,
      valid && Number.isSafeInteger(cached) && cached! >= 0 && cached! <= usage.input_tokens ? cached! : null,
      now, id, taskId);
  }
  view(now = Date.now()) {
    const totals = this.db.prepare(`SELECT count(*) AS requests,
      coalesce(sum(status='pending' AND deadline>?),0) AS active,
      coalesce(sum(input_tokens),0) AS reportedInput,coalesce(sum(output_tokens),0) AS reportedOutput,
      coalesce(sum(cached_tokens),0) AS reportedCachedInput,
      coalesce(sum(input_tokens IS NULL OR output_tokens IS NULL),0) AS unknownRequests
      FROM requests`).get(now) as Record<string, number>;
    const tasks = this.db.prepare(`SELECT t.surface,t.max_requests AS maxRequests,t.timeout_ms AS requestTimeoutMs,t.last_stop AS lastStop,
      count(r.id) AS requests,coalesce(sum(r.input_tokens),0) AS reportedInput,coalesce(sum(r.output_tokens),0) AS reportedOutput,
      coalesce(sum(r.id IS NOT NULL AND (r.input_tokens IS NULL OR r.output_tokens IS NULL)),0) AS unknownRequests
      FROM tasks t LEFT JOIN requests r ON r.task_id=t.id GROUP BY t.id ORDER BY t.created_at DESC LIMIT 50`).all();
    return { policy: MODEL_COORDINATION, totals, tasks, tasksLimit:50,
      usageComplete: totals.unknownRequests === 0, tokenBudget: null,
      note:'Reported input includes cached input. No user-wide token budget is configured. Unknown requests are not zero usage. Earlier JSONL-only history is not backfilled.' };
  }
}
export function withModelBudget<T>(root: string, operation: (ledger: ModelBudget) => T): T {
  const ledger = new ModelBudget(root); try { return operation(ledger); } finally { ledger.close(); }
}

export function modelBudgetView(root = budgetRoot()) {
  if (!existsSync(join(root,'usage.sqlite'))) return {policy:MODEL_COORDINATION,
    totals:{requests:0,active:0,reportedInput:0,reportedOutput:0,reportedCachedInput:0,unknownRequests:0},tasks:[],tasksLimit:50,
    usageComplete:true,tokenBudget:null,note:'No requests have been recorded in the shared ledger. Earlier JSONL-only history is not backfilled.'};
  const ledger=new ModelBudget(root,true);try{return ledger.view();}finally{ledger.close();}
}
