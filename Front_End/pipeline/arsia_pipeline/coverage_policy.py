"""Observed bounds are not complete temporal coverage or deletion authority."""
from calendar import monthrange

VERSION = 'temporal-coverage-v1'


def complete_intervals(result):
    proof = result.get('temporal_coverage', {})
    if proof.get('version') == VERSION:
        return proof.get('complete_intervals', [])
    # Reviewed historical native publications carry fixed rule/byte evidence.
    # Their scope is this dataset snapshot, never all crashes in the population.
    evidence = result.get('evidence', {})
    if (evidence.get('execution_kind') == 'local_sqlite_adapter' and evidence.get('canonical_sha256')
            and evidence.get('rule_fingerprint') and evidence.get('upstream')):
        return [{'from': '2020-01-01', 'to': '2024-12-31'}]
    return []


def covers(intervals, lower, upper):
    cursor = lower
    from datetime import date, timedelta
    for item in sorted(intervals, key=lambda x: x['from']):
        if item['to'] < cursor:
            continue
        if item['from'] > cursor:
            return False
        if item['to'] >= upper:
            return True
        cursor = (date.fromisoformat(item['to']) + timedelta(days=1)).isoformat()
    return False


def fill_complete_months(rows, intervals, start, end, known):
    """Missing crash months are zeros only inside verified complete intervals."""
    measured = {(r['year'], r['month']): r for r in rows}
    for index in range(start.year * 12 + start.month - 1, end.year * 12 + end.month):
        year, month = index // 12, index % 12 + 1
        lower, upper = f'{year:04}-{month:02}-01', f'{year:04}-{month:02}-{monthrange(year, month)[1]:02}'
        if (year, month) not in measured and covers(intervals, lower, upper):
            measured[(year, month)] = {'year': year, 'month': month, **{k: 0 if v else None for k, v in known.items()}}
    return [measured[key] for key in sorted(measured)]
