"""Scoped publisher code/label dictionaries; no record-frequency inference.

Supports ArcGIS coded domains and single-field unique-value renderers. Renderer
groups take precedence over legacy infos. Default symbols and Arcade expressions
cannot authorize unspecified classifications. Labels remain source-specific;
the small outcome vocabulary does not define mortality windows or harmonize
injury severity between publishers.
"""
from .evidence_references import covers_pointer
from .evidence_scope import applicable_documents
from .metadata_extractors import _token

VERSION = 'scoped-category-evidence-v1'
SPEC = 'https://developers.arcgis.com/web-map-specification/objects/uniqueValueRenderer/'


def _label(value):
    return ' '.join(value.split()).casefold() if isinstance(value, str) else ''


def fatal_flag(label):
    """Interpret named source outcomes; unknown labels stay explicitly unknown."""
    value = _label(label)
    if value in {'fatal', 'fatal crash', 'fatality', 'killed'}:
        return True
    if value in {'property damage only', 'pdo', 'pdo major', 'pdo minor',
                 'non-fatal', 'non fatal', 'non-fatal injury', 'non fatal injury',
                 'injury', 'minor injury', 'serious injury', 'first aid', 'minor',
                 'serious', 'hospital', 'medical'}:
        return False
    return None


def extract_categories(data, prefix=''):
    records, issues, declared = [], [], set()
    if not isinstance(data, dict):
        return {'records': records, 'issues': issues, 'declared_fields': []}

    def issue(field, code, message):
        issues.append({'field': field, 'code': code, 'message': message})

    def add(field, code, label, pointer, kind):
        if type(code) not in (str, int) or not isinstance(label, str) or not label.strip() or len(label) > 1024:
            issue(field, 'CATEGORY_METADATA_INVALID', 'An explicit bounded code and label are required.')
            return
        records.append({'field': field, 'code': str(code), 'label': label, 'locator': prefix + pointer, 'kind': kind})

    fields = data.get('fields', [])
    if isinstance(fields, list):
        for index, field in enumerate(fields):
            if not isinstance(field, dict) or not isinstance(field.get('name'), str):
                continue
            domain = field.get('domain')
            if not isinstance(domain, dict) or domain.get('type') != 'codedValue':
                continue
            name = field['name']; declared.add(name)
            values = domain.get('codedValues')
            if not isinstance(values, list) or len(values) > 2048:
                issue(name, 'CATEGORY_METADATA_INVALID', 'Invalid or oversized coded-value domain.')
                continue
            for position, value in enumerate(values):
                if not isinstance(value, dict):
                    issue(name, 'CATEGORY_METADATA_INVALID', 'Invalid coded-value entry.')
                    continue
                add(name, value.get('code'), value.get('name'), f'/fields/{index}/domain/codedValues/{position}', 'coded_value_domain')

    drawing = data.get('drawingInfo', {})
    renderer = drawing.get('renderer') if isinstance(drawing, dict) else None
    if not isinstance(renderer, dict) or renderer.get('type') != 'uniqueValue':
        return {'records': records, 'issues': issues, 'declared_fields': sorted(declared)}
    field = renderer.get('field1')
    if not isinstance(field, str) or not field:
        # Expression-based renderers without field1 are reported separately;
        # they cannot accidentally become a dictionary for every source field.
        if renderer.get('valueExpression'):
            issue(None, 'CATEGORY_EXPRESSION_UNSUPPORTED', 'Expression-based category renderers need a reviewed transformation plan.')
        return {'records': records, 'issues': issues, 'declared_fields': sorted(declared)}
    declared.add(field)
    if renderer.get('field2') or renderer.get('field3') or renderer.get('valueExpression'):
        issue(field, 'CATEGORY_EXPRESSION_UNSUPPORTED', 'Composite or expression-based renderers cannot authorize a single-field category map.')
        return {'records': records, 'issues': issues, 'declared_fields': sorted(declared)}
    base = '/drawingInfo/renderer'
    if 'uniqueValueGroups' in renderer:
        groups = renderer['uniqueValueGroups']
        if not isinstance(groups, list) or len(groups) > 2048:
            issue(field, 'CATEGORY_METADATA_INVALID', 'Invalid renderer groups.')
        else:
            for gi, group in enumerate(groups):
                classes = group.get('classes') if isinstance(group, dict) else None
                if not isinstance(classes, list) or len(classes) > 2048:
                    issue(field, 'CATEGORY_METADATA_INVALID', 'Invalid renderer classes.'); continue
                for ci, item in enumerate(classes):
                    values = item.get('values') if isinstance(item, dict) else None
                    if not isinstance(values, list) or len(values) > 2048:
                        issue(field, 'CATEGORY_METADATA_INVALID', 'Invalid class value tuples.'); continue
                    for value in values:
                        if not isinstance(value, list) or len(value) != 1:
                            issue(field, 'CATEGORY_EXPRESSION_UNSUPPORTED', 'A single-field class needs one-element value tuples.'); continue
                        add(field, value[0], item.get('label'), f'{base}/uniqueValueGroups/{gi}/classes/{ci}', 'renderer_group')
    else:
        values = renderer.get('uniqueValueInfos', [])
        if not isinstance(values, list) or len(values) > 2048:
            issue(field, 'CATEGORY_METADATA_INVALID', 'Invalid renderer values.')
        else:
            for index, item in enumerate(values):
                if not isinstance(item, dict):
                    issue(field, 'CATEGORY_METADATA_INVALID', 'Invalid renderer value.'); continue
                add(field, item.get('value'), item.get('label'), f'{base}/uniqueValueInfos/{index}', 'renderer_info')
    return {'records': records, 'issues': issues, 'declared_fields': sorted(declared)}


