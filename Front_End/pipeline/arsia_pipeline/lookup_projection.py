"""Typed lookup references for provisional canonical projection.

This does not grant admission. trusted_qa currently blocks lookup contracts
until scoped evidence review and full host replay are integrated. Field
references are rewritten only in explicitly supported mapping positions.
"""
import copy
import hashlib
import json

from .canonical import project
from .errors import ValidationFailure
from .lookup_plan import LookupIndex


def fail(message):
    raise ValidationFailure(message, [{'code': 'LOOKUP_PROJECTION_INVALID', 'status': 'block', 'message': message}])


def field_slots(mapping):
    """Yield (container, key) only where canonical expects a source field."""
    for kind, names in (
        ('date', ('field', 'year_field', 'month_field')),
        ('severity', ('field',)), ('injury', ('field',)),
        ('geography', ('x_field', 'y_field', 'region_field')),
    ):
        spec = mapping.get(kind)
        if isinstance(spec, dict):
            for name in names:
                if name in spec:
                    yield spec, name
    counts = [mapping.get(name) for name in ('fatalities', 'casualties', 'declared_units', 'declared_casualties')]
    if isinstance(mapping.get('metrics'), dict):
        counts.extend(mapping['metrics'].values())
    for spec in counts:
        if not isinstance(spec, dict):
            continue
        if 'field' in spec:
            yield spec, 'field'
        if isinstance(spec.get('sum_fields'), list):
            for index in range(len(spec['sum_fields'])):
                yield spec['sum_fields'], index
    if 'unit_type' in mapping:
        yield mapping, 'unit_type'
    if isinstance(mapping.get('dimensions'), dict):
        for name in mapping['dimensions']:
            yield mapping['dimensions'], name


class LookupProjection:
    def __init__(self, contract, files, work_dir, check_cancelled=lambda: None, *, compile_only=False):
        if type(compile_only) is not bool:
            fail('Lookup compilation mode must be an explicit boolean.')
        self.compile_only = compile_only
        self.contract = copy.deepcopy(contract)
        self.compiled = copy.deepcopy(contract)
        self.indexes = {}
        self.references = {}
        self.closed = False
        self.failed = False
        tables = self.contract.get('lookup_tables', [])
        resources = self.contract.get('resources', [])
        if not isinstance(tables, list) or not 1 <= len(tables) <= 24:
            fail('Declare 1–24 lookup tables separately from canonical fact resources.')
        if not isinstance(resources, list) or not 1 <= len(resources) <= 24:
            fail('Lookup projection requires bounded fact resources.')
        by_role = {}
        for table in tables:
            if not isinstance(table, dict) or not isinstance(table.get('role'), str) or table['role'] in by_role:
                fail('Lookup table roles must be unique.')
            by_role[table['role']] = table
        fact_roles = [resource.get('role') for resource in resources if isinstance(resource, dict)]
        if len(fact_roles) != len(resources) or any(not isinstance(role, str) for role in fact_roles):
            fail('Fact resources must declare explicit roles.')
        if len(set(fact_roles)) != len(fact_roles) or set(fact_roles) & set(by_role):
            fail('Fact and lookup table roles must be distinct.')
        used_tables = set()
        plans = []
        try:
            for resource in self.compiled['resources']:
                role = resource['role']
                if not isinstance(resource.get('mapping', {}), dict):
                    fail('Fact mapping must be an object with typed field positions.')
                lookups = resource.get('lookups', [])
                if not isinstance(lookups, list) or len(lookups) > 8:
                    fail('Each fact role may declare up to eight explicit lookups.')
                bindings = {}
                for lookup in lookups:
                    if (not isinstance(lookup, dict) or set(lookup) != {'name', 'parent', 'fields', 'select', 'allow_blank', 'on_missing'}
                            or not isinstance(lookup.get('name'), str) or not lookup['name'] or len(lookup['name']) > 64
                            or lookup['name'] in bindings or not isinstance(lookup.get('parent'), str)
                            or lookup['parent'] not in by_role):
                        fail('Lookup declarations require unique names and an existing lookup parent role.')
                    bindings[lookup['name']] = lookup
                    used_tables.add(lookup['parent'])
                self.references[role] = []
                used_bindings = set()
                for container, key in field_slots(resource.get('mapping', {})):
                    value = container[key]
                    if isinstance(value, str) or value is None:
                        continue
                    if (not isinstance(value, dict) or set(value) != {'lookup', 'field'}
                            or not isinstance(value.get('lookup'), str) or value['lookup'] not in bindings
                            or not isinstance(value.get('field'), str)):
                        fail('A field reference must name an explicitly declared lookup and selected parent field.')
                    binding = bindings[value['lookup']]
                    if not isinstance(binding['select'], list) or value['field'] not in binding['select']:
                        fail('A mapped lookup field must be explicitly selected from its parent table.')
                    # NUL cannot occur in a supported physical header. Never
                    # use a model-controlled alias that might overwrite a key.
                    token = '\x00lookup:' + hashlib.sha256(json.dumps([role, value['lookup'], value['field']]).encode()).hexdigest()
                    self.references[role].append((token, value['lookup'], value['field']))
                    container[key] = token
                    used_bindings.add(value['lookup'])
                if set(bindings) != used_bindings:
                    fail('Every lookup must supply mapped fields; unused declarations cannot hide uploaded fact tables.')
                for name, binding in bindings.items():
                    join = {key: copy.deepcopy(binding[key]) for key in ('fields', 'select', 'allow_blank', 'on_missing')}
                    join['child_role'] = role
                    plans.append((role, name, by_role[binding['parent']], join))
            if set(by_role) != used_tables:
                fail('Every declared lookup table must be used by an explicit fact mapping.')
            if len(plans) > 64:
                fail('A bundle may declare at most 64 lookup operations.')
            self.declarations = copy.deepcopy(plans)
            # Validate all reference positions before opening any disk index.
            if not compile_only:
                for role, name, table, join in plans:
                    self.indexes[(role, name)] = LookupIndex(table, files, join, work_dir, check_cancelled)
        except BaseException:
            self.close()
            raise

    def project(self, role, locator, raw):
        if self.closed or self.failed or self.compile_only:
            fail('A closed or failed lookup projection cannot process records.')
        try:
            return self._project(role, locator, raw)
        except BaseException:
            self.failed = True
            raise

    def _project(self, role, locator, raw):
        if role not in self.references or not isinstance(raw, dict):
            fail('Lookup projection requires a declared fact role and source row.')
        rows = {name: index.resolve(raw) for (child_role, name), index in self.indexes.items() if child_role == role}
        enriched = dict(raw)
        for token, name, field in self.references[role]:
            if token in raw:
                fail('Source row conflicts with an internal lookup reference.')
            enriched[token] = rows[name]['values'][field]
        result = project(self.compiled, role, locator, enriched)
        result['extensions'] = copy.deepcopy(raw)
        if rows:
            result['lookup_lineage'] = {name: {'status': value['status'], 'parent': value['lineage']}
                                        for name, value in rows.items()}
        return result

    def receipts(self):
        if self.closed or self.failed or self.compile_only:
            fail('A closed or failed lookup projection cannot provide completed receipts.')
        return [{'child_role': role, 'lookup': name, **index.receipt()}
                for (role, name), index in sorted(self.indexes.items())]

    def close(self):
        for index in self.indexes.values():
            index.close()
        self.closed = True
