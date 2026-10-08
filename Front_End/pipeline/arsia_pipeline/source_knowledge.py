"""Versioned research evidence, never an alternative to trusted QA.

No network, database, or model access occurs on import. Official source text is
untrusted data. A catalogue match is a research candidate, not source admission.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata
from uuid import uuid4

CATALOG = Path(__file__).with_name('knowledge') / 'catalog.json'
VERSION = 'official-knowledge-v1'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def file_hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


class EvidenceStore:
    """Small content-addressed objects. Callers supply an explicit private root."""
    def __init__(self, root):
        self.root = Path(root)
        if any(p.is_symlink() for p in [self.root, *self.root.parents]):
            raise ValueError('Knowledge store cannot use symlinks')
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def put(self, data):
        if not isinstance(data, bytes) or len(data) > 4 * 1024**2:
            raise ValueError('Knowledge object must be bytes, at most 4 MiB')
        sha = hashlib.sha256(data).hexdigest()
        target = self.root / sha
        if target.exists():
            if self.get(sha) != data:
                raise ValueError('Knowledge object collision')
            return sha
        temporary = self.root / ('.pending-' + uuid4().hex)
        try:
            fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, target)  # Publish complete bytes, never replace an existing object.
            except FileExistsError:
                if self.get(sha) != data:
                    raise ValueError('Concurrent knowledge object mismatch')
        finally:
            temporary.unlink(missing_ok=True)
        return sha

    def get(self, sha):
        if not isinstance(sha, str) or not re.fullmatch('[a-f0-9]{64}', sha):
            raise ValueError('Invalid content hash')
        path = self.root / sha
        if path.is_symlink() or path.stat().st_size > 4 * 1024**2:
            raise ValueError('Invalid knowledge object')
        value = path.read_bytes()
        if hashlib.sha256(value).hexdigest() != sha:
            raise ValueError('Knowledge object changed')
        return value


def load_catalog(path=CATALOG):
    value = json.loads(Path(path).read_text())
    if value.get('schema_version') != VERSION:
        raise ValueError('Unsupported knowledge catalogue version')
    from .catalog_schema import validate_catalog
    validate_catalog(value)
    return value


def lookup(*, dataset_id=None, jurisdiction=None, resource_id=None, catalog=None):
    catalog = catalog or load_catalog()
    sources = [s for s in catalog['sources'] if
               (not dataset_id or s['id'] == dataset_id) and
               (not jurisdiction or jurisdiction.upper() in s['jurisdiction'])]
    if resource_id:
        sources = [{'id':s['id'],'resources':[r for r in s['resources'] if r['id']==resource_id]}
                   for s in sources if any(r['id']==resource_id for r in s['resources'])]
    else:
        sources = [{**{k:v for k,v in s.items() if k not in {'native_baseline','representative_archive','resources'}},
                    'resources':[{k:v for k,v in r.items() if k not in {'fields','headers'}} for r in s['resources']]}
                   for s in sources]
        if not dataset_id:
            sources = [{k:s[k] for k in ('id','jurisdiction','publisher','entry_url','adapter_status','evidence')}
                       for s in sources]
    if dataset_id:
        # A separate, versioned interpretation rule is implemented host code
        # data, not an upgrade of this research catalogue to admission authority.
        from .count_definitions import REVIEWED
        interpretations = json.loads(REVIEWED.read_text())['claims']
        for source in sources:
            original = next(s for s in catalog['sources'] if s['id'] == source['id'])
            source['reviewed_count_interpretations'] = [
                {key: claim[key] for key in ('id','field','grain','key','measure','coverage','document_url','document_sha256','source_limits')}
                for claim in interpretations if original['entry_url'] in claim['dataset_urls']]
    return {'schema_version': VERSION, 'researched_at': catalog['researched_at'],
            'sources': sources, 'authority': 'research_only_requires_fresh_QA',
            'catalog_sha256': digest(catalog)}


def read_evidence(evidence_id, *, locator=None, offset=0, max_chars=12000, catalog_path=CATALOG):
    if type(offset) is not int or offset < 0 or type(max_chars) is not int or not 100<=max_chars<=16000:
        raise ValueError('Invalid evidence pagination')
    catalog = load_catalog(catalog_path)
    record = catalog['evidence_index'].get(evidence_id)
    if not record:
        raise ValueError('Unknown evidence ID')
    if record.get('status') != 'fetched':
        return {'evidence':record,'available':False,'untrusted_evidence':True}
    # No directory creation on the model's read-only tool path.
    evidence_root = Path(catalog_path).parent/'evidence'
    if not evidence_root.is_dir():
        raise ValueError('Packaged evidence is unavailable')
    raw = EvidenceStore(evidence_root).get(record['sha256'])
    if raw.startswith(b'%PDF-'):
        from .document_parser import pdf_text
        if locator and not re.fullmatch(r'page:[1-9][0-9]*',locator):
            raise ValueError('PDF locator must be page:N')
        pages=pdf_text(evidence_root/record['sha256'],int(locator[5:])-1 if locator else None)
        text=pages[0] if locator else '\n'.join(f'PAGE {i+1}\n{p}' for i,p in enumerate(pages))
    else:
        text = raw.decode('utf-8-sig')
        if locator:
            value = json.loads(text)
            if not locator.startswith('/'):
                raise ValueError('Use a JSON Pointer')
            for token in locator[1:].split('/'):
                token = token.replace('~1','/').replace('~0','~')
                value = value[int(token)] if isinstance(value,list) else value[token]
            text = json.dumps(value,ensure_ascii=False,indent=2)
    return {'evidence_id':evidence_id,'sha256':record['sha256'],'url':record.get('final_url'),
            'locator':locator,'text':text[offset:offset+max_chars], 'total_chars':len(text),
            'next_offset':offset+max_chars if offset+max_chars<len(text) else None,
            'untrusted_evidence':True,'admission_authority':False}


def schema_signature(headers):
    """Order independent, but never silently collapse Unicode/space collisions."""
    if not headers or any(not isinstance(h, str) or not h.strip() for h in headers):
        raise ValueError('Empty or nontext column')
    normalized = [unicodedata.normalize('NFKC', h).strip().casefold() for h in headers]
    if len(set(headers)) != len(headers) or len(set(normalized)) != len(headers):
        raise ValueError('Ambiguous duplicate/normalized column collision')
    return digest(sorted(headers))


def schema_delta(previous, current):
    schema_signature(previous)
    schema_signature(current)
    return {'added': sorted(set(current)-set(previous)), 'removed': sorted(set(previous)-set(current)),
            'order_changed': previous != current and set(previous) == set(current)}


def semantic_diff(previous, current, claims=(), max_changes=80):
    """Bounded JSON Pointer diff, with the evidence IDs of affected claims.

    Lists remain ordered: keys, coordinate axes and code priority are semantic.
    Callers must pass a scoped semantic projection, not arbitrary web text.
    """
    changes = []
    truncated = False
    def walk(a, b, pointer):
        nonlocal truncated
        if type(a) is type(b) and a == b:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(a.keys() | b.keys()):
                p = pointer + '/' + key.replace('~', '~0').replace('/', '~1')
                if key in a and key in b:
                    walk(a[key], b[key], p)
                else:
                    emit(p, 'added' if key not in a else 'removed', a.get(key), b.get(key))
        else:
            emit(pointer or '/', 'changed', a, b)
    def emit(pointer, kind, a, b):
        nonlocal truncated
        if len(changes) >= max_changes:
            truncated = True
            return
        affected = [c for c in claims if any(pointer == p or pointer.startswith(p+'/') or p.startswith(pointer+'/')
                                            for p in c.get('depends_on', []))]
        def bounded(value):
            encoded = json.dumps(value, ensure_ascii=False)
            return value if len(encoded) <= 800 else {'sha256': digest(value), 'chars':len(encoded), 'omitted':True}
        changes.append({'path':pointer, 'kind':kind, 'before':bounded(a), 'after':bounded(b),
                        'claim_ids':[c['id'] for c in affected],
                        'evidence_ids':sorted({e for c in affected for e in c.get('evidence_ids', [])})})
    walk(previous, current, '')
    return {'before_sha256':digest(previous), 'after_sha256':digest(current),
            'changes':changes, 'truncated':truncated,
            'route':'delta_investigation' if changes else 'unchanged_semantics',
            'admitted':False}


def metadata_projection(value, provider):
    """Provider-specific semantic facts; volatile view counters are excluded.

    Unknown publisher additions are retained except the explicit cosmetic keys.
    No CRS is propagated between datasets, resources or geometry/attributes.
    """
    if provider == 'ckan':
        value = value.get('result', value)
        if not value.get('id') or not isinstance(value.get('resources'), list):
            raise ValueError('Expected one package_show dataset')
        drop = {'tracking_summary', 'metadata_created', 'metadata_modified', 'revision_id',
                'creator_user_id', 'num_resources', 'num_tags'}
        out = {k:v for k,v in value.items() if k not in drop and k != 'resources'}
        out['resources'] = {r['id']:{k:v for k,v in r.items() if k not in {'tracking_summary','created','metadata_modified'}}
                            for r in value['resources']}
        if len(out['resources']) != len(value['resources']):
            raise ValueError('Duplicate resource identity')
        return out
    if provider == 'socrata':
        return {k:v for k,v in value.items() if k not in {'viewCount','downloadCount','viewLastModified',
                                                       'rowsUpdatedAt','rowsUpdatedBy','publicationDate'}}
    if provider == 'arcgis':
        if value.get('error'):
            raise ValueError('ArcGIS error response is not layer metadata')
        return {k:v for k,v in value.items() if k not in {'editingInfo','drawingInfo','minScale','maxScale'}}
    raise ValueError('Unsupported metadata provider')


def registered_document_bytes(document, trusted_root):
    """Read immutable host evidence with the existing receipt and size boundary."""
    root = Path(trusted_root).resolve()
    receipt_path = Path(document.get('receipt_path',''))
    if receipt_path.is_symlink() or not receipt_path.is_file() or not receipt_path.resolve().is_relative_to(root):
        raise ValueError('Fresh metadata must have a host-registered receipt')
    receipt = json.loads(receipt_path.read_text())
    if receipt.get('status') != 'fetched' or receipt.get('sha256') != document.get('sha256'):
        raise ValueError('Fresh metadata receipt does not match the document')
    raw = receipt_path.parent/'sha256'/receipt['sha256']
    if raw.is_symlink() or not raw.resolve().is_relative_to(root) or raw.stat().st_size>4*1024**2 or file_hash(raw)!=receipt['sha256']:
        raise ValueError('Fresh metadata bytes changed or escaped their boundary')
    payload = raw.read_bytes()
    if hashlib.sha256(payload).hexdigest() != receipt['sha256']:
        raise ValueError('Metadata bytes changed while being read')
    return payload, receipt


def reuse_metadata_compatibility(old_raw, new_raw, url):
    """Small CKAN equivalence subset, stricter than the research projection.

    The research projection drops e.g. revision IDs and resource creation dates;
    those are NOT automatically cosmetic for reuse. Only JSON serialization,
    package metadata_modified and known nonnegative tracking counters may vary.
    Resource order and every other unknown/property/semantic change stay blocking.
    This proves neither source upload provenance nor QA admission.
    """
    from urllib.parse import urlsplit
    from .metadata_extractors import _json, MetadataError
    from .source_identity import url_identity
    audit = {'rule': 'ckan-reuse-cosmetic-v1', 'before_raw_sha256': hashlib.sha256(old_raw).hexdigest(),
             'after_raw_sha256': hashlib.sha256(new_raw).hexdigest(), 'compatible': False, 'admission': False}
    identity = url_identity(url)
    if not identity or identity['kind'] != 'ckan' or not urlsplit(url).path.endswith('/3/action/package_show'):
        return {**audit, 'reason': 'structured_provider_not_supported'}
    try:
        old, new = _json(old_raw), _json(new_raw)
        for envelope in (old, new):
            value = envelope.get('result', {})
            if envelope.get('success') is not True or identity['dataset'] not in {value.get('id'), value.get('name')}:
                raise ValueError('Exact CKAN dataset identity is required')
        before, after = metadata_projection(old, 'ckan'), metadata_projection(new, 'ckan')
        semantic = semantic_diff(before, after, max_changes=40)
        # Use the raw structured diff as well: the research projection alone
        # intentionally omits more information than reuse is allowed to ignore.
        raw_delta = semantic_diff(old, new, max_changes=40)
        changes = raw_delta['changes']
        def cosmetic(change):
            import re
            from datetime import datetime
            path = change['path']
            if path == '/result/metadata_modified' and change['kind'] == 'changed':
                try:
                    return all(isinstance(change[key], str) and datetime.fromisoformat(change[key].replace('Z', '+00:00'))
                               for key in ('before', 'after'))
                except ValueError:
                    return False
            if re.fullmatch(r'/result/tracking_summary/(?:total|recent)', path):
                return change['kind'] == 'changed' and all(type(change[key]) is int and change[key] >= 0 for key in ('before','after'))
            return False
        permitted = not semantic['changes'] and not semantic['truncated'] and not raw_delta['truncated'] and all(cosmetic(c) for c in changes)
        return {**audit, 'compatible': permitted, 'reason': 'explicit_cosmetic_only' if permitted else 'semantic_or_unclassified_change',
                'semantic_diff': semantic, 'raw_diff': raw_delta,
                'allowed_changes': [{'path': c['path'], 'kind': c['kind']} for c in changes if cosmetic(c)]}
    except (MetadataError, ValueError, TypeError, AttributeError, KeyError) as exc:
        return {**audit, 'reason': 'metadata_not_provably_compatible', 'error_type': type(exc).__name__}


def compare_registered_metadata(baseline_evidence_id, document, provider, trusted_root):
    """Research comparison only; it does not grant reuse or QA authority."""
    catalog = load_catalog()
    baseline = catalog['evidence_index'].get(baseline_evidence_id, {})
    if baseline.get('status') != 'fetched':
        raise ValueError('Baseline metadata is unavailable')
    old_raw = EvidenceStore(CATALOG.parent/'evidence').get(baseline['sha256'])
    raw, receipt = registered_document_bytes(document, trusted_root)
    old = metadata_projection(json.loads(old_raw),provider)
    new = metadata_projection(json.loads(raw),provider)
    claims = [{'id':key, 'depends_on':['/'+key], 'evidence_ids':[baseline_evidence_id,document['document_id']]}
              for key in sorted(old.keys() | new.keys())]
    delta = semantic_diff(old,new,claims,max_changes=20)
    old_id,new_id = old.get('id'),new.get('id')
    if old_id is None or old_id != new_id:
        delta['route'] = 'source_identity_review'
    delta.update(baseline_evidence_id=baseline_evidence_id,current_document_id=document['document_id'],
                 baseline_url=baseline.get('final_url'),current_url=receipt.get('final_url'),
                 untrusted_evidence=True,admission_authority=False)
    return delta


def inspect_files(files, catalog=None):
    """Return candidates and deltas without reading raw records into AI context."""
    from .intakereaders import detect_tables, detect_format
    catalog = catalog or load_catalog()
    observed = []
    for file in files:
        if Path(file['path']).is_symlink() or file_hash(file['path']) != file['sha256']:
            raise ValueError('Input changed after receipt')
        kind = detect_format(file)
        if kind in {'zip','pdf'}:
            observed.append({'file_id':file['id'], 'format':kind, 'requires_inspection':True})
            continue
        from .errors import NeedsInput
        try:
            tables = detect_tables(file)
        except NeedsInput as exc:
            observed.append({'file_id':file['id'],'format':kind,'requires_inspection':True,
                             'reader_diagnostic':str(exc)[:500]})
            continue
        for table in tables:
            headers = table['header']
            signature = schema_signature(headers)
            candidates = []
            for source in catalog['sources']:
                for resource in source['resources']:
                    baseline = resource.get('headers')
                    if not baseline:
                        continue
                    intersection = set(headers) & set(baseline)
                    exact = signature == schema_signature(baseline)
                    if exact or (len(intersection) >= 3 and len(intersection)/max(len(headers),len(baseline)) >= .7):
                        candidates.append({'dataset_id':source['id'], 'resource_id':resource['id'],
                            'match':'schema_candidate' if exact else 'schema_drift_candidate',
                            'delta':schema_delta(baseline,headers), 'evidence_ids':source['evidence'],
                            'adapter_status':source.get('adapter_status','research_only')})
            observed.append({'file_id':file['id'], 'table_id':table['table_id'], 'format':kind,
                             'headers':headers, 'signature':signature, 'candidates':candidates})
    count = sum(len(t.get('candidates',[])) for t in observed)
    return {'route':'delta_investigation' if count else 'autonomous_investigation',
            'tables':observed, 'admitted':False, 'model_calls':0,
            'notice':'Headers and filenames do not prove publisher identity or QA. Resolve only listed changes against scoped evidence.'}
