"""Bounded, source-scoped casualty register completeness evidence.

Whole affirmative declarations can authorize equality. Field mentions, model
booleans, negations and hypothetical sentences cannot. A known partial scope
is retained as a system capability gap, not converted to complete coverage.
"""
import re

from .evidence_grounding import _json_document, _normal
from .evidence_references import verify_reference
from .evidence_scope import applicable_documents
from .geography_review import specific_document
from .metadata_extractors import MetadataError

VERSION = 'scoped-casualty-completeness-v2'
TABLE = r'(?:the\s+)?casualty\s+(?:register|table|dataset)'
KEYED = r'(?:keyed\s+by|identified\s+by|using)'
COMPLETE_PATTERNS = [
    r'(?:the\s+)?complete\s+casualty\s+(?:register|table|dataset)\s+'
    r'(?:is\s+identified\s+by|is\s+keyed\s+by|uses)\s+(?P<keys>.+)',
    TABLE + r'\s+' + KEYED + r'\s+(?P<keys>.+?)\s+'
    r'(?:is\s+complete|(?:contains|includes|records)\s+all\s+(?:reported\s+)?casualties)',
]
PARTIAL_PATTERNS = [
    TABLE + r'\s+' + KEYED + r'\s+(?P<keys>.+?)\s+'
    r'(?:(?:contains|includes|records)\s+only\s+.+|is\s+not\s+complete|'
    r'is\s+(?:a\s+)?(?:sample|subset)\s+of\s+.+)',
]


def applicable_resources(contract):
    roles = {r['role']: r for r in contract.get('resources', [])}
    for relation in contract.get('relations', []):
        parent, child = roles.get(relation.get('parent'), {}), roles.get(relation.get('child'), {})
        mapping = parent.get('mapping', {})
        if (parent.get('grain') == 'crash' and child.get('grain') == 'casualty'
                and mapping.get('casualties') and not mapping.get('declared_casualties')):
            yield parent, child


def _sentences(text):
    if not isinstance(text, str):
        return []
    return [' '.join(sentence.split()) for sentence in re.split(r'[.!?](?:\s|$)', text)
            if sentence.strip()]


def _keys_match(text, resource):
    # No arbitrary prose may hide in the key clause. Each actual key appears
    # exactly once; extra/duplicate/missing key fields are not the same scope.
    keys = [_normal(key) for key in resource.get('key', [])]
    actual = [_normal(part.strip().strip('`\"\'')) for part in
              re.split(r',\s*(?:and\s+)?|\s+(?:and|&)\s+', text, flags=re.I)]
    return bool(keys) and len(set(keys)) == len(keys) and sorted(keys) == sorted(actual)


def _scope(statement, resource):
    for kind, patterns in [('complete', COMPLETE_PATTERNS), ('partial', PARTIAL_PATTERNS)]:
        for pattern in patterns:
            match = re.fullmatch(pattern, statement, flags=re.I)
            if match and _keys_match(match['keys'], resource):
                return kind
    return None


def _document_statements(doc, node=None):
    if not specific_document(doc):
        return []
    value = _json_document(doc)
    if value is None:
        return _sentences(doc.get('text', ''))
    # Never search JSON serialization: adjacent resources, samples or examples
    # can contain the same words. Only scoped metadata root descriptions apply.
    packages = node.get('scoped_packages', []) if node else []
    roots = [package for package, _ in packages] or [value]
    return [statement for root in roots if isinstance(root, dict)
            for key in ('description', 'notes') for statement in _sentences(root.get(key))]


def _verified_quote(entry, doc):
    if 'locator' in entry:
        try:
            return verify_reference(entry, doc)
        except (MetadataError, KeyError):
            return None
    quote = entry.get('quote')
    if (isinstance(quote, str) and 12 <= len(quote) <= 12000
            and ' '.join(quote.split()) in ' '.join(doc.get('text', '').split())):
        return {'document_id': entry['document_id'], 'url': doc.get('url'),
                'sha256': doc.get('sha256'), 'quote': quote}
    return None


def review_casualty_scope(contract, documents, grounding, *, graph=None):
    issues, decisions = [], []
    complete = contract.get('definitions', {}).get('casualty_table_complete')
    entries = contract.get('evidence', {}).get('casualty_scope', [])
    for parent, child in applicable_resources(contract):
        connected = set(applicable_documents(grounding, child['role']))
        declarations = {}
        for key in sorted(connected):
            doc = documents.get(key, {})
            node = (graph or {}).get('nodes', {}).get(key)
            declarations[key] = {statement: kind for statement in _document_statements(doc, node)
                                 if (kind := _scope(statement, child))}
        proofs = {'complete': [], 'partial': []}
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict) or entry.get('resource_role') != child['role']:
                continue
            key = entry.get('document_id')
            if key not in connected:
                continue
            verified = _verified_quote(entry, documents.get(key, {}))
            if verified is None:
                continue
            for statement in _sentences(verified['quote']):
                kind = declarations[key].get(statement)
                if kind:
                    proofs[kind].append({**verified, 'statement': statement})
        known = [{'document_id': key, 'sha256': documents[key].get('sha256'),
                  'statement': statement, 'scope': kind}
                 for key, statements in declarations.items() for statement, kind in statements.items()]
        known_kinds = {item['scope'] for item in known}
        # Both directions: an uncited partial declaration must also block a
        # complete assertion. Keeping fewer citations cannot erase a conflict.
        contradiction = (len(known_kinds) > 1 or complete is True and 'partial' in known_kinds
                         or complete is False and 'complete' in known_kinds)
        if complete is True and proofs['complete'] and not contradiction:
            decisions.append({'parent_role': parent['role'], 'resource_role': child['role'],
                              'complete': True, 'evidence': proofs['complete']})
            continue
        partial_unsupported = complete is False and proofs['partial'] and not contradiction
        code = ('CASUALTY_SCOPE_CONFLICT' if contradiction else
                'CASUALTY_PARTIAL_SCOPE_UNSUPPORTED' if partial_unsupported else 'CASUALTY_SCOPE_REQUIRED')
        issues.append({'code': code, 'claim': 'casualty_scope', 'parent_role': parent['role'],
            'role': child['role'], 'resource_role': child['role'], 'complete_key': child['key'],
            'conflicting_complete_scope': bool(contradiction), 'declarations': known,
            'message': ('Scoped official casualty completeness declarations conflict with this proposal.' if contradiction else
                'The publisher documents partial casualty coverage; scoped partial-table reconciliation is not implemented.' if partial_unsupported else
                'Count reconciliation needs an affirmative, resource-bound official completeness declaration.'),
            'next_action': ('Implement and verify scoped partial-table reconciliation; more copies of the same dictionary cannot add this system capability.' if partial_unsupported else
                'Resolve the specific source scope. mapping.declared_casualties is appropriate only for a source-declared total applying to the child table. Otherwise cite an exact affirmative declaration of the table and its complete key. Model booleans, hypothetical or negated statements do not authorize equality.')})
    return {'version': VERSION, 'ok': not issues, 'issues': issues, 'decisions': decisions}
