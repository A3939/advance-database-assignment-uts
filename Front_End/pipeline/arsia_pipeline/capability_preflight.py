"""Deterministic capability checks; no executor, model, network or DB writes."""
from .errors import NeedsInput, ValidationFailure, BudgetExhausted

VERSION = 'import-capability-preflight-v2'
SYSTEM_KINDS = {'unsupported_capability', 'environment_dependency', 'system_configuration', 'system_fault'}


def adaptation_enabled(config):
    """Trusted runtime opt-in only; strings, upload options and proposals cannot enable it."""
    return config.get('autonomous_adaptation_v1') is True


def execution_blockers(run, *, operation):
    """Classify the host executor envelope, not a reconstructed ValueError.

    bounded_report strips adapter-supplied origins/codes and stamps 'adapter'.
    Consequently a generated ImportError remains fixable task code; it is not
    proof that the trusted environment lacks a dependency.
    """
    from .errors import ImportCancelled, BudgetExhausted
    error = run.get('error') or {}
    kind, code = 'adapter_revision', 'ADAPTER_EXECUTION_FAILED'
    if run.get('status') == 'cancelled':
        raise ImportCancelled(error.get('message', 'Adapter execution was cancelled'))
    if error.get('origin') == 'trusted_host' and error.get('type') in {'BudgetExhausted', 'AgentStalled'}:
        raise BudgetExhausted('Trusted execution stopped at its existing budget.', {'run_id': run.get('run_id')})
    # ImageUnavailable is host-only even in historical envelopes: the bounded
    # runner's allowlist cannot emit this type or an 'unavailable' status.
    if run.get('status') == 'unavailable' and error.get('type') == 'ImageUnavailable' and error.get('origin') in {None, 'trusted_host'}:
        kind, code = 'environment_dependency', 'EXECUTOR_IMAGE_UNAVAILABLE'
    elif error.get('origin') == 'trusted_host':
        # Only the trusted executor may stamp this origin. Unknown host failures
        # (including immutable-input checks) cannot be repaired by task code.
        kind, code = 'system_fault', error.get('code') or 'EXECUTOR_HOST_FAILURE'
        if error.get('type') in {'ExecutorEnvironmentError', 'TransformError', 'StorageError'} and error.get('kind') in {
                'environment_dependency', 'unsupported_capability', 'system_configuration'}:
            kind, code = error['kind'], error.get('code', 'EXECUTOR_DEPENDENCY_UNAVAILABLE')
        elif error.get('type') in {'ImportError', 'ModuleNotFoundError', 'FileNotFoundError'}:
            kind, code = 'environment_dependency', 'EXECUTOR_HOST_DEPENDENCY_MISSING'
    details = {'run_id': run.get('run_id'), 'executor_status': run.get('status'), 'executor_error': error}
    exc = NeedsInput(error.get('message', 'Adapter execution failed'), [], {'blockers': [
        blocker(code, kind, error.get('message', 'Adapter execution failed'), details=details)]})
    return classified_blockers(exc, operation=operation)


