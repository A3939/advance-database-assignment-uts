"""Immutable read facts materialized only after database reconciliation."""
VERSION = 'publication-read-facts-v1'


def capture(conn, batch, result):
    if result.get('database_verification', {}).get('status') != 'pass':
        raise ValueError('Read facts require reconciled publication rows')
    table = 'canonical_observation' if result.get('source', {}).get('grain') == 'observation' else 'canonical_crash'
    precision = conn.execute('SELECT count(*) AS n,count(month) AS months FROM '+table+' WHERE batch_id=%s', (batch,)).fetchone()
    return {'version': VERSION, 'batch_id': str(batch), 'row_count': precision['n'],
            'monthly': bool(precision['n'] and precision['n'] == precision['months']),
            'basis': 'reconciled_persisted_rows'}


def monthly(result, batch):
    facts = result.get('query_facts', {})
    if facts.get('version') == VERSION and facts.get('batch_id') == str(batch) and type(facts.get('monthly')) is bool:
        return facts['monthly']
    return None
