"""Source-scoped direct count meanings, with pinned implementation-reviewed facts.

Field presence is not metric meaning. Generic whole definitions and reviewed
PDF aliases share the same scope/citation checks. Bundled facts are not model
proposals or source admission; their source bytes must be registered, applicable
and reverified by QA. They do not certify upload provenance or harmonization.
"""
from datetime import date
import json
from pathlib import Path
import re

from .evidence_grounding import _normal
from .evidence_references import covers_pointer, verify_reference
from .evidence_scope import applicable_documents
from .metadata_extractors import _token, MetadataError

VERSION = 'scoped-direct-count-v1'
REVIEWED = Path(__file__).with_name('knowledge') / 'reviewed-count-claims.json'
MEASURES = {'fatalities': 'fatalities', 'casualties': 'casualties',
            'declared_units': 'units', 'declared_casualties': 'casualties',
            'crashes': 'crashes', 'fatal_crashes': 'fatal_crashes'}
NOUNS = {'fatalities': r'(?:fatalities|deaths|deceased persons|persons killed|people killed)',
         'casualties': r'(?:casualties|persons killed or injured|people killed or injured)',
         'injuries': r'(?:injuries|injured persons|persons injured|people injured)',
         'units': r'units', 'crashes': r'(?:road )?crashes', 'fatal_crashes': r'fatal crashes'}


def definition_meaning(statement):
    """Consume the entire definition; no substring proof from prose/examples."""
    if not isinstance(statement, str) or len(statement) > 2048:
        return None
    text = ' '.join(statement.split()).removesuffix('.').casefold()
    for measure, nouns in NOUNS.items():
        pattern = (r'(?:the )?(?:total )?number of ' + nouns +
                   r'(?P<scope> as a result of (?:a|the) (?:road )?crash| per (?:road )?crash|'
                   r' involved in (?:a|the) (?:road )?crash| for a unit involved in a road crash)?')
        match = re.fullmatch(pattern, text)
        if match:
            scope = match['scope'] or ''
            return {'measure': measure, 'per_grain': 'unit' if 'for a unit' in scope else 'crash' if scope else None,
                    'definition': statement, 'interpretation': 'whole_literal_count_definition'}
    # A source-defined total may have an explicit addition as its definition.
    # Mapping that stored total is distinct from executing that addition.
    from .count_semantics import expression
    for metric, measure in MEASURES.items():
        if expression(statement, metric):
            return {'measure': measure, 'per_grain': None, 'definition': statement,
                    'interpretation': 'stored_total_with_explicit_source_equation'}
    return None


def _cited(entries, key, statement, pointer=None):
    return any(entry.get('document_id') == key and
               (covers_pointer(entry, pointer) if pointer and 'locator' in entry else
                ' '.join(statement.split()) in ' '.join(entry.get('quote', '').split()))
               for entry in entries)


def _structured(node, field, source_url=None):
    from .evidence_scope import schema_subjects, schema_fields
    for root, path in schema_subjects(node, source_url):
        for native, aliases, item, pointer in schema_fields(root, path):
            if _normal(field) not in {_normal(a) for a in aliases}:continue
            for prop in ('description', 'definition'):
                value = item.get(prop)
                if isinstance(value, str) and value.strip():
                    yield value, pointer + '/' + prop


def _text(doc, field):
    # Exact leading physical field, followed by its definition. A few wrapped
    # lines may complete one definition, never arbitrary nearby paragraphs.
    lines = doc.get('text', '').splitlines()
    pattern = re.compile(r'^\s*' + re.escape(field) + r'(?:\s*[:=]\s*|\s+)(.+)$', re.I)
    for i, line in enumerate(lines):
        match = pattern.fullmatch(line)
        if not match:
            continue
        for more in range(3):
            definition = ' '.join([match[1], *lines[i+1:i+1+more]])
            if definition_meaning(definition):
                yield definition
                break
        else:
            yield match[1]


def _reviewed(contract, resource, field, documents, allowed, entries):
    catalog = json.loads(REVIEWED.read_text())
    if catalog.get('version') != 'implementation-reviewed-count-claims-v1':
        raise MetadataError('COUNT_RULE_VERSION', 'Unsupported reviewed count rule version.')
    for claim in catalog['claims']:
        if (contract['source'].get('dataset_url') not in claim['dataset_urls']
                or resource['grain'] != claim['grain'] or resource['key'] != claim['key']
                or field != claim['field']):
            continue
        coverage = contract['source'].get('coverage', {})
        try:
            if not (date.fromisoformat(claim['coverage']['from']) <= date.fromisoformat(coverage['from'])
                    <= date.fromisoformat(coverage['to']) <= date.fromisoformat(claim['coverage']['to'])):
                continue
        except (KeyError, ValueError, TypeError):
            continue
        for key in allowed:
            doc = documents[key]
            if doc.get('sha256') != claim['document_sha256'] or doc.get('url') != claim['document_url']:
                continue
            references = [verify_reference({**ref, 'document_id': key}, doc) for ref in claim['references']]
            # Every semantic definition must be actually cited by this candidate;
            # review cannot lend facts from a document the Agent did not cite.
            definition = references[claim['definition_reference']]['quote']
            if not _cited(entries, key, definition):
                continue
            yield {'document_id': key, 'document_sha256': doc['sha256'],
                   'measure': claim['measure'], 'per_grain': claim['grain'], 'definition': definition,
                   'interpretation': 'implementation_reviewed_pinned_alias', 'reviewed_claim_id': claim['id'],
                   'references': references, 'scope': claim['coverage'], 'source_limits': claim['source_limits']}