def classified_blockers(exc, *, operation=None):
    """Bounded routing for this development slice, not a universal error parser.

    Classify structured host codes/types, never publisher prose or model text.
    Keep the original diagnostics alongside the actionable envelope.
    """
    from .errors import UnsupportedCapability, ModelUnavailable, BudgetExhausted
    actions = {
        'unsupported_capability': ('system', 'Preserve the candidate and stop investigation.', 'A reviewed implementation supports this exact operation.'),
        'environment_dependency': ('system', 'Preserve the candidate; repair the trusted environment.', 'The required dependency is available and the candidate is revalidated.'),
        'system_configuration': ('system', 'Stop and preserve the isolation/configuration failure.', 'The explicit instance configuration passes startup checks.'),
        'system_fault': ('system', 'Stop and preserve the unexpected host failure for diagnosis.', 'The trusted implementation is repaired and revalidated.'),
        'model_transport': ('system', 'Preserve the checkpoint; do not replay completed data steps.', 'The model transport is available and an authorized resume occurs.'),
        'source_quality_block': ('source_owner', 'Inspect the located raw rows and conflicting values; do not discard them.', 'A corrected source or an evidence-backed interpretation resolves the issue.'),
        'evidence_conflict': ('agent', 'Compare the conflicting definitions within their exact scopes.', 'The applicable definition is established without suppressing conflicts.'),
        'evidence_missing': ('agent', 'Retrieve the specific missing scoped evidence.', 'Applicable source evidence passes the same gate.'),
        'adapter_revision': ('agent', 'Revise the declared mapping or task-local adapter and rerun the failed gate.', 'The revised candidate passes the same independent gate.'),
        'budget_exhausted': ('operator', 'Save the checkpoint and stop.', 'The user authorizes continuation with an explicit budget.'),
    }
    rows = exception_blockers(exc)
    if isinstance(exc, ModelUnavailable):
        rows = [blocker(exc.code, 'model_transport', str(exc))]
    elif isinstance(exc, BudgetExhausted):
        rows = [blocker(exc.code, 'budget_exhausted', str(exc))]
    elif getattr(exc, 'details', {}).get('blockers'):
        pass  # Keep an already-classified inner failure; do not nest envelopes.
    elif isinstance(exc, (ImportError, FileNotFoundError)):
        rows = [blocker(type(exc).__name__, 'environment_dependency', str(exc))]
    elif not isinstance(exc, (NeedsInput, ValidationFailure)):
        rows = [blocker(getattr(exc, 'code', type(exc).__name__),
                        getattr(exc, 'kind', 'adapter_revision' if isinstance(exc, ValueError) else 'system_fault'),
                        str(exc), details=getattr(exc, 'details', {}))]
    elif isinstance(exc, ValidationFailure) and not getattr(exc, 'details', {}):
        rows = [dict(q, kind='source_quality_block' if q.get('code') in {
                     'QA04_AUXILIARY', 'LOOKUP_PARENT_NOT_UNIQUE', 'LOOKUP_KEY_INVALID',
                     'LOOKUP_KEY_INCOMPLETE', 'LOOKUP_INPUT_CHANGED'}
                     or q.get('metrics', {}).get('failure_origin') == 'source'
                     else 'adapter_revision', details=q.get('metrics', {})) for q in exc.qa]
    result = []
    for row in rows:
        code = row.get('code', 'UNCLASSIFIED_GATE_FAILURE')
        kind = row.get('kind', 'evidence_missing')
        if isinstance(exc, UnsupportedCapability):
            kind = 'unsupported_capability'
        if getattr(exc, 'kind', None) in SYSTEM_KINDS:
            kind = exc.kind
        party, action, resume = actions.get(kind, actions['evidence_missing'])
        details = row.get('details', {})
        result.append({**row, 'kind': kind, 'responsible_party': party,
                       'operation': row.get('operation') or operation, 'next_action': action, 'resumable_when': resume,
                       'details': details, 'subject': {k: row.get(k, details.get(k)) for k in
                       ('role','field','fields','metric','row_locator') if k in row or k in details}})
    return result


