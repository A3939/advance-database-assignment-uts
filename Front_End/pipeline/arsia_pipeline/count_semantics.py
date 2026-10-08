"""Bounded verification of official additive count definitions.

An explicit publisher equation authorizes its stated total, not arbitrary sums
of individually documented fields. No eval, model confidence or state-specific
field names. This is an intentionally bounded grammar, not general natural
language semantic understanding or an assertion of scientific comparability.
"""
import re

from .evidence_grounding import _normal
from .evidence_scope import applicable_documents
from .evidence_references import covers_pointer
from .metadata_extractors import _token

VERSION = 'official-count-semantics-v2'
TARGETS = {'fatalities': {'fatalities', 'number of fatalities', 'total fatalities', 'total number of fatalities'},
           'casualties': {'casualties', 'number of casualties', 'total casualties', 'total number of casualties'},
           'declared_units': {'units', 'number of units', 'total units', 'total number of units'},
           'declared_casualties': {'casualties', 'number of casualties', 'total casualties', 'total number of casualties'},
           'crashes': {'crashes', 'number of crashes', 'total crashes', 'total number of crashes'},
           'fatal_crashes': {'fatal crashes', 'number of fatal crashes', 'total fatal crashes', 'total number of fatal crashes'}}


def count_specs(resource):
    mapping = resource.get('mapping', {})
    for metric in ('fatalities', 'casualties', 'declared_units', 'declared_casualties'):
        if metric in mapping:
            yield metric, mapping[metric]
    for metric, spec in mapping.get('metrics', {}).items():
        yield metric, spec


def expression(statement, metric):
    """A whole line/description: 'Total casualties = field A + field B'.

    All text must be consumed. Negations, approximations, prose before/after,
    multiplication, subtraction, functions and ambiguous punctuation cannot
    become an affirmative fact through substring matching.
    """
    if not isinstance(statement, str) or len(statement) > 2048:
        return None
    match = re.fullmatch(r'\s*([^=:+]{1,100})\s*(?:=|:)\s*([^=;\n]+?)\s*\.?\s*', statement)
    if not match or _normal(match[1]) not in TARGETS.get(metric, set()):
        return None
    terms = [term.strip() for term in match[2].split('+')]
    if not 2 <= len(terms) <= 32:
        return None
    result = []
    for term in terms:
        if len(term) >= 2 and term[0] == term[-1] and term[0] in ('"', "'", '`'):
            term = term[1:-1]
        if not term or len(term) > 128 or any(char in term for char in '=+;*()/<>\n"\'`'):
            return None
        result.append(term)
    return result


def _statements(node, source_url=None):
    """Only the already selected resource schema or literal document lines."""
    value = node['facts'].get('value')
    from .evidence_scope import schema_subjects, schema_fields
    packages = schema_subjects(node, source_url)
    if value is not None:
        for package, path in packages:
            # Preserve every declaration, including duplicate descriptors. An
            # alias dictionary's last value must not hide a known contradiction.
            for _, _, field, pointer in schema_fields(package, path):
                for property_name in ('description', 'definition'):
                    if property_name in field:
                        yield field[property_name], pointer + '/' + property_name
    else:
        for line in node['facts'].get('text', '').splitlines():
            if line.strip():
                yield line, None


def review_count_operations(contract, documents, grounding, accepted, graph):
    if contract.get('lookup_tables'):
        from .lookup_semantics import count_views
        from .count_definitions import review_lookup_population
        views, issues = count_views(contract)
        result = _review_count_operations({**contract, 'resources': views}, documents, grounding, accepted, graph)
        result['issues'].extend(issues)
        result['lookup_populations'] = []
        for view in views:
            if 'lookup_consumer' not in view:continue
            population = review_lookup_population(contract, view, documents, grounding, accepted, graph)
            result['lookup_populations'].append(population)
            result['issues'].extend(population['issues'])
        result['ok'] = not result['issues']
        return result
    return _review_count_operations(contract, documents, grounding, accepted, graph)


