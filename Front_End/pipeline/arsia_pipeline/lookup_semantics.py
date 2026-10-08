"""Resolve typed lookup references to physical evidence subjects.

No synthetic field alias gains authority. Physical equality and key uniqueness
are checked elsewhere; these helpers keep publisher scope with the input field.
They do not establish direct-count, category or publication admission by themselves.
"""
import copy

from .errors import UnsupportedCapability, ValidationFailure

VERSION = 'physical-lookup-field-origin-v1'


def field_origin(contract, resource, value):
    if isinstance(value, str) and value:
        return {'role': resource['role'], 'field': value, 'lookup': None}
    if (not isinstance(value, dict) or set(value) != {'lookup', 'field'}
            or not isinstance(value.get('lookup'), str)
            or not isinstance(value.get('field'), str) or not value['field']):
        raise ValidationFailure('A semantic field reference must name a physical field or an explicit lookup field.')
    bindings = [item for item in resource.get('lookups', []) if item.get('name') == value['lookup']]
    if len(bindings) != 1 or value['field'] not in bindings[0].get('select', []):
        raise ValidationFailure('A semantic lookup reference must select an explicitly bound parent field.')
    parents = [item for item in contract.get('lookup_tables', []) if item.get('role') == bindings[0].get('parent')]
    if len(parents) != 1:
        raise ValidationFailure('A semantic lookup reference needs one declared physical parent role.')
    return {'role': parents[0]['role'], 'field': value['field'], 'lookup': value['lookup']}


def geography_resources(contract):
    """Proof views of the actual physical coordinate table, never joined rows.

    Both axes must come from the same parent row/binding. The returned role,
    file/table/key/source_url are the parent's; a child's receipt cannot certify
    it. Omission checks retain the original child view in their own caller.
    """
    views = []
    parents = {r['role']: r for r in contract.get('lookup_tables', [])}
    for resource in contract.get('resources', []):
        geography = resource.get('mapping', {}).get('geography')
        if not geography:
            views.append(copy.deepcopy(resource))
            continue
        axes = [geography.get(name) for name in ('x_field', 'y_field')]
        if not any(isinstance(value, dict) for value in axes):
            views.append(copy.deepcopy(resource))
            continue
        origins = [field_origin(contract, resource, value) for value in axes]
        if len({(value['role'], value['lookup']) for value in origins}) != 1:
            raise UnsupportedCapability('LOOKUP_COORDINATE_PAIR_SPLIT',
                'A coordinate pair must resolve from one physical row; mixed tables or independently matched parent rows need a reviewed coordinate composition rule.')
        parent = parents[origins[0]['role']]
        view = copy.deepcopy(parent)
        view['grain'] = resource['grain']
        geo = copy.deepcopy(geography)
        # Region semantics are separately field-bound; they are not CRS axes.
        geo.pop('region_field', None)
        geo.update(x_field=origins[0]['field'], y_field=origins[1]['field'])
        view['mapping'] = {'geography': geo}
        view['lookup_consumer'] = {'role': resource['role'], 'lookup': origins[0]['lookup']}
        views.append(view)
    return views


def capability_resources(contract):
    """Physical views for omission checks, retaining child and parent inputs."""
    views = []
    geographic = geography_resources(contract)
    for resource, resolved in zip(contract.get('resources', []), geographic):
        original = copy.deepcopy(resource)
        if resolved['role'] != original['role']:
            original.get('mapping', {}).pop('geography', None)
        views.append(original)
        parents = {r['role']: r for r in contract.get('lookup_tables', [])}
        for binding in resource.get('lookups', []):
            parent = copy.deepcopy(parents[binding['parent']])
            # A codebook's point/polygon is not automatically a crash location.
            # Only an explicit geography projection makes it an output capability.
            parent.update(grain='lookup', mapping={},
                          lookup_consumer={'role': resource['role'], 'lookup': binding['name']})
            if (resolved.get('lookup_consumer') == parent['lookup_consumer']
                    and resolved['role'] == parent['role']):
                parent['mapping'] = resolved['mapping']
                parent['grain'] = resource['grain']
            views.append(parent)
    return views


def count_views(contract):
    """One count operation per physical evidence subject, preserving consumer.

    Cross-row sums need a formula that identifies every operand's resource;
    existing unqualified same-table equations cannot authorize them.
    """
    from .count_semantics import count_specs
    parents = {r['role']: r for r in contract.get('lookup_tables', [])}
    views, issues = [], []
    for resource in contract.get('resources', []):
        for metric, spec in count_specs(resource):
            operands = ([spec['field']] if 'field' in spec else spec.get('sum_fields', [])) if isinstance(spec, dict) else []
            if not any(isinstance(value, dict) for value in operands):
                mapping = {'metrics': {metric: copy.deepcopy(spec)}} if metric in resource.get('mapping', {}).get('metrics', {}) else {metric: copy.deepcopy(spec)}
                views.append({**copy.deepcopy(resource), 'mapping': mapping})
                continue
            origins = [field_origin(contract, resource, value) for value in operands]
            owners = {(origin['role'], origin['lookup']) for origin in origins}
            if len(owners) != 1:
                issues.append({'code': 'LOOKUP_CROSS_RESOURCE_SUM_UNSUPPORTED', 'role': resource['role'], 'metric': metric,
                               'operands': origins,
                               'message': 'A sum across independently matched rows requires a resource-qualified population and addition proof; same-table equations do not establish it.'})
                continue
            role, lookup = next(iter(owners))
            rewritten = copy.deepcopy(spec)
            if 'field' in rewritten: rewritten['field'] = origins[0]['field']
            else: rewritten['sum_fields'] = [origin['field'] for origin in origins]
            mapping = {'metrics': {metric: rewritten}} if metric in resource.get('mapping', {}).get('metrics', {}) else {metric: rewritten}
            views.append({**copy.deepcopy(parents[role]), 'grain': resource['grain'], 'mapping': mapping,
                          'lookup_consumer': {'role': resource['role'], 'grain': resource['grain'], 'lookup': lookup},
                          'lookup_operands': origins})
    return views, issues


def count_allocations(contract, role, row):
    """Exact parent-row allocations for host QA; not an aggregate receipt.

    This is independent of whether a count is zero, null or nonzero. Allocation
    multiplicity must not silently change when source values change later.
    """
    from .count_semantics import count_specs
    resource = next(r for r in contract['resources'] if r['role'] == role)
    for metric, spec in count_specs(resource):
        operands = ([spec['field']] if 'field' in spec else spec.get('sum_fields', [])) if isinstance(spec, dict) else []
        seen = set()
        for value in operands:
            if not isinstance(value, dict):continue
            origin = field_origin(contract, resource, value)
            key = (origin['role'], origin['lookup'])
            if key in seen:continue
            seen.add(key)
            match = row.get('lookup_lineage', {}).get(origin['lookup'])
            if not isinstance(match, dict):raise ValidationFailure('Lookup count has no host-derived parent lineage.')
            if match['status'] == 'matched':
                parent = match['parent']
                yield {'parent_role': origin['role'], 'metric': metric,
                       'parent_locator': [parent['file_sha256'], parent['table_id'], parent['row_locator']],
                       'consumer_role': role, 'consumer_locator': row['row_locator']}