def operation_support(contract):
    """Describe existing operators and their independent host verifiers.

    This is a restriction on opt-in candidates, not permission to run arbitrary
    Python semantics. Existing parser/lookup/transform compilers remain final.
    """
    entries, issues = [], []
    for resource in contract.get('resources', []):
        role = resource.get('role')
        from .row_preprocessing import enabled
        if enabled(resource):
            entries.append({'role':role,'operation':'collapse_exact_duplicates',
                            'executor':'adapter_sdk.AdapterContext.iter_rows',
                            'verifier':'trusted_qa independent full raw-row ledger',
                            'checks':['complete key','all raw fields equal','every row destination','one count allocation per key']})
        entries.append({'role': role, 'operation': 'row_projection',
                        'executor': 'adapter_sdk.Context.project',
                        'verifier': 'trusted_qa.validate_candidate raw-row replay',
                        'checks': ['original key','original values','field origins','row conservation']})
        if resource.get('grain') == 'observation':
            issues.append(blocker('AGGREGATE_ADAPTATION_UNSUPPORTED', 'unsupported_capability',
                                  'Aggregate adapters are outside this opt-in operation set.', role=role))
        if 'partitions' in resource:
            entries.append({'role': role, 'operation': 'homogeneous_union', 'executor': 'table_plan.iter_resource',
                            'verifier': 'trusted_qa raw-row replay and full key index',
                            'checks': ['input membership','all rows retained','cross-partition business keys']})
        for lookup in resource.get('lookups', []):
            entries.append({'role': role, 'operation': 'unique_lookup', 'lookup': lookup.get('name'),
                            'executor': 'lookup_projection.LookupProjection',
                            'verifier': 'trusted_qa host lookup replay and count allocation',
                            'checks': ['full parent uniqueness','matched and unmatched','output cardinality','no count broadcasting']})
    # No extensible execution language is introduced here. Unknown declarations
    # must not be silently ignored by a successful Python run.
    for key in ('operations','semantic_operations','aggregate','unpivot'):
        if key in contract or any(key in r for r in contract.get('resources', [])):
            issues.append(blocker('DECLARED_OPERATION_UNSUPPORTED', 'unsupported_capability',
                                  'Use existing mapping/table/lookup plans; this operation has no reviewed verifier.',
                                  details={'required_capability': key}))
    return {'version': 'verified-adaptation-operations-v1', 'operations': entries, 'blockers': issues,
            'admission': False, 'limitation': 'Python execution is not semantic authority. All existing independent QA and publication gates remain required.'}


def require_supported_operations(contract):
    result = operation_support(contract)
    if result['blockers']:
        raise NeedsInput('A declared operation requires a reviewed system implementation.', [], result)
    return result


def requires_system_change(details):
    return any(isinstance(item, dict) and item.get('kind') in SYSTEM_KINDS
               and item.get('responsible_party') == 'system' for item in details.get('blockers', []))


def blocker(code, kind, message, *, role=None, details=None):
    system = kind in SYSTEM_KINDS
    return {'code': code, 'kind': kind, 'message': message, 'role': role,
            'responsible_party': 'system' if system else 'agent',
            'resumable_when': ('A reviewed implementation or environment update supports this capability.' if system
                               else 'Resolve the specific input/evidence conflict and rerun preflight.'),
            'details': details or {}}


def exception_blockers(exc):
    details = getattr(exc, 'details', {})
    nested = details.get('blockers')
    if isinstance(nested, list) and nested:
        return nested
    issues = [issue for group in ('grounding', 'capability_review', 'casualty_scope_review', 'count_operation_review', 'category_review', 'lookup_relation_review', 'lookup_geography_subject_review')
              for issue in details.get(group, {}).get('issues', [])]
    result = []
    for issue in issues:
        code = issue.get('code', 'EVIDENCE_MISSING')
        kind = 'evidence_conflict' if any(part in code for part in ('CONFLICT', 'MISMATCH')) else 'evidence_missing'
        if code in {'METADATA_LIMIT', 'EVIDENCE_GRAPH_LIMIT', 'RDF_LOCATION_UNSUPPORTED', 'JSONLD_CONTEXT_UNSUPPORTED', 'EVIDENCE_SCOPE_UNSUPPORTED', 'EVIDENCE_TIME_SCOPE_UNSUPPORTED', 'CATEGORY_EXPRESSION_UNSUPPORTED', 'CASUALTY_PARTIAL_SCOPE_UNSUPPORTED', 'LOOKUP_CROSS_RESOURCE_SUM_UNSUPPORTED', 'LOOKUP_MISSING_POLICY_UNSUPPORTED', 'LOOKUP_CSVW_UNSUPPORTED'}:
            kind = 'unsupported_capability'
        # Only this host verification site has established a safe alternative.
        # A suffix, publisher text or proposed contract cannot grant authority.
        if code == 'TIMEZONE_RULE_INTEGRITY':
            kind = 'environment_dependency'
        repair = issue.get('candidate_repair', {})
        if code == 'ARCGIS_SUBSET_UPDATE_UNSUPPORTED' and repair.get('version') == 'bounded-update-repair-v1':
            kind = 'adapter_revision'
        elif code in {'ARCGIS_DATE_MAPPING_CONFLICT', 'ARCGIS_TIMEZONE_CONFLICT', 'ARCGIS_UPDATE_RANGE_CONFLICT'}:
            kind = 'adapter_revision'
        result.append(blocker(code, kind, issue.get('message', str(exc)), role=issue.get('role'), details=issue))
    if result:
        return result
    return [blocker(getattr(exc, 'code', 'SOURCE_CONTRACT_INVALID'),
                    'source_quality_block' if isinstance(exc, ValidationFailure) else 'evidence_missing', str(exc), details=details)]


