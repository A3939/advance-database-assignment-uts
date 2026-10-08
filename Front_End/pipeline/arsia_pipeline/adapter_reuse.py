"""Opt-in host-side replay of admitted recipes before entering the Codex loop.

The cache is scoped to a DB instance and is not authority. Every hit rechecks
the real registry, evidence bytes, dependencies and fresh sample/full QA.
Changed bytes may select a conservative opt-in version candidate; they never
inherit an old admission. Unresolved differences return to the existing Agent.
"""
import hashlib
import json
from pathlib import Path

from .source_knowledge import EvidenceStore, digest, file_hash, inspect_files
from .table_plan import physical_resources, bound_inputs
from .dependency_scope import scope as dependency_scope, compatible as compatible_dependencies

ADAPTER = '''def adapt(ctx):
    for resource in ctx.contract['resources']:
        role = resource['role']
        for locator, row in ctx.iter_rows(role):
            ctx.emit(resource['grain'], ctx.project(role, locator, row))
'''


def dependencies():
    from .trusted_qa import POLICY, trusted_implementation
    root = Path(__file__).parent
    names = ('adapter_reuse.py','source_knowledge.py','adapter_sdk.py','isolated_executor.py',
             'source_identity.py','update_compatibility.py','registry.py','recipe_index.py','dependency_scope.py')
    return {'policy':POLICY, 'trusted':trusted_implementation(),
            'reuse':{n:file_hash(root/n) for n in names}}


def registered(version):
    from . import registry, store
    record = registry.read(version)  # Includes immutable-code verification.
    with store.connect() as conn:
        row = conn.execute('SELECT verification,dependency_version FROM adapter_versions WHERE id=%s', (version,)).fetchone()
    if not row or row['verification'].get('admission',{}).get('status') != 'admitted':
        raise ValueError('Registered adapter has no full admission')
    return {**record, **row}


def active_files(files):
    from .intakereaders import detect_format
    containers = {f.get('archive_file_id') for f in files if f.get('archive_file_id')}
    return [f for f in files if f['id'] not in containers and f.get('role') != 'public_evidence'
            and detect_format(f) not in {'pdf'}]


def supplement_hashes(files):
    """A new uploaded dictionary may change meanings even with identical data."""
    from .intakereaders import detect_format
    hashes = []
    for f in files:
        if f.get('role') != 'public_evidence' and detect_format(f) == 'pdf':
            if Path(f['path']).is_symlink() or file_hash(f['path']) != f['sha256']:
                raise ValueError('Supporting document changed after receipt')
            hashes.append(f['sha256'])
    return sorted(hashes)


