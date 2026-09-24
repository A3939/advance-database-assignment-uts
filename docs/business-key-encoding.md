# Shared SQL business-key encoding

Migration `sql/migrations/010_business_key.sql` installs the shared PostgreSQL
function:

```sql
rv.encode_business_key(VARIADIC components text[]) RETURNS text
```

The function encodes native text components, in their declared order, as
PostgreSQL JSON-array text. It preserves case, leading zeroes and all other
valid identifier text. It rejects an empty component list and every `NULL`,
empty or whitespace-only component with SQLSTATE `22023`.

## Fixed calls

Crash identity uses `[Crash ID]`:

```sql
SELECT rv.encode_business_key('0001');
-- ["0001"]
```

Traffic-unit identity uses `[Crash ID, Traffic unit ID]`:

```sql
SELECT rv.encode_business_key('0001', '01');
-- ["0001", "01"]
```

Callers must not change component order, cast identifiers to integers, or build
keys by concatenating strings. A child row must use the identical encoded crash
key as its parent.

The encoded key alone is not the complete identity scope. Vault constraints
combine it with `batch_id`, `source_id` and `release_scope`, preventing records
from different snapshots, sources or release scopes from being mixed.

## Access

`arsia_loader` can execute the function. Access is revoked from `PUBLIC`, so
`arsia_reader` cannot create business keys while serving published data.
