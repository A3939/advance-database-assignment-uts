"""Independent canonical-v2 replay and admission, outside generated Python.

Never consumes an adapter's self-reported totals as the answer. Every emitted
record is checked against the immutable raw row and evidence-backed contract.
"""
from collections import Counter
import calendar
from datetime import date
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit
from uuid import uuid4

from .canonical import ContractError, project, stable_json
from .errors import NeedsInput, ValidationFailure
from .intakereaders import iter_table, detect_format, detect_tables
from .table_plan import physical_resources, expand_resources, prepare_union, iter_resource, input_resources, bound_inputs

POLICY="canonical-v2-auto-admission-26"
ARTIFACT_NAMES={"crash":"crashes.jsonl","unit":"units.jsonl","casualty":"casualties.jsonl","observation":"observations.jsonl"}
TRUSTED_FILES=('source_binding.py','representation_binding.py','retained_resources.py','row_preprocessing.py','native_membership.py','capability_limits.py','licence_assessment.py','publication_summary.py','archive_parser.py','parser_guard.py','parser_worker.py','document_parser.py','coverage_policy.py','date_bounds.py','knowledge/date-range.json','publication_policy.py','timezone_rules.py','knowledge/timezones/manifest.json','knowledge/timezones/windowsZones.json','knowledge/timezones/tzdb.zip','publication_identity.py','arcgis_query.py','trusted_qa.py','evidence_grounding.py','evidence_graph.py','evidence_scope.py','update_compatibility.py','source_completeness.py','publication.py','public_sources.py','arcgis_export.py','count_semantics.py','count_definitions.py','knowledge/reviewed-count-claims.json','category_evidence.py','source_identity.py','metadata_extractors.py','evidence_references.py','rdf_geography.py','geometry_evidence.py','capability_preflight.py','geography_review.py','casualty_review.py','canonical.py','transform_plan.py','isolated_executor.py','intakereaders.py','workbook_plan.py','table_plan.py','lookup_plan.py','lookup_projection.py','lookup_semantics.py','lookup_evidence.py','knowledge/reviewed-lookup-claims.json','table_classification.py','intake_tools.py','errors.py')


TRUSTED_FILES += ('independent_versions.py', 'task_authority.py', 'task_diagnostics.py', 'repair_context.py')


def row_digest(row):
    # Same canonical serialization previously compared as full SQLite TEXT.
    # Input and canonical files remain intact; this only bounds the scratch DB.
    return hashlib.sha256(stable_json(row).encode()).digest()


def qa_projection(row, *, collapsed=False):
    """Only fields later consumed by relational/aggregate SQL, never row proof."""
    fields = ('declared_units', 'declared_casualties', 'casualties',
              'fatalities', 'is_fatal', 'severity_label', 'unit_type', 'geography_status')
    return stable_json({key: row[key] for key in (*fields, *(['row_locator'] if collapsed else [])) if key in row})


def trusted_implementation():
    return {name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in TRUSTED_FILES}


LOADED_IMPLEMENTATION=trusted_implementation()


def semantic_contract(contract):
    value=json.loads(stable_json(contract))
    documents={d.get('document_id'):d for d in value.get('documents',[]) if isinstance(d,dict)}
    value.pop('documents',None)
    # Public catalogue responses contain volatile download/view counters. Their
    # exact bytes remain in admission evidence, but a changed receipt ID alone
    # must not republish identical inputs under identical transformation rules.
    for entries in value.get('evidence',{}).values():
        if not isinstance(entries,list):continue
        for entry in entries:
            if not isinstance(entry,dict):continue
            doc=documents.get(entry.get('document_id'))
            if doc and doc.get('url'):
                entry.pop('document_id',None);entry['document_url']=doc['url']
                if isinstance(entry.get('quote'),str):entry['quote']=' '.join(entry['quote'].split())
    for resource in bound_inputs(value):
        date_mapping=resource.get('mapping',{}).get('date',{})
        if date_mapping.get('kind') in {'epoch_ms','epoch_s'}:
            from .timezone_rules import canonical_zone
            date_mapping['timezone']=canonical_zone(date_mapping.get('timezone','UTC'))
        resource['file_id']='resource:'+resource['role']
        for index,part in enumerate(resource.get('partitions',[])):
            part['file_id']=resource['file_id'] if index==0 else resource['file_id']+':partition:'+str(index)
    return value