class ReuseCache:
    def __init__(self, root, instance_id):
        if not isinstance(instance_id,str) or not instance_id:
            raise ValueError('Explicit database instance required')
        self.store = EvidenceStore(Path(root)/digest(instance_id)/'objects')
        self.instance = instance_id
        from .recipe_index import RecipeIndex
        self.index = RecipeIndex(self.store, instance_id)

    def remember(self, session):
        result = session.validated
        if not result or not session.registered or result.get('admission',{}).get('status') != 'admitted':
            raise ValueError('Knowledge promotion requires current full QA and registry admission')
        version = session.registered['adapter_version_id']
        original = registered(version)
        if original['code_sha256'] != hashlib.sha256(session.code.encode()).hexdigest():
            raise ValueError('Registry and active adapter differ')
        from .registry import execution_contract_hash
        contract = result['source_contract']
        if result['admission']['source_contract_sha256'] != execution_contract_hash(contract):
            raise ValueError('Contract changed after admission')
        files = {f['id']:f for f in session.files}
        resources = []
        for resource in bound_inputs(contract):
            for index,part in enumerate(physical_resources(resource)):
                f = files[part['file_id']]
                if file_hash(f['path']) != f['sha256']:
                    raise ValueError('Cannot remember changed inputs')
                resources.append({'role':resource['role'], 'partition_index':index, 'sha256':f['sha256'], 'size':f['size'],
                                  'file_id':f['id']})
        # Full QA covers all original rows, but arbitrary Python can include
        # extra side logic. The replay compiler is intentionally the SDK's
        # declarative projection, always followed by new independent QA.
        docs = list(session.documents.values())
        pins = {}
        for doc in docs:
            for field in ('receipt_path','text_path'):
                if doc.get(field):
                    p = Path(doc[field]); pins[str(p)] = file_hash(p)
            if doc.get('receipt_path'):
                receipt = json.loads(Path(doc['receipt_path']).read_text())
                raw = Path(doc['receipt_path']).parent/'sha256'/receipt['sha256']
                pins[str(raw)] = file_hash(raw)
        binding_files=[f for f in session.files if f.get('role')=='public_evidence' and f.get('receipt_path')]
        for file in binding_files:
            pins[file['receipt_path']]=file_hash(file['receipt_path'])
            pins[file['path']]=file_hash(file['path'])
        record = {'format':'admitted-recipe-v1', 'instance':self.instance, 'version':version,
                  'contract':contract, 'documents':docs, 'evidence_pins':pins, 'binding_files':binding_files,
                  'binding_proofs':result['admission'].get('evidence',{}).get('upload_bindings',[]),
                  'resources':resources, 'dependencies':dependencies(), 'dependency_scope':dependency_scope(contract),
                  'supplement_hashes':supplement_hashes(session.files),
                  'image':result['admission'].get('image')}
        if getattr(session, 'adaptation_v1', False):
            # Only a new full admission can seed a version candidate. Old cache
            # records are not silently upgraded from their schema alone.
            record['version_candidate'] = version_profile(contract, session.files, result,
                                                           session.cancel)
        return self.index.promote(record)

    def match(self, files, cancelled=lambda: None):
        supplements = supplement_hashes(files)
        files = active_files(files)
        by_hash = {}
        for f in files:
            if Path(f['path']).is_symlink() or file_hash(f['path']) != f['sha256']:
                raise ValueError('Input changed before reuse')
            by_hash.setdefault((f['sha256'],f['size']),[]).append(f)
        matches = []
        invalidations = []
        shas, truncated = self.index.shortlist(files=files, cancelled=cancelled)
        if truncated:
            return None, {'route':'ambiguous','reason':'matching_template_budget','truncated':True}
        dependency_identity = dependencies()
        for sha in shas:
            cancelled()
            path = self.store.root / sha
            record = json.loads(self.store.get(sha))
            if record.get('instance') != self.instance or record.get('format') != 'admitted-recipe-v1':
                raise ValueError('Invalid recipe scope')
            required = {(r['sha256'],r['size']) for r in record['resources']}
            # Ambiguous duplicate uploads or one file used by multiple tables
            # are investigated, never arbitrarily paired.
            if set(by_hash) != required or len(required) != len(record['resources']) or any(len(v)!=1 for v in by_hash.values()):
                continue
            reason = None
            if record.get('supplement_hashes',[]) != supplements: reason = 'supporting_documents_changed'
            elif not compatible_dependencies(record, dependency_identity): reason = 'dependency_changed'
            elif any(not Path(p).is_file() or Path(p).is_symlink() or file_hash(p)!=sha for p,sha in record['evidence_pins'].items()): reason = 'evidence_changed'
            if reason:
                invalidations.append({'recipe':path.name,'reason':reason}); continue
            original = registered(record['version'])
            from .trusted_qa import semantic_contract
            registered_contract = json.loads(json.dumps(original['contract']))
            # Registry normalization omits ephemeral file IDs/documents.
            cached_contract = json.loads(json.dumps(record['contract']))
            for c in (registered_contract,cached_contract):
                c.pop('documents',None)
                for r in bound_inputs(c):
                    r.pop('file_id',None)
                    for part in r.get('partitions',[]):part.pop('file_id',None)
            if registered_contract != cached_contract:
                raise ValueError('Recipe differs from immutable registered contract')
            if original['verification']['admission'].get('image') != record['image']:
                raise ValueError('Recipe image differs from registry')
            bindings = {(r['role'],r.get('partition_index',0)):by_hash[(r['sha256'],r['size'])][0]['id'] for r in record['resources']}
            matches.append((record,bindings,path.name))
        # Repeated successful replay may create another registry version with
        # the same semantics. Collapse only identical contract/evidence/deps.
        unique = {}
        for record,bindings,sha in matches:
            key = digest({'contract':semantic_contract(record['contract']), 'pins':record['evidence_pins'],
                          'dependencies':record['dependencies'], 'image':record['image']})
            unique[key] = (record,bindings,sha)
        if len(unique) != 1:
            return None, {'route':'ambiguous' if len(unique)>1 else 'cache_miss', 'invalidations':invalidations}
        record, bindings, sha = next(iter(unique.values()))
        contract = json.loads(json.dumps(record['contract']))
        contract.pop('documents',None)
        for resource in bound_inputs(contract):
            resource['file_id'] = bindings[(resource['role'],0)]
            for index,part in enumerate(resource.get('partitions',[])):
                part['file_id']=bindings[(resource['role'],index)]
        return {'contract':contract, 'documents':record['documents'], 'image':record['image'], 'binding_files':record.get('binding_files',[])}, {
            'route':'verified_recipe_requires_fresh_QA', 'recipe_sha256':sha, 'model_calls':0}