def review_categories(contract, graph, grounding, accepted):
    issues, decisions, origins = [], [], []
    for resource in contract.get('resources', []):
        for kind in ('severity', 'injury'):
            mapping = resource.get('mapping', {}).get(kind)
            if not isinstance(mapping, dict):
                continue
            role, field = resource['role'], mapping.get('field')
            physical = resource
            if isinstance(field, dict):
                from .lookup_semantics import field_origin
                origin = field_origin(contract, resource, field)
                origins.append({'consumer_role': role, 'mapping': kind, **origin})
                role, field = origin['role'], origin['field']
                physical = next(r for r in contract['lookup_tables'] if r['role'] == role)
            categories = mapping.get('categories', {})
            if not isinstance(categories, dict):
                issues.append({'code': 'CATEGORY_MAPPING_INVALID', 'role': role, 'field': field, 'message': 'Category mapping must be an object.'})
                continue
            # Canonical category identifiers drive aggregation. Different source
            # meanings must not collapse into one identifier, even when each
            # individual source label has valid evidence. Same-label aliases
            # remain allowed; cross-source harmonization needs its own plan.
            meanings = {}
            if kind == 'severity':
                for code, proposed in categories.items():
                    if not isinstance(proposed, dict) or not isinstance(proposed.get('code'), str) or not proposed['code']:
                        issues.append({'code': 'CATEGORY_MAPPING_INVALID', 'role': role, 'field': field, 'source_code': code,
                                       'message': 'Each severity category needs a nonempty canonical identifier.'})
                        continue
                    meaning = (_label(proposed.get('label')), proposed.get('is_fatal_crash'))
                    identifier = proposed['code']
                    if identifier in meanings and meanings[identifier] != meaning:
                        issues.append({'code': 'CATEGORY_CODE_COLLISION', 'role': role, 'field': field, 'source_code': code,
                                       'message': 'One canonical category identifier cannot combine different source labels or outcomes.'})
                    meanings[identifier] = meaning
            official = {field}
            for binding in grounding.get('field_bindings', []):
                if binding['role'] == role and binding['claim'] == 'severity' and binding['field'] == field:
                    official.update(e['official_field'] for e in binding['evidence'] if e.get('official_field'))
            records, declared, unbound_expressions = [], False, []
            for key in applicable_documents(grounding, role):
                node = graph['nodes'][key]
                from .evidence_scope import schema_subjects
                for data, path in schema_subjects(node, physical.get('source_url')):
                    prefix = '/' + '/'.join(_token(part) for part in path) if path else ''
                    extracted = extract_categories(data, prefix)
                    declared |= bool(official.intersection(extracted['declared_fields']))
                    issues.extend({**item, 'role': role} for item in extracted['issues'] if item['field'] in official)
                    unbound_expressions.extend(item for item in extracted['issues'] if item['field'] is None)
                    records.extend({**item, 'document_id': key, 'document_sha256': node['document_sha256']}
                                   for item in extracted['records'] if item['field'] in official)
            if not declared:
                if unbound_expressions:
                    issues.extend({**item, 'role': role, 'field': field} for item in unbound_expressions)
                    continue
                decisions.append({'role': role, 'field': field, 'status': 'legacy_text_scope',
                                  'limitation': 'No supported structured classification dictionary; existing text grounding remains, not a new classification proof.'})
                continue
            for code, proposed in categories.items():
                matches = [item for item in records if item['code'] == code]
                labels = {_label(item['label']) for item in matches}
                issue = None
                if len(labels) > 1:
                    issue = ('CATEGORY_DEFINITION_CONFLICT', 'Scoped official category labels disagree for this code.')
                elif not matches:
                    issue = ('CATEGORY_CODE_UNGROUNDED', 'This code has no explicit scoped official dictionary entry; a default symbol is insufficient.')
                elif not isinstance(proposed, dict):
                    issue = ('CATEGORY_MAPPING_INVALID', 'Each category must be a declared mapping object.')
                else:
                    label = matches[0]['label']; flag = fatal_flag(label)
                    flag_key = 'is_fatal_crash' if kind == 'severity' else 'is_fatal'
                    if proposed.get(flag_key) is not flag:
                        issue = ('CATEGORY_OUTCOME_CONFLICT', 'Fatal/unknown classification differs from the supported source-label meaning; unfamiliar outcomes stay unknown.')
                    elif kind == 'severity' and _label(proposed.get('label')) != _label(label):
                        issue = ('CATEGORY_LABEL_MISMATCH', 'Preserve the explicit official source category label.')
                    elif proposed.get('standard_code') is not None:
                        issue = ('CATEGORY_HARMONIZATION_UNPROVEN', 'A source label does not authorize a cross-source standardized severity category.')
                    else:
                        cited = any(entry.get('document_id') == item['document_id'] and
                                    (covers_pointer(entry, item['locator']) if 'locator' in entry else item['label'] in entry.get('quote', ''))
                                    for item in matches for entry in accepted.get('severity', []))
                        if not cited:
                            issue = ('CATEGORY_CITATION_REQUIRED', 'Cite the exact official category entry or its renderer/domain, not only the field name.')
                if issue:
                    issues.append({'code': issue[0], 'message': issue[1], 'role': role, 'field': field, 'source_code': code})
                else:
                    decisions.append({'role': role, 'field': field, 'source_code': code, 'source_label': label,
                                      'fatal_flag': flag, 'status': 'structured_category_bound', 'evidence': matches})
    return {'version': VERSION, 'ok': not issues, 'issues': issues, 'decisions': decisions,
            **({'lookup_field_origins': origins} if origins else {}),
            'limitation': 'Named source classifications only; does not define mortality time windows, injury comparability, or person counts.'}
