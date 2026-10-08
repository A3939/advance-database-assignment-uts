"""Scoped investigation progress derived from durable host tool outcomes.

This tracker grants neither evidence authority nor admission. In particular,
missing issues in a later early-return failure are not assumed resolved.
"""
import hashlib
import json

VERSION = 'scoped-issue-progress-v2'
GATES = {'preflight_contract', 'set_source_contract', 'patch_source_contract',
         'submit_workspace', 'validate_candidate', 'run_adapter', 'run_python', 'publish_candidate'}
SUBJECT = ('role', 'resource_role', 'parent_role', 'field', 'fields', 'claim', 'metric',
           'table_id', 'complete_key', 'required_capability', 'required_evidence_type')
CONFLICT = ('crs', 'declared_crs', 'expected_crs', 'actual_crs', 'datum', 'axis_order',
            'units', 'scope', 'expected', 'actual', 'conflicting_values')
GROUPS = ('grounding', 'capability_review', 'casualty_scope_review',
          'count_operation_review', 'category_review')


def stable(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(stable(value).encode()).hexdigest()


def host_scope(contract, files, policy_version, *, stable_subjects=False):
    """Selectors are observed proposals, not proof of source identity."""
    contract = contract if isinstance(contract, dict) else {}
    source = contract.get('source', {})
    source = source if isinstance(source, dict) else {}
    resources = contract.get('resources', [])
    resources = resources if isinstance(resources, list) else []
    return {'source_id': ('input-bundle:'+digest(sorted(f['sha256'] for f in files
                if f.get('role') != 'public_evidence' and not f.get('archive_file_id')))
                if stable_subjects else source.get('source_id')),
            'dataset_url': None if stable_subjects else source.get('dataset_url'),
            'roles': {r['role']: (None if stable_subjects else {'grain': r.get('grain'), 'key': r.get('key')})
                      for r in resources if isinstance(r, dict) and isinstance(r.get('role'), str)},
            **({'stable_subjects': True} if stable_subjects else {}),
            'inputs': {f['id']: f.get('sha256') for f in files}, 'policy_version': policy_version}


def _nested_semantics(value):
    """Only known value predicates; URLs, quoted prose and document hashes excluded."""
    if not isinstance(value, dict):
        return {}
    result = {k: value[k] for k in CONFLICT if k in value}
    if isinstance(result.get('conflicting_values'), list):
        result['conflicting_values'] = sorted(result['conflicting_values'], key=stable)
    for key in ('details', 'metrics'):
        child = _nested_semantics(value.get(key))
        if child:
            result[key] = child
    for key in ('evidence', 'geometry_references', 'declarations', 'conflicts'):
        entries = value.get(key)
        if isinstance(entries, list):
            facts = [_nested_semantics(item) for item in entries]
            facts = sorted({stable(fact) for fact in facts if fact})
            if facts:
                result[key] = [json.loads(fact) for fact in facts]
    return result


def issue_identity(issue, scope, gate):
    details = issue.get('details', issue.get('metrics', {}))
    details = details if isinstance(details, dict) else {}
    subject = {k: issue[k] if k in issue else details[k] for k in SUBJECT if k in issue or k in details}
    role = subject.get('role') or subject.get('resource_role')
    identity = {'code': issue.get('code', 'UNCLASSIFIED_GATE_FAILURE'), 'gate': gate,
                'source': {k: scope.get(k) for k in ('source_id', 'dataset_url')},
                'resource': scope.get('roles', {}).get(role), 'subject': subject,
                'conflict_values_sha256': digest(_nested_semantics(issue)),
                'policy_version': scope.get('policy_version', 'historical-unrecorded')}
    return digest(identity), identity


def observation(step):
    """Return only controlled gate outcomes; source document prose is never scanned."""
    name = step.get('name'); output = step.get('result') or {}
    if name not in GATES or not isinstance(output, dict) or step.get('status') == 'running':
        return None
    context = output.get('host_context') or {}
    args = step.get('arguments') or {}
    mode = context.get('run_mode') or args.get('mode') or ('sample' if output.get('status') == 'sample_only' else 'unknown')
    gate = ('publication' if name == 'publish_candidate' else 'validation.'+mode if name == 'validate_candidate' else 'execution.'+mode
            if name in {'run_adapter', 'run_python'} else 'preflight')
    payload = output
    if gate == 'preflight':
        if name == 'submit_workspace':
            payload = output.get('contract', {}).get('preflight', output)
        elif name in {'set_source_contract', 'patch_source_contract'}:
            payload = output.get('preflight', output)
    details = payload.get('details') or {}
    issues = list(payload.get('blockers') or details.get('blockers') or [])
    if not issues:
        groups = GROUPS + (('lookup_relation_review', 'lookup_geography_subject_review')
                          if context.get('progress_scope', {}).get('stable_subjects') else ())
        issues = [issue for group in groups for issue in details.get(group, {}).get('issues', [])]
    qa = [q for q in output.get('qa', []) if isinstance(q, dict)]
    qa += [q for q in payload.get('checks', details.get('checks', [])) if isinstance(q,dict)]
    issues += [q for q in qa if q.get('status') == 'block']
    success = step.get('status') == 'succeeded' and not issues and (
        payload.get('ok') is True if gate == 'preflight' else
        output.get('status') in {'sample_only', 'validated'} if name == 'validate_candidate' else
        output.get('status') in {'succeeded','no_change'} if gate == 'publication' else
        output.get('status') == 'succeeded')
    failed = bool(issues) or step.get('status') in {'failed', 'needs_evidence', 'paused'} or payload.get('ok') is False or output.get('status') in {'failed', 'error'}
    if failed and not issues:
        # No prose hashing: a changed exception wording is still the same
        # unclassified problem, with the full diagnostic reachable by step ID.
        issues = [{'code': output.get('type') or 'UNCLASSIFIED_GATE_FAILURE', 'kind': 'unclassified'}]
    if not success and not failed:
        return None
    return gate, success, [i for i in issues if isinstance(i, dict)], qa


def progress_report(steps, settings, *, current_attempt=None):
    issues = {}; active = set(); passed = set(); events = set(); measured = set()
    idle = meaningful = 0; last = None; last_at = None; last_reason = None; completed = 0; current_seen = False
    for step in steps:
        # Code Mode dispatch is transport around the same MCP operation. It
        # consumes the global tool/CPU budgets, but is not a second semantic
        # investigation action and must not halve the no-progress allowance.
        if step.get('name') in {'codex.exec','codex.wait'} and (step.get('result') or {}).get('status') == 'authorized_for_dispatch':
            continue
        if step.get('status') == 'running':
            continue
        if current_attempt is not None:
            this_attempt = step.get('attempt_id') or (step.get('result') or {}).get('host_context', {}).get('attempt_id')
            if str(this_attempt) == str(current_attempt):
                current_seen = True
            elif current_seen:
                continue  # A late old-worker result cannot clear this attempt's issue.
        completed += 1; idle += 1
        output = step.get('result') or {}
        if not isinstance(output, dict):
            output = {}
        scope = (output.get('host_context') or {}).get('progress_scope', {})
        result = observation(step); improvements = []
        if result:
            gate, success, found, qa = result
            covered_gates = {gate}
            admission = output.get('admission') or {}
            if success and step.get('name') == 'validate_candidate' and admission.get('policy_version') == scope.get('policy_version'):
                if admission.get('status') == 'sample_only' and gate == 'validation.sample':
                    covered_gates |= {'preflight', 'execution.sample'}
                elif admission.get('status') == 'admitted' and gate == 'validation.full':
                    covered_gates |= {'preflight', 'execution.sample', 'validation.sample', 'execution.full'}
            applicable = {key for key in active if issues[key]['identity']['gate'] in covered_gates
                          and (issues[key]['identity']['source'] == {k: scope.get(k) for k in ('source_id', 'dataset_url')}
                               or not any(issues[key]['identity']['source'].values()))
                          and issues[key]['identity']['policy_version'] == scope.get('policy_version', 'historical-unrecorded')}
            # A passing check can clear only that exact QA code, never a failed
            # full gate from a new sample or an unrelated execution success.
            # Partial passes are scoped per subject; another field failing the same
            # code must not suppress this field's explicit passing check.
            failures=[issue_identity(i,scope,gate)[1] for i in found]
            pass_subjects=[issue_identity(q,scope,gate)[1] for q in qa if q.get('status')=='pass'
                           and isinstance(q.get('code'),str)]
            pass_subjects=[p for p in pass_subjects if not any(
                p['code']==f['code'] and p['subject']==f['subject'] and p['resource']==f['resource'] for f in failures)]
            resolved = applicable if success else {k for k in applicable if any(
                p['code'] == issues[k]['identity']['code'] and p['subject'] == issues[k]['identity']['subject']
                and p['resource'] == issues[k]['identity']['resource'] for p in pass_subjects)}
            for key in resolved:
                active.remove(key); issues[key]['resolved_at_step'] = step.get('id')
                if ('resolved', key) not in events:
                    events.add(('resolved', key)); improvements.append({'resolved_issue': key})
            for issue in found:
                key, identity = issue_identity(issue, scope, gate)
                if key not in issues:
                    issues[key] = {'issue_id': key, 'identity': identity, 'first_step_id': step.get('id'),
                        'first_observed_at_tool': completed, 'observations': 0, 'kind': issue.get('kind', 'gate_failure')}
                row = issues[key]; row.update(last_step_id=step.get('id'), observations=row['observations']+1)
                row.pop('resolved_at_step', None); active.add(key)
            if success and ('gate', gate) not in events:
                events.add(('gate', gate)); improvements.append({'first_passing_gate': gate})
            for check in pass_subjects:
                key=digest(check)
                if key not in passed:
                    passed.add(key); improvements.append({'new_passing_check':check})
        # Before a blocking gate exists, actual complete measurement can advance
        # investigation. While blocked it must be tested at the relevant gate.
        name = step.get('name')
        if not active and step.get('status') == 'succeeded':
            value = None
            if name == 'profile_dataset' and output.get('complete'):
                value = {k: output.get(k) for k in ('table', 'row_count', 'columns', 'unique_column_candidates')}
                value['input_sha256'] = scope.get('inputs', {}).get(output.get('file_id'))
                if not value['input_sha256']:
                    value['historical_file_id'] = output.get('file_id')
            elif name == 'inspect_relations':
                value = {k: output.get(k) for k in ('child_fields', 'parent_fields', 'metrics')}
                value['input_sha256'] = [scope.get('inputs', {}).get(output.get(k), output.get(k))
                                        for k in ('child_file_id', 'parent_file_id')]
            if value is not None and (name, digest(value)) not in measured:
                measured.add((name, digest(value))); improvements.append({'complete_measurement': name})
        if improvements:
            idle = 0; meaningful += 1; last = step.get('id'); last_reason = improvements
            timestamp = step.get('finished_at') or step.get('created_at')
            last_at = timestamp.isoformat() if hasattr(timestamp, 'isoformat') else timestamp
    pending = []
    for key in sorted(active):
        item = issues[key]
        pending.append({**item, 'tools_since_first_observation': completed-item['first_observed_at_tool'],
                        'repeated_without_resolution': item['observations'] >= 3,
                        'read_full': {'tool': 'read_task_state', 'arguments': {'kind':'tool_result','step_id':item['last_step_id'],'pointer':'','max_chars':4000}}})
    # Unrelated profile/gate progress cannot conceal a long-standing issue.
    longest = max([idle, *[r['tools_since_first_observation'] for r in pending]])
    warn, stop = settings.get('warn_after_tools', 0), settings.get('stop_after_tools', 0)
    state = ('stalled' if stop and longest >= stop else 'replan' if (warn and longest >= warn)
             or any(r['repeated_without_resolution'] for r in pending) else 'continuing')
    return {'version': VERSION, 'state': state, 'meaningful_events': meaningful,
            'tools_without_progress': longest, 'global_tools_without_progress': idle,
            'last_progress_step_id': last, 'last_progress_at': last_at, 'last_progress': last_reason, 'unresolved_issues': pending,
            'completed_tools': completed, 'basis': 'Host gate/check improvement and complete measurements before blockage. New URLs, document hashes, quote changes, edits and rereads never renew allowance.',
            'next_action': 'Re-evaluate the exact blocked subject with a different diagnostic; do not repeat downloads or edits.' if state != 'continuing' else None,
            'limits': 'Explicit host check passes count once per subject. Not-checked/absent results and unverified partial evidence changes are not progress. Three unchanged gate observations prompt replanning, not an added stop budget. Existing configured stop/model/tool/time limits remain unchanged.'}


def public_summary(report):
    """UI receives counters/timestamps, never problem subjects or source content."""
    return {key: report.get(key) for key in ('version', 'state', 'meaningful_events',
            'tools_without_progress', 'last_progress_at')} | {'unresolved_count': len(report.get('unresolved_issues', []))}