def digest(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def block(message,code="QA06_RECONCILIATION",**metrics):
    raise ValidationFailure(message,[{"code":code,"status":"block","message":message,"metrics":metrics}])


def evidence_integrity(message, document_id):
    # Host receipts are not a source-quality question for the data Agent.
    raise ValidationFailure(message,
        [{'code':'EVIDENCE_INTEGRITY','status':'block','message':message,'metrics':{'document_id':document_id}}],
        {'blockers':[{'code':'EVIDENCE_INTEGRITY','kind':'environment_dependency','message':message,
                      'responsible_party':'system','details':{'document_id':document_id}}]})


def projection_difference(expected, candidate):
    """Actionable schema/hash diagnostics without exposing raw personal rows.

    This never changes the exact comparison or authorizes a tolerance.
    """
    fields = sorted(key for key in expected.keys() | candidate.keys()
                    if key not in expected or key not in candidate or stable_json(expected[key]) != stable_json(candidate[key]))
    result = {"differing_fields":[key if key in expected else '<unexpected_field>' for key in fields[:32]], "differing_field_count":len(fields),
              "expected_sha256":hashlib.sha256(stable_json(expected).encode()).hexdigest(),
              "candidate_sha256":hashlib.sha256(stable_json(candidate).encode()).hexdigest()}
    import math
    points = [expected.get('coordinates'),candidate.get('coordinates')]
    if all(isinstance(p,list) and len(p)==2 and all(type(v) in (float,int) and math.isfinite(v) for v in p) for p in points):
        result['coordinate_absolute_delta_degrees'] = [abs(a-b) for a,b in zip(*points)]
    return result


def _proof(contract,work_dir,files=None,check_cancelled=None):
    diagnostics=[]
    try:return _proof_checks(contract,work_dir,files,check_cancelled,diagnostics)
    except NeedsInput as exc:
        exc.details.setdefault('checks',diagnostics)
        raise


def _proof_checks(contract,work_dir,files=None,check_cancelled=None,diagnostics=None):
    """Only receipts from the trusted fetch/read-document registry are eligible.

    The orchestrator injects these descriptors; a contract supplied by the model
    alone has no documents authority. This function also rechecks the archived
    response and extracted text against the receipt on disk.
    """
    check_cancelled=check_cancelled or (lambda:None)
    check_cancelled()
    diagnostics=diagnostics if diagnostics is not None else []
    documents={}
    for doc in contract.get("documents",[]):
        check_cancelled()
        if not isinstance(doc,dict):continue
        doc_id=doc.get("document_id") or doc.get("file_id") or doc.get("id")
        receipt_path=doc.get("receipt_path")
        if not doc_id or not receipt_path:continue
        receipt_path=Path(receipt_path).resolve()
        # Evidence can be reused from another registered attempt in this lab,
        # but never from an arbitrary host path supplied by generated code.
        from .config import ROOT
        if not receipt_path.is_relative_to(ROOT.resolve()) or not receipt_path.is_file():
            from .config import RuntimeConfigurationError
            raise RuntimeConfigurationError('Registered evidence receipt escaped or is missing from this instance')
        try:receipt=json.loads(receipt_path.read_text())
        except (json.JSONDecodeError,UnicodeError):evidence_integrity('Registered evidence receipt is invalid',doc_id)
        if not isinstance(receipt,dict):evidence_integrity('Registered evidence receipt is not an object',doc_id)
        if receipt.get('status')!='fetched':continue
        url=receipt.get('final_url','')
        host=urlsplit(url).hostname or ''
        # Fetch safety and authority are separate. Verified external bytes are
        # eligible only for the scoped roles derived by the evidence graph.
        from .evidence_graph import representation
        if representation(url) is None:continue
        sha=receipt.get('sha256');content=receipt_path.parent/'sha256'/str(sha)
        if not content.is_file() or digest(content)!=sha:
            evidence_integrity('Registered evidence bytes are missing or changed',doc_id)
        text_path=doc.get('text_path');text_sha=doc.get('text_sha256')
        if text_path:
            text_path=Path(text_path).resolve()
            if not text_path.is_relative_to(ROOT.resolve()) or not text_path.is_file() or digest(text_path)!=text_sha:
                evidence_integrity('Registered extracted evidence text is missing, changed or outside this instance',doc_id)
            text=text_path.read_text(encoding='utf-8')
        else:
            try:text=content.read_text(encoding='utf-8')
            except UnicodeError:continue
        documents[doc_id]={"url":url,"sha256":sha,"text":text,"content_bytes":content.read_bytes(),
                           "publisher_verified":bool(host.endswith('.gov.au') and receipt.get('final_host_official')),
                           "fetched_at":receipt.get('fetched_at'), 'receipt_sha256':digest(receipt_path),
                           'requested_url':receipt.get('url',receipt.get('requested_url')), 'redirects':receipt.get('redirects',[])}
    required={'source_identity','grain','coverage_update','date'}
    if any(r.get('mapping',{}).get('severity') or r.get('mapping',{}).get('injury') for r in contract['resources']):required.add('severity')
    if any(any(k in r.get('mapping',{}) for k in ('fatalities','casualties','declared_units','declared_casualties','metrics')) for r in contract['resources']):required.add('counts')
    if contract.get('relations') or contract.get('lookup_tables'):required.add('relations')
    if any(r.get('mapping',{}).get('geography') for r in contract['resources']):required.add('geography')
    accepted={};missing=[];rejected=[]
    for claim in required:
        entries=contract.get('evidence',{}).get(claim,[])
        accepted[claim]=[]
        for entry in entries if isinstance(entries,list) else []:
            if not isinstance(entry,dict):continue
            doc=documents.get(entry.get('document_id'));quote=entry.get('quote')
            if doc and 'locator' in entry:
                from .evidence_references import verify_reference
                from .metadata_extractors import MetadataError
                try:
                    accepted[claim].append(verify_reference(entry, doc))
                except MetadataError as exc:
                    rejected.append({'claim':claim,'document_id':entry.get('document_id'), 'reason':exc.code,
                        'next_action':'Read the exact registered document location again; keep its original hash and locator.'})
            elif doc and isinstance(quote,str) and 12<=len(quote)<=12000 and ' '.join(quote.split()) in ' '.join(doc['text'].split()):
                accepted[claim].append({"document_id":entry['document_id'],"url":doc['url'],"sha256":doc['sha256'],"quote":quote})
            else:
                rejected.append({'claim':claim,'document_id':entry.get('document_id'),
                    'reason':'document_not_verified' if not doc else 'quote_length_invalid' if not isinstance(quote,str) or not 12<=len(quote)<=12000 else 'quote_not_exact',
                    'next_action':'Read the registered document using a targeted field-name search and copy an exact supporting excerpt.'})
        if not accepted[claim]:missing.append(claim)
    diagnostics.extend({'code':'OFFICIAL_CLAIM_REFERENCE','claim':claim,'status':'fail' if claim in missing else 'pass'} for claim in sorted(required))
    if missing:
        diagnostics.append({'code':'SOURCE_GROUNDING','status':'not_checked'})
        raise NeedsInput("Official evidence is incomplete for automatic source admission.",
            ["Obtain an accessible official definition for: "+', '.join(sorted(missing))+". Uploaded documents can guide discovery but do not authorize unsupported meanings."],
            {"missing_evidence":sorted(missing),"rejected_evidence":rejected[:32],
             "verified_documents":[{'document_id':key,'url':doc['url']} for key,doc in documents.items()],"policy_version":POLICY})
    from .evidence_grounding import ground_contract
    from .evidence_graph import build_graph
    from .metadata_extractors import MetadataError
    from .rdf_geography import prove_coordinates, CoordinateBindingError
    try:
        graph=build_graph(contract.get('source',{}).get('dataset_url',''),documents,
                          {entry['document_id'] for entry in accepted.get('source_identity',[])},
                          cited_ids={entry['document_id'] for entries in contract.get('evidence',{}).values() for entry in entries if isinstance(entry,dict) and entry.get('document_id')},
                          resource_urls=[r.get('source_url') for r in input_resources(contract) if r.get('source_url')],check_cancelled=check_cancelled)
        coordinates=prove_coordinates(contract,files,documents,graph,check_cancelled=check_cancelled,include_omitted=True)
    except (MetadataError,CoordinateBindingError) as exc:
        raise NeedsInput(str(exc), [], {'grounding':{'ok':False,'issues':[{'code':exc.code,'message':str(exc),
            **getattr(exc,'details',{})}]},'policy_version':POLICY}) from exc
    grounding=ground_contract(contract,documents,accepted,graph=graph,coordinate_proofs=coordinates)
    diagnostics.extend(grounding.get('checks',[]))
    if not grounding['ok']:
        raise NeedsInput('Official evidence does not ground the declared source or mapped fields.',
            ['Resolve the scoped source/field evidence diagnostics, preserving documented source capabilities.'],
            {'grounding':grounding,'policy_version':POLICY})
    from .arcgis_query import bind_uploads
    try:
        representation_proofs=bind_uploads(contract,files,documents,graph,check_cancelled)
    except MetadataError as exc:
        diagnostics.append({'code':exc.code,'status':'fail'})
        raise NeedsInput(str(exc),[],{'grounding':{'issues':[{'code':exc.code,'message':str(exc), **exc.details}]}}) from exc
    if files is None:diagnostics.append({'code':'ARCGIS_UPLOAD_BINDING','status':'not_checked'})
    for item in representation_proofs:
        diagnostics.append({'code':'ARCGIS_UPLOAD_BINDING','role':item['role'],'status':'pass'})
    if contract.get('lookup_tables'):
        from .lookup_evidence import review_lookup_relations
        from .lookup_semantics import capability_resources
        from .geography_review import review_lookup_geography_subject
        from .errors import UnsupportedCapability
        # A parent's date could be a birth, installation or publication date.
        # Physical projection alone cannot prove it is the consumer event date.
        if any(isinstance(value,dict) for resource in contract['resources']
               for value in resource.get('mapping',{}).get('date',{}).values()):
            raise UnsupportedCapability('LOOKUP_DATE_SEMANTICS_UNSUPPORTED',
                'A date taken from another table requires a reviewed event-date subject rule; source presence and a foreign key are insufficient.')
        try:
            relation_review=review_lookup_relations(contract,graph,grounding,accepted,documents=documents)
        except MetadataError as exc:
            raise NeedsInput(str(exc), [], {'lookup_relation_review':{'ok':False,'issues':[{'code':exc.code,'message':str(exc)}]}}) from exc
        subject_review=review_lookup_geography_subject(contract,documents,grounding,accepted,graph)
        if not relation_review['ok'] or not subject_review['ok']:
            raise NeedsInput('Lookup relationship or coordinate subject evidence is incomplete or conflicting.',
                ['Resolve the exact scoped relation and coordinate-subject diagnostics; preserve the original rows.'],
                {'lookup_relation_review':relation_review,'lookup_geography_subject_review':subject_review,'policy_version':POLICY})
        accepted['lookup_relation_review']=relation_review
        accepted['lookup_geography_subject_review']=subject_review
        capability_views=capability_resources(contract)
    else:
        capability_views=contract['resources']
    # Do not let unrelated extra citations acquire registry/update authority
    # merely because another citation was sufficient to ground the claim.
    for claim, entries in accepted.items():
        if claim in {'lookup_relation_review','lookup_geography_subject_review','upload_bindings'}:continue
        permitted = grounding['source_anchor_documents'] if claim == 'source_identity' else grounding['connected_documents']
        accepted[claim] = [entry for entry in entries if entry['document_id'] in permitted]
    from .geography_review import review_geography
    observed={}
    admitted_files={file['id']:file for file in (files or [])}
    for resource in expand_resources(capability_views):
        file=admitted_files.get(resource['file_id'])
        if file is None:continue
        table_spec=resource.get('table',{})
        tables=detect_tables(file,table_spec,check_cancelled)
        selected=table_spec.get('sheet',table_spec.get('table_id'))
        matching=[table for table in tables if table['table_id']==selected or (selected is None and len(tables)==1)]
        if len(matching)==1:observed[resource['role']]=matching[0]['header']
    geography_review=review_geography({**contract,'resources':capability_views},documents,grounding,observed)
    from .capability_limits import geography_limited, limitations
    limited_roles={r['role'] for r in contract['resources'] if geography_limited(r)}
    geography_review['limited_issues']=[i for i in geography_review['issues'] if i.get('role') in limited_roles]
    geography_review['blocking_issues']=[i for i in geography_review['issues'] if i.get('role') not in limited_roles]
    geography_review['ok']=not geography_review['blocking_issues']
    geography_review['status']='limited' if limited_roles else 'pass' if geography_review['ok'] else 'blocked'
    from .retained_resources import limitations as retained_limitations
    accepted['capability_limits']=limitations(contract)+retained_limitations(contract)
    if contract.get('retained_resources'):
        geography_review['status']='limited'
        geography_review['retained_auxiliary_issues']=[{'code':'AUXILIARY_SEMANTICS_UNRESOLVED','role':r['role'],
            'grain':r['grain'],'message':r['reason'],'requested':r['requested']} for r in contract['retained_resources']]
    from .casualty_review import review_casualty_scope
    casualty_review=review_casualty_scope(contract,documents,grounding,graph=graph)
    if not geography_review['ok'] or not casualty_review['ok']:
        failure=NeedsInput('Documented source capabilities or reconciliation applicability need review.',
            ['Resolve the specific geographic and casualty-scope diagnostics, then rerun sample/full QA.'],
            {'capability_review':geography_review,'casualty_scope_review':casualty_review,'policy_version':POLICY})
        from .capability_preflight import exception_blockers, requires_system_change
        failure.details['blockers']=exception_blockers(failure)
        if requires_system_change(failure.details):failure.questions=[]
        raise failure
    accepted['evidence_selection']=graph['selection']
    accepted['representation_proofs']=representation_proofs
    accepted['grounding']=grounding
    accepted['capability_review']=geography_review
    accepted['casualty_scope_review']=casualty_review
    from .count_semantics import review_count_operations
    counts_review=review_count_operations(contract,documents,grounding,accepted,graph)
    if not counts_review['ok']:
        raise NeedsInput('Official evidence does not authorize the proposed count operation.',
                         ['Resolve the specific count-operation definition; do not manufacture equivalence or silently remove supported metrics.'],
                         {'count_operation_review':counts_review,'policy_version':POLICY})
    accepted['count_operation_review']=counts_review
    from .category_evidence import review_categories
    categories_review=review_categories(contract,graph,grounding,accepted)
    if contract.get('lookup_tables'):
        origins={(item['role'],item['field']) for item in categories_review.get('lookup_field_origins',[])}
        if any(item.get('status')=='legacy_text_scope' and (item['role'],item['field']) in origins
               for item in categories_review['decisions']):
            from .errors import UnsupportedCapability
            raise UnsupportedCapability('LOOKUP_CATEGORY_SEMANTICS_UNSUPPORTED',
                'A projected parent category needs a scoped code/label/outcome proof. Field presence or legacy text scope alone cannot authorize the lookup classification.')
    if not categories_review['ok']:
        raise NeedsInput('Official category definitions do not support the proposed classification.',
                         ['Resolve the specific category/label/outcome diagnostics without discarding source classifications.'],
                         {'category_review':categories_review,'policy_version':POLICY})
    accepted['category_review']=categories_review
    from .source_completeness import review_completeness
    from .config import ROOT
    accepted['source_completeness']=review_completeness(contract,files or [],graph,grounding,root=ROOT,check_cancelled=check_cancelled)
    from .source_binding import bind_uploads as bind_resource_uploads
    accepted['upload_bindings']=bind_resource_uploads(contract,files,graph,ROOT,work_dir,check_cancelled,
        completeness=accepted['source_completeness'])
    for item in accepted['upload_bindings']:
        diagnostics.append({'code':'OFFICIAL_UPLOAD_BINDING','role':item['role'],'status':'pass','rule':item['rule']})
    from .transform_plan import contract_plans, TransformError
    try:
        accepted['transform_plans']=contract_plans(contract)
    except TransformError as exc:
        from .capability_preflight import blocker
        raise NeedsInput(str(exc), [], {'blockers':[blocker(exc.code,exc.kind,str(exc),details=exc.details)]}) from exc
    accepted['checks']=diagnostics
    from .licence_assessment import assess
    accepted['licensing'] = assess(contract, documents, graph)
    return accepted


def validate_contract(contract,files,native_context=None,check_cancelled=None,table_receipts=None):
    check_cancelled=check_cancelled or (lambda:None)
    check_cancelled()
    if not isinstance(contract,dict) or contract.get('contract_version')!='canonical-v2':block('Expected canonical-v2 source contract','QA01_INPUT')
    from .independent_versions import validate as validate_version
    validate_version(contract, files)
    if 'confirmed' in contract:block('Model-supplied confirmation is not automatic admission','QA01_INPUT')
    source=contract.get('source',{})
    sid=source.get('source_id')
    if native_context is not None:
        if contract.get('retained_resources'):
            from .errors import UnsupportedCapability
            raise UnsupportedCapability('NATIVE_RETAINED_AUXILIARY_UNSUPPORTED','Frozen native layout cannot silently restrict an auxiliary resource')
        if 'lookup_tables' in contract or any('lookups' in r for r in contract.get('resources',[])):
            from .errors import UnsupportedCapability
            raise UnsupportedCapability('NATIVE_LOOKUP_UNSUPPORTED','Autonomous lookup cannot alter a frozen native table layout.')
        if any('partitions' in r for r in contract.get('resources',[])):
            from .errors import UnsupportedCapability
            raise UnsupportedCapability('NATIVE_UNION_UNSUPPORTED','Frozen native revisions require their reviewed native table layout; autonomous union cannot change that boundary.')
        from .native_revision import validate_revision_contract
        validate_revision_contract(native_context,contract,files)
    if not isinstance(sid,str) or not re.fullmatch(r'[a-z][a-z0-9_]{1,79}',sid) or sid.startswith('syn_') or (sid.startswith('official_') and native_context is None):
        block('Autonomous sources need a stable new dataset identity; frozen source namespaces cannot be overwritten','QA01_INPUT')
    for key in ('publisher','title','dataset_url'):
        if not isinstance(source.get(key),str) or not source[key].strip():block('Source metadata is missing: '+key,'QA01_INPUT')
    if source.get('licence') is not None and not isinstance(source['licence'], (str, dict)):
        block('Licence must be a declaration or explicit unknown value', 'QA01_INPUT')
    states=source.get('jurisdiction')
    if isinstance(states,str):states=[states]
    if not isinstance(states,list) or not states or not set(states)<= {'NSW','VIC','QLD','SA','ACT','TAS','WA','NT','AU'}:
        block('Declare source jurisdictions independently of source identity','QA01_INPUT')
    coverage=source.get('coverage',{})
    update=contract.get('update',{})
    try:
        lo=date.fromisoformat(coverage['from']);hi=date.fromisoformat(coverage['to'])
        if lo>hi:raise ValueError()
        if update.get('mode') not in {'snapshot','partition','incremental'}:raise ValueError()
        if update.get('mode')=='partition' and date.fromisoformat(update['from'])>date.fromisoformat(update['to']):raise ValueError()
    except (ValueError,KeyError,TypeError):block('Coverage and update semantics must be explicit','QA01_INPUT')
    resources=contract.get('resources',[])
    if not isinstance(resources,list) or not 1<=len(resources)<=24:block('Declare 1–24 resources','QA01_INPUT')
    lookup_compilation=None;lookup_plans=[]
    if 'lookup_tables' in contract or any(isinstance(r,dict) and 'lookups' in r for r in resources):
        from .lookup_projection import LookupProjection
        from .lookup_plan import prepare_lookup
        lookup_compilation=LookupProjection(contract,files,None,check_cancelled,compile_only=True)
        for role,name,parent,join in lookup_compilation.declarations:
            _,plan=prepare_lookup(parent,files,join,check_cancelled)
            lookup_plans.append({'purpose':'lookup_plan','role':parent['role'],'child_role':role,'lookup':name,'plan':plan})
    compiled_roles={r['role']:r for r in lookup_compilation.compiled['resources']} if lookup_compilation else {}
    lookup_roles={r['role'] for r in contract.get('lookup_tables',[])}
    file_ids={f['id'] for f in files};roles={};grains=Counter();union_plans=[]
    for r in resources:
        if not isinstance(r,dict) or r.get('grain') not in ARTIFACT_NAMES:block('Unsupported or missing record grain','QA01_INPUT')
        from .capability_limits import geography_limited
        geography_limited(r)
        from .row_preprocessing import enabled as collapse_enabled
        collapse_enabled(r)
        if not isinstance(r.get('role'),str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',r['role']) or r['role'] in roles:block('Resource roles must be unique','QA01_INPUT')
        if r.get('file_id') not in file_ids:block('A resource is not an admitted input','QA01_INPUT')
        if not isinstance(r.get('key'),list) or not 1<=len(r['key'])<=16 or any(not isinstance(k,str) or not k for k in r['key']):block('Complete source keys are required','QA01_INPUT')
        roles[r['role']]=r;grains[r['grain']]+=1
        if 'partitions' in r:
            _,plan=prepare_union(r,files,check_cancelled)
            union_plans.append({'purpose':'logical_union','role':r['role'],'plan':plan})
        from .canonical import count_fields, ContractError
        from .count_semantics import count_specs
        for metric,spec in count_specs(compiled_roles.get(r['role'],r)):
            try:count_fields(spec)
            except ContractError as exc:block(str(exc),'QA05_SEMANTICS',role=r['role'],metric=metric)
    if grains['crash']>1 or (grains['crash'] and grains['observation']):block('One dataset publication cannot combine overlapping crash and aggregate grains','QA01_INPUT')
    if not (grains['crash'] or grains['observation']):block('Provide a crash dataset or explicit aggregate observations','QA01_INPUT')
    from .retained_resources import validate as validate_retained
    retained=validate_retained(contract,files)
    retained_roles={r['role'] for r in retained}
    physical=expand_resources(bound_inputs(contract))
    inventory=[];document_decisions=[]
    for file in files:
        check_cancelled()
        if file.get('role')=='public_evidence' or file.get('evidence_url'):continue
        kind=detect_format(file)
        if kind not in {'csv','xlsx','xls','json','geojson'}:continue
        assigned=[r for r in physical if r['file_id']==file['id']]
        try:tables=detect_tables(file,assigned[0].get('table') if assigned else None,check_cancelled)
        except NeedsInput:
            from .table_classification import document_object
            if kind=='json' and not assigned and document_object(file):
                document_decisions.append({'file_sha256':file['sha256'],'purpose':'structured_document',
                                           'basis':'Bounded metadata-only JSON object grammar; no record collections.'})
                continue
            raise
        inventory.append((file,kind,tables,assigned))
    from .table_classification import dictionary_review
    physical_tables=[(file,table) for file,_,tables,_ in inventory for table in tables]
    decisions=document_decisions;assigned_physical=set()
    for file,kind,tables,assigned in inventory:
        for table in tables:
            plaintext=kind=='csv' and Path(file['name']).suffix.lower() in {'.txt','.md'} and len(table['header'])==1
            decision={'file_sha256':file['sha256'],'table_id':table['table_id']}
            matches=[r for r in assigned if (r.get('table',{}).get('sheet',r.get('table',{}).get('table_id'))==table['table_id']
                or (len(tables)==1 and not r.get('table',{}).get('sheet') and not r.get('table',{}).get('table_id')))]
            if table.get('empty'):
                if matches:block('An empty worksheet cannot be assigned a fact grain','QA02_RAW',table_id=table['table_id'])
                decisions.append({**decision,'purpose':'empty','parser_plan':table.get('parser_plan')})
                continue # Inventory retains it; the reader inspected the entire sheet.
            if not matches:
                dictionary=dictionary_review(file,table,physical_tables,check_cancelled)
                if dictionary:
                    decisions.append(dictionary)
                    continue
                if plaintext:
                    decisions.append({**decision,'purpose':'plaintext_document','basis':'Legacy single-column TXT/MD document path; not publisher authority.'})
                    continue
            if len(matches)!=1:
                block('Uploaded tabular resource was not assigned a grain exactly once; bundle rows cannot silently disappear or duplicate','QA02_RAW',
                    file_id=file['id'],filename=file['name'],table_id=table['table_id'],assignments=len(matches))
            if lookup_compilation:
                identity=(file.get('sha256'),table['table_id'])
                if identity in assigned_physical:
                    block('The same physical table cannot be assigned to multiple fact/lookup roles under different upload IDs','QA02_RAW')
                assigned_physical.add(identity)
            if matches[0]['role'] in retained_roles:
                decisions.append({**decision,'purpose':'retained_unverified_auxiliary','role':matches[0]['role'],
                                  'reason':matches[0]['reason'],'semantic_qa':'not_passed'})
                continue
            if kind=='xlsx':
                from .workbook_plan import validate_hint
                validate_hint(table,matches[0].get('table',{}))
            from .capability_preflight import table_blockers
            assigned_resource=matches[0]
            if assigned_resource['role'] in lookup_roles:
                from .lookup_semantics import capability_resources
                for view in capability_resources(contract):
                    if view['role']==assigned_resource['role']:
                        issues=table_blockers(view,table)
                        if issues:raise NeedsInput(issues[0]['message'],[],{'blockers':issues,'policy_version':POLICY})
                decisions.append({**decision,'purpose':'lookup','role':assigned_resource['role'],
                                  'key':assigned_resource['key'],'parent_scan':'required_in_sample_and_full_replay'})
                continue
            missing_join_fields=sorted({field for lookup in assigned_resource.get('lookups',[]) for field in lookup['fields']}-set(table['header']))
            if missing_join_fields:
                block('Lookup child key fields are absent from the actual table','QA02_RAW',role=assigned_resource['role'],fields=missing_join_fields)
            if lookup_compilation:
                from .lookup_semantics import capability_resources
                physical_view=next(view for view in capability_resources(contract) if view['role']==assigned_resource['role'])
            else:physical_view=assigned_resource
            issues=table_blockers(physical_view,table)
            if issues:
                raise NeedsInput(issues[0]['message'],[],{'blockers':issues,'policy_version':POLICY})
            decisions.append({**decision,'purpose':'fact','role':matches[0]['role'],'grain':matches[0]['grain']})
    relations=contract.get('relations',[]);edges=set()
    for rel in relations:
        if rel.get('child') not in roles or rel.get('parent') not in roles or rel['child']==rel['parent'] or (rel['child'],rel['parent']) in edges:
            block('Invalid or duplicate parent relation','QA04_AUXILIARY')
        if not isinstance(rel.get('fields'),list) or len(rel['fields'])!=len(roles[rel['parent']]['key']):block('Relationship must address the full parent key','QA04_AUXILIARY')
        edges.add((rel['child'],rel['parent']))
    for role,r in roles.items():
        if r['grain'] in {'unit','casualty'} and not any(c==role and roles[p]['grain']=='crash' for c,p in edges):
            block('Unit/casualty tables need an explicit crash relationship','QA04_AUXILIARY')
    if table_receipts is not None:
        table_receipts.extend(sorted(decisions+union_plans+lookup_plans,key=lambda item:stable_json(item)))
    return roles


def _aggregate(db,clause='1',args=()):
    row=db.execute('SELECT count(*),count(fatal),sum(fatal),count(fatalities),sum(fatalities),count(casualties),sum(casualties) FROM verified WHERE grain=\'crash\' AND '+clause,args).fetchone()
    return {'crash_count':row[0],'fatal_crash_count':(row[2] or 0) if row[1]==row[0] else None,
        'fatalities':(row[4] or 0) if row[3]==row[0] else None,'casualties':(row[6] or 0) if row[5]==row[0] else None}


def validate_candidate(run,source_contract,files,adapter_sha256,work_dir,check_cancelled=None,native_context=None,operation_policy=False):
    if run.get('mode') not in {'sample', 'full'}:
        block('Diagnostic execution can never authorize canonical admission', 'QA01_INPUT')
    if operation_policy:
        from .capability_preflight import require_supported_operations
        require_supported_operations(source_contract)
    check_cancelled=check_cancelled or (lambda:None)
    implementation=trusted_implementation()
    if implementation!=LOADED_IMPLEMENTATION:block('Trusted QA code changed while the worker was running; restart before validating','QA01_INPUT')
    table_receipts=[]
    roles=validate_contract(source_contract,files,native_context=native_context,check_cancelled=check_cancelled,table_receipts=table_receipts)
    native_transition=native_context.public() if native_context is not None else None
    native_semantics={key:native_transition[key] for key in ('transition_version','source_id','frozen_references','implementation','exceptions_inherited')} if native_transition else None
    full=run.get('mode')=='full'
    if run.get('status')!='succeeded':block('Adapter has not completed successfully','QA02_RAW')
    if run.get('code_sha256')!=adapter_sha256:block('Adapter version differs from the executed code','QA01_INPUT')
    contract_hash=hashlib.sha256(json.dumps(source_contract,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
    if run.get('contract_sha256')!=contract_hash:block('Source contract changed after execution','QA01_INPUT')
    root=Path(work_dir).resolve();output=Path(run['output_dir']).resolve()
    if not output.is_relative_to(root) or output.is_symlink():block('Candidate directory is outside the active task','QA01_INPUT')
    has_lookups='lookup_tables' in source_contract
    # Lookup row equality is useful diagnostic evidence even while semantic
    # admission is blocked. Preflight still calls _proof before any execution.
    # A lookup can never return sample_only/admitted without its semantic gate.
    proofs=_proof(source_contract,root,files,check_cancelled) if not has_lookups and (full or source_contract.get('documents')) else {}
    proofs['table_classification']={'version':'schema-linked-table-classification-v1','tables':table_receipts}
    from .transform_plan import contract_plans, compare_plans, TransformError
    try:
        host_plans=contract_plans(source_contract)
        if host_plans:
            compare_plans(host_plans,run.get('transform_plans'))
            if run.get('transform_probe_image')!=run.get('image') or not run.get('image'):
                raise TransformError('TRANSFORM_RUNTIME_MISMATCH','Coordinate probe and actual execution image differ.')
    except TransformError as exc:
        block(str(exc),exc.code,**exc.details)
    proofs['transform_plans']={'host':host_plans,'executor':run.get('transform_plans',{}),'executor_image':run.get('image')}
    admitted={f['id']:f for f in files}
    for f in files:
        check_cancelled()
        if Path(f['path']).is_symlink() or digest(f['path'])!=f['sha256']:block('Original input hash changed','QA01_INPUT')
    proofs['parser_plans']={}
    for role,resource in roles.items():
        if 'partitions' in resource:
            selected,plan=prepare_union(resource,admitted,check_cancelled)
            proofs['parser_plans'][role]={'union_plan':plan,'partitions':[table.get('parser_plan') for _,table in selected]}
            continue
        file=admitted[resource['file_id']]
        if detect_format(file)=='xlsx':
            spec=resource.get('table',{})
            tables=detect_tables(file,spec,check_cancelled)
            selected=spec.get('sheet',spec.get('table_id'))
            matching=[table for table in tables if table['table_id']==selected or (selected is None and len(tables)==1)]
            if len(matching)!=1:block('Workbook parser plan selection is ambiguous','QA01_INPUT',role=role)
            proofs['parser_plans'][role]=matching[0]['parser_plan']
    hashes={a['name']:a['sha256'] for a in run.get('artifacts',[])}
    for name in ARTIFACT_NAMES.values():
        path=output/name
        if path.is_symlink() or not path.is_file() or name not in hashes or digest(path)!=hashes[name]:block('Candidate artifacts changed after isolated execution','QA01_INPUT')
    from .row_preprocessing import enabled as collapse_enabled, VERSION as LINEAGE_VERSION
    collapsed_roles={role for role,r in roles.items() if collapse_enabled(r)}
    lineage_path=output/'row-lineage.jsonl'
    audited_names=set(ARTIFACT_NAMES.values())
    if collapsed_roles:
        audited_names.add('row-lineage.jsonl')
        if (lineage_path.is_symlink() or not lineage_path.is_file() or
                digest(lineage_path)!=hashes.get('row-lineage.jsonl')):
            block('Missing or changed row-destination ledger','QA02_RAW')
    elif lineage_path.exists() and lineage_path.stat().st_size:
        block('Row-destination ledger requires an explicit supported operation','QA02_RAW')
    exclusions=output/'exclusions.jsonl'
    if exclusions.exists() and exclusions.stat().st_size:
        block('Unapproved exclusions are not admitted. Preserve rows and supply a documented selection policy instead of silently dropping them.','QA02_RAW')
    # A worker may die during validation. Keep its partial evidence, then replay
    # into a fresh bounded database instead of treating recovery as corruption.
    dbpath=root/('trusted-qa-'+run['run_id']+'-'+uuid4().hex+'.sqlite')
    db=sqlite3.connect(dbpath);lookup_projection=None
    from .qa_storage import begin as storage_begin, finish as storage_finish
    storage_token=None
    storage_result_path=None;storage_error=None
    try:
        storage_token=storage_begin(root,dbpath,run)
        if has_lookups:
            from .lookup_projection import LookupProjection
            lookup_projection=LookupProjection(source_contract,files,root/('trusted-lookup-'+uuid4().hex),check_cancelled)
        db.execute('PRAGMA temp_store=FILE');db.execute('PRAGMA cache_size=-16384')
        db.executescript('''CREATE TABLE IF NOT EXISTS verified(role TEXT, locator TEXT, pk TEXT, grain TEXT, payload TEXT,
            year INTEGER,month INTEGER,severity TEXT,fatal INTEGER,fatalities INTEGER,casualties INTEGER,
            row_sha256 BLOB NOT NULL, raw_sha256 BLOB,
            PRIMARY KEY(role,locator),UNIQUE(role,pk)) WITHOUT ROWID;
            CREATE TABLE IF NOT EXISTS links(child TEXT,pk TEXT,parent TEXT,parent_pk TEXT);
            CREATE INDEX IF NOT EXISTS relations_parent ON links(parent,parent_pk);
            CREATE TABLE IF NOT EXISTS lookup_count_usage(parent_role TEXT,metric TEXT,parent_locator TEXT,
                consumer_role TEXT,consumer_locator TEXT,PRIMARY KEY(parent_role,metric,parent_locator));
            CREATE TABLE IF NOT EXISTS candidate(role TEXT,locator TEXT,PRIMARY KEY(role,locator)) WITHOUT ROWID;
            CREATE TABLE raw_destinations(role TEXT,locator TEXT,payload TEXT,checked INTEGER DEFAULT 0,PRIMARY KEY(role,locator));''')
        retained_counts={};retained_proofs=[]
        for r in source_contract.get('retained_resources',[]):
            count=0;content_hash=hashlib.sha256()
            for locator,raw in iter_resource(r,admitted,check_cancelled=check_cancelled):
                if not full and count>=1000:break
                content_hash.update(stable_json([locator,raw]).encode()+b'\n');count+=1
            retained_counts[r['role']]=count
            retained_proofs.append({'role':r['role'],'file_sha256':admitted[r['file_id']]['sha256'],
                'table':r['table'],'records_scanned':count,'raw_row_sequence_sha256':content_hash.hexdigest(),
                'scan_complete':full,'semantic_qa':'not_passed','destination':'immutable_original_input',
                'requested':r['requested'],'reason':r['reason']})
        if retained_proofs:
            proofs['retained_resources']={'version':'retained-auxiliary-v1','resources':retained_proofs,
                'canonical_contribution':0,'limitation':'No metric or verified relationship may derive from these unverified rows.'}
        raw_counts={}
        coverage=source_contract['source']['coverage']
        coverage_start=date.fromisoformat(coverage['from']);coverage_end=date.fromisoformat(coverage['to'])
        for role,r in roles.items():
            raw_counts[role]=0
            for locator,raw in iter_resource(r,admitted,check_cancelled=check_cancelled):
                if not full and raw_counts[role]>=1000:break
                try:row=(lookup_projection.project(role,locator,raw) if lookup_projection else project(source_contract,role,locator,raw))
                except ContractError as exc:block(str(exc),'QA05_SEMANTICS',role=role,row_locator=locator)
                raw_counts[role]+=1
                if role in collapsed_roles:
                    previous=db.execute('SELECT payload,raw_sha256 FROM verified WHERE role=? AND pk=?',(role,row['record_id'])).fetchone()
                    first=json.loads(previous[0]) if previous else row
                    if previous and previous[1]!=row_digest(raw):
                        block('Conflicting raw values for the same complete source key; no row was selected','QA03_PROJECTED',role=role,row_locator=locator)
                    retained=previous is None
                    destination={'version':LINEAGE_VERSION,'role':role,'row_locator':locator,
                        'record_id':row['record_id'],'raw_sha256':hashlib.sha256(stable_json(raw).encode()).hexdigest(),
                        'destination_locator':first['row_locator'],'disposition':'retained' if retained else 'exact_duplicate',
                        'count_allocation':1 if retained else 0}
                    try:db.execute('INSERT INTO raw_destinations(role,locator,payload) VALUES(?,?,?)',(role,str(locator),stable_json(destination)))
                    except sqlite3.IntegrityError:block('Raw row locator is not unique','QA02_RAW',role=role)
                    if not retained:
                        if raw_counts[role]%5000==0:db.commit();check_cancelled()
                        continue
                if lookup_projection:
                    from .lookup_semantics import count_allocations
                    for allocation in count_allocations(source_contract,role,row):
                        identity=(allocation['parent_role'],allocation['metric'],stable_json(allocation['parent_locator']))
                        consumer=(role,str(locator))
                        previous=db.execute('SELECT consumer_role,consumer_locator FROM lookup_count_usage WHERE parent_role=? AND metric=? AND parent_locator=?',identity).fetchone()
                        if previous and previous!=consumer:
                            block('One parent count would be allocated to multiple consumer records; a reviewed disaggregation rule is required instead of repeating a total.',
                                  'LOOKUP_COUNT_BROADCAST',role=role,parent_role=allocation['parent_role'],metric=allocation['metric'])
                        if not previous:db.execute('INSERT INTO lookup_count_usage VALUES(?,?,?,?,?)',(*identity,*consumer))
                if row.get('year'):
                    year=row['year'];month=row.get('month')
                    if row.get('date_precision')=='day':first=last=date.fromisoformat(row['occurrence_date'])
                    elif month:first=date(year,month,1);last=date(year,month,calendar.monthrange(year,month)[1])
                    else:first=date(year,1,1);last=date(year,12,31)
                    if first<coverage_start or last>coverage_end:block('Source coverage excludes or cuts across supplied record dates; no rows were dropped','QA05_SEMANTICS',role=role,row_locator=locator)
                try:
                    db.execute('INSERT INTO verified VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(role,str(locator),row['record_id'],r['grain'],qa_projection(row, collapsed=role in collapsed_roles),row.get('year'),row.get('month'),row.get('severity'),row.get('is_fatal_crash'),row.get('fatalities'),row.get('casualties'),row_digest(row),row_digest(raw) if role in collapsed_roles else None))
                except sqlite3.IntegrityError:block('Duplicate complete source key or row locator','QA03_PROJECTED',role=role,
                    **({'failure_origin':'source'} if operation_policy else {}))
                for parent,key in row.get('relations',{}).items():
                    if key is not None:db.execute('INSERT INTO links VALUES(?,?,?,?)',(role,row['record_id'],parent,key))
                if raw_counts[role]%5000==0:db.commit();check_cancelled()
            if not raw_counts[role]:block('Required source table has no records','QA02_RAW',role=role)
        db.commit()
        collapsed_count=0
        if collapsed_roles:
            with lineage_path.open() as handle:
                for number,line in enumerate(handle):
                    if number%1000==0:check_cancelled()
                    if len(line)>1024*1024:block('Row-destination entry exceeds its size bound','QA02_RAW')
                    try:
                        entry=json.loads(line);identity=(entry['role'],str(entry['row_locator']))
                    except (ValueError,KeyError,TypeError):block('Invalid row-destination entry','QA02_RAW')
                    expected=db.execute('SELECT payload,checked FROM raw_destinations WHERE role=? AND locator=?',identity).fetchone()
                    if not expected or expected[1] or stable_json(entry)!=expected[0]:
                        block('Row-destination or count allocation differs from independent raw replay','QA02_RAW')
                    db.execute('UPDATE raw_destinations SET checked=1 WHERE role=? AND locator=?',identity)
                    if entry['disposition']=='exact_duplicate':collapsed_count+=1
            if db.execute('SELECT count(*) FROM raw_destinations WHERE checked=0').fetchone()[0]:
                block('Input/output conservation failed: original row destinations disappeared','QA02_RAW')
            proofs['row_preprocessing']={'version':LINEAGE_VERSION,'roles':sorted(collapsed_roles),
                'raw_rows':sum(raw_counts[role] for role in collapsed_roles),'collapsed_duplicate_rows':collapsed_count,
                'lineage_sha256':hashes['row-lineage.jsonl'], 'rule':'Complete key and every raw field equal; each retained key counted once; conflicts block'}
        candidate_counts={}
        for grain,name in ARTIFACT_NAMES.items():
            n=0
            with (output/name).open() as handle:
                for line in handle:
                    if len(line)>1024*1024:block('Candidate record exceeds its size bound','QA02_RAW')
                    try:row=json.loads(line);role=row['resource_role'];locator=str(row['row_locator'])
                    except (ValueError,KeyError,TypeError):block('Invalid candidate JSON/lineage','QA03_PROJECTED')
                    if role not in roles or roles[role]['grain']!=grain:block('Candidate has the wrong source grain','QA03_PROJECTED')
                    expected=db.execute('SELECT row_sha256 FROM verified WHERE role=? AND locator=?',(role,locator)).fetchone()
                    if not expected: block('Candidate has no matching raw-row projection','QA06_RECONCILIATION',role=role,row_locator=locator)
                    if row_digest(row)!=expected[0]:
                        # Reconstruct a located diagnostic only on mismatch; no
                        # additional full copy of every source row is retained.
                        difference={}
                        for raw_locator,raw in iter_resource(roles[role],admitted,check_cancelled=check_cancelled):
                            if str(raw_locator)==locator:
                                replay=lookup_projection.project(role,raw_locator,raw) if lookup_projection else project(source_contract,role,raw_locator,raw)
                                difference=projection_difference(replay,row);break
                        block('Candidate differs from independent raw-row projection','QA06_RECONCILIATION',role=role,row_locator=locator,**difference)
                    try:db.execute('INSERT INTO candidate VALUES(?,?)',(role,locator))
                    except sqlite3.IntegrityError:block('Candidate repeats a source row','QA03_PROJECTED',role=role)
                    n+=1
                    if n%5000==0:db.commit();check_cancelled()
            candidate_counts[grain]=n
        missing=db.execute('SELECT count(*) FROM verified v LEFT JOIN candidate c ON c.role=v.role AND c.locator=v.locator WHERE c.locator IS NULL').fetchone()[0]
        if missing:block('Input/output conservation failed: source rows disappeared','QA02_RAW',missing_records=missing)
        orphan=db.execute('SELECT count(*) FROM links l LEFT JOIN verified v ON v.role=l.parent AND v.pk=l.parent_pk WHERE v.pk IS NULL').fetchone()[0]
        if orphan and full:block('Complete source files have orphan foreign keys; no relationships were repaired','QA04_AUXILIARY',orphans=orphan)
        lookup_counts={}
        if lookup_projection:
            lookup_receipts=lookup_projection.receipts()
            for item in lookup_receipts:
                parent_role=item['plan']['parent_role']
                count=item['metrics']['parent_rows']
                if parent_role in lookup_counts and lookup_counts[parent_role]!=count:
                    block('Shared lookup parent scans disagree','QA02_RAW',role=parent_role)
                lookup_counts[parent_role]=count
                if item['metrics']['requests']!=raw_counts[item['child_role']]:
                    block('Lookup request conservation differs from the verified child rows','QA02_RAW',role=item['child_role'])
            for f in files:
                check_cancelled()
                if Path(f['path']).is_symlink() or digest(f['path'])!=f['sha256']:block('Original input changed during lookup replay','QA01_INPUT')
            for name in ARTIFACT_NAMES.values():
                if digest(output/name)!=hashes[name]:block('Candidate changed during lookup replay','QA01_INPUT')
            replay={'version':'host-lookup-replay-v1','mode':'full' if full else 'sample',
                    'fact_rows':raw_counts,'parent_rows':lookup_counts,'candidate_counts':candidate_counts,
                    'contract_sha256':contract_hash,'artifact_hashes':{name:hashes[name] for name in ARTIFACT_NAMES.values()},
                    'lookups':lookup_receipts,'row_equality_verified':True,'admission':False,
                    'limits':'Raw-row projection and lookup lineage equality only; semantic proof, all applicable population reconciliation and publication gates remain required.'}
            (root/('trusted-lookup-replay-'+run['run_id']+'.json')).write_text(json.dumps(replay,indent=2,ensure_ascii=False,allow_nan=False))
            try:
                semantic_proofs=_proof(source_contract,root,files,check_cancelled)
            except NeedsInput as exc:
                exc.details['lookup_replay']={'row_equality_verified':True,'mode':replay['mode'],
                    'fact_rows':raw_counts,'parent_rows':lookup_counts,'admission':False}
                raise
            proofs.update({key:value for key,value in semantic_proofs.items() if key != 'transform_plans'})
            proofs['lookup_replay']=replay
        if full:
            for role,r in roles.items():
                child_roles={grain:[name for name,child in roles.items() if child['grain']==grain and any(rel['child']==name and rel['parent']==role for rel in source_contract.get('relations',[]))] for grain in ('unit','casualty')}
                for pk,payload in db.execute('SELECT pk,payload FROM verified WHERE role=?',(role,)):
                    row=json.loads(payload)
                    for grain,name in [('unit','declared_units'),('casualty','declared_casualties')]:
                        if name not in row or row[name] is None:continue
                        if not child_roles[grain]:block('Declared child count lacks the required child table','QA04_AUXILIARY',role=role,metric=name)
                        actual=sum(db.execute('SELECT count(*) FROM links WHERE child=? AND parent=? AND parent_pk=?',(c,role,pk)).fetchone()[0] for c in child_roles[grain])
                        if actual!=row[name]:block('Declared parent child count differs from full child records','QA04_AUXILIARY',role=role,metric=name,expected=row[name],actual=actual)
            # Only verified parent/child scope decisions authorize this equality.
            # A global model boolean cannot activate it for other resource roles.
            for decision in proofs.get('casualty_scope_review',{}).get('decisions',[]):
                if decision.get('complete') is not True:continue
                role,child_role=decision['parent_role'],decision['resource_role']
                for pk,payload in db.execute('SELECT pk,payload FROM verified WHERE role=?',(role,)):
                    row=json.loads(payload)
                    children=[json.loads(p[0]) for p in db.execute("SELECT v.payload FROM links l JOIN verified v ON v.role=l.child AND v.pk=l.pk WHERE l.parent=? AND l.child=? AND l.parent_pk=? AND v.grain='casualty'",(role,child_role,pk))]
                    if row.get('casualties') is not None and len(children)!=row['casualties']:block('Complete casualty register and declared casualties disagree','QA04_AUXILIARY')
                    if row.get('fatalities') is not None and all(c.get('is_fatal') is not None for c in children) and sum(c['is_fatal'] for c in children)!=row['fatalities']:block('Casualty fatal classifications and declared deaths disagree','QA04_AUXILIARY')
        if full:
            for proof in proofs.get('source_completeness', {}).get('resources', []):
                if proof.get('status') == 'verified' and raw_counts.get(proof['role']) != proof['record_count']:
                    block('Selected resource rows do not conserve the verified complete export.', 'QA02_RAW', role=proof['role'])
        source=source_contract['source'];summary=_aggregate(db)
        observational=not any(r['grain']=='crash' for r in roles.values())
        if observational:
            summary={k:None for k in ('crash_count','fatal_crash_count','fatalities','casualties')}
            summary['observation_count']=candidate_counts['observation']
        summary.update(raw_record_count=sum(raw_counts.values())+sum(lookup_counts.values())+sum(retained_counts.values()),excluded_crash_count=0,quarantined_record_count=0,
            canonical_unit_count=candidate_counts['unit'],canonical_casualty_count=candidate_counts['casualty'],
            unit_count=candidate_counts['unit'] if any(r['grain']=='unit' for r in roles.values()) else None,
            year_from=int(coverage['from'][:4]),year_to=int(coverage['to'][:4]),source_id=source['source_id'])
        if retained_proofs:summary['retained_unverified_record_count']=sum(retained_counts.values())
        if collapsed_roles:summary['collapsed_duplicate_record_count']=collapsed_count
        if lookup_counts:summary['raw_lookup_record_count']=sum(lookup_counts.values())
        years=[r[0] for r in db.execute('SELECT DISTINCT year FROM verified WHERE year IS NOT NULL ORDER BY year')]
        trend=[{'year':year,**_aggregate(db,'year=?',(year,))} for year in years] if not observational else []
        monthly=[{'year':year,'month':month,**_aggregate(db,'year=? AND month=?',(year,month))} for year,month in db.execute("SELECT DISTINCT year,month FROM verified WHERE grain='crash' AND month IS NOT NULL ORDER BY year,month")] if not observational else []
        severity=[{'code':code,'label':label,'count':n} for code,label,n in db.execute("SELECT severity,json_extract(payload,'$.severity_label'),count(*) FROM verified WHERE grain='crash' GROUP BY severity,json_extract(payload,'$.severity_label') ORDER BY severity")]
        unit_rows=[{'unit_type':kind,'count':n} for kind,n in db.execute("SELECT json_extract(payload,'$.unit_type'),count(*) FROM verified WHERE grain='unit' GROUP BY json_extract(payload,'$.unit_type')")]
        units={'status':'available' if summary['unit_count'] is not None else 'unavailable','scope':source['title']+' source-specific units',
               'rows':unit_rows if summary['unit_count'] is not None else None,'reason':None if summary['unit_count'] is not None else 'No source unit-level resource supplied'}
        geo=db.execute("SELECT count(*) FROM verified WHERE json_extract(payload,'$.geography_status')='available'").fetchone()[0]
        qa=[{'code':code,'status':'pass','message':message} for code,message in [
            ('QA01_INPUT','Immutable inputs, executed adapter and source contract identities match.'),
            ('QA02_RAW','Every parsed fact row has a verified canonical destination; exact duplicates have zero additional count allocation. Any explicitly unresolved auxiliary rows remain in immutable inputs.' if collapsed_roles else 'Every verified fact row is conserved; explicitly unresolved auxiliary rows remain in the immutable original inputs with no canonical contribution.' if retained_proofs else 'Every parsed input row is conserved in the appropriate canonical grain.'),
            ('QA03_PROJECTED','Complete source keys, locators and independent row projections reconcile.'),
            ('QA04_AUXILIARY','Full-file relationships and applicable source-declared child totals reconcile.' if full else 'Sample diagnostics only; full-file relation checks are still required.'),
            ('QA05_SEMANTICS','Declared projection rules replayed; mapped fields grounded and supported additive count definitions verified. This does not establish arbitrary scientific or cross-source semantic equivalence.'),
            ('QA06_RECONCILIATION','Candidate rows equal independently recomputed canonical rows and aggregates.')]]
        qa.append({'code':'QA07_LOCATION','status':'pass' if geo else 'limited','message':'Evidence-backed, offline frozen operations agree across host and executor; points checked against operation/source areas and broad Australian domain. This does not establish source positional accuracy.' if geo else 'No validated map points; other verified metrics remain available.','metrics':{'eligible':geo,'transform_plans':{role:{'operation_sha256':plan['operation_sha256'],'accuracy_metres':plan['operation']['accuracy_metres'],'ballpark':False} for role,plan in host_plans.items()}}})
        for name,expected in hashes.items():
            if name in audited_names and digest(output/name)!=expected:block('Candidate changed during trusted validation','QA01_INPUT')
        for f in files:
            check_cancelled()
            if Path(f['path']).is_symlink() or digest(f['path'])!=f['sha256']:block('Original input changed during trusted validation','QA01_INPUT')
        semantic_hash=hashlib.sha256(stable_json(semantic_contract(source_contract)).encode()).hexdigest()
        if trusted_implementation()!=implementation:block('Trusted QA implementation changed during validation','QA01_INPUT')
        fingerprint=hashlib.sha256(stable_json({'source':source['source_id'],'inputs':sorted((r['role'],index,admitted[part['file_id']]['sha256']) for r in bound_inputs(source_contract) for index,part in enumerate(physical_resources(r))),
            'adapter':adapter_sha256,'contract':semantic_hash,'image':run.get('image'),'policy':POLICY,'trusted_implementation':implementation,'native_transition':native_semantics,'transform_plans':proofs['transform_plans'],'parser_plans':proofs['parser_plans']}).encode()).hexdigest()
        result={'source_id':source['source_id'],'profile_id':'autonomous:'+source['source_id'],'profile_version':'canonical-v2',
            'fingerprint':fingerprint,'mode':'local-test','summary':summary,'trend':trend,'monthly_trend':monthly,'severity':severity,'units':units,
            'qa':qa,'limitations':['Source-specific definitions; overlapping datasets and jurisdictions are not combined.']+[f"{item['role']}: {item['actual']}. {item['reason']}" for item in proofs.get('capability_limits',[])],
            'capability_limits':proofs.get('capability_limits',[]),
            'canonical_path':str(output/'crashes.jsonl'),'units_path':str(output/'units.jsonl'),
            'casualties_path':str(output/'casualties.jsonl'),'observations_path':str(output/'observations.jsonl'),
            'source':source,'update':source_contract['update'],'coverage':coverage,'licensing':proofs.get('licensing', {'version':'unassessed','resources':[],'scope':'local_research_only','redistribution':'not_assessed'}),
            'capabilities':{'crashes':not observational,'fatalities':summary.get('fatalities') is not None,'casualties':summary.get('casualties') is not None,
                'units':summary['unit_count'] is not None,'casualty_records':candidate_counts['casualty']>0,'observations':observational,'map_points':geo>0},
            'files':[{k:f[k] for k in ('id','name','sha256','size') if k in f} for f in files],
            'admission':{'policy_version':POLICY,'status':'admitted' if full else 'sample_only','automatic':True,'adapter_sha256':adapter_sha256,
                'source_contract_sha256':contract_hash,'semantic_contract_sha256':semantic_hash,'artifact_hashes':{k:v for k,v in hashes.items() if k in audited_names},'image':run.get('image'),'trusted_implementation':implementation,'native_transition':native_transition,'evidence':proofs},
            'evidence':{'source_contract':{k:v for k,v in source_contract.items() if k!='documents'},'input_counts':{**raw_counts,**lookup_counts,**retained_counts},'candidate_counts':candidate_counts,
                'run_id':run['run_id'],'usage':run.get('usage'),'trusted_qa_version':POLICY,'sample_only':not full}}
        from .coverage_policy import VERSION as COVERAGE_VERSION
        if source_contract.get('version_scope'):
            result['version_scope'] = source_contract['version_scope']
            result.setdefault('limitations', []).append('Independent dataset version: cross-version event correspondence is unverified. Select exactly one version; do not pool overlapping counts. No chronological ordering or replacement is inferred.')
            result.setdefault('capability_limits', []).append({'capability':'cross_version_record_mapping',
                'requested':True,'status':'unverified','target_satisfied':False,
                'reason':'No verified event-key correspondence across releases.',
                'actual':'Standalone version with independently checked rows and within-version relations.'})
        result['temporal_coverage'] = {'version':COVERAGE_VERSION,'complete_intervals':[],
            'basis':'observed-records-only',
            'limitation':'Observed dates and whole-layer membership do not establish complete reporting for every calendar period.'}
        if operation_policy:
            result['admission']['operation_policy'] = 'verified-adaptation-operations-v1'
        from .storage_lifecycle import atomic_json
        storage_result_path=root/('trusted-qa-'+run['run_id']+'.json')
        atomic_json(storage_result_path,result)
        return result
    except BaseException as exc:
        storage_error=exc
        raise
    finally:
        if lookup_projection is not None:lookup_projection.close()
        db.close()
        storage_finish(storage_token,result_path=storage_result_path,error=storage_error)