def geometry_blockers(resource, table):
    from .capability_limits import geography_limited
    if geography_limited(resource):
        return []  # Source/row validity still checked; explicitly no map claim.
    if table.get('json_kind') not in {'arcgis', 'geojson'}:
        return []
    role = resource.get('role')
    kinds = set(table.get('observed_geometry_types', []))
    if kinds - {'Point', 'null'}:
        return [blocker('NONPOINT_GEOMETRY_UNSUPPORTED', 'unsupported_capability',
                        'This resource contains geometry that the point projection and map cannot preserve as points.',
                        role=role, details={'geometry_types': sorted(kinds), 'required_capability': 'native_nonpoint_geometry'})]
    geography = resource.get('mapping', {}).get('geography') or {}
    if 'Point' in kinds and not geography:
        return [blocker('GEOGRAPHY_MAPPING_MISSING', 'evidence_missing',
                        'Observed source points require an evidence-backed geographic mapping; do not discard them.', role=role)]
    if (geography.get('x_field'), geography.get('y_field')) != ('__geometry_x', '__geometry_y'):
        return []
    from .geometry_evidence import reference_evidence
    from .geography_review import coordinate_crs_matches
    refs = []
    if table.get('geojson_default_crs'):
        refs.append({'crs': table['geojson_default_crs'], 'locator': '/type'})
    if table.get('legacy_crs'):
        refs.append({'crs': table['legacy_crs']['properties']['name'], 'locator': '/crs/properties/name'})
    refs.extend(reference_evidence(table.get('spatial_reference_definition'), '/spatialReference'))
    for observed in table.get('geometry_spatial_references', []):
        refs.extend(reference_evidence(observed['reference'], '/geometry/spatialReference'))
    if not refs:
        return [blocker('GEOMETRY_CRS_UNRESOLVED', 'evidence_missing',
                        'Uploaded geometry does not state a supported coordinate reference; an explicit source-bound geometry plan is required.', role=role)]
    if not all(coordinate_crs_matches(ref, geography.get('crs', '')) for ref in refs):
        return [blocker('GEOMETRY_CRS_CONFLICT', 'evidence_conflict',
                        'The proposed CRS does not match all scoped declarations in the uploaded geometry.',
                        role=role, details={'declared_crs': geography.get('crs'), 'geometry_references': refs})]
    return []


def table_blockers(resource, table):
    from .evidence_grounding import _critical_fields
    missing = sorted({field for _, _, field in _critical_fields({'resources': [resource]}, include_lookup_fields=False)
                      if field not in table['header']})
    # Unprojected lookup geometry is retained as a parent input, not silently
    # promoted to an incident point (e.g. postcode centroids or region polygons).
    issues = ([] if resource.get('grain') == 'lookup' and not resource.get('mapping', {}).get('geography')
              else geometry_blockers(resource, table))
    if missing:
        issues.append(blocker('MAPPED_FIELD_ABSENT', 'source_quality_block',
                              'Mapped fields are absent from the actual selected table.', role=resource['role'],
                              details={'table_id': table['table_id'], 'fields': missing}))
    return issues


def inspect_geometry(contract, files, check_cancelled=lambda: None):
    from .intakereaders import detect_tables
    admitted = {file['id']: file for file in files}
    issues = []
    from .table_plan import expand_resources
    from .lookup_semantics import capability_resources
    for resource in expand_resources(capability_resources(contract)):
        check_cancelled()
        file = admitted.get(resource.get('file_id'))
        if file is None:
            continue  # Contract validation owns resource admission.
        spec = resource.get('table', {})
        tables = detect_tables(file, spec, check_cancelled)
        selected = spec.get('sheet', spec.get('table_id'))
        for table in tables:
            if table['table_id'] == selected or selected is None and len(tables) == 1:
                if resource.get('grain') != 'lookup' or resource.get('mapping', {}).get('geography'):
                    issues.extend(geometry_blockers(resource, table))
    return issues


