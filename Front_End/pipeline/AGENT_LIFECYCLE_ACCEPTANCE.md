# Live Agent cancellation and worker-recovery acceptance

Status at the latest document review: live worker-loss execution remains pending. The main task observed actual SA Agent cancellation in about 0.6 seconds with the release unchanged; its receipt is artifacts/autonomous-imports/sa-active-cancellation.json. Three earlier confirmed watcher invocations retained receipts with injected=false and passed=false because the designated attempt or short sandbox ended before a safe trigger. These are safe non-injections, not successful recovery tests. The new opt-in controlled container hold is being verified and is not yet a live pass. Coordinate every interruption with the operator and never interrupt an unrelated acceptance job. Existing mock Agent and real native-worker tests cover different boundaries.

The independent generated-code repair test in tools/verify_real_model_recovery.py uses a disposable marked test database and intentionally injects one NameError. Keep that test separate from the following actual live-worker lifecycle tests.

## Preconditions and evidence

Wait for the main source acceptance work to finish and coordinate an explicit injection window with its operator. Use a fresh job and a byte-identical copy of an already accepted official source, such as the ACT upload. Supply only a source hint with its official dataset URL, never independent oracle values, generated code, or a preapproved mapping. Use the actual Next 3100 import endpoints, actual model gateway and real worker.

Before each case, verify the local database marker, expected private API socket, the configured worker PID's command and working directory, and that both the queue and active-job slot are empty. Reject if any unrelated job appears. Record only source/batch/release IDs, aggregate row counts, job/session/attempt IDs, input hashes, owner checks and UTC times. Keep credentials and full runtime configuration out of receipts.

Retain the current release's complete source-to-batch mapping. Validate the established native counts through the read-only database helper before and after the sequence. Write receipts below artifacts/imports-local/audits/ with mode 0600; include failed or timed-out assertions rather than discarding incomplete evidence.

## Case A: cancellation during a real model request

1. Upload the accepted source as a fresh job and submit normal autonomous options. Wait until a model step is actually persisted as running and the health endpoint names this exact job as active. Confirm this job has no running adapter container before injecting.
2. POST this job's cancel endpoint. Do not stop the API, database, model gateway or other jobs. Record request and terminal timestamps.
3. Require the job, attempt and Agent session to become cancelled; the running model/tool step must terminate with a cancellation/interruption result. Inspect call/output pairs and verify the checkpoint and earlier evidence remain readable. Record actual cancellation latency without inventing a threshold pass.
4. Require zero batches published by this job, the identical current release and full source mapping, and a healthy worker that returns to idle. Check that the cancelled session starts no further model/tool steps after terminal cancellation.

This proves local request cancellation and release safety. It does not prove that a remote model provider stopped computing after the local connection was closed.

## Case B: actual worker process loss and recovery

1. Use the operator-designated actual source job and its exact expected attempt. Automatic recovery is counted separately from manual retries and cancellation, so those activities do not pre-exhaust the crash allowance. Wait until saved actual code/contract starts a real labelled adapter container. A long investigation or fast execution can miss the trigger; report that honestly rather than inject at a different phase.
2. Re-read the worker PID and prove command/cwd ownership, the database instance marker, and this exact active job immediately before signalling. Require exactly one running adapter container for this job with a matching host receipt, exact attempt path and labels. Record the session ID, attempt number, checkpoint code/contract hashes, pending call IDs, cumulative model/tool/correction counts and active seconds.
3. Send SIGKILL to that one proven worker PID. In a finally path, invoke the owned lifecycle `dev up`; it preserves the database and existing API and launches a replacement worker. Never use global process matching, Docker prune, database reset, or stopping unrelated services. If ownership changes during validation, refuse the injection.
4. Require a distinct worker PID, the same durable job and Agent session, the designated attempt marked interrupted and its successor started. The interrupted running step must be marked interrupted. Earlier full transcript, exact input hashes, code and contract must remain available; cumulative budgets must not decrease or reset. Pending controlled calls must have paired results after recovery.
5. Require the resumed attempt to execute and independently validate a fresh sample, then run and validate full data, before registering or requesting publication. Prior-attempt QA must not authorize the resumed publication.
6. Wait for actual completion. A successful admission must affect only this source; every other source retains its prior batch. Reconcile actual canonical counts and foreign keys and compare the source's official oracle independently. If the same effective registered version is reused, require no_change and the same release. If the model proposes a genuinely different admitted version, record that distinction and do not report it as no-change acceptance. Any needs_input or failure remains a failed/incomplete end-to-end recovery acceptance, even if checkpoint recovery itself worked.

