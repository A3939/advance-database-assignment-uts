# Agent foundations and task-based model routing

Implemented locally on 1 October 2026. This is the preparation phase for replacing
the generic agent runtime with Codex; it does not switch the import worker to Codex.

## Model selection

The human-selected models are `gpt-5.6-terra` and `gpt-6.1-sol`, both with `high`
reasoning. `src/server/agent/model-routing.ts` makes a deterministic server-side
selection, without an extra model call:

| Task | Model |
| --- | --- |
| Short greeting, definition, single-source count or lookup | GPT-5.6 Terra |
| Comparison, calculation, explanation, multi-source or follow-up question | GPT-6.1 Sol |
| Studio persistent research | GPT-6.1 Sol |
| Imports schema assistance and new autonomous source onboarding | GPT-6.1 Sol |
| Unknown/ambiguous intent | GPT-6.1 Sol |
| Exact known native data processing, QA, publication | Deterministic Python/PostgreSQL; no model needed |

This first router uses conservative Chinese/English rules. It cannot guarantee
perfect difficulty classification, and the live two-question smoke test is not a
routing accuracy benchmark. There is no automatic model fallback or mid-session
Terra-to-Sol escalation. Generic `OPENAI_MODEL` no longer overrides the task router.

Ask AI, Studio and schema assistance write routing decisions and actual provider
usage receipts to private `artifacts/model-routing/*.jsonl`, excluding prompts,
keys and raw source rows. Missing usage is unknown, never zero. Ask AI and Studio
retain their existing 12-round/16-tool ceilings and 240-second overall timeout;
the per-response output allowance is now 12,000 tokens for high reasoning. The
Imports limits below are separate.

## Import experiments and limits

`arsia_pipeline/profiles/agent-policies.json` is the host-owned catalog, consumed by
Python and the Next model gateway. The runtime's `agent_profile` selects the
profile for a NEW session. The session saves the exact policy and catalog hash;
resume cannot silently change the model or reset consumed budgets. Pre-existing
sessions retain the baseline. Changing a pinned catalog fails closed instead of
silently mixing experiment settings. A changed experiment should start a fresh
session with the same immutable inputs.

| Setting | Historical baseline-v1 | New expanded-v1 |
| --- | --- | --- |
| Model / reasoning | gpt-6-luna / medium | gpt-6.1-sol / high |
| Model calls | 80 | 120 |
| Tool calls | 120 | 200 |
| Corrections | 24 | 40 |
| Cumulative active time | 3,600 s | 7,200 s |
| Cumulative sandbox time | 2,400 s | 2,400 s |
| Model request timeout | 240 s | 600 s |
| Model output tokens | 12,000 | 24,000 |
| Context compaction threshold | 55 KB | 180 KB |
| Compacted context bound | 60 KB | 240 KB |
| Investigation memory | 25 KB | 80 KB |

The context values are bytes, not tokens, and exclude the separately supplied
system/SDK instructions. Single sandbox execution limits and independent QA have
not been loosened. Final-permitted-response tools still execute; request N+1 is
never permitted.

Expanded sessions warn after 20 tool operations without new measurable evidence
and stop after 40. New complete profiles, relation measurements, exact citation
spans, downloaded content hashes, newly passing QA checks and first sample/full
QA stages count as progress. Edits, repeated reads and passing the same sample
again do not reset the allowance. This is progress-aware continuation WITHIN a
fixed ceiling, not an automatic unlimited quota extension.

Operational stops have distinct codes: `budget_exhausted`, `agent_stalled`, and
`model_unavailable`. They do not manufacture questions asking users for missing
source data. Actual missing source evidence uses `evidence_needed`. Permanent
provider errors (such as unknown model/authorization errors) stop after one
request without fallback; transient failures retain bounded retry behavior.

## Evidence survives compaction and recovery

- Sample QA success cannot clear a full QA or full-run preflight failure.
- Diagnostics distinguish sample/full execution and validation failures.
- Full success must match the current code/contract and attempt to clear failures.
- Corrections leave failed gates marked as requiring fresh validation.
- Deep CRS evidence IDs and quotations are not destroyed by depth truncation.
- `read_task_state` pages the complete current contract, unresolved diagnostics or
  an exact durable tool result. Step access is bound to the owning session.
- Large compact excerpts point to the exact saved step rather than pretending
  omitted evidence has been resolved. Model-response steps cannot be read by this tool.

## Codex handoff preparation

`tools/prepare_codex_task.py` exports a saved session using a read-only database
transaction. It does NOT instantiate/resume the AgentSession. Example:

```sh
.venv/bin/python tools/prepare_codex_task.py --job-id JOB_UUID \
  --output /absolute/path/to/ARSIA/artifacts/autonomous-imports/FRESH_HANDOFF
```

The fresh task directory contains the exact contract, adapter, complete unresolved
diagnostics, tool results, registered source document text, SDK and an integrity
manifest. `proposals/` is separate. Source data, DB credentials and personal Codex
auth are not copied. `admit_proposal` remains a host-worker operation and reuses
normal contract validation and gate invalidation; proposal files cannot publish.

The control directory pins the supplied Codex 0.159.3 binary/version/SHA256,
selects Sol/high and creates an independent Codex config with only the read-only
ARSIA evidence MCP. Preflight checks the actual CLI MCP configuration without
inference. The stdio MCP lists indexed files and supports hash-checked paginated
reads. Traversal, symlinks, hardlinks and changed evidence are rejected.

**This export is a handoff format, not an OS sandbox.** Its `execution_ready` is
false. Host filesystem read restrictions, a task-scoped bridge to the live worker,
cancellation, durable Codex event/usage accounting and process recovery still
need implementation/acceptance before Codex owns an import. The Mac bundle is not
a Linux server runtime. No personal `auth.json` is shared.

## Validation and remaining work

See the local checkpoint linked from `artifacts/autonomous-imports/
agent-foundations-20261001T073825Z/README.md` for actual results and token receipts.
Tests cover full-versus-sample QA, deep evidence, >8 reads plus compaction/resume,
cross-session rejection, policy persistence, progress/no-progress behavior,
workspace integrity and MCP requests. Live checks cover actual Terra and Sol
read-only data answers and one Sol/high Imports protocol request.

These checks do not establish full SA onboarding success under the new model,
TAS acceptance, Codex crash recovery or deployment readiness. The earlier SA
strict-QA issue and existing needs_input jobs are preserved. A future full
comparison must distinguish model, budget and harness changes; existing failures
must not be relabelled as passing or overwritten.

Official references checked: [model catalog](https://developers.openai.com/api/docs/models/all),
[non-interactive Codex](https://learn.chatgpt.com/docs/non-interactive-mode),
[MCP client configuration](https://learn.chatgpt.com/docs/extend/mcp).