def inspect_capabilities(resources):
    """Use a host-produced inspect_bundle inventory, not model-supplied facts."""
    results = []
    for resource in resources:
        tables = []
        for table in resource.get('tables', []):
            kinds = set(table.get('observed_geometry_types', []))
            issues = ([blocker('NONPOINT_GEOMETRY_UNSUPPORTED', 'unsupported_capability',
                               'Point publication cannot represent the observed non-point geometry.',
                               details={'geometry_types': sorted(kinds)})] if kinds - {'Point', 'null'} else [])
            tables.append({'table_id': table['table_id'], 'reader_supported': True,
                           'geometry_types': sorted(kinds), 'blockers': issues,
                           'requires_source_semantic_proof': True})
        results.append({'file_id': resource['file_id'], 'format': resource.get('format'), 'tables': tables,
                        'inspection_issue': resource.get('inspection_issue'),
                        'blockers': resource.get('details', {}).get('blockers', [])})
    return {'version': VERSION, 'resources': results, 'admission': False,
            'limitation': 'Reader recognition does not establish source semantics, full QA or publication support.'}


def preflight_contract(contract, files, work_dir, *, native_context=None, check_cancelled=lambda: None, operation_policy=False):
    from .trusted_qa import validate_contract, _proof
    check_cancelled()
    try:
        operations = require_supported_operations(contract) if operation_policy else None
        table_receipts = []
        validate_contract(contract, files, native_context=native_context, check_cancelled=check_cancelled, table_receipts=table_receipts)
        proof = _proof(contract, work_dir, files, check_cancelled)
    except BudgetExhausted:
        raise
    except (NeedsInput, ValidationFailure) as exc:
        return {'version': VERSION, 'ok': False, 'blockers': classified_blockers(exc, operation='preflight') if operation_policy else exception_blockers(exc), 'admission': False,
                'checks':getattr(exc,'details',{}).get('checks',[{'code':'SOURCE_GROUNDING','status':'not_checked'}])}
    grounding = proof.get('grounding', {})
    return {'version': VERSION, 'ok': True, 'blockers': [], 'admission': False,
            **({'operation_support': operations, 'coverage_authority': {
                role: [row['declared_scope']['temporal'] for row in scope['documents']
                       if row['applies'] and row['declared_scope'].get('temporal')
                       and row['document_id'] in {entry['document_id'] for entry in proof.get('coverage_update', [])}]
                for role, scope in grounding.get('applicability', {}).get('roles', {}).items()}} if operation_policy else {}),
            'checks':proof.get('checks',[]),'representation_proofs':proof.get('representation_proofs',[]),
            'capability_limits':proof.get('capability_limits',[]),
            'limited_geography_issues':proof.get('capability_review',{}).get('limited_issues',[]),
            'table_classification': table_receipts,
            'evidence_graph_sha256': grounding.get('evidence_graph', {}).get('proof_sha256'),
            'field_binding_count': len(grounding.get('field_bindings', [])),
            'coordinate_proof_count': len(grounding.get('coordinate_proofs', [])),
            'verified_count_operations': [{'role':item['role'],'metric':item['metric'],'official_operands':item['official_operands']}
                                          for item in proof.get('count_operation_review',{}).get('decisions',[])],
            'category_review': [{k:item[k] for k in ('role','field','source_code','source_label','fatal_flag','status') if k in item}
                                for item in proof.get('category_review',{}).get('decisions',[])],
            'source_completeness': proof.get('source_completeness', {}),
            'evidence_applicability': {role:{'source_url':scope['source_url'],
                'applicable_documents':scope['applicable_documents'],
                'excluded_documents':[{'document_id':row['document_id'],'reasons':row['reasons']} for row in scope['documents'] if not row['applies']]}
                for role,scope in grounding.get('applicability',{}).get('roles',{}).items()},
            'next_step': 'Run isolated sample execution and independent candidate QA.'}
