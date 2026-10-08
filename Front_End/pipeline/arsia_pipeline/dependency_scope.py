"""Narrow replay compatibility; this never reuses an old QA admission.

All shared validators and the replay classifier remain exact-hash dependencies.
Only modules behind unchanged, false capability branches may differ. Historical
records without this rule retain their original exact dependency requirement.
"""
VERSION = 'recipe-dependency-scope-v1'


def scope(contract):
    from .table_plan import input_resources, physical_resources
    unused = set()
    resources = input_resources(contract)
    if resources and all(part.get('table', {}).get('format') == 'csv'
                         for r in resources for part in physical_resources(r)):
        unused.add('workbook_plan.py')
    if 'lookup_tables' not in contract and not any('lookups' in r for r in resources):
        unused.update(('lookup_plan.py', 'lookup_projection.py', 'lookup_evidence.py', 'knowledge/reviewed-lookup-claims.json'))
    return {'version': VERSION, 'unused_trusted_modules': sorted(unused)}


def compatible(record, current):
    previous = record['dependencies']
    if previous == current:
        return True
    rule = record.get('dependency_scope')
    if rule != scope(record['contract']):
        return False
    if set(previous) != set(current) or any(previous[k] != current[k] for k in current if k != 'trusted'):
        return False
    old, new = previous.get('trusted', {}), current.get('trusted', {})
    return set(old) == set(new) and all(old[name] == new[name] for name in new
                                      if name not in rule['unused_trusted_modules'])
