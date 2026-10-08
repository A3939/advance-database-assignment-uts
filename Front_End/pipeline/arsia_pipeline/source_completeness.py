"""Host-derived complete-export proof, separate from conservation of an upload.

Currently supports exact ArcGIS all-object-ID exports made by the trusted v2
fetcher. It rechecks archived endpoint scope, inventories, pages and the complete
derived byte stream. A contract's snapshot flag, date range or model assertion
is never evidence. This establishes the publisher's observed current layer
membership, not historical coverage, positional accuracy or a transaction lock.
"""
import hashlib
import json
from pathlib import Path
import re
from datetime import datetime, timezone
from urllib.parse import urlsplit, parse_qsl

from .arcgis_export import export_prefix, preserve_page
from .evidence_graph import identity, representation
from .evidence_scope import applicable_documents
from .errors import NeedsInput, ValidationFailure

VERSION = 'verified-source-membership-v1'


def observed_time(value):
    parsed = datetime.fromisoformat(value) if isinstance(value, str) else value
    if not isinstance(parsed, datetime) or parsed.tzinfo is None:
        raise ValueError('Source observation needs an explicit timezone.')
    return parsed.astimezone(timezone.utc)


def verify_arcgis_export(file, *, root, source_url, metadata_sha256, check_cancelled=lambda: None):
    """Only call for a metadata hash already authorized for this exact resource."""
    def require(condition, message):
        if not condition:
            raise ValidationFailure(message, details={'code': 'COMPLETE_EXPORT_UNPROVEN'})
    def read(path, limit):
        path = Path(path)
        require(not path.is_symlink() and path.resolve().is_relative_to(Path(root).resolve()) and path.is_file(), 'Complete-export evidence is outside this instance or unavailable.')
        require(path.stat().st_size <= limit, 'Complete-export evidence exceeds the supported verification bound.')
        return path.read_bytes()
    raw_receipt = read(file['receipt_path'], 8 * 1024**2)
    receipt = json.loads(raw_receipt)
    require(isinstance(receipt, dict), 'Invalid complete-export receipt.')
    require(receipt.get('status') == 'fetched' and receipt.get('derivation') == 'verified_arcgis_all_object_ids_v2', 'A current verified all-ID export receipt is required.')
    base = representation(receipt.get('final_url'))
    require(base is not None and base == representation(source_url) and not urlsplit(base).query, 'Complete-export receipt is for a different resource or filtered representation.')
    require(identity(base) is not None and identity(base)['kind'] == 'arcgis_layer', 'Completeness proof requires an exact ArcGIS layer.')
    require(receipt.get('metadata_sha256') == metadata_sha256, 'Export metadata differs from the authorized resource metadata.')
    objects = Path(file['receipt_path']).parent / 'sha256'
    def object_bytes(digest):
        require(isinstance(digest, str) and re.fullmatch('[a-f0-9]{64}', digest), 'Invalid evidence content hash.')
        raw = read(objects / digest, 32 * 1024**2)
        require(hashlib.sha256(raw).hexdigest() == digest, 'Complete-export evidence content hash changed.')
        return raw
    def response(entry, path, allowed, expected=None):
        require(isinstance(entry, dict), 'Invalid archived response receipt.')
        url = urlsplit(entry.get('final_url', ''))
        wanted = urlsplit(base)
        params = parse_qsl(url.query, keep_blank_values=True); query = dict(params)
        require(url.scheme == 'https' and url.netloc == wanted.netloc and url.path == path and
                len(params) == len(query) and set(query) <= allowed and not url.fragment,
                'Complete-export query endpoint or parameter scope changed.')
        require(all(query.get(k) == v for k, v in (expected or {}).items()), 'Complete-export query does not cover the declared full layer.')
        raw = object_bytes(entry.get('sha256'))
        require(len(raw) == entry.get('size'), 'Archived response size differs from its receipt.')
        value = json.loads(raw)
        require(isinstance(value, dict) and not value.get('error') and not value.get('exceededTransferLimit'), 'Incomplete or failed response cannot prove source membership.')
        return value, query
    requests = receipt.get('requests', {})
    metadata, _ = response(requests.get('metadata', {}), urlsplit(base).path, {'f'}, {'f': 'pjson'})
    require(requests['metadata']['sha256'] == metadata_sha256, 'Metadata receipt is not bound to the authorized document.')
    oid = receipt.get('object_id_field')
    published_oid = metadata.get('objectIdField') or next((item['name'] for item in metadata.get('fields', []) if item.get('type') == 'esriFieldTypeOID'), None)
    require(isinstance(oid, str) and oid == published_oid, 'Export object identifier is not the published layer identifier.')
    inventories = []
    for name in ('initial_ids', 'final_ids'):
        value, _ = response(requests.get(name, {}), urlsplit(base).path + '/query', {'where', 'returnIdsOnly', 'f'}, {'where': '1=1', 'returnIdsOnly': 'true', 'f': 'json'})
        ids = value.get('objectIds')
        require(isinstance(ids, list) and len(ids) <= 500000 and all(type(i) is int for i in ids), 'Invalid full-layer ID inventory.')
        require(len(ids) == len(set(ids)), 'Full-layer ID inventory contains duplicates.')
        require(requests[name]['sha256'] == receipt.get(name + '_sha256'), 'Inventory receipt is not bound to the export.')
        inventories.append(set(ids))
    count, _ = response(requests.get('count', {}), urlsplit(base).path + '/query', {'where', 'returnCountOnly', 'f'}, {'where': '1=1', 'returnCountOnly': 'true', 'f': 'json'})
    require(inventories[0] == inventories[1] and type(count.get('count')) is int and count['count'] == len(inventories[0]) == receipt.get('record_count'), 'Before/after inventories or exact count disagree.')
    require(requests['count']['sha256'] == receipt.get('count_sha256'), 'Count receipt is not bound to the export.')
    pages = receipt.get('pages')
    require(isinstance(pages, list) and len(pages) == receipt.get('page_count'), 'Export page manifest is incomplete.')
    start, initial, final, end = (observed_time(requests[key].get('fetched_at')) for key in ('metadata', 'initial_ids', 'final_ids', 'count'))
    require(start <= initial <= final <= end, 'Complete-export observation chronology is inconsistent.')
    require(all(initial <= observed_time(page.get('fetched_at')) <= final for page in pages), 'Page observations are outside the full-ID verification interval.')
    digest = hashlib.sha256((json.dumps(export_prefix(metadata, oid), ensure_ascii=False)[:-1] + ',"features":[').encode())
    seen, first = set(), True
    for page in pages:
        check_cancelled()
        value, query = response(page, urlsplit(base).path + '/query', {'objectIds', 'outFields', 'returnGeometry', 'f', 'outSR', 'returnZ', 'returnM'}, {'outFields': '*', 'returnGeometry': 'true', 'f': 'json'})
        require(isinstance(query.get('objectIds'), str) and re.fullmatch(r'-?\d+(?:,-?\d+)*', query['objectIds']), 'Page request has no exact object-ID scope.')
        requested = [int(i) for i in query['objectIds'].split(',')]
        require(len(requested) == len(set(requested)), 'Page request repeats an object identifier.')
        features, _ = preserve_page(metadata, value, requested_reference=json.loads(query['outSR']) if 'outSR' in query else None)
        observed = [feature['attributes'].get(oid) for feature in features]
        require(all(type(i) is int for i in observed) and len(set(observed)) == len(observed) and set(observed) == set(requested), 'Page membership differs from the requested IDs.')
        require(not seen.intersection(observed), 'Export pages overlap.')
        seen.update(observed)
        for feature in sorted(features, key=lambda item: item['attributes'][oid]):
            digest.update(('' if first else ',').encode()); first = False
            digest.update(json.dumps(feature, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode())
    digest.update(b']}')
    require(seen == inventories[0], 'Export pages omit or add source records.')
    require(digest.hexdigest() == receipt.get('sha256') == file.get('sha256'), 'Complete page content does not reconstruct the supplied export.')
    path = Path(file['path'])
    require(not path.is_symlink() and path.resolve().is_relative_to(Path(root).resolve()) and path.is_file(), 'Supplied complete export is outside this instance.')
    with path.open('rb') as stream:
        require(hashlib.file_digest(stream, 'sha256').hexdigest() == digest.hexdigest(), 'Supplied export bytes changed.')
    return {'status': 'verified', 'method': VERSION, 'source_url': base, 'input_sha256': digest.hexdigest(),
            'metadata_sha256': metadata_sha256, 'receipt_sha256': hashlib.sha256(raw_receipt).hexdigest(),
            'observed_from': start.isoformat(), 'observed_until': end.isoformat(),
            'record_count': len(seen), 'scope': 'whole_current_layer',
            'limitation': 'Observed source membership only; live field edits, historical coverage and cross-version stable IDs are not established.'}


def review_completeness(contract, files, graph, grounding, *, root, check_cancelled=lambda: None):
    decisions = []
    for resource in contract.get('resources', []):
        selected = next((f for f in files if f['id'] == resource.get('file_id')), None)
        scope = grounding.get('applicability', {}).get('roles', {}).get(resource['role'], {}).get('source_url')
        decision = {'role': resource['role'], 'grain': resource['grain'], 'source_url': scope,
                    'status': 'unproven', 'reason': 'No supported complete-resource receipt matching this input.'}
        if 'partitions' in resource:
            decision['reason'] = 'Union row conservation does not prove publisher-complete partition coverage; individual whole-layer receipts cannot authorize deletion from this union.'
            decisions.append(decision)
            continue
        if selected:
            for file in files:
                if file.get('sha256') != selected.get('sha256') or not file.get('receipt_path'):
                    continue
                for key in applicable_documents(grounding, resource['role']):
                    node = graph['nodes'][key]
                    if identity(node['url']) != identity(scope) or identity(scope) is None or identity(scope).get('kind') != 'arcgis_layer':
                        continue
                    try:
                        proof = verify_arcgis_export({**file, 'path': selected['path']}, root=root, source_url=scope,
                                                     metadata_sha256=node['document_sha256'], check_cancelled=check_cancelled)
                    except (ValidationFailure, NeedsInput, ValueError, KeyError, TypeError, OSError) as exc:
                        decision['reason'] = str(exc)
                    else:
                        decision = {**decision, **proof}; decision.pop('reason', None); break
                if decision['status'] == 'verified': break
        decisions.append(decision)
    return {'version': VERSION, 'resources': decisions, 'scope': 'Resource membership proof is separate from input row conservation and semantic admission.'}


def require_removal_authority(previous_contract, result, removals, *, previous_published_at):
    """Called on actual DB membership differences, inside publication's transaction."""
    if not removals:
        return {'status': 'no_records_removed', 'removals': []}
    resources = {r['role']: r for r in (previous_contract or {}).get('resources', [])}
    proofs = result.get('admission', {}).get('evidence', {}).get('source_completeness', {})
    candidates = proofs.get('resources', []) if proofs.get('version') == VERSION else []
    input_hashes = {f.get('sha256') for f in result.get('files', [])}
    def fresh(proof):
        try:
            return observed_time(previous_published_at) <= observed_time(proof.get('observed_from')) <= observed_time(proof.get('observed_until'))
        except (ValueError, TypeError):
            return False
    missing, verified = [], []
    for item in removals:
        role = item['role']; previous = resources.get(role)
        source = (previous or {}).get('source_url') or (previous_contract or {}).get('source', {}).get('dataset_url')
        claim = next((p for p in candidates if previous and p.get('role') == role and p.get('grain') == item['grain'] and
                      p.get('status') == 'verified' and p.get('method') == VERSION and p.get('scope') == 'whole_current_layer' and
                      representation(p.get('source_url')) == representation(source) and p.get('input_sha256') in input_hashes and
                      fresh(p) and
                      all(isinstance(p.get(k), str) and re.fullmatch('[a-f0-9]{64}', p[k]) for k in ('input_sha256', 'metadata_sha256', 'receipt_sha256'))), None)
        (verified if claim else missing).append(item)
    if missing:
        mode = result.get('update', {}).get('mode', 'snapshot')
        def supported(item):
            resource = resources.get(item['role'])
            if not resource: return False
            key = identity(resource.get('source_url') or (previous_contract or {}).get('source', {}).get('dataset_url'))
            return key is not None and key['kind'] == 'arcgis_layer'
        unsupported = not all(supported(item) for item in missing)
        message = 'This update would remove published records without verified complete-source membership evidence.'
        raise NeedsInput(message, [],
                         {'code': 'SOURCE_MEMBERSHIP_UNPROVEN', 'update_mode': mode, 'removals': missing,
                          'blockers': [{'code': 'COMPLETE_RESOURCE_PROOF_UNSUPPORTED' if unsupported else 'SOURCE_MEMBERSHIP_UNPROVEN',
                                        'kind': 'unsupported_capability' if unsupported else 'evidence_missing',
                                        'responsible_party': 'system' if unsupported else 'agent', 'message': message,
                                        'resumable_when': 'Add a reviewed completeness verifier for this resource.' if unsupported else 'Obtain a complete official export matching these exact input bytes.'}],
                          'resumable_when': 'Obtain a supported complete official resource receipt matching these exact input bytes, or use an evidenced update that preserves existing records.',
                          'limitation': 'A declared interval, matching total, timestamp alone or model-written flag does not authorize deletion. A complete live-layer export must be observed after the source version being replaced was published.'})
    return {'status': 'verified_source_membership', 'removals': verified, 'version': VERSION}
