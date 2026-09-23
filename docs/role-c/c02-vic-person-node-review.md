# C02: VIC Person / Node review

Version `c02-review-2026-09-23-r2`. The team has adopted the
[restricted-use decision](vic-restricted-use-decision.md) under the user-reported
C/E delegation. Publisher definitions and full-bundle compatibility remain
unconfirmed; legacy `bundle_confirmed=false`.

This updates [C02 at 87d1c58](https://github.com/A3939/advance-database-assignment-uts/blob/87d1c5803a6ec61475823ea877a995ba589f22f7/docs/role-c/c02-vic-person-node-review.md)
using [B's shared review at 3185b84](https://github.com/A3939/advance-database-assignment-uts/blob/3185b841a86a4b8f9c998636766efbf6332efa8c/docs/sources/vic-accident-vehicle.md)
and the [23 September follow-up](../sources/evidence/vic/followup-2026-09-23/README.md).
The new `team-v1.1-vic-r1` addendum defines the accepted use and amended QA
conditions. Legacy v1.1 behavior is unchanged until that version is implemented.

## Evidence and scope

The [evidence index](c02-evidence-index.json) maps original workspace paths to
included byte-identical source observations and snapshots. Generated validation
records are held separately as listed in the index; the frozen policy retains
their original paths and hashes.

The follow-up rescanned the four originals and reproduced the earlier results
with unchanged SHA256 values. It also repeated selected official API queries.
These selections confirm that the reported cases still exist; they do not
validate the whole current release. All CSV locators use `csv-logical-v1`, not
API `_id` values. Parser: `csv-native-v1`; source: `official_vic`.

| Resource | Full rows | Original SHA256 |
|---|---:|---|
| Accident | 200,352 | `a148c00601fab10d44368df80492c594123700a7f9e334ff896fd215295e91d9` |
| Vehicle | 365,470 | `05a7a1b9171abaeb5c188df549dee38edde6e76d5a03553988305a8280dccd12` |
| Person | 467,730 | `71ca8fec01370e301f282fc83e8f11e4cde16a535ee421cbbb72512ceb7194f9` |
| Node | 405,918 | `b0bdbec22ac33df66e15cff9b531ba3203320ec5fbe20076a2820b8fec966ed4` |

The local Accident dates span 2012–2025; the default analysis is 2020–2024,
containing 72,170 accidents. Match children against the full selected parent
files first, then derive scope from `ACCIDENT_DATE`. An absent parent is an
orphan, not an out-of-range record. Keep all native key text, including leading
zeros; missing or whitespace-only required keys block.

| Observed issue | Full files | 2020–2024 |
|---|---:|---:|
| Nonempty Person references without a Vehicle | 39 | 39 |
| Blank Vehicle reference, pedestrian role `1` | 18,752 | 6,186 |
| Blank Vehicle reference, unknown role `9` | 24 | 6 |
| Vehicle declared/native count differences | 5 | 3 |
| Person total / injury-component difference cases | 2 / 2 | 0 / 0 |
| Vehicle type `21` / Person role `16` rows | 454 / 425 | 149 / 129 |
| Accidents without a matching Node | 85 | 7 |
| Node rows / conflicting coordinate groups | 405,918 / 0 | 145,709 / 0 |

No missing/duplicate Accident, Vehicle or Person keys, Person/Vehicle rows
without an Accident parent, invalid Node coordinates or Node-to-Accident ID
mismatches were found. These observations do not remove checks for later inputs.

## What is supported, and what is still uncertain

**Official definitions.** The [Person dictionary](https://opendata.transport.vic.gov.au/dataset/victoria-road-crash-data/resource/60c8fc0c-2806-40f3-bb33-5c52691120e8)
defines `(ACCIDENT_NO, PERSON_ID)` and the Accident relationship. A nonempty
Vehicle reference uses `(ACCIDENT_NO, VEHICLE_ID)` within the same source and
selected snapshot. The Accident dictionary defines `NO_PERSONS` as participants,
including uninjured people. It does not guarantee every participant appears in
the Person export. Blank Vehicle-ID permission is not documented.

**File/API observations.** All 39 missing Vehicle references persist in the API.
Three crashes have no Vehicle rows; the other 36 lack the referenced key.
Thirty-one pedestrians have valid nonempty Vehicle references, so pedestrian
status must not clear an existing link. The 24 unknown-role blanks include LF/LR
seats outside the default range; all six in range have seating `NA`.

Both Person count differences are in 2015. Each Accident declares two people,
including one uninjured person, but only the injured Person is present.
`T20150023069` is Accident `csv:63102`, Person `csv:294959`;
`T20150025312` is Accident `csv:130238`, Person `csv:54095`.
Missing uninjured detail is a possible explanation, not an approved exclusion.

The three in-scope Vehicle count differences are `T20210022607` (`csv:183745`),
`T20210022263` (`csv:184156`) and `T20230009098` (`csv:148970`): each declares
one Vehicle but has none. They overlap the 39 reference cases. The other two
are in 2025: `T20250032463`, declared/native 1/2, includes a parked trailer;
`T20250030921`, 2/3, includes a type-21 device. Possible scope exclusions do not
explain the three empty Vehicle groups.

Vehicle `21 / Electric Device` and Person `16 / E-scooter Rider` labels occur in
published data but are absent from the dictionaries checked. They are not
synonyms: type-16 people also link to other Vehicle types. Full definitions,
historical coding and count eligibility remain open.

**Node.** The [Node dictionary](https://opendata.transport.vic.gov.au/dataset/victoria-road-crash-data/resource/466fd3b5-201b-42b5-b10d-e926324fa215)
describes a location ID shared by crashes. `(ACCIDENT_NO, NODE_ID)` is a matching
key, not an export-row identity. There are 143,808 Node IDs, 200,267 matching
groups and 199,359 repeated groups. The 205,651 extra observations include
202,505 exact duplicates; 3,137 groups differ only in `DEG_URBAN_NAME`.
Coordinates agree as unrounded decimals within each matching group.

The separate [Accident Location table](https://opendata.transport.vic.gov.au/dataset/victoria-road-crash-data/resource/e1beb92b-5836-448a-9769-e7aa6a9e7413)
returned one row for each of the 85 missing-Node cases and five repeated examples.
It preserves the same negative IDs (`-1`, `-10`, `-3`). For example,
`T20140014662` / `273173` has one Location row but four Node observations at
`csv:140`, `csv:1430`, `csv:398965`, `csv:400622`. This does not explain the
negative codes or export duplication. An urban-area join is a hypothesis only.

**CRS and release.** WGS84 metadata belongs to the current flat crash resource,
not the saved Node CSV. Twelve matching coordinate comparisons and metadata
mirrors add no Node-specific datum declaration; AMG/VicGrid field labels also
differ. No EPSG code is confirmed for Node. Current Accident metadata is dated
14 September 2026; Vehicle/Person/Node remain dated 10 August. One selected
2025 Accident has revised injury fields without matching Person changes.
Matching original hashes and August dates do not establish a compatible release.

## Adopted use and remaining source questions

The [decision](vic-restricted-use-decision.md) now permits VIC-only Accident
trends, native severity, fatal-crash counts, deaths and casualties for the
pinned 2020–2024 snapshot. Person/Vehicle-dependent measures and VIC official
maps are unavailable. The decision fixes blank-reference treatment and count
usage; it does not invent missing publisher definitions or claim compatible
publication. No further C/E policy approval is pending for this exact scope.

The [versioned policy](../../config/vic-restricted-use-v1.json) contains all four
file identities, the 39 unmatched references, 24 unknown-role blank cases, seven
count-difference cases and 85 missing Node matches. Each case has original keys,
locators and occurrence scope. Pedestrian/NA empty references have a separate,
file-bound team rule. Keep all native values and all valid in-range accidents.
Known observations are still reported; any new case or changed file is outside
this decision. The earlier [draft register](vic-minimum-impact-draft.json) stays
unchanged as history and is not the active policy.

The addendum specifies QA01/04/05 checks, preserves QA07 location isolation
and requires all seven QA groups before publication. Newer B work supports
its manifest/input checks, while this branch still contains B's earlier
implementation. C06 has a separately validated restricted diagnostic entry;
C10, D's restrictions and E's publication gate remain integration work.
See [C06](c06-person-checks.md) for the precise checkout and runtime boundary.
This is not a request for another policy decision. Continue S0/S8 integration.

Publisher evidence would still be useful for blank permissions, Person/Vehicle
export scope, categories 21/16 and special vehicle eligibility, Node duplication
and negative codes, Node CRS and a compatible release. Those gaps remain listed
with explicit restrictions in the policy. Expanding outputs requires a new
version; they do not prevent development of the adopted restricted scope.

The included source materials contain the local scan, saved API selections and
metadata retrievals. Generated validation reports are retained separately by
the team and are not part of this code delivery. See [C06](c06-person-checks.md)
for the runtime scope and the [handoff](c02-c06-handoff.md) for reproduction and
remaining integration prerequisites.
