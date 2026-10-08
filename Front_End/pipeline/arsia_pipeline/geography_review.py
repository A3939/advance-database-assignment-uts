"""Detect omitted documented coordinates using trusted observed table fields.

Inputs are supplied by QA after receipt/hash and dataset-connectivity checks.
This review never chooses a CRS, rewrites a contract, or authorizes an adapter.
"""
import re

from .evidence_grounding import _geometry_metadata, _json_document, _normal, _schemas

EPSG = re.compile(r"\bEPSG\s*[:=#]?\s*(\d{3,6})\b", re.I)
AXES = {"x": "x", "easting": "x", "longitude": "x", "lon": "x", "lng": "x",
        "y": "y", "northing": "y", "latitude": "y", "lat": "y"}


def coordinate_pairs(fields):
    """Names identify review candidates only; official field+CRS proof is required."""
    groups = {}
    for field in fields:
        tokens = _normal(field).split()
        positions = [i for i, token in enumerate(tokens) if token in AXES]
        if len(positions) != 1:
            continue
        i = positions[0]
        # Axis names must identify the same pair, not merely two numeric fields.
        family = "geographic" if tokens[i] in {"longitude", "latitude", "lon", "lat", "lng"} else "cartesian"
        key = (family, tuple(tokens[:i] + tokens[i + 1:]))
        groups.setdefault(key, {}).setdefault(AXES[tokens[i]], []).append(field)
    return [(value["x"][0], value["y"][0]) for value in groups.values()
            if len(value.get("x", [])) == len(value.get("y", [])) == 1]


def _field_locations(field, text):
    # Permit punctuation/spacing differences used by official dictionaries,
    # without accepting model-declared aliases or a partial-name substring.
    tokens = re.findall(r"[^\W_]+", field, re.UNICODE)
    if not tokens:
        return []
    pattern = r"(?<!\w)" + r"[\W_]+".join(re.escape(token) for token in tokens) + r"(?!\w)"
    return list(re.finditer(pattern, text, re.I))


def _text_evidence(document_id, document, x, y):
    text = document.get("text", "")
    xs, ys = _field_locations(x, text), _field_locations(y, text)
    for crs in EPSG.finditer(text):
        # A nearby coordinate declaration and both real field names are needed;
        # an EPSG elsewhere in a large dictionary is insufficient.
        near_x = [m for m in xs if abs(m.start() - crs.start()) <= 1200]
        near_y = [m for m in ys if abs(m.start() - crs.start()) <= 1200]
        if not near_x or not near_y:
            continue
        mx = min(near_x, key=lambda m: abs(m.start() - crs.start()))
        my = min(near_y, key=lambda m: abs(m.start() - crs.start()))
        start = max(0, min(mx.start(), my.start(), crs.start()) - 50)
        end = min(len(text), max(mx.end(), my.end(), crs.end()) + 100)
        quote = text[start:end]
        if not re.search(r"\b(?:coordinate|coordinates|projection|datum|spatial reference|CRS)\b", quote, re.I):
            continue
        yield {"document_id": document_id, "url": document.get("url"), "crs": "EPSG:" + crs[1],
               "quote": quote, "start": start, "end": end, "mode": "official_text_coordinate_declaration"}


def specific_document(document):
    """Broad catalogue results are discovery, not per-resource scope proof.

    Connectivity may validly identify one package in a search response. Its
    neighbouring packages must never lend CRS or completeness declarations.
    Fetch the dedicated package/layer document for these stronger decisions.
    """
    data = _json_document(document)
    if isinstance(data, dict):
        nodes = [data, data.get("result")]
        if any(isinstance(node, dict) and any(isinstance(node.get(key), list) for key in ("results", "datasets")) for node in nodes):
            return False
    return True


def coordinate_evidence(document_id, document, x, y):
    if not specific_document(document):
        return []
    data = _json_document(document)
    _, structured = _schemas(data)
    from .geometry_evidence import geometry_metadata
    point, references = geometry_metadata(data)
    evidence = []
    if point and (x, y) == ("__geometry_x", "__geometry_y"):
        evidence.extend({"document_id": document_id, "url": document.get("url"),
            "mode": "official_structured_geometry_metadata", **reference} for reference in references)
    # A layer's spatialReference applies to its geometry, not arbitrary numeric
    # attributes such as station/local-grid X and Y. Structured attribute fields
    # need a separate explicit field-pair declaration rather than nearby JSON.
    if not structured and data is None:
        evidence.extend(_text_evidence(document_id, document, x, y))
    return evidence


def coordinate_crs_matches(evidence, declared):
    from pyproj import CRS
    try:
        wanted = CRS.from_user_input(declared)
        if evidence.get("crs"):
            return wanted.equals(CRS.from_user_input(evidence["crs"]), ignore_axis_order=True)
        if evidence.get("authority") != "ArcGIS WKID":
            return False
        candidates = []
        for authority in ("EPSG", "ESRI"):
            try:
                candidates.append(CRS.from_authority(authority, evidence["code"]))
            except Exception:
                pass
        # Resolve only recognized, unambiguous database definitions. Never turn
        # the integer WKID into an invented EPSG authority label.
        return bool(candidates) and all(wanted.equals(candidate, ignore_axis_order=True) for candidate in candidates)
    except Exception:
        return False


