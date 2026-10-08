"""Host-only proof joining a provider dictionary, RDF samples and an upload.

The provider protocol, not a state or dataset ID, selects this rule. Source
coordinates are never replaced with downloaded records. A finite official
sample proves only those keys; the full upload comparison proves internal
field correspondence, not publisher certification of every row.
"""
from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re

from .intakereaders import detect_tables, iter_table
from .metadata_extractors import GEO

VERSION = 'socrata-rdf-coordinate-binding-v1'
TOLERANCE_DEGREES = Decimal('0.0000001')
NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
PAIR = re.compile(r'\s*\(\s*(' + NUMBER + r')\s*,\s*(' + NUMBER + r')\s*\)\s*')
RDFS_MEMBER = '{http://www.w3.org/2000/01/rdf-schema#}member'


class CoordinateBindingError(ValueError):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def _normal(value):
    return ' '.join(re.findall(r'[^\W_]+', str(value).casefold()))


def _column(columns, field):
    found = [c for c in columns if isinstance(c, dict) and _normal(field) in
             {_normal(c.get('name', '')), _normal(c.get('fieldName', ''))}]
    if len(found) != 1 or not isinstance(found[0].get('fieldName'), str):
        return None
    return found[0]


def _number(value):
    try:
        result = Decimal(str(value))
        if not result.is_finite():
            raise InvalidOperation()
        return result
    except (InvalidOperation, ValueError):
        raise CoordinateBindingError('RDF_COORDINATE_INVALID', 'Coordinate representation is not a finite decimal.') from None


def _location(value):
    if isinstance(value, dict) and 'latitude' in value and 'longitude' in value:
        return _number(value['longitude']), _number(value['latitude'])
    if isinstance(value, str):
        pair = PAIR.fullmatch(value)
        if pair:
            return _number(pair[2]), _number(pair[1])
    raise CoordinateBindingError('RDF_LOCATION_UNSUPPORTED', 'Uploaded location representation has no supported longitude/latitude structure.')


def _literal(point, namespace, name):
    values = point['record_literals'].get('{' + namespace + '}' + name, [])
    if len(values) != 1:
        raise CoordinateBindingError('RDF_FIELD_BINDING_MISSING', 'Official RDF sample does not bind the required field.', field=name)
    return values[0]