def controlled(session, name, args):
    """Same durable tool accounting as Codex, without making a model request."""
    session.check_budget()
    session.usage['tool_calls'] += 1
    step = session.step('tool',name,args)
    session.active_tool = {'name': name, 'arguments': args}
    try:
        output = session.execute_tool(name,args)
        session.finish_step(step,output,'succeeded')
        session.persist()
        return output
    except Exception as exc:
        from .errors import ImportCancelled, BudgetExhausted
        from .capability_preflight import requires_system_change
        cancelled = isinstance(exc, ImportCancelled)
        terminal = isinstance(exc, BudgetExhausted) or requires_system_change(getattr(exc, 'details', {}))
        session.finish_step(step, {'type':type(exc).__name__,'message':str(exc)[:1000],
                                  'details':getattr(exc, 'details', {})},
                            'cancelled' if cancelled else 'paused' if terminal else 'failed')
        session.persist('cancelled' if cancelled else 'needs_input' if terminal else 'investigating')
        raise
    finally:
        session.active_tool = {}


def prepare(session, config):
    """Disabled by default; no new authority is exposed to the model."""
    if not config.get('knowledge_root') or session.native_context is not None or session.contract or session.code:
        return None
    cache = ReuseCache(config['knowledge_root'], config['instance_id'])
    controlled(session,'inspect_bundle',{})
    candidate, decision = cache.match(session.files, session.cancel)
    if not candidate and getattr(session, 'adaptation_v1', False):
        candidate, version_decision = prepare_version_candidate(cache, session)
        decision = {**version_decision, 'exact_byte_reuse': decision}
    if not candidate:
        research = inspect_files(active_files(session.files))
        session.runtime_state['source_knowledge'] = {**research,'reuse':decision}
        session.messages.append({'role':'user','content':'Host source-knowledge preflight (research evidence only): '+json.dumps(session.runtime_state['source_knowledge'])})
        session.persist()
        return None
    from .isolated_executor import docker, IMAGE
    image = docker(['image','inspect',IMAGE,'--format','{{.Id}}'])
    if image.returncode or image.stdout.strip() != candidate['image']:
        session.runtime_state['source_knowledge'] = {'route':'dependency_changed','dependency':'executor_image','admitted':False}
        session.persist()
        if getattr(session, 'adaptation_v1', False):
            from .errors import NeedsInput
            from .capability_preflight import blocker
            raise NeedsInput('The candidate requires a compatible trusted executor; source investigation cannot repair it.', [],
                {'blockers': [blocker('VERSION_EXECUTOR_UNAVAILABLE', 'environment_dependency',
                                     'Reviewed executor image is unavailable or differs from the candidate.') ]})
        return None
    session.runtime_state['source_knowledge'] = decision
    if getattr(session, 'bounded_repair_v1', False):
        from .task_authority import state
        authority = state(session)
        # The cache has already checked the registered source, byte binding,
        # current dependencies and image. This grants task relevance only;
        # every sample/full/QA/publication gate below remains mandatory.
        authority['files'].update({f['id']: {'sha256': f['sha256'], 'purpose': 'crash_intake',
            'basis': 'verified_recipe_candidate', 'admission': False} for f in active_files(session.files)})
        authority['status'] = 'scoped_for_investigation'
    session.documents.update({d['document_id']:d for d in candidate['documents']})
    if candidate.get('binding_files'):
        session.intake.register_files(candidate['binding_files'])
        session.files=list(session.intake.files)
    controlled(session,'set_source_contract',{'contract':candidate['contract']})
    controlled(session,'write_adapter',{'code':ADAPTER,'reason':'Compile previously admitted declarative recipe; fresh QA required'})
    for mode in ('sample','full'):
        run = controlled(session,'run_adapter',{'mode':mode})
        controlled(session,'validate_candidate',{'run_id':run['run_id']})
    controlled(session,'register_adapter',{})
    controlled(session,'publish_candidate',{})
    return session.ready


class VersionCandidateDeclined(ValueError):
    """A candidate difference to investigate, never an admission failure bypass."""
    def __init__(self, code, **details):
        super().__init__(code)
        self.code, self.details = code, details


def required_fields(contract, resource):
    """Fields consumed by the reviewed semantics; other columns remain raw values."""
    from .evidence_grounding import _critical_fields
    required={field for role,_,field in _critical_fields(contract) if role==resource['role']}
    required.update(resource.get('key',[]))
    mapping=resource.get('mapping',{})
    required.update(v for v in [mapping.get('unit_type'),*mapping.get('dimensions',{}).values()] if isinstance(v,str))
    return required


def shape_compatible(contract, resource, observed, previous):
    """A candidate shortlist only. Every source byte and mapped meaning is rechecked."""
    required=required_fields(contract,resource)
    return (observed['format']==previous['format']=='csv' and observed['table_id']==previous['table_id']
            and required<=set(observed['fields']))