def review_geography(contract, documents, grounding, observed_fields):
    """Return a required review when proven source coordinates were omitted.

    `observed_fields` maps resource role to the actual selected table header.
    Callers must obtain it from trusted readers, never a model-supplied list.
    Missing or ambiguous metadata stays unsupported rather than guessing a CRS.
    """
    findings = []
    for resource in contract.get("resources", []):
        if resource.get("grain") not in {"crash", "observation"}:
            continue
        role = resource["role"]
        geography = resource.get("mapping", {}).get("geography") or {}
        pairs = coordinate_pairs(observed_fields.get(role, []))
        if geography.get("crs") and (geography.get("x_field"), geography.get("y_field")) in pairs:
            # One supported representation is sufficient when a table supplies
            # both projected and longitude/latitude coordinate pairs.
            continue
        for x, y in pairs:
            evidence = [proof for proof in grounding.get('coordinate_proofs', [])
                        if proof.get('role') == role and proof.get('file_id') == resource.get('file_id')
                        and (proof.get('x_field'), proof.get('y_field')) == (x, y)]
            from .evidence_scope import applicable_documents
            for document_id in applicable_documents(grounding,role):
                document = documents.get(document_id)
                if not document:
                    continue
                evidence.extend(coordinate_evidence(document_id, document, x, y))
            if not evidence:
                continue
            findings.append({"code": "CAPABILITY_REVIEW_REQUIRED", "claim": "geography", "role": role,
                "file_id": resource.get("file_id"), "fields": {"x_field": x, "y_field": y},
                "official_evidence": evidence[:8],
                "message": "The actual table contains a coordinate pair with connected official CRS metadata, but the contract omits this geographic capability.",
                "next_action": "Read the cited official evidence, add an evidence-backed geography mapping, then rerun sample and full QA. If it does not apply to this resource, request clarification with the conflicting official evidence; a free-text unsupported claim cannot bypass this review."})
    return {"ok": not findings, "issues": findings}


def coordinate_subject(statement):
    """Whole definitions identify what a position locates, independently of CRS."""
    if not isinstance(statement, str) or len(statement) > 2048:return None
    text = ' '.join(statement.split()).removesuffix('.').casefold()
    match = re.fullmatch(r'(longitude|latitude|easting|northing|x|y) coordinates? of (?:the |a )?'
                         r'(crash|accident|observation|station|postcode|region|area|area centroid|postcode centroid)', text)
    if not match:return None
    axis, subject = match.groups()
    return {'axis': 'x' if axis in {'longitude', 'easting', 'x'} else 'y',
            'subject': 'crash' if subject == 'accident' else subject}


def review_lookup_geography_subject(contract, documents, grounding, accepted, graph):
    from .lookup_semantics import geography_resources
    from .count_definitions import _structured, _cited
    from .evidence_scope import applicable_documents
    issues, decisions = [], []
    for resource in geography_resources(contract):
        consumer = resource.get('lookup_consumer')
        if not consumer:continue
        expected = resource['grain']; role = resource['role']
        geo = resource['mapping']['geography']
        for axis in ('x', 'y'):
            field = geo[axis + '_field']; facts, unresolved = [], []
            for key in applicable_documents(grounding, role):
                node = graph['nodes'][key]
                for statement, pointer in _structured(node, field, resource.get('source_url')):
                    meaning = coordinate_subject(statement)
                    fact = {'document_id': key, 'document_sha256': node['document_sha256'],
                            'schema_pointer': pointer, 'statement': statement, 'meaning': meaning,
                            'cited': _cited(accepted.get('geography', []), key, statement, pointer)}
                    (facts if meaning else unresolved).append(fact)
            conflicts = [fact for fact in facts if fact['meaning'] != {'axis': axis, 'subject': expected}]
            matches = [fact for fact in facts if fact not in conflicts and fact['cited']]
            if conflicts or unresolved or not matches:
                issues.append({'code': 'LOOKUP_GEOGRAPHY_SUBJECT_CONFLICT' if conflicts else 'LOOKUP_GEOGRAPHY_SUBJECT_UNGROUNDED',
                               'role': consumer['role'], 'parent_role': role, 'lookup': consumer['lookup'],
                               'field': field, 'expected': {'axis': axis, 'subject': expected},
                               'conflicts': conflicts, 'unresolved': unresolved,
                               'message': 'A parent coordinate needs a scoped field definition identifying the output event/observation and correct axis. CRS and a foreign key alone do not establish this meaning.'})
            else:
                decisions.append({'role': consumer['role'], 'parent_role': role, 'lookup': consumer['lookup'],
                                  'field': field, 'axis': axis, 'subject': expected, 'evidence': matches})
    return {'version': 'lookup-coordinate-subject-v1', 'ok': not issues, 'issues': issues, 'decisions': decisions,
            'limitation': 'Explicit structured field definitions only. Not source positional accuracy, CRS authority, verified foreign-key meaning, upload provenance or admission.'}