def prove_resource(resource, file, documents, graph, *, check_cancelled=lambda: None):
    geography = resource.get('mapping', {}).get('geography')
    if not geography:
        return []
    proofs = []
    tables = detect_tables(file, resource.get('table', {}), check_cancelled)
    selected = resource.get('table', {}).get('sheet', resource.get('table', {}).get('table_id'))
    tables = [table for table in tables if table['table_id'] == selected or selected is None and len(tables) == 1]
    if len(tables) != 1:
        return []
    table = tables[0]
    for metadata_id in sorted(graph['authorized']):
        node = graph['nodes'][metadata_id]
        ident = node['identity']
        data = node['facts'].get('value', {})
        if (not ident or ident['kind'] != 'socrata' or not isinstance(data, dict)
                or data.get('id') != ident['dataset'] or not isinstance(data.get('columns'), list)):
            continue
        columns = data['columns']
        xcol, ycol = (_column(columns, geography.get(axis, '')) for axis in ('x_field', 'y_field'))
        keycols = [_column(columns, field) for field in resource.get('key', [])]
        if not xcol or not ycol or not keycols or any(c is None for c in keycols):
            continue
        base = 'https://' + ident['host'] + '/resource/'
        dataset_uri = base + '_' + ident['dataset']
        namespace = dataset_uri + '/'
        for location_column in columns:
            if not isinstance(location_column, dict) or location_column.get('dataTypeName') != 'location':
                continue
            names = [name for name in table['header'] if _column([location_column], name)]
            if len(names) != 1:
                continue
            location_field = names[0]
            samples, evidence = {}, []
            for rdf_id in sorted(graph['authorized']):
                rdf_node = graph['nodes'][rdf_id]
                if rdf_node['identity'] != ident:
                    continue
                for point in rdf_node['facts'].get('rdf_points', []):
                    if point['namespace'] != GEO or point['property'] != '{' + namespace + '}' + location_column['fieldName']:
                        continue
                    # Socrata's record class is in /resource/, while its field
                    # vocabulary is in /resource/_<dataset>/. Both must bind
                    # the same dataset; matching only a property namespace is
                    # not a record-level identity proof.
                    if point['record_type'] != '{' + base + '}_' + ident['dataset']:
                        continue
                    subject = point.get('subject') or ''
                    if not subject.startswith(namespace) or not re.fullmatch(r'row-[A-Za-z0-9._~-]+', subject[len(namespace):]):
                        continue
                    if point.get('record_references', {}).get(RDFS_MEMBER) != [dataset_uri]:
                        continue
                    key = tuple(_literal(point, namespace, c['fieldName']) for c in keycols)
                    x = _number(_literal(point, namespace, xcol['fieldName']))
                    y = _number(_literal(point, namespace, ycol['fieldName']))
                    lon, lat = _number(point['longitude']), _number(point['latitude'])
                    if not (-180 <= lon <= 180 and -90 <= lat <= 90) or max(abs(x-lon), abs(y-lat)) > TOLERANCE_DEGREES:
                        raise CoordinateBindingError('RDF_AXIS_CONFLICT', 'Official sample coordinate fields disagree with its WGS84 properties.', document_id=rdf_id)
                    if key in samples and samples[key] != (x, y):
                        raise CoordinateBindingError('RDF_SAMPLE_CONFLICT', 'Official sample receipts disagree for the same key.', document_id=rdf_id)
                    samples[key] = (x, y)
                    evidence.append({'document_id': rdf_id, 'sha256': rdf_node['document_sha256'],
                                     'latitude_locator': point['latitude_locator'], 'longitude_locator': point['longitude_locator']})
            if not samples:
                continue
            path = Path(file['path'])
            if path.is_symlink():
                raise CoordinateBindingError('RDF_INPUT_CHANGED', 'Input must be an immutable regular file.')
            with path.open('rb') as stream:
                input_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
            if file.get('sha256') != input_hash:
                raise CoordinateBindingError('RDF_INPUT_CHANGED', 'Upload bytes do not match the admitted receipt.')
            count = paired = missing = 0
            maximum = Decimal(0)
            matched = Counter()
            comparison_hash = hashlib.sha256()
            for locator, row in iter_table(file, table, check_cancelled):
                count += 1
                values = [row.get(geography['x_field']), row.get(geography['y_field']), row.get(location_field)]
                blank = [v in (None, '') for v in values]
                if all(blank):
                    missing += 1
                    continue
                if any(blank):
                    raise CoordinateBindingError('RDF_UPLOAD_BINDING_INCOMPLETE', 'Coordinate representations are only partially present.', row_locator=locator)
                x, y = _number(values[0]), _number(values[1])
                lon, lat = _location(values[2])
                delta = max(abs(x-lon), abs(y-lat))
                if not (-180 <= lon <= 180 and -90 <= lat <= 90) or delta > TOLERANCE_DEGREES:
                    raise CoordinateBindingError('RDF_UPLOAD_COORDINATE_CONFLICT', 'Upload coordinate fields disagree with the documented location.', row_locator=locator)
                maximum = max(maximum, delta)
                paired += 1
                key = tuple(str(row.get(field, '')) for field in resource['key'])
                if key in samples:
                    sx, sy = samples[key]
                    if max(abs(sx-x), abs(sy-y)) > TOLERANCE_DEGREES:
                        raise CoordinateBindingError('RDF_OFFICIAL_SAMPLE_MISMATCH', 'Uploaded key coordinates differ from the official sample.', row_locator=locator)
                    matched[key] += 1
                comparison_hash.update(json.dumps([locator, key, str(x), str(y), str(lon), str(lat)], separators=(',', ':')).encode() + b'\n')
            # Partial official samples may include records outside this upload;
            # those do not certify its scope. Require at least one unique match
            # and report coverage instead of rejecting a valid yearly partition.
            if not matched or any(n != 1 for n in matched.values()):
                raise CoordinateBindingError('RDF_SAMPLE_KEY_UNBOUND', 'Official sample needs unique matching upload keys.')
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != input_hash:
                    raise CoordinateBindingError('RDF_INPUT_CHANGED', 'Upload changed during coordinate binding.')
            proof = {'mode': VERSION, 'role': resource['role'], 'file_id': file['id'], 'input_sha256': input_hash,
                     'crs': 'OGC:CRS84', 'x_field': geography['x_field'], 'y_field': geography['y_field'],
                     'location_field': location_field, 'axis_order': ['longitude', 'latitude'], 'units': ['degree', 'degree'],
                     'metadata_document_id': metadata_id, 'metadata_sha256': node['document_sha256'],
                     'vocabulary_namespace': GEO, 'rule_id': 'rdf-basic-geo-wgs84-v1',
                     'rdf_evidence': evidence, 'official_sample_keys': len(samples), 'matched_official_keys': len(matched),
                     'upload_rows_compared': count, 'paired_rows': paired, 'all_coordinates_missing_rows': missing,
                     'tolerance_degrees': str(TOLERANCE_DEGREES), 'maximum_axis_delta_degrees': str(maximum),
                     'comparison_sha256': comparison_hash.hexdigest(),
                     'limitation': 'Official sample coverage is finite; full upload comparison proves internal coordinate correspondence, not all-row publisher certification or positional accuracy.'}
            proofs.append(proof)
    return proofs


def prove_coordinates(contract, files, documents, graph, *, check_cancelled=lambda: None, include_omitted=False):
    if not any(graph['nodes'][key]['facts'].get('rdf_points') for key in graph['authorized']):
        return []
    admitted = {file['id']: file for file in files or []}
    from .evidence_scope import build_applicability
    applicability = build_applicability(contract, graph)
    proofs = []
    from .table_plan import expand_resources
    from .lookup_semantics import geography_resources
    for resource in expand_resources(geography_resources(contract)):
        check_cancelled()
        file = admitted.get(resource.get('file_id'))
        if file is None:
            continue
        scoped_graph = {**graph, 'authorized':set(applicability['roles'][resource['role']]['applicable_documents'])}
        if resource.get('mapping', {}).get('geography'):
            proofs.extend(prove_resource(resource, file, documents, scoped_graph, check_cancelled=check_cancelled))
        elif include_omitted and resource.get('grain') in {'crash', 'observation'}:
            from .capability_limits import geography_limited
            if geography_limited(resource):
                continue  # Raw values remain; this request grants no spatial claim.
            # Axis names generate candidates only. The same official metadata,
            # record/key/field chain and whole-file comparison still apply.
            # This does not add a mapping or mutate the proposed contract.
            from .geography_review import coordinate_pairs
            spec = resource.get('table', {})
            tables = detect_tables(file, spec, check_cancelled)
            selected = spec.get('sheet', spec.get('table_id'))
            tables = [t for t in tables if t['table_id'] == selected or selected is None and len(tables) == 1]
            if len(tables) != 1:
                continue
            for x, y in coordinate_pairs(tables[0]['header']):
                candidate = {**resource, 'mapping': {**resource.get('mapping', {}),
                             'geography': {'x_field': x, 'y_field': y}}}
                proofs.extend(prove_resource(candidate, file, documents, scoped_graph, check_cancelled=check_cancelled))
    return proofs
