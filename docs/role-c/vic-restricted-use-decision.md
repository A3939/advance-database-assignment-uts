# VIC restricted-use decision

Profile: `vic-accident-only-2020-2024-v1`
QA contract: `team-v1.1-vic-r1`

The team adopts this decision under the C/E authority delegated through the
user on 23 September 2026. This records a project decision, not separate
teammate signatures or confirmation from the publisher. `team_use_approved=true`;
official definitions and compatible release remain unconfirmed.

The [frozen policy](../../config/vic-restricted-use-v1.json) identifies the four
original files, parser/locator versions, cases, evidence and restrictions.
[C02](c02-vic-person-node-review.md) explains the source findings. The earlier
draft and validation receipts remain historical records.

## Allowed results

Use one validated Accident row per original identity for VIC occurrence years
2020–2024. Retain all 72,170 accidents, including those with incomplete child
relationships. Allowed outputs are accident trends, severity counts, fatal
crash counts, fatalities and casualties. The Accident dictionary supports
severity `1/2/3/4`, `NO_PERSONS_KILLED`, and casualties as killed + seriously
injured + other injured. Missing components remain unknown; malformed core
values still block. Use the versioned definitions cited in B's source review.

Do not publish Person/Vehicle-derived KPIs, relationship statistics, Person/Vehicle category
metrics, VIC official map points or interstate totals under this profile.
These outputs are unavailable, not zero. Accident totals must not come from
child joins. All Raw rows and the full in-range unit projection remain;
VIC units have `count_eligible=false` and `definition_unconfirmed` notes.
Person remains Raw-only. Do not drop accidents or units to meet this policy.

Every report must show the profile/version, years and unavailable outputs.
This decision does not approve other states or cross-state comparability.

## Handling the findings

| Finding | Adopted treatment |
|---|---|
| 39 nonempty Person references without Vehicle targets | Preserve the original reference and Person. Only the exact registered cases qualify for restricted use; create no Vehicle and clear no ID. |
| Empty Vehicle ID, pedestrian role `1`, seating `NA` | Accept native empty string as a team-defined non-association for these fixed files. This is not a claim about official nullability. Preserve the 31 pedestrians with valid nonempty links. Whitespace-only or other tokens are not covered. |
| Unknown-role empty references | Retain the 24 registered cases, including six in scope, as unresolved associations. Do not infer non-association from seating or convert them to pedestrians. |
| Person and Vehicle count differences | Keep declared values and observed row counts separate. Comparing all Person rows is diagnostic; it does not establish export completeness. Keep both 2015 Person cases and all five Vehicle cases, including the three in scope. Never replace Accident counts or create missing detail. |
| Vehicle `21` / Person `16` | Preserve original codes/labels. Do not infer interchangeable categories or count eligibility. Full definitions remain unknown; affected output families are disabled. |
| Repeated Node observations | Preserve and check every observation. Never join raw Node into aggregate counts. Representative selection remains subject to all original validity, equivalence and CRS requirements. |
| Missing Node / unknown CRS | No VIC official map points. Canonical latitude, longitude, CRS and location-record ID are NULL; map eligibility is false. Keep candidate references and `no_location` or `crs_unconfirmed` reasons. |

The file hashes bound every treatment. The register binds exact unmatched
references, count cases and missing-location cases, including cases outside
the reporting years. Blank/category predicates also require their pinned file
and native token values. Counts alone never identify an exception.

## Contract amendment

For this profile only, this addendum supersedes the conflicting official
confirmation and known-anomaly blocking requirements in team 04 §§2–3 and
DEC04, and team 05 §§3–5. It does not alter the physical tables or the legacy
`team-v1.1` protocol. Full-source `bundle_confirmed` and `contract_confirmed`
stay false: neither a compatible full bundle nor unrestricted official use is
confirmed. Only `profile_approved` is true. These are deliberately different
expectations from legacy v1.1; do not alter an old result to match them.
Unresolved source questions stay recorded with dispositions.
These amendments apply only to `official_vic`; other sources keep their
existing requirements and receive no approval from this profile.

