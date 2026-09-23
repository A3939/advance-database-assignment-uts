# VIC source observations: 23 September 2026

This code-delivery index accompanies the preserved source observations. It is
not the original investigation README or a new execution receipt. The original
README and generated validation records remain in the team's retained archive.

## Included material

- `evidence/local-review.json`: observations from the pinned four-file scan.
- `evidence/api-replay.json`, `api-extra.json`, `api-types.json`: saved public
  response bodies and request metadata.
- `evidence/api-comparison.json`: comparisons with the saved native inputs.
- `evidence/source-retrieval.json`: dictionary/metadata retrievals, including
  failed requests retained as such.
- `basis/`: metadata and historical team-contract snapshots.
- `collect.py`: the original collection source.
- `check_evidence.py`: the offline checker, updated to use explicit UTF-8 for text input and output.

Source JSON and contract snapshots retain their original bytes and timestamps. 
Source observations are not development regression reports, and are not proof of publisher
approval, compatible export scope or complete platform acceptance.

## Records held separately

The original `evidence/cross-check.json`, `evidence/validation.json` and
`evidence/pytest.xml` are generated verification records and are not included.
Their original paths, sizes and hashes are listed in
[the source index](../../../../role-c/c02-evidence-index.json). The unchanged
VIC policy still cites them. B/E must obtain the originals from the retained
team archive before running newer B's `check_profile_evidence`; that function
requires those exact bytes in the recorded repository paths. Newly generated
reports cannot substitute for the frozen originals.

## Offline reproduction

From the Git repository root, using the active Python environment and pinned
originals configured in `config/native-inputs.json`:

```sh
mkdir -p .local
python docs/sources/evidence/vic/followup-2026-09-23/check_evidence.py --repo . --evidence docs/sources/evidence/vic/followup-2026-09-23/evidence --output .local/c02-source-check-new.json
```

Choose a fresh output name. This reads the saved source observations and
original CSVs; it does not need the omitted generated reports or contact the
publisher. It does require the base repository's source-review tools/history.
`collect.py` performs live retrievals and is not needed for offline reproduction.
New responses may differ from the stored snapshot.

Links inside frozen `basis/team-04-v1.1.md` and `team-05-v1.1.md` retain the
original team folder context. Use the current C02/C06 guides for navigation.