def historical_representation_candidate(record,observed,session):
    """Use the precise resource receipt behind this admitted version, without HTTP."""
    from .source_binding import reference_receipt
    from .representation_binding import compare_csv
    from .config import ROOT
    proofs=record.get('binding_proofs',[])
    if not proofs:return None
    bindings={};audits=[]
    for entry in record['version_candidate']['resources']:
        receipts=[p['reference'] for p in proofs if p['role']==entry['role'] and p['partition_index']==0]
        references=[f for f in record.get('binding_files',[]) if any(
            f['sha256']==r['sha256'] and f.get('evidence_url')==r['url']==entry['source_url'] for r in receipts)]
        matches={}
        for ref in references:
            receipt=reference_receipt(ref,ROOT)
            for row in observed:
                for choice in row['choices']:
                    if choice['role']!=entry['role']:continue
                    comparison=compare_csv(ref,row['file'],session.work_dir/'historical-representation',
                        reference_table=choice['table'],upload_table=choice['table'],cancelled=session.cancel)
                    if comparison['equivalent']:
                        matches[row['file']['id']]=(row['file'],choice['table'],{'role':entry['role'],
                            'reference':receipt,'comparison':comparison})
        if len(matches)!=1:return None
        file,table,audit=next(iter(matches.values()));bindings[entry['role']]=(file,table);audits.append(audit)
    if len({file['id'] for file,_ in bindings.values()})!=len(observed):return None
    contract=json.loads(json.dumps(record['contract']));contract.pop('documents',None)
    for resource in bound_inputs(contract):
        file,table=bindings[resource['role']];resource['file_id']=file['id'];resource['table']=table
    return contract,audits


def csv_shape(file, table, cancelled=lambda: None):
    """Only the existing name-addressed CSV reader is eligible in this slice.

    Workbook/JSON parser plans carry additional byte-bound dependencies. They
    remain usable by the Agent but need separate reviewed version matching.
    """
    from .representation_binding import csv_table
    if set(table) - {'format', 'table_id', 'header', 'encoding', 'delimiter'}:
        raise VersionCandidateDeclined('VERSION_PARSER_PLAN_UNSUPPORTED')
    spec = csv_table(file, table, cancelled)
    return {'format': spec['format'], 'table_id': spec['table_id'],
            'fields': sorted(spec['header']), 'encoding': spec['encoding'],
            'delimiter': spec['delimiter']}, spec


def version_profile(contract, files, result, cancelled=lambda: None):
    """Record a host-derived candidate envelope after full QA, not a new cache."""
    from .source_identity import canonical_source_identity
    from .capability_preflight import require_supported_operations
    from .errors import NeedsInput, ValidationFailure, BudgetExhausted
    try:
        require_supported_operations(contract)
        identity = canonical_source_identity(result, contract)
        admitted = {f['id']: f for f in files}
        scope = result['admission']['evidence']['grounding']['applicability']['roles']
        resources = []
        for resource in bound_inputs(contract):
            # Existing union remains executable. Its partitions currently share
            # one source_url; that cannot authorize pairing different exports.
            if 'partitions' in resource:
                raise VersionCandidateDeclined('VERSION_PARTITION_BINDING_UNSUPPORTED', role=resource['role'])
            url = resource.get('source_url')
            if not url or scope[resource['role']]['source_url'] != url:
                raise VersionCandidateDeclined('VERSION_RESOURCE_BINDING_MISSING', role=resource['role'])
            shape, _ = csv_shape(admitted[resource['file_id']], resource.get('table', {}), cancelled)
            resources.append({'role': resource['role'], 'source_url': url, 'shape': shape})
        if len({r['source_url'] for r in resources}) != len(resources):
            raise VersionCandidateDeclined('VERSION_RESOURCE_BINDING_AMBIGUOUS')
        if not contract.get('documents') or any(not isinstance(d.get('url'), str) or not d['url']
                                                for d in contract['documents']):
            raise VersionCandidateDeclined('VERSION_EVIDENCE_UNAVAILABLE')
        return {'version': 'same-source-candidate-v1', 'eligible': True,
                'identity': identity, 'resources': resources}
    except BudgetExhausted:
        raise
    except (VersionCandidateDeclined, KeyError, ValueError, NeedsInput, ValidationFailure) as exc:
        return {'version': 'same-source-candidate-v1', 'eligible': False,
                'code': getattr(exc, 'code', 'VERSION_PROFILE_UNAVAILABLE'),
                'details': getattr(exc, 'details', {})}


