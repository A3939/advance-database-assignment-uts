# First main integration

## Scope and history

This PR brings the integrated B runtime into `main`. It starts from
`peixian/dev` at `37c6b134c6e3e5d5445008e2df4722b09849a164` and merges
`main` at `addc15118be8875d3eac62473dd95cbc35145bcf` using a merge commit.
Main's only separate commit has the same files as the common ancestor.
The merge therefore keeps B's file tree without dropping main's history.

The added runtime covers A's fixed schema and Vault loader, B's intake,
manifest, QA and runner, C's projections and QA, D02–D11, E's FP1/publication,
and the team Docker package. Original A/C/D/E commits and authors remain in
Git. Peixian wrote B and added the recorded cross-role fixes, integration,
packaging and validation. Importing a module does not make it B's original work.

Beyond the existing B version, this PR changes documentation only. It does not
change runtime code, dependencies, migrations, package resources, Compose or
inventory bytes. Member and task branches are retained. Use a merge commit for
the final PR merge so their history remains visible.

## Start and read the evidence

Use the [team Docker guide](team-docker.md) for setup, S0, the real D09 page,
separate acceptance, recovery and cleanup. Select a full reviewed commit, set
`ARSIA_REVISION` to that commit and prepare its Git proof before building.
For a replay of this PR, use its reviewed head; after merging, use the full
merge commit. A different revision needs its own prepared proof and receipt.

Historical results keep their original tested versions:

| Evidence | Actual version and scope |
|---|---|
| [Official B build](official-build.md) | `d5239db471e33ce30c137e9087f712c14cc6cea0`: eight full-snapshot PostgreSQL checks. |
| E PR #50 | Runtime `1765269507d7cf0b9cb76eef7b9ccf97de7f1cc5`: synthetic, recovery and official acceptance. Its root handoff remains on E's branch; Docker already vendors the required checks. |
| [Docker receipt](evidence/team-docker-2026-09-29.json) | `f9d22c698e2a47559923179da3c76fd7d53b13a6`: 501 checks on native ARM64 and emulated AMD64; 1,072 default checks with 402 optional skips on ARM64. |
| [Yihua's independent replay](https://github.com/A3939/advance-database-assignment-uts/pull/52#issuecomment-5873642661) | The same `f9d22c6` implementation: Windows x64 / WSL2, Linux AMD64 containers without cross-architecture emulation; 501 passed, no failures or skips. This is a verification comment, not an Approved review. |
| [Revision-check fix](evidence/team-docker-revision-fix-2026-09-29.json) | `d4530455944e5ac393440b456b77758c6658962a`: 63 focused tests and 11 real Docker build checks. ARM64 and emulated AMD64 images built. No completed full acceptance or Windows PowerShell run for this fix. |

This PR checks history, file preservation, inventory and Docker source hashes,
entry links, versions and Compose configuration. It does not rerun the full
pipeline or the official inputs. The [integration receipt](evidence/main-integration-2026-09-30.json)
records this review scope separately from those runtime results.

VIC remains restricted to the recorded source review and policy. Official
reports stay source-specific; official maps and VIC/QLD unit-detail reports
remain unavailable. Local publication is not publisher approval or a public
release. Teacher confirmation, final report, video and actual signed meeting
records remain team work. Historical `final_platform_accepted` and human
sign-off fields are not rewritten.

## Separate follow-up deliveries

### A07 and A08 — JJ, with B integration review

A07 commit `c48378eb17f7510e4a0d911fef580dca80023a24` adds the append-only
history test and its evidence. Apply that small change separately, preserving
JJ's author, then run the affected test against private PostgreSQL.

A08 commit `c1ded1163dbd54b25178a376a059dc75f95f5557` has six missing files:
the input config, NSW model guide, query SQL, replay tool, test and recorded
result. Bring these in together in a small delivery PR. Check input identities,
paths and the test; new query execution should get a new receipt. The missing
files do not mean the NSW runtime projection is missing from B.

### A09 / PR #32 — JJ and B

The latest head is `8f91a6b41dc0777d5873d2151f71e9f1cbe05501`.
Its `tools/verify_a01_lifecycle.py` selects root `compose.yaml` but writes only
`ARSIA_DB_PASSWORD` and `ARSIA_DB_PORT` into its temporary env file. The
integrated Compose also requires `ARSIA_REVISION`, `ARSIA_LOADER_PASSWORD`,
`ARSIA_READER_PASSWORD` and `ARSIA_EXECUTOR`. With a clean environment,
`docker compose config --quiet` rejects that input because required values are
missing; the first reported variable can depend on Compose traversal order.
Separate omission checks reject each of the four missing values. Resolving the
README conflict alone is insufficient.

Adapt the lifecycle script to the integrated Compose and explicit private test
settings. Check the separate daily and acceptance project names. Run startup,
stop/start, restart, retained-volume recreation and cleanup using only its own
resources. Keep A03 loader/reader permissions. Review the `requirements-db.txt`
merge, refresh every affected inventory hash, and repeat affected installation
and lifecycle checks. Existing A-only evidence is not evidence for that change.

### C11 — Serenity, with B delivery review

C head `93158311db8561f3b86fd92c260265aaf04ec5ff` still contains four
uncollected delivery files:

- `sql/evidence/c11_vic_source_model_queries.sql`
- `tools/replay_c11_postgres.py`
- `docs/role-c/c11-vic-source-model-and-query-evidence.md`
- `docs/role-c/c11-validation.json`

The tool expects root `config/c06-vic-r1.json`; B already has the same config
under `src/arsia_c/config/`. Resolve that path explicitly before running it.
Bring in the model, query tool and evidence together. The relevant VIC native
reader/model/Raw loader code already matches C; this is a missing delivery,
not a missing VIC pipeline. Keep B's later S8/AT10 fixes and VIC restrictions.
Do not merge the whole C branch over the integrated runtime.

### D — Yihua

The latest `yihua/dev` head is `09a7d5b7c0fe3d639b0bf544f51fa9b6bacc9889`.
A merge simulation adds no file changes to B. D09–D11 and their evidence are
already present, so no duplicate import is needed for this stage.

### E — Aditya, with B acceptance review

PR #50 is merged into E at `eba079a59ab7eb41835ee044c12e45dbdca03e9b`.
Docker already contains its required checks, configs and isolated database
runner in `docker/team/vendor/e/`. A separate small PR can collect the missing
root verifier/summarizer, summary test and `docs/role-e-acceptance/` handoff.
Reuse the vendored files rather than adding a second copy without a reason.
Keep the original runtime `1765269` and receipt unchanged. Any verification of
new main code must record its actual version and results.

`aditya/development` at `5ec0a9f0fd8eb2be5a5943c1f3e8aec4e8ab644c` adds
optional UI and developer tooling beyond B. Ten inventories still contain an
old `pyproject.toml` hash. Review those features separately, correct all affected
hashes and test the wheel resources, UI and Docker changes before integration.
Those optional features are not included here.
