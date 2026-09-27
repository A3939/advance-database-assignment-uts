# B09: manifest and FP1

**The installed S0/S8 build inventory is available; final platform freezing remains separate.** [B's installed build](full-build-integration.md) uses E's real FP1/publication and hashes all current build components in `config/build-inventory.json`. The [S8 guide](s8-integration.md) records the four-source extension and its validation.

[`manifest.py`](../src/arsia_ingest/manifest.py) follows team v1.1: 04 §2 for L1/FP1, 04 §3 for QA, 05 §5 for source contracts, and 02 for frozen fields. The wrappers below are B's transport format; the tested SQL binding is documented in the [build guide](full-build-integration.md).

## Inputs and checks

The eight root members are `contract_version`, `dataset_kind`, `analysis`, `sources`, `files`, `rules`, `required_checks` and `provenance`.

`build_manifest` reuses a completed intake run's metadata, archive references and filenames. It streams archive/JSONL hash checks; B08 checks the record stream during loading. Each source needs its complete resource set, one file and contract per resource, and explicit display fields and release label/scope. No state or resource count is fixed.

Analysis years are inclusive integers, defaulting to 2020–2024. IDs use the `official_`/`syn_` namespaces. Provenance adds the recorded finish time, preparer, download URLs and evidence references. Synthetic downloads may be null if the evidence identifies the fixture; official inputs need direct download URLs. Host paths are omitted.

Use `read_json(path)` for supplied JSON. Duplicate keys/list identities, invalid versions, unknown root fields and floating-point values are rejected. Write fractional configuration values as decimal strings.

## Rules format

`rules` contains the following six members:

| Member | Required content |
|---|---|
| `contracts` | Entries `{id, version, status, mapping_ids, content}`. ID equals the resource ID; status is `confirmed` for official or `synthetic_defined` for synthetic. The adopted VIC profile alone uses `restricted`, with full-source confirmation still false. |
| Contract `content` | `input`: exact 13-field file object. `identity`: key, explicit parent (possibly null), release label/scope/resource IDs, coverage, bundle basis, scope filter. `semantics`: full rules, `severity_codes`, `severity_definition_version`. `snapshot`: policy and change statement (null for baseline). `confirmation`: status and evidence. |
| Official confirmation | Also requires `owner`, `reviewed_by` (C), `licence`, ISO `checked_at`, nonempty `references`, and `unresolved` issues with dispositions. These are supplied review records. |
| `mappings` | Entries `{id, version, content}` with full mapping objects; IDs must exactly match contract references. |
| `severity` | Entries with `source_id`, `severity_code`, `severity_label`, `definition_version`, `definition_text`, `is_fatal_crash` (boolean/null). Include unused categories and `__MISSING__`; codes/version must match each source's declaration. |
| `qa_contract` | `{id: "team_qa", version, content: {text: ...}}`: full 04 §3 for `team-v1.1`; full section plus the adopted VIC addendum for `team-v1.1-vic-r1`. |
| `code_files`, `schema_files` | Lists of `{path, sha256}` from actual project files. |

[`qa-team-v1.1.json`](../config/qa-team-v1.1.json) includes the unchanged English QA section for standalone clones. `team_qa_contract(path)` also extracts either language from the handoff. Known section hashes reject excerpts or edits; they check protocol content, not FP1. Changes need an agreed version update.

For the adopted VIC policy, use `vic_restricted_definitions()` from `arsia_ingest.vic_restricted`. It freezes the full case register, restrictions, unresolved definitions, native severity and QA amendment. The exact four file identities and 2020–2024 scope are enforced. See [VIC input support](vic-restricted-inputs.md) for the API and remaining integration.

All seven `required_checks` remain ordered, from `QA01_INPUT` to `QA07_LOCATION`. B09 writes no QA results. Source semantics, compatibility and snapshot reductions remain checks for the responsible modules.

## Build inventory

Supply `{components, schema_files}`. Each component maps to a nonempty list of project-relative paths:

```text
intake, raw, runner, project, vault, canonical, dw,
qa, publish, analysis, fp1
```

Include helpers, dependencies and configuration used by these operations. Components may share paths; additional components are allowed. `schema_files` lists A's actual migrations. Every file must exist. Absolute/traversal paths, symlinks, LFS pointers, documentation, tests, evidence and raw/output directories are rejected.

B hashes the supplied files; authors must identify every file their modules use. These digests freeze the code/structure versions. Missing files cannot be replaced by placeholder digests or old reference SQL.

[D02 is installed in B](d02-integration.md). Its [inventory fragment](../config/d02-inventory.json) records the relocated code and hashes. That fragment covers dimensions only. The combined C/D inventory now includes D03 facts and D04 reconciliation.

The [A/C integration fragment](../config/ac-inventory.json) adds real C03/A06/C09 bindings, packaged SQL, B interface dependencies and A migrations 001–011. It remains a partial inventory; see the [tested scope and remaining modules](ac-integration.md).

The [D05–D08 analysis fragment](../config/analysis-inventory.json) adds the installed query APIs and SQL. It has real S0 reader tests; see [analysis integration](analysis-integration.md). It is not a final platform inventory and does not include D09.

## Using S0 and S8

Definitions can be read now without a database:

```python
from arsia_ingest.manifest import read_json, s0_definitions

contract_path = "tests/fixtures/s0/contract.json"
definitions = s0_definitions(contract_path)
qa = read_json("config/qa-team-v1.1.json")
```

The helper reuses B07's labels, keys, mappings, coverage, counts, snapshot rules and fictional classification. For a generated variant, pass its `contract.json`; intake files must match. This does not approve official data.

For [AT15's S8 extension](s8-inputs.md), set `contract_path` to `tests/fixtures/s8/contract.json` or `tests/fixtures/s8-bad-key/contract.json`. A resource may supply its own `fixture_version`, `coverage`, complete `common_rules` and `confirmation_basis`; otherwise the S0 defaults apply. This adds S8 without changing the original seven frozen definitions. The helper still needs the team's actual inventory to produce a build manifest.

For a complete synthetic build request, use `arsia_ingest.build.s0_request()` or `s8_request()` with the matching prepared inputs. `synthetic_request()` accepts an explicit contract path for generated variants. These helpers check the installed build inventory and call the real `FrozenManifest` constructor; see [S8 integration](s8-integration.md).

For direct manifest assembly, pass the checked `inventory` and the `run_dir` returned by native preparation:

```python
from pathlib import Path
from arsia_ingest.manifest import build_manifest

origins = {
    contract["id"]: {
        "download_url": None,
        "evidence_ref": contract_path,
    }
    for contract in definitions["contracts"]
}
frozen = build_manifest(
    run_dir, **definitions, qa_contract=qa,
    inventory=inventory, project_root=Path.cwd(),
    prepared_by="Role B", origins=origins,
)
frozen.write("artifacts/synthetic/manifests/s0-build-001.json")
```

The S0/S8 build inventory is shipped; it excludes the remaining D09 and official/platform acceptance scope. Missing inputs stop assembly. Choose a new filename for each snapshot; writes are atomic and never replace history. A provides database history protection.

`FrozenManifest.as_dict()` returns a fresh copy for each consumer. D reads frozen sources, severity and years; all modules share the contracts/mappings. `freeze_manifest(value, project_root=..., inventory=...)` checks an assembled object against actual files.

FP1 input excludes provenance. Identity lists, mapping references, resource IDs and declared severity-code sets are sorted. Headers, key components and transformation arrays keep their order. Object-key order, archive relocation and preparer changes leave the SQL input unchanged. Changed code or rules require a new snapshot.

## FP1 boundary

[`fingerprint.py`](../src/arsia_ingest/fingerprint.py) provides:

```python
from arsia_ingest.fingerprint import FP1Operation, fingerprint

# Supplied by E, using the agreed A/E environment.
operation = FP1Operation(
    schema=schema, name=function_name, implementation_version=sql_version,
    postgres_version_num=pg_version, code_path=sql_path,
)
input_fingerprint = fingerprint(connection, frozen, operation, project_root=Path.cwd())
```

The proposed signature accepts one `jsonb` and returns one `text`. There is no default function; omitting it raises `FP1_UNAVAILABLE`. The adapter checks the SQL file digest, exact PostgreSQL 16 patch, UTF8, UTC, installed signature and EXECUTE permission. It binds normalized JSON as a parameter and accepts only 64 lowercase hexadecimal characters.

Python does not hash manifest JSON. Only cursors are opened on the caller's `autocommit=False` connection; commit, rollback and close belong to the caller. Local SQL bytes and a declared version cannot verify the installed implementation. A/E must provide deployment evidence and real FP1 tests. A different E signature requires an explicit adapter change.

## Validation and remaining inputs

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
```

The [initial receipt](evidence/b09-validation-2026-09-19.json) records 302 passed and 8 skipped. The [test supplement](evidence/b09-validation-2026-09-19-supplement.json) records 306 passed and 8 skipped after adding snapshot variants and assembled-manifest adapter tests. The old receipt is unchanged. Tests use small S0 files, temporary code inventories and scripted SQL replies; they do not verify PostgreSQL, real FP1, durable writes or `no_change`.

Still needed:

- **E/B:** FP1/publication are integrated and exercised in the S0 runner. E still owns the independent acceptance comparison.
- **A:** fixed migrations 001–011 are integrated and hashed in the A/C fragment. The shared deployment must use those same bytes and grants.
- **Module authors:** actual code inventory and versioned contracts/mappings. Official draft contracts are blocked.

On 2026-09-19, inspected remote branches had no E03 SQL. `setup` specified PostgreSQL 15; `yihua-zhang` contained a draft QLD review. The old `docs/phase1-design-lite` fingerprint is `reference_unexecuted` and includes provenance in its input. These were neither adopted nor changed.