def verified_version_record(record):
    """Repeat the registry/byte/dependency checks; cache files have no authority."""
    if not compatible_dependencies(record, dependencies()):
        raise VersionCandidateDeclined('VERSION_DEPENDENCY_CHANGED')
    for path, sha in record['evidence_pins'].items():
        if not Path(path).is_file() or Path(path).is_symlink() or file_hash(path) != sha:
            raise VersionCandidateDeclined('VERSION_EVIDENCE_CHANGED')
    original = registered(record['version'])
    normalized = json.loads(json.dumps(record['contract']))
    normalized.pop('documents', None)
    for resource in bound_inputs(normalized):
        resource.pop('file_id', None)
        for part in resource.get('partitions', []):
            part.pop('file_id', None)
    if normalized != original['contract']:
        raise VersionCandidateDeclined('VERSION_REGISTRY_CONTRACT_MISMATCH')
    admission = original['verification']['admission']
    if admission.get('image') != record['image']:
        raise VersionCandidateDeclined('VERSION_EXECUTOR_CHANGED')
    from .source_identity import canonical_source_identity
    if canonical_source_identity({'admission': admission}, record['contract']) != record['version_candidate']['identity']:
        raise VersionCandidateDeclined('VERSION_SOURCE_IDENTITY_CHANGED')


def measured_coverage(contract, files, cancelled):
    """Measure every crash date without filtering; other grains stay under QA."""
    from calendar import monthrange
    from .canonical import date_value, ContractError
    from .table_plan import iter_resource
    crashes = [r for r in contract['resources'] if r['grain'] == 'crash']
    if len(crashes) != 1:
        raise VersionCandidateDeclined('VERSION_COVERAGE_GRAIN_UNSUPPORTED')
    resource = crashes[0]
    spec = resource.get('mapping', {}).get('date')
    if not isinstance(spec, dict) or 'lookup' in spec:
        raise VersionCandidateDeclined('VERSION_COVERAGE_EXPRESSION_UNSUPPORTED', role=resource['role'])
    lower = upper = None
    count = 0
    for locator, raw in iter_resource(resource, files, cancelled):
        cancelled()
        try:
            parsed = date_value(raw, spec, contract)
        except ContractError as exc:
            raise VersionCandidateDeclined('VERSION_DATE_INVALID', role=resource['role'], row_locator=locator) from exc
        value = parsed['occurrence_date']
        precision = parsed['date_precision']
        if precision == 'year':
            lo, hi = value+'-01-01', value+'-12-31'
        elif precision == 'month':
            lo, hi = value+'-01', value+f'-{monthrange(int(value[:4]), int(value[5:7]))[1]:02d}'
        else:
            lo = hi = value
        lower, upper = min(lower, lo) if lower else lo, max(upper, hi) if upper else hi
        count += 1
    if not count:
        raise VersionCandidateDeclined('VERSION_EMPTY_INPUT')
    return {'from': lower, 'to': upper}, count


def version_signature(record):
    """Collapse only equivalent recipes, not 'latest wins' semantic changes."""
    from .trusted_qa import semantic_contract
    contract = semantic_contract(record['contract'])
    contract['source'].pop('coverage', None)  # Always remeasured and reauthorized.
    profile=json.loads(json.dumps(record['version_candidate']))
    resources={r['role']:r for r in bound_inputs(contract)}
    for entry in profile['resources']:
        entry['shape']={key:value for key,value in entry['shape'].items() if key not in {'encoding','delimiter'}}
        # Optional raw columns do not create competing semantic recipes. The
        # actual selected upload still needs whole-file official binding and
        # fresh QA, and no column may be silently dropped from its raw values.
        entry['shape']['fields']=sorted(required_fields(contract,resources[entry['role']]))
    shapes = {r['role']: r['shape'] for r in profile['resources']}
    for resource in bound_inputs(contract):
        resource['table'] = shapes[resource['role']]
    return digest({'contract': contract, 'profile': profile,
                   'evidence': sorted({(d['url'], d['sha256']) for d in record['documents']}),
                   'dependencies': record['dependencies'], 'image': record['image']})


def rebind_version_evidence(contract, old, fresh, old_raw, fresh_raw):
    """Reissue only unchanged structured claim values against the fresh bytes.

    Semantic comparison never licenses retaining a stale document hash or
    claiming that a free-text quotation has the same meaning after an edit.
    Full QA still rechecks scope, authority, reviewed pins and all constraints.
    """
    from .evidence_references import verify_reference, reference
    from .metadata_extractors import MetadataError
    for entries in contract.get('evidence', {}).values():
        if not isinstance(entries, list):
            continue
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict) or entry.get('document_id') != old['document_id']:
                continue
            locator = entry.get('locator') or {}
            if locator.get('kind') != 'json-pointer':
                raise VersionCandidateDeclined('VERSION_CITATION_REBIND_UNSUPPORTED', document_id=old['document_id'])
            try:
                previous = verify_reference(entry, {'sha256': old['sha256'], 'content_bytes': old_raw, 'url': old['url']})
                current = reference(fresh_raw, fresh['sha256'], fresh['document_id'], locator)
            except MetadataError as exc:
                raise VersionCandidateDeclined('VERSION_CITATION_CHANGED', document_id=old['document_id'], reason=exc.code) from exc
            if previous['value_sha256'] != current['value_sha256']:
                raise VersionCandidateDeclined('VERSION_CITATION_CHANGED', document_id=old['document_id'], locator=locator)
            entries[index] = {**entry, **current}


