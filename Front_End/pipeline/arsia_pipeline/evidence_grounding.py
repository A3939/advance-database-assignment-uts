"""Deterministic source/field grounding after trusted receipt and quote checks.

This does not decide whether a scientific definition is appropriate. It closes
the narrower failure in which genuine but unrelated official text is cited for
an upload. Only the caller's already verified document bytes/text are consumed.
There are no state adapters, network calls, file reads or model confirmations.
"""
from __future__ import annotations

import re


def _normal(value):
    return " ".join(re.findall(r"[^\W_]+", str(value).casefold(), re.UNICODE))


def _mentioned(field, text):
    field, text = _normal(field), _normal(text)
    return bool(field) and (" " + field + " ") in (" " + text + " ")


def _json_document(doc):
    raw = doc.get("content_bytes", doc.get("text", ""))
    if isinstance(raw, str):
        raw = raw.encode('utf-8')
    if not isinstance(raw, bytes) or not raw.lstrip(b'\xef\xbb\xbf \n\r\t').startswith((b'{', b'[')):
        return None
    from .metadata_extractors import extract
    return extract(raw)['value']


def _schemas(node, prefix=''):
    """Fields of one already scoped metadata object, never nested resources.

    Provider envelopes must be selected by the caller using the evidence graph.
    Recursive field discovery would let a neighbour layer, historical version
    or a record's payload lend its schema to this resource.
    """
    result, has_schema = {}, False
    def merge(incoming):
        for name, definition in incoming.items():
            previous = result.get(name)
            if previous and (previous.get('ambiguous') or previous.get('official_field') != definition.get('official_field')):
                result[name] = {'ambiguous': True, 'official_field': None}
            else:
                result[name] = definition
    from .geometry_evidence import geojson_fields
    fields = geojson_fields(node)
    if fields is not None:
        for name in fields:
            merge({_normal(name): {'official_field': name, 'aliases': [name], 'description': ''}})
        return result, True
    from .evidence_scope import schema_fields
    for raw, aliases, field, pointer in schema_fields(node, []):
        has_schema = True
        for alias in aliases:
            merge({_normal(alias): {"official_field": raw, "aliases": aliases,
                                   "schema_pointer": prefix + pointer,
                                   "description_pointer": prefix + pointer + ('/description' if 'description' in field else '/definition'),
                                   "description": field.get("description", field.get("definition", ""))}})
    return result, has_schema


def _geometry_metadata(node):
    from .geometry_evidence import geometry_metadata
    point, refs = geometry_metadata(node)
    return point, {r['code'] for r in refs if 'code' in r}


def _critical_fields(contract, *, include_lookup_fields=True):
    required = []
    def add(role, claim, value):
        if isinstance(value, str) and value:
            required.append((role, claim, value))
        elif isinstance(value, dict) and include_lookup_fields:
            from .lookup_semantics import field_origin
            resource = next(r for r in contract.get('resources', []) if r['role'] == role)
            origin = field_origin(contract, resource, value)
            required.append((origin['role'], claim, origin['field']))
    def counts(role, value):
        if isinstance(value, dict):
            add(role, "counts", value.get("field"))
            for field in value.get("sum_fields", []):
                add(role, "counts", field)
    for resource in contract.get("resources", []):
        role = resource["role"]
        for field in resource.get("key", []):
            add(role, "grain", field)
        mapping = resource.get("mapping", {})
        for key in ("field", "year_field", "month_field"):
            add(role, "date", mapping.get("date", {}).get(key))
        for kind in ("severity", "injury"):
            add(role, "severity", mapping.get(kind, {}).get("field"))
        for kind in ("fatalities", "casualties", "declared_units", "declared_casualties"):
            counts(role, mapping.get(kind))
        for value in mapping.get("metrics", {}).values():
            counts(role, value)
        for key in ("x_field", "y_field", "region_field"):
            add(role, "geography", mapping.get("geography", {}).get(key))
        for field in mapping.get("unit_key", []):
            add(role, "relations", field)
        if include_lookup_fields:
            # These positions previously had no field proof. Require it for
            # new lookup semantics without changing legacy native contracts.
            if isinstance(mapping.get('unit_type'), dict):add(role, 'grain', mapping['unit_type'])
            for value in mapping.get('dimensions', {}).values():
                if isinstance(value, dict):add(role, 'grain', value)
            parents = {r['role']: r for r in contract.get('lookup_tables', [])}
            for lookup in resource.get('lookups', []):
                for field in lookup.get('fields', []):add(role, 'relations', field)
                parent = parents.get(lookup.get('parent'))
                if parent:
                    for field in parent.get('key', []):add(parent['role'], 'relations', field)
    roles = {resource["role"]: resource for resource in contract.get("resources", [])}
    for relation in contract.get("relations", []):
        for field in relation.get("fields", []):
            add(relation["child"], "relations", field)
        for field in roles.get(relation["parent"], {}).get("key", []):
            add(relation["parent"], "relations", field)
    return list(dict.fromkeys(required))


