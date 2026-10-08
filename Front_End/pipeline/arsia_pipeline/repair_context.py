"""Host-owned blocker routing and bounded handoff, not a second Agent loop."""
import hashlib
import json

from .errors import BudgetExhausted, ImportCancelled, NeedsInput

VERSION = 'bounded-repair-v1'


def enabled(session):
    return getattr(session, 'bounded_repair_v1', False) is True


def route(exc, blockers):
    if isinstance(exc, (ImportCancelled, BudgetExhausted)):
        return 'stop'
    # Integrity failures cannot be repaired by changing a data proposal.
    if any(row.get('kind') == 'system_configuration' or row.get('code') in {'STORAGE_BUDGET', 'STORAGE_OWNER', 'STORAGE_PATH'}
           or any(word in row.get('code', '') for word in ('INTEGRITY', 'BOUNDARY', 'OWNERSHIP', 'SYMLINK'))
           for row in blockers):
        return 'stop'
    if any(row.get('kind') in {'system_fault', 'environment_dependency', 'unsupported_capability'}
           for row in blockers):
        return 'engineering'
    return 'data_investigation'


def record(session, exc, operation):
    from .agent import safe
    from .capability_preflight import classified_blockers
    from .registry import digest_json
    blockers = classified_blockers(exc, operation=operation)
    binding = {'job_id': str(session.job['id']), 'attempt_id': str(session.job['attempt_id']),
               'inputs': sorted((f['id'], f['sha256']) for f in session.files)}
    identity = digest_json({'binding': binding, 'operation': operation,
                            'blockers': blockers})
    details = dict(getattr(exc, 'details', {}))
    previous = details.pop('repair', None)
    if isinstance(previous, dict):
        details['prior_blocker_id'] = previous.get('blocker_id')
    value = {'version': VERSION, 'blocker_id': identity, 'binding': binding,
             'operation': operation, 'origin': 'trusted_host', 'error_type': type(exc).__name__,
             'message': str(exc)[:3000], 'blockers': safe(blockers),
             'route': route(exc, blockers), 'details': safe(details),
             'qa': safe(getattr(exc, 'qa', [])),
             'contract_sha256': digest_json(session.contract),
             'code_sha256': hashlib.sha256(session.code.encode()).hexdigest(),
             'original_goal': session.runtime_state.get('original_goal'),
             'available_actions': ['read_task_state', 'inspect_task_scope', 'run_diagnostic',
                                   'request_engineering_repair', 'request_missing_information'],
             'authority': 'Diagnostic evidence only; no permission to change host code or publish.'}
    session.runtime_state['repair'] = value
    return value


def should_stop(session, exc):
    from .capability_preflight import requires_system_change
    if not enabled(session):
        return requires_system_change(getattr(exc, 'details', {}))
    current = session.runtime_state.get('repair', {})
    return current.get('route') == 'stop' or getattr(exc, 'code', '') in {
        'scope_not_established', 'engineering_repair_required'}


def engineering_handoff(session, args):
    current = require_blocker(session, args['blocker_id'])
    # A validator defect can initially look like an adapter revision. Accept
    # a review request without granting engineering execution or trusting it.
    proposal = args.get('proposal', '')
    if not isinstance(proposal, str) or not 1 <= len(proposal.encode()) <= 64000:
        raise ValueError('Use a bounded investigation/patch proposal, at most 64 KiB')
    path = session.work_dir / ('engineering-' + current['blocker_id'] + '.json')
    packet = {**current, 'proposal': proposal, 'trusted': False,
              'requested_route': 'engineering_review',
              'budget_consumed': dict(session.usage),
              'active_wall_seconds': session.active_wall_seconds(),
              'integration_conditions': ['independent source workspace', 'positive and negative tests',
                                        'idle services and unchanged baseline', 'backup and rollback'],
              'automatic_load_allowed': False}
    path.write_text(json.dumps(packet, indent=2, ensure_ascii=False) + '\n')
    exc = NeedsInput('A scoped engineering repair is required; the reproducible proposal is saved. '
                     'Data tools cannot load this patch.', [], {'repair': packet})
    exc.code = 'engineering_repair_required'
    exc.kind = 'unsupported_capability'
    raise exc


def require_blocker(session, blocker_id):
    current = session.runtime_state.get('repair', {})
    if not current or current.get('blocker_id') != blocker_id:
        raise ValueError('Use the current host blocker_id from get_workflow_state')
    binding = current['binding']
    if binding['job_id'] != str(session.job['id']) or binding['attempt_id'] != str(session.job['attempt_id']):
        raise ValueError('Blocker belongs to another job or attempt')
    if current['route'] == 'stop':
        raise ValueError('A stop condition cannot authorize diagnostic execution')
    return current


def terminal_context(job, exc, phase, *, pinned=False):
    """Explain retained worker-level stops without starting another Agent.

    Frozen policies and integrity/validation failures are not data-Agent
    authority. Their next action is isolated engineering review or user facts.
    """
    from .capability_preflight import classified_blockers
    from .agent import safe
    blockers = classified_blockers(exc, operation=phase)
    destination = route(exc, blockers)
    if destination != 'stop' and (pinned or phase != 'agent'):
        destination = 'engineering_review'
    return {'phase': phase, 'route': destination, 'origin': 'trusted_host',
            'job_id': str(job['id']), 'attempt_id': str(job['attempt_id']),
            'inputs': [{'sha256':f['sha256'], 'file_id':f['id']} for f in job['files']],
            'original_request': safe({k:job.get('options', {}).get(k) for k in ('answers','source_hint','requested_capabilities')}),
            'message': str(exc)[:3000], 'blockers': safe(blockers),
            'next_action': ('Preserve this stop and its cumulative budget; no automatic retry.' if destination == 'stop'
                else 'Review saved diagnostics in isolated source/tests; do not weaken fixed source or publication gates.'
                if destination == 'engineering_review' else 'Read the saved Agent blocker and specific missing evidence.'),
            'automatic_retry': False}