def refresh_version_document(session, contract, doc):
    """Use existing fetch/document registry and bounded knowledge comparison."""
    from .config import ROOT
    from .source_knowledge import registered_document_bytes, reuse_metadata_compatibility
    url = doc.get('url')
    if not url:
        raise VersionCandidateDeclined('VERSION_EVIDENCE_URL_MISSING')
    response = controlled(session, 'fetch_public_source', {'url': url, 'max_bytes': 4*1024**2})
    if response.get('status') != 'fetched' or response.get('final_url') != url:
        raise VersionCandidateDeclined('VERSION_EVIDENCE_LOCATION_CHANGED', document_id=doc['document_id'])
    # Fetch normally extracts metadata itself; otherwise use the same existing
    # registered-document tool. Never accept a model-supplied receipt or path.
    ids = [item['document_id'] for item in response.get('documents', []) if item.get('document_id')]
    if not ids:
        read = controlled(session, 'read_document', {'file_id': response['file_id']})
        ids = [read.get('document_id')]
    matches = [session.documents[i] for i in ids if i in session.documents
               and session.documents[i].get('sha256') == response['sha256']
               and session.documents[i].get('url') == url
               and session.documents[i].get('fetched_at') == response.get('fetched_at')]
    if len(matches) != 1:
        raise VersionCandidateDeclined('VERSION_FRESH_DOCUMENT_UNBOUND', document_id=doc['document_id'])
    fresh = matches[0]
    try:
        old_raw, old_receipt = registered_document_bytes(doc, ROOT)
        new_raw, new_receipt = registered_document_bytes(fresh, ROOT)
    except (ValueError, OSError) as exc:
        raise VersionCandidateDeclined('VERSION_EVIDENCE_RECEIPT_INVALID', document_id=doc['document_id']) from exc
    if old_receipt.get('final_url') != url or new_receipt.get('final_url') != url:
        raise VersionCandidateDeclined('VERSION_EVIDENCE_LOCATION_CHANGED', document_id=doc['document_id'])
    audit = {'rule': 'exact-evidence-bytes-v1', 'compatible': True,
             'before_raw_sha256': doc['sha256'], 'after_raw_sha256': fresh['sha256']}
    if fresh['sha256'] != doc['sha256']:
        audit = reuse_metadata_compatibility(old_raw, new_raw, url)
        if not audit['compatible']:
            raise VersionCandidateDeclined('VERSION_EVIDENCE_INCOMPATIBLE', document_id=doc['document_id'], comparison=audit)
        rebind_version_evidence(contract, doc, fresh, old_raw, new_raw)
    elif fresh['document_id'] != doc['document_id']:
        # Identical raw bytes at the same verified URL need no semantic
        # reinterpretation, even if a historical registry used another ID.
        for entries in contract.get('evidence', {}).values():
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict) and entry.get('document_id') == doc['document_id']:
                        entry['document_id'] = fresh['document_id']
    return fresh, {**audit, 'url': url, 'fetched_at': fresh.get('fetched_at'),
                   'old_document_id': doc['document_id'], 'new_document_id': fresh['document_id']}