def review_direct_count(contract, resource, metric, field, documents, grounding, accepted, graph):
    role = resource['role']; expected = MEASURES.get(metric)
    allowed = set(applicable_documents(grounding, role)); entries = accepted.get('counts', [])
    facts, unresolved = [], []
    for key in sorted(allowed):
        node = graph['nodes'][key]
        values = list(_structured(node, field, resource.get('source_url')))
        if node['facts'].get('value') is None:
            values = [(s, None) for s in _text(documents[key], field)]
        for statement, pointer in values:
            meaning = definition_meaning(statement)
            record = {'document_id': key, 'document_sha256': node['document_sha256'],
                      'statement': statement, 'schema_pointer': pointer}
            if meaning:
                facts.append({**record, **meaning, 'cited': _cited(entries, key, statement, pointer)})
            else:
                unresolved.append(record)
    reviewed = list(_reviewed(contract, resource, field, documents, allowed, entries))
    facts.extend({**fact, 'cited': True} for fact in reviewed)
    conflicts = [fact for fact in facts if fact['measure'] != expected or
                 fact['per_grain'] is not None and fact['per_grain'] != resource['grain']]
    # An arbitrary longer definition cannot be silently ignored in favour of
    # another short one. Resolve its interpretation/scope before admission.
    unresolved = [fact for fact in unresolved if not any(
        r['document_id'] == fact['document_id'] for r in reviewed)]
    matches = [fact for fact in facts if fact['cited'] and fact not in conflicts]
    if expected is None or conflicts or unresolved or not matches:
        return {'issue': {'code': 'COUNT_MEANING_CONFLICT' if conflicts else 'COUNT_MEANING_UNGROUNDED',
                'role': role, 'metric': metric, 'field': field, 'expected_measure': expected,
                'message': 'Scoped official definitions do not establish this direct count meaning and row population.',
                'conflicts': conflicts, 'unresolved_definitions': unresolved,
                'next_action': 'Cite the exact official field definition or an applicable implementation-reviewed pinned interpretation. Field presence, a model-written explanation, and a one-field sum are not semantic proof. Preserve the metric until its meaning is resolved.'}}
    return {'decision': {'claim_type': 'direct_count_definition', 'role': role, 'metric': metric,
                        'official_operands': [field], 'measure': expected, 'evidence': matches}}


def review_lookup_population(contract, resource, documents, grounding, accepted, graph):
    """A parent's count must explicitly concern the consumer's row grain.

    Field presence or a same-table addition equation cannot establish whether a
    stored total refers to a crash, unit, year or whole dataset. Full host QA also
    enforces one allocation of each parent/metric across all consumer records.
    """
    role = resource['role']; consumer = resource['lookup_consumer']
    allowed = set(applicable_documents(grounding, role)); issues, decisions = [], []
    for field in dict.fromkeys(origin['field'] for origin in resource['lookup_operands']):
        facts, unknown = [], []
        for key in sorted(allowed):
            node = graph['nodes'][key]
            values = list(_structured(node, field, resource.get('source_url')))
            if node['facts'].get('value') is None:
                values = [(statement, None) for statement in _text(documents[key], field)]
            for statement, pointer in values:
                meaning = definition_meaning(statement)
                fact = {'document_id': key, 'document_sha256': node['document_sha256'], 'statement': statement,
                        'schema_pointer': pointer, 'meaning': meaning,
                        'cited': _cited(accepted.get('counts', []), key, statement, pointer)}
                (facts if meaning and meaning.get('per_grain') is not None else unknown).append(fact)
        reviewed = list(_reviewed(contract, resource, field, documents, allowed, accepted.get('counts', [])))
        facts.extend({**fact, 'meaning': {'per_grain': fact['per_grain']}, 'cited': True} for fact in reviewed)
        unknown = [fact for fact in unknown if not any(item['document_id'] == fact['document_id'] for item in reviewed)]
        conflicts = [fact for fact in facts if fact['meaning']['per_grain'] != consumer['grain']]
        matches = [fact for fact in facts if fact not in conflicts and fact['cited']]
        if conflicts or unknown or not matches:
            issues.append({'code': 'LOOKUP_COUNT_POPULATION_CONFLICT' if conflicts else 'LOOKUP_COUNT_POPULATION_UNGROUNDED',
                           'role': consumer['role'], 'parent_role': role, 'field': field,
                           'expected_grain': consumer['grain'], 'conflicts': conflicts, 'unresolved': unknown,
                           'message': 'A lookup count needs an explicit scoped row population matching its consumer, and fresh full-data nonbroadcast verification.'})
        else:
            decisions.append({'field': field, 'evidence': matches, 'population': consumer['grain']})
    return {'parent_role': role, 'consumer': consumer, 'ok': not issues, 'issues': issues,
            'decisions': decisions, 'host_allocation_check_required': True}