def _review_count_operations(contract, documents, grounding, accepted, graph):
    decisions, issues = [], []
    bindings = grounding.get('field_bindings', [])
    for resource in contract.get('resources', []):
        role = resource['role']
        allowed = set(applicable_documents(grounding, role))
        field_identity = {}
        # Structured aliases may resolve several physical columns to one count.
        for binding in bindings:
            if binding['role'] != role or binding['claim'] != 'counts':
                continue
            names = {item['official_field'] for item in binding['evidence'] if item.get('official_field')}
            if len(names) == 1:
                field_identity[binding['field']] = next(iter(names))
        for metric, spec in count_specs(resource):
            if isinstance(spec, dict) and ('field' in spec or len(spec.get('sum_fields', [])) == 1):
                from .count_definitions import review_direct_count
                field = spec['field'] if 'field' in spec else spec['sum_fields'][0]
                direct = review_direct_count(contract, resource, metric, field, documents, grounding, accepted, graph)
                if 'issue' in direct:
                    issues.append(direct['issue'])
                else:
                    decision = direct['decision']
                    if 'sum_fields' in spec:decision['claim_type'] = 'identity_count_projection'
                    decisions.append(decision)
                continue
            if not isinstance(spec, dict) or 'sum_fields' not in spec:
                continue
            fields = spec['sum_fields']
            identities = [field_identity.get(field, field) for field in fields]
            if len(set(identities)) != len(identities):
                issues.append({'code': 'COUNT_OPERANDS_OVERLAP', 'role': role, 'metric': metric,
                               'message': 'Two sum operands refer to the same source count.', 'fields': fields})
                continue
            matches, conflicts = [], []
            for key in sorted(allowed):
                node = graph['nodes'][key]
                # Literal text is taken from byte-verified extraction, never a
                # model's narrative. extract() text may be unavailable for PDF;
                # trusted _proof supplies the verified extracted document text.
                statements = list(_statements(node, resource.get('source_url')))
                if node['facts'].get('value') is None:
                    statements = [(line, None) for line in documents[key].get('text', '').splitlines() if line.strip()]
                for statement, pointer in statements:
                    terms = expression(statement, metric)
                    if terms is None:
                        continue
                    # Match exact field names or official aliases only. Whitespace
                    # normalization is not enough to invent a field relationship.
                    resolved = []
                    for term in terms:
                        if term in fields:
                            resolved.append(field_identity.get(term, term))
                        elif term in identities:
                            resolved.append(term)
                        else:
                            resolved.append(None)
                    item = {'document_id': key, 'document_sha256': node['document_sha256'],
                            'statement': statement, 'schema_pointer': pointer, 'operands': terms}
                    if None in resolved or sorted(resolved) != sorted(identities):
                        conflicts.append(item)
                        continue
                    cited = any(entry.get('document_id') == key and
                                (covers_pointer(entry, pointer) if pointer and 'locator' in entry
                                 else ' '.join(statement.split()) in ' '.join(entry.get('quote', '').split()))
                                for entry in accepted.get('counts', []))
                    if cited:
                        matches.append(item)
            if conflicts or not matches:
                issues.append({'code': 'COUNT_SUM_DEFINITION_CONFLICT' if conflicts else 'COUNT_SUM_UNGROUNDED',
                               'role': role, 'metric': metric, 'fields': fields,
                               'message': 'The proposed sum disagrees with a scoped official addition definition.' if conflicts else
                               'Individually documented count fields do not prove this sum. Cite a scoped explicit official addition definition, or map a documented source total directly.',
                               'conflicts': conflicts,
                               'supported_definition': 'A complete literal line or scoped field description: Total casualties = field A + field B. Other prose requires a reviewed semantic interpretation, not a model confirmation.'})
            else:
                decisions.append({'claim_type': 'additive_count_definition', 'role': role, 'metric': metric,
                                  'official_operands': sorted(identities), 'evidence': matches})
    return {'version': VERSION, 'ok': not issues, 'issues': issues, 'decisions': decisions,
            'limitation': 'Bounded direct definitions and explicit addition. Pinned reviewed interpretations have exact source/version scope. No arbitrary prose equivalence or cross-source comparability.'}