def prepare_version_candidate(cache, session):
    """Bounded candidate reuse, followed by the original fresh-QA path.

    No schema-only match is promoted: fresh official endpoint bytes must equal
    the uploaded bytes, scoped evidence must pass a bounded compatibility rule, and a
    newly measured period needs explicit applicable temporal evidence. Nothing
    here updates a registry, reuses QA, grants deletion rights or changes no_change.
    """
    from .errors import NeedsInput, ValidationFailure, BudgetExhausted
    from .capability_preflight import preflight_contract, requires_system_change
    differences = []
    candidates = {}
    files = active_files(session.files)
    supplements = supplement_hashes(session.files)
    if not files or len(files) > 24:
        return None, {'route': 'version_investigation', 'differences': [{'code': 'VERSION_BUNDLE_LIMIT'}]}
    # Index-based shortlist, independent of unrelated legacy/audit object count.
    from .intakereaders import detect_tables
    observed_fields = set()
    for file in files:
        for table in detect_tables(file, {}, session.cancel):
            observed_fields.update(table.get('header', []))
    shas, truncated = cache.index.shortlist(fields=observed_fields, count=len(files), cancelled=session.cancel)
    if truncated:
        return None, {'route':'version_investigation','differences':[{'code':'VERSION_RELEVANT_CANDIDATE_LIMIT','truncated':True}]}
    paths = [cache.store.root / sha for sha in shas]
    for path in paths:
        session.cancel()
        record = json.loads(cache.store.get(path.name))
        if record.get('instance') != cache.instance or record.get('format') != 'admitted-recipe-v1':
            raise ValueError('Invalid recipe scope')
        profile = record.get('version_candidate') or {}
        if not profile.get('eligible'):
            if profile:
                differences.append({'recipe': path.name, 'code': profile.get('code', 'VERSION_PROFILE_UNAVAILABLE'),
                                    'details': profile.get('details', {})})
            continue
        try:
            if record.get('supplement_hashes', []) != supplements:
                raise VersionCandidateDeclined('VERSION_SUPPORTING_DOCUMENTS_CHANGED')
            if len(files) != len(profile['resources']):
                raise VersionCandidateDeclined('VERSION_RESOURCE_SET_CHANGED')
            verified_version_record(record)
            # Conservative shortlist only. Pairing is proved later by official
            # bytes, allowing two different roles to share a column schema.
            observed = []
            for file in files:
                if file_hash(file['path']) != file['sha256'] or Path(file['path']).is_symlink():
                    raise VersionCandidateDeclined('VERSION_INPUT_CHANGED')
                choices = []
                comparisons = []
                for entry in profile['resources']:
                    resource = next(r for r in bound_inputs(record['contract']) if r['role'] == entry['role'])
                    shape, spec = csv_shape(file, resource.get('table', {}), session.cancel)
                    comparisons.append({'role': entry['role'],
                        'added_fields': sorted(set(shape['fields'])-set(entry['shape']['fields'])),
                        'missing_fields': sorted(set(entry['shape']['fields'])-set(shape['fields'])),
                        'parser_changed': [k for k in ('format','table_id','encoding','delimiter') if shape[k] != entry['shape'][k]]})
                    if shape_compatible(record['contract'],resource,shape,entry['shape']):
                        choices.append({'role': entry['role'], 'table': spec})
                if not choices:
                    raise VersionCandidateDeclined('VERSION_SCHEMA_OR_PARSER_DRIFT', file_id=file['id'], comparisons=comparisons)
                observed.append({'file': file, 'choices': choices})
            key = version_signature(record)
            candidates[key] = (record, observed, path.name)
        except (VersionCandidateDeclined, NeedsInput, ValidationFailure) as exc:
            differences.append({'recipe': path.name, 'code': getattr(exc, 'code', 'VERSION_CANDIDATE_INVALID'),
                                'details': getattr(exc, 'details', {})})
    if len(candidates) != 1:
        return None, {'route': 'version_investigation', 'differences': differences[:24] + [
            {'code': 'VERSION_CANDIDATE_AMBIGUOUS' if candidates else 'VERSION_NO_COMPATIBLE_CANDIDATE',
             'candidate_count': len(candidates)}]}
    record, observed, sha = next(iter(candidates.values()))
    session.runtime_state['version_reuse_candidate'] = {'recipe_sha256': sha, 'status': 'checking_binding', 'admitted': False}
    session.persist()
    try:
        historical=historical_representation_candidate(record,observed,session)
        if historical:
            proposal,bindings=historical
            proposal['documents']=record['documents']
            references=record.get('binding_files',[])
            checked=preflight_contract(proposal,[*session.files,*[f for f in references if f['id'] not in {i['id'] for i in session.files}]],
                session.work_dir,check_cancelled=session.cancel,operation_policy=True)
            if not checked['ok']:
                if requires_system_change(checked):raise NeedsInput('Historical candidate requires a system change.',[],checked)
                raise VersionCandidateDeclined('VERSION_HISTORICAL_PREFLIGHT_BLOCKED',preflight=checked)
            proposal.pop('documents',None)
            decision={'route':'same_source_representation_candidate_requires_fresh_QA','recipe_sha256':sha,
                'binding_proofs':bindings,'metadata':'Previously reviewed and byte-pinned applicable version evidence',
                'model_calls':0,'admitted':False}
            session.runtime_state['version_reuse_candidate']=decision;session.persist()
            return {'contract':proposal,'documents':record['documents'],'image':record['image'],'binding_files':references},decision
        # Bounded exact refetches use the existing controlled public fetch tool;
        # no new HTTP stack or input replacement. Failed fetches go to the Agent.
        old_docs = record['documents']
        if not old_docs or len(old_docs) > 16:
            raise VersionCandidateDeclined('VERSION_EVIDENCE_REFRESH_LIMIT')
        contract = json.loads(json.dumps(record['contract']))
        contract.pop('documents', None)
        docs, refreshed = [], []
        for doc in old_docs:
            fresh, comparison = refresh_version_document(session, contract, doc)
            docs.append(fresh)
            refreshed.append(comparison)
            session.runtime_state['version_reuse_candidate']['evidence_refresh'] = refreshed
            session.persist()
        bindings = {}
        for entry in record['version_candidate']['resources']:
            response = controlled(session, 'fetch_public_source', {'url': entry['source_url'], 'max_bytes': 512*1024**2})
            if response.get('status') != 'fetched' or response.get('final_url') != entry['source_url']:
                raise VersionCandidateDeclined('VERSION_RESOURCE_REPRESENTATION_CHANGED', role=entry['role'])
            matches = [(row['file'], choice['table']) for row in observed for choice in row['choices']
                       if choice['role'] == entry['role'] and row['file']['sha256'] == response.get('sha256')
                       and row['file']['size'] == response.get('size')]
            if not matches:
                from .representation_binding import compare_csv
                reference=next((f for f in session.files if f['id']==response.get('file_id') and f.get('role')=='public_evidence'),None)
                if reference:
                    from .source_binding import reference_receipt
                    from .config import ROOT
                    reference_receipt(reference,ROOT)
                    for row in observed:
                        for choice in row['choices']:
                            if choice['role']!=entry['role']:continue
                            comparison=compare_csv(reference,row['file'],session.work_dir/'version-representation',
                                reference_table=choice['table'],upload_table=choice['table'],cancelled=session.cancel)
                            if comparison['equivalent']:matches.append((row['file'],choice['table']))
            if len(matches) != 1:
                raise VersionCandidateDeclined('VERSION_OFFICIAL_BYTES_UNBOUND', role=entry['role'], matches=len(matches),
                    source_url=entry['source_url'], current_export_sha256=response.get('sha256'),
                    reason='No supported proof binds this uploaded version/representation; a current export, matching schema or related URL is insufficient.')
            bindings[entry['role']] = matches[0]
        if len({f['id'] for f, _ in bindings.values()}) != len(files):
            raise VersionCandidateDeclined('VERSION_RESOURCE_BINDING_AMBIGUOUS')
        for resource in bound_inputs(contract):
            file, table = bindings[resource['role']]
            resource['file_id'] = file['id']
            resource['table'] = table  # Same parser; header order comes from this input.
        coverage, rows = measured_coverage(contract, files, session.cancel)
        contract['source']['coverage'] = coverage
        # Keep update semantics unchanged. Extending a partition or claiming a
        # complete snapshot needs its own current source-completeness proof.
        if contract['update']['mode'] == 'partition' and (
                coverage['from'] < contract['update']['from'] or coverage['to'] > contract['update']['to']):
            raise VersionCandidateDeclined('VERSION_UPDATE_SCOPE_CHANGED', measured_coverage=coverage)
        proposal = {**contract, 'documents': docs}
        preflight = preflight_contract(proposal, session.files, session.work_dir, check_cancelled=session.cancel, operation_policy=True)
        if not preflight['ok']:
            if requires_system_change(preflight):
                raise NeedsInput('Version candidate requires a system change.', [], preflight)
            raise VersionCandidateDeclined('VERSION_PREFLIGHT_BLOCKED', preflight=preflight)
        # Measured date extent is not a completeness/deletion claim. Exact
        # official resource binding and applicable meanings still passed above;
        # publication separately checks actual removed history in its transaction.
        decision = {'route': 'same_source_version_candidate_requires_fresh_QA', 'recipe_sha256': sha,
                    'measured_coverage': coverage, 'coverage_kind':'observed-records-only', 'complete':False, 'crash_rows_scanned': rows, 'refreshed_evidence': refreshed,
                    'binding': 'exact or completely replayed CSV representation from each scoped official resource endpoint', 'admitted': False}
        session.runtime_state['version_reuse_candidate'] = decision
        session.persist()
        return {'contract': contract, 'documents': docs, 'image': record['image']}, decision
    except BudgetExhausted:
        raise
    except (VersionCandidateDeclined, NeedsInput, ValidationFailure) as exc:
        details = getattr(exc, 'details', {})
        if requires_system_change(details):
            raise
        decision = {'route': 'version_investigation', 'recipe_sha256': sha,
                    'differences': [{'code': getattr(exc, 'code', 'VERSION_BINDING_UNRESOLVED'), 'details': details}],
                    'evidence_refresh': session.runtime_state.get('version_reuse_candidate', {}).get('evidence_refresh', []),
                    'admitted': False, 'next_action': 'Investigate these exact differences with the existing Agent; fresh QA is mandatory.'}
        session.runtime_state['version_reuse_candidate'] = decision
        session.persist()
        return None, decision
