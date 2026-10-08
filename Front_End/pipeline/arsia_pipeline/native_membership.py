"""Translate reviewed legacy key encodings for native-to-v2 membership checks.

Only a current host-owned native transition and unchanged native key fields
activate this path. It grants no permission to remove a record or alter meaning.
"""
from .errors import NeedsInput
from .publication_policy import admission_level

# Same key grammar as native._load_crashes/_load_children, included in QA hashes.
KEYS = {'NSW': {'crash': ['Crash ID'], 'traffic_unit': ['Crash ID', 'Traffic unit ID']},
        'QLD': {'crash': ['Crash_Ref_Number']},
        'VIC': {'crash': ['ACCIDENT_NO'], 'vehicle': ['ACCIDENT_NO', 'VEHICLE_ID']}}


def transition_plan(previous, candidate):
    if admission_level(previous) != 'fixed_native': return None
    receipt = candidate.get('admission', {}).get('native_transition')
    if not receipt: return None  # Ordinary membership policy still applies.
    from .native_revision import VERSION
    if (receipt.get('transition_version') != VERSION or receipt.get('source_id') != previous['source_id']
            or receipt.get('source_id') != candidate['source_id']
            or receipt.get('baseline_profile_id') != previous['profile_id']
            or candidate.get('update', {}).get('mode') != 'snapshot'):
        raise NeedsInput('Legacy membership requires a matching host native transition')
    resources = candidate['source_contract']['resources']
    plan = []
    for native in receipt['required_resources']:
        if native['grain'] not in {'crash', 'unit'}: continue
        matches = [r for r in resources if r['file_id'] == native['file_id'] and r['grain'] == native['grain']]
        expected = KEYS.get(receipt.get('jurisdiction'), {}).get(native['role'])
        if len(matches) != 1 or expected is None or matches[0]['key'] != expected:
            raise NeedsInput('Native key encoding is not compatible with this candidate; removal authority has not been established')
        plan.append({'grain':native['grain'], 'native_resource_id':native['resource_id'], 'role':matches[0]['role']})
    return plan


def removals(conn, previous, candidate, plan, cancel):
    removed = []
    for grain, table in [('crash','canonical_crash'),('unit','canonical_unit')]:
        cancel()
        roles = [r for r in plan if r['grain'] == grain]
        known = [r['native_resource_id'] for r in roles]
        unknown = conn.execute(f"SELECT count(*) AS n FROM {table} WHERE batch_id=%s AND (payload->>'resource_id' IS NULL OR NOT (payload->>'resource_id'=ANY(%s)))", (previous,known)).fetchone()['n']
        if unknown:removed.append({'grain':grain,'role':None,'count':unknown})
        # Compare JSON arrays, preserving text and leading zeroes. No casts to integers.
        key = "jsonb_build_array(old.record_id)" if grain == 'crash' else "(old.payload->>'record_id')::jsonb"
        conn.execute(f"CREATE TEMP TABLE arsia_native_keys ON COMMIT DROP AS SELECT payload->>'resource_role' AS role,payload->'raw_key' AS raw_key FROM {table} WHERE batch_id=%s",(candidate,))
        conn.execute('CREATE INDEX ON pg_temp.arsia_native_keys(role,raw_key)')
        conn.execute('ANALYZE pg_temp.arsia_native_keys')
        for item in roles:
            n=conn.execute(f"SELECT count(*) AS n FROM {table} old WHERE old.batch_id=%s AND old.payload->>'resource_id'=%s AND NOT EXISTS (SELECT 1 FROM pg_temp.arsia_native_keys new WHERE new.role=%s AND new.raw_key={key})",(previous,item['native_resource_id'],item['role'])).fetchone()['n']
            if n:removed.append({'grain':grain,'role':item['role'],'count':n})
        conn.execute('DROP TABLE pg_temp.arsia_native_keys')
    return removed
