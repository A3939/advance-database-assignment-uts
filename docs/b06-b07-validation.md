# B06 / B07 validation record

Recorded on 2026-09-17 using Python 3.12.6, openpyxl 3.1.5 and pytest 8.4.2.

## Checks run

Commands, run from the repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -q -p no:cacheprovider
.venv/bin/python -m arsia_ingest --config tests/fixtures/s0/config.json --output artifacts/s0-intake
```

All **146 tests passed** in 0.80 seconds: the original 123, 20 S0 tests and 3 VIC profiling tests. They use small files, without a full official JSONL export.

S0 tests read CSV/XLSX values back against 04's fixed sample, covering crashes, actual units, person references, exact Node coordinates and missing values. They compare these with L1 output, check repeatable file bytes and overwrite protection, and exercise all 14 variants. Missing files, bad headers and incorrect hashes fail preparation; business errors retain their values for SQL checks.

The CLI returned `prepared`: seven resources, 197 columns and 19 L1 records with six fields each. Run ID: `ff95726d-6d16-4cec-bd77-90f7e6c4c4cf`. The local [run.json](../artifacts/s0-intake/synthetic/runs/ff95726d-6d16-4cec-bd77-90f7e6c4c4cf/run.json) is excluded from Git. Other members can run the command above to create their own receipt.

The [VIC review](sources/vic-accident-vehicle.md) links to the scan and anomaly locations. Validation confirmed that the scan's script/configuration hashes match the files, all seven originals match the catalogue SHA256 values, and the saved API response matches its retrieval receipt.

The [validation receipt](evidence/b06-b07-validation-2026-09-17.json) stores command output, dependency versions, and input/code hashes. Full-input results remain in the 2026-09-15 record; that run was not repeated here.

## Current status

B07's native inputs are complete: use the shared [S0 files](../tests/fixtures/s0/) and [input guide](s0-inputs.md), generating variants as needed.

B06's findings are ready for C02 review. Unmatched nonempty vehicle references, declared count differences and an undocumented vehicle type block official approval. Original files and rules are unchanged; no rows or references were altered to remove findings.

E04's independent expected-result check is pending. Database Raw/Vault/Canonical/DW, QA63, FP1, transactions and publication were not tested here. The fixture's `test_status=NOT_RUN` refers to that later business acceptance.