All checks retain `evaluated_count`, `violation_count` and `metrics` in actual
and expected. Expected violation count is zero. A violation now means failure
of this explicit restricted contract; native findings are still counted below.
Unexecuted checks cannot become pass.
As before, a pass has `affected_count=0`; registered native limitations remain
visible in metrics and case evidence. A block counts distinct violating rows,
while QA07 limited counts the distinct unmapped accidents.

| Rule | Exact metric keys and expectations under `team-v1.1-vic-r1` |
|---|---|
| QA01 | `hash_match`, `header_match`, `bundle_confirmed`, `contract_confirmed`, `profile_approved`, `selected_identity_match`, `profile_scope_match`, `case_register_match`. The two full-source confirmation values must be false; all others true. `case_register_match` verifies the frozen register and evidence digests, not semantic execution. |
| QA04 | `orphan_count`, `nonblank_unmatched_count`, `declared_count_delta`, `duplicate_group_count`, `coordinate_conflict_group_count`, `case_set_match`, `full_count_difference_count`, `analysis_count_difference_count`, `restriction_violation_count`. Orphans and restriction violations must be zero; case-set match true. Person unmatched count is 39 only with exact case equality. Declared delta is NULL because a common complete export scope is not claimed. Diagnostic differences are Person 2/full, 0/analysis and Vehicle 5/full, 3/analysis. Inapplicable metrics are NULL with reasons. Node group counts remain observations with NULL expectations and QA07 treatment. |
| QA05 | `undefined_category_count`, `unconfirmed_definition_count`, `eligibility_error_count`, `disposition_match`, `restriction_violation_count`. Count rows, not distinct codes: Vehicle 454 + Person 425 = 879 full-file undefined-category rows; record the in-scope subtotal 278 in evidence. Unconfirmed definition count is 10, matching the publisher-unconfirmed IDs in the frozen policy, including special vehicle eligibility and negative Node codes. Expected counts come from that policy and its evidence, not the produced results. Disposition match must be true; eligibility and restriction violations zero. |

QA02, QA03, QA06 and QA07 keep their existing metrics and requirements. QA04
expected metrics are listed per resource in the policy JSON. Person and Vehicle
duplicate-group expectations are zero; Node duplicate/conflict expectations
remain NULL observations. Non-Person vehicle-reference metrics and Node count
comparisons are inapplicable, explicitly NULL with reasons.
All QA04 checks inspect complete parents and child files before deriving reporting scope.
Cases outside 2020–2024 are still audited; their recognition grants no right
to publish other years. Any unexpected case, missing parent, invalid core
value, duplicate business key, changed native token or incorrect isolation
blocks. Known findings are not subtracted from observed metrics. The numbers
above are evidence-based expectations, not executed database QA results.

Only QA07 permits `limited`: every retained VIC accident is unmapped, with
zero incorrectly eligible locations. Other rules pass only when the amended
checks actually run and succeed. This is not a warning override for old blocks.

## Publication and activation

E must independently derive all expected objects, require all seven summaries,
and retain the rule that any block or missing result prevents publication.
It must verify the same profile, files, case sets, years and enforced outputs.
Neither an extra block nor an old-protocol block may be discarded. D must prove
that forbidden outputs are unavailable and Accident counts cannot multiply.
No official success or release is recorded by this document.

B must freeze the full policy and dispositions within versioned
`rules.contracts`/`rules.mappings`, with the amended QA contract and actual code
inventory included in FP1. No new root manifest field or physical table is
needed. Do not clear unresolved issues or label the source fully confirmed.

The decision is adopted. C06 now implements its Person reference and count
diagnostics through a standalone entry; see [C06](c06-person-checks.md). Full
pipeline activation remains incomplete (`runtime_integrated=false` in the
frozen policy). B's legacy manifest and publication path retain their blockers
until the new protocol, complete QA producers, report restrictions and release
gate are integrated and tested together. S0/S8 development continues separately. New hashes, cases,
years or outputs require a new reviewed policy version; this is no error budget.
