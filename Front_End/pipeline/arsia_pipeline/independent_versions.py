"""Explicit immutable dataset versions when cross-release keys are unproved.

Each version is independently admitted and selected by its own source ID. No
record mapping, membership replacement, union, or chronological order is implied.
"""
import re

from .errors import ValidationFailure
from .publication_policy import digest

VERSION = 'independent-dataset-version-v1'


def inputs(contract, files):
    from .table_plan import bound_inputs, physical_resources
    by_id = {f['id']: f for f in files}
    ids = {p['file_id'] for r in bound_inputs(contract) for p in physical_resources(r)}
    if not ids or not ids <= by_id.keys():
        raise ValidationFailure('Independent version requires all declared original inputs')
    return digest(sorted((by_id[key]['sha256'], by_id[key]['size']) for key in ids))


def source_id(family, input_sha256):
    if not re.fullmatch(r'official-dataset-[a-f0-9]{64}', family or '') or not re.fullmatch(r'[a-f0-9]{64}', input_sha256 or ''):
        raise ValidationFailure('Independent version needs a verified official family and whole-input identity')
    return 'version_' + family[-64:][:16] + '_' + input_sha256[:24]


def validate(contract, files):
    value = contract.get('version_scope')
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) != {'version', 'family_identity_key', 'input_sha256', 'cross_version_record_mapping'}:
        raise ValidationFailure('Invalid independent version declaration')
    if value['version'] != VERSION or value['cross_version_record_mapping'] != 'unverified':
        raise ValidationFailure('Independent versions do not prove cross-version record correspondence')
    actual = inputs(contract, files)
    if value['input_sha256'] != actual or contract['source']['source_id'] != source_id(value['family_identity_key'], actual):
        raise ValidationFailure('Independent version identity differs from the complete original input')
    if contract.get('update') != {'mode': 'snapshot'}:
        raise ValidationFailure('Independent versions cannot merge or replace another version')
    return value


def select(session):
    # Namespace selection is a proposal, not admission. Resolve it before the
    # expensive full execution; otherwise selecting isolation doubles every
    # canonical output and forces an avoidable second full QA run.
    from .source_identity import _identity_from_proof
    from .trusted_qa import validate_contract, _proof
    import copy
    if not session.contract:
        raise ValueError('Set an evidence-backed source contract first')
    contract = copy.deepcopy({**session.contract, "documents": list(session.documents.values())})
    validate_contract(contract, session.files, native_context=session.native_context,
                      check_cancelled=session.cancel_check)
    proof = _proof(contract, session.work_dir, session.files, session.cancel_check)
    family = _identity_from_proof(proof, contract)
    if contract.get('version_scope'):
        validate(contract, session.files)
        if contract['version_scope']['family_identity_key'] != family['identity_key']:
            raise ValidationFailure('Independent version cannot invent another official family')
        return {'status': 'already_independent', 'version_scope': contract['version_scope'], 'admission': False}
    raw_identity = inputs(contract, session.files)
    contract['version_scope'] = {'version': VERSION, 'family_identity_key': family['identity_key'],
        'input_sha256': raw_identity, 'cross_version_record_mapping': 'unverified'}
    contract['source']['source_id'] = source_id(family['identity_key'], raw_identity)
    contract['update'] = {'mode':'snapshot'}
    result = session.execute_tool('set_source_contract', {'contract': contract})
    return {**result, 'version_scope': contract['version_scope'], 'source_id': contract['source']['source_id'],
            'target_satisfied': False, 'admission': False, 'limitations': ['Cross-version record correspondence remains unverified.',
                'Choose exactly one explicit source version for a query. No pooled count or automatic latest-version inference.',
                'Complete fresh sample/full execution and QA after this contract change.']}


def bind_identity(identity, result, contract):
    value = contract.get('version_scope')
    if value is None:
        return identity
    # The admission hash pins this declaration; independently recompute input
    # identity from the host QA file inventory and prove the official family.
    validate(contract, result['files'])
    if value['family_identity_key'] != identity['identity_key']:
        raise ValidationFailure('Independent version cannot invent another official family')
    return {**identity, 'family_identity_key': identity['identity_key'],
            'identity_key': identity['identity_key'] + ':independent:' + value['input_sha256'],
            'version_scope': value}