## Scoped sandbox-orphan recovery and designated watcher

The executor now writes an immutable mode-0600 host ownership receipt before container launch and supplies instance/job/attempt/run/receipt-hash labels. The receipt is outside the container mounts. Worker startup holds the verified database's global session lock, validates exact input/output mounts and the durable database attempt, then removes only an incomplete owned container by its immutable Docker ID before recovering or claiming work. Conflicting or missing ownership evidence blocks new work without deleting that container. Containers belonging to another marked database/project are ignored. Each removal retains its run evidence and writes a private audit.

Twenty-two offline ownership tests and a real isolated-test-database/container cleanup test passed. The real test launched only its own labelled container, held the test database lock, verified exact reaping and unchanged release, and retained input evidence. It did not kill the live worker.

The independently prepared tools/watch_owned_agent_recovery.py is restricted to an explicit --job-id and --expected-attempt. Its historical defaults refer to the first SA job and must not select a new test implicitly: the operator supplies the current actual job and attempt. Default invocation prints a dry description without database or Docker work. --confirm-owned-agent-interruption enables a 0.1-second watcher for that job's actual running sandbox. It checks private receipt, Docker labels/mounts, database marker, sole active job, worker PID/command/cwd/start identity, and receipt worker PID immediately before signalling. It never modifies an adapter, inserts a sleep, changes QA, submits a job or resets its counters.

The optional --hold-owned-container flag pauses only the immutable container ID that has already passed those ownership checks, stabilizing the short fault-injection window. This is a deliberate test fault, recorded as controlled_container_hold; it does not change adapter code or manufacture processing time. If SIGKILL is not injected, a finally path attempts to unpause that exact container and records the result. After a successful injection, the replacement worker must reap the paused orphan using its ordinary strict startup guard. Hold mode is under live validation; its implementation and offline checks do not establish end-to-end recovery.

After SIGKILL, a finally path runs only the owned dev up lifecycle. Acceptance requires a distinct worker, the exact container's startup-reaping audit (container absence alone is insufficient), the same Agent session with preserved cumulative counters, the injected attempt interrupted, and the following attempt performing fresh sample/full execution and independent QA before successful publication. If a candidate finishes before the final check, the watcher records the skipped candidate and continues within its original deadline; ended attempts and ownership conflicts do not authorize a signal.

Earlier non-injection receipts are retained under artifacts/imports-local/audits/: sa-real-worker-recovery.json, real-agent-worker-recovery-8056ec76-da6c-4bfd-afc4-3b7681e426ec-attempt-3.json, and sa-attempt3-worker-recovery-second-watch.json. Do not overwrite them with a later successful case or count them as injected failures.

This cleanup runs on worker startup; it is not a separate watchdog. If the operator or service manager never restarts a dead worker, host-enforced timeouts cannot stop a leftover sandbox by themselves. Continuous independent timeout enforcement remains a deployment limitation.

## Receipt assertions

The final receipt distinguishes actual invocation, trigger reached, fault injected, ownership checks, interruption evidence, budgets preserved, renewed QA, release/source retention and terminal outcome. Include gateway model_policy_sha256 and sdk_contract_sha256 from the real model steps. Preserve both pre- and post-recovery attempt evidence and exact observed counters. Never infer a live pass from the existing mock tests or the native recovery script.