def ground_contract(contract, documents, accepted, *, graph=None, coordinate_proofs=None):
    """Return diagnostics over documents already verified by trusted QA.

    ``documents`` is ``{document_id: {url,text,sha256,content_bytes?}}`` from
    immutable fetch receipts. ``accepted`` is the caller's exact-quote-checked
    evidence grouped by claim. Any issue blocks this candidate; callers must
    never silently remove a geography mapping or alter its contract here.
    """
    source_url = contract.get("source", {}).get("dataset_url", "")
    from .metadata_extractors import MetadataError
    from .evidence_graph import build_graph
    try:
        if graph is None:
            graph = build_graph(source_url, documents,
                                {entry.get('document_id') for entry in accepted.get('source_identity', [])})
        from .evidence_scope import build_applicability
        applicability = build_applicability(contract, graph)
    except MetadataError as exc:
        return {'ok': False, 'issues': [{'code': exc.code, 'message': str(exc)}], 'field_bindings': [],
                'source_anchor_documents': [], 'connected_documents': []}
    anchors, connected = graph['anchors'], graph['authorized']
    info = {}
    for key, node in graph['nodes'].items():
        value = node['facts'].get('value')
        info[key] = {'data': value}
    issues, bindings = list(applicability['issues']), []
    expected_checks=[{'code':'SOURCE_IDENTITY_UNBOUND','claim':'source_identity'}]
    expected_checks += [{'code':'CLAIM_SCOPE_UNBOUND','claim':claim} for claim,entries in accepted.items() if entries]
    for role,scope in applicability['roles'].items():
        expected_checks += [{'code':'RESOURCE_IDENTITY_UNBOUND','role':role},
                            {'code':'CLAIM_APPLICABILITY_UNBOUND','role':role,'claim':'coverage_update'}]
    if not anchors:
        issues.append({"code": "SOURCE_IDENTITY_UNBOUND", "claim": "source_identity",
                       "message": "No cited official document identifies the declared dataset URL or links its resource. A shared government host is insufficient."})
    for claim, entries in accepted.items():
        scope = anchors if claim == 'source_identity' else connected
        if entries and not any(entry.get('document_id') in scope for entry in entries):
            issues.append({'code': 'CLAIM_SCOPE_UNBOUND', 'claim': claim,
                           'message': 'Cited documents do not have publisher authority for this dataset claim.'})
    for role, scope in applicability['roles'].items():
        entries = accepted.get('coverage_update', [])
        if entries and not any(entry.get('document_id') in scope['applicable_documents'] for entry in entries):
            issues.append({'code':'CLAIM_APPLICABILITY_UNBOUND','role':role,'claim':'coverage_update',
                           'message':'Coverage/update evidence does not apply to this resource and declared time range. Document timestamps or versions cannot grant snapshot deletion authority.'})
    for role, claim, field in _critical_fields(contract):
        expected_checks.append({'code':'MAPPED_FIELD_UNGROUNDED','role':role,'claim':claim,'field':field})
        from .evidence_references import covers_pointer
        applicable = set(applicability['roles'][role]['applicable_documents'])
        matches = []
        for entry in accepted.get(claim, []):
            key = entry.get("document_id")
            if key not in applicable:
                continue
            point, _ = _geometry_metadata(info[key]["data"])
            from .geometry_evidence import geometry_metadata
            geometry_pointers = ['/type', '/geometryType'] + [item['locator'] for item in geometry_metadata(info[key]['data'])[1] if 'locator' in item]
            if claim == "geography" and field in {"__geometry_x", "__geometry_y"} and point and any(covers_pointer(entry, p) for p in geometry_pointers):
                matches.append({"document_id": key, "mode": "trusted_point_geometry_reader", "official_field": "geometry"})
            from .evidence_scope import schema_subjects
            from .metadata_extractors import _token
            scope = applicability['roles'][role]
            target = scope['source_url'] if scope['selected_resource_explicitly'] else None
            for schema_node, path in schema_subjects(graph['nodes'][key], target):
                prefix = '/' + '/'.join(_token(part) for part in path) if path else ''
                schema, _ = _schemas(schema_node, prefix)
                definition = schema.get(_normal(field))
                if definition and not definition.get('ambiguous') and covers_pointer(entry, definition.get('schema_pointer')):
                    matches.append({"document_id": key, "mode": "official_structured_field", **definition})
            # JSON without a recognized schema is not a plain-text dictionary:
            # string-searching its serialization reintroduces nested scope leaks.
            if info[key]['data'] is None and _mentioned(field, entry.get('quote', '') if 'locator' in entry else documents[key].get("text", "")):
                matches.append({"document_id": key, "mode": "official_text_field", "official_field": field})
        if matches:
            bindings.append({"role": role, "claim": claim, "field": field, "evidence": matches})
        else:
            issues.append({"code": "MAPPED_FIELD_UNGROUNDED", "role": role, "claim": claim, "field": field,
                           "scope_role": role,
                           "message": "Mapped field is absent OR its exact field-definition pointer is not cited for this claim in an applicable official dictionary. Cite the field descriptor as well as semantic definitions; unrelated pointers are insufficient."})
    from .table_plan import expand_resources
    from .lookup_semantics import geography_resources
    for resource in expand_resources(geography_resources(contract)):
        geography = resource.get("mapping", {}).get("geography")
        if not geography:
            continue
        crs = str(geography.get("crs", ""))
        applicable = set(applicability['roles'][resource['role']]['coordinate_documents'])
        expected_checks += [{'code':code,'role':resource['role'],'claim':'geography'} for code in ('CRS_UNGROUNDED','CRS_EVIDENCE_CONFLICT')]
        evidence_items = []
        from .geography_review import coordinate_evidence, coordinate_crs_matches
        for proof in coordinate_proofs or []:
            if (proof.get('role') == resource['role'] and proof.get('file_id') == resource.get('file_id')
                    and (proof.get('x_field'), proof.get('y_field')) == (geography.get('x_field'), geography.get('y_field'))):
                evidence_items.append(proof)
        # Known scoped contradictions cannot be hidden by omitting one citation
        # from the model's proposal. Authority/applicability were host-derived.
        for key in sorted(applicable):
            evidence = coordinate_evidence(key, documents[key], geography.get("x_field", ""), geography.get("y_field", ""))
            evidence_items.extend(evidence)
        matches = [coordinate_crs_matches(item, crs) for item in evidence_items]
        if any(matches) and not all(matches):
            issues.append({'code': 'CRS_EVIDENCE_CONFLICT', 'role': resource['role'], 'claim': 'geography',
                           'crs': crs, 'evidence': evidence_items,
                           'message': 'Scoped coordinate declarations disagree. Resolve the resource/version applicability before admission.'})
        elif not matches or not all(matches):
            issues.append({"code": "CRS_UNGROUNDED", "role": resource["role"], "claim": "geography", "crs": crs,
                           "message": "The declared CRS lacks scoped official coordinate-system evidence. Resolve the field and CRS binding without discarding documented source coordinates."})
    from .issue_progress import SUBJECT
    def same(check,issue):
        return check['code']==issue['code'] and all(check.get(k)==issue.get(k) for k in SUBJECT)
    checks=[{**check,'status':'fail' if any(same(check,i) for i in issues) else 'pass'} for check in expected_checks]
    return {"ok": not issues, "issues": issues, 'checks':checks, "field_bindings": bindings,
            "applicability": applicability,
            "source_anchor_documents": sorted(anchors), "connected_documents": sorted(connected),
            "evidence_graph": graph['proof'],
            "coordinate_proofs": coordinate_proofs or [],
            "limitation": "Field/source grounding complements exact quotes and full replay; it does not establish scientific comparability or resolve contradictory official definitions."}
