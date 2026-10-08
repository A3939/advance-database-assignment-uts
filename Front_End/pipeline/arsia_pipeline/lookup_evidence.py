"""Publisher-scoped CSVW foreign-key evidence for a finite lookup plan.

Only a fixed CSVW JSON context is interpreted, without fetching remote contexts.
Reference targets identify exact resources; links never expand publisher trust.
Column names, composite order and direction remain significant. This module
does not prove category/count/CRS meaning or grant adapter admission.
"""
from urllib.parse import urljoin
from datetime import date
import json
from pathlib import Path

from .evidence_graph import representation
from .evidence_references import covers_pointer, verify_reference
from .evidence_scope import applicable_documents
from .metadata_extractors import MetadataError

VERSION = 'scoped-lookup-relation-v2'
REVIEWED = Path(__file__).with_name('knowledge') / 'reviewed-lookup-claims.json'
CONTEXT = 'http://www.w3.org/ns/csvw'
SPEC = 'https://www.w3.org/TR/tabular-metadata/#schemas'


def csvw_tables(node):
    value = node['facts'].get('value')
    if not isinstance(value, dict) or value.get('@context') != CONTEXT:
        return []
    if value.get('@type') not in (None, 'Table', 'TableGroup'):
        raise MetadataError('LOOKUP_CSVW_UNSUPPORTED', 'This CSVW evidence needs a supported Table or TableGroup description.')
    if 'tables' in value:
        tables = value['tables']
        if not isinstance(tables, list) or not 1 <= len(tables) <= 64:
            raise MetadataError('LOOKUP_CSVW_UNSUPPORTED', 'CSVW table groups must contain 1–64 inline table descriptions.')
        pairs = [(table, f'/tables/{index}') for index, table in enumerate(tables)]
    else:
        pairs = [(value, '')]
    result = []
    for table, pointer in pairs:
        if not isinstance(table, dict) or '@context' in table and table is not value:
            raise MetadataError('LOOKUP_CSVW_UNSUPPORTED', 'Nested CSVW context overrides are not interpreted.')
        url = table.get('url')
        if not isinstance(url, str) or not url or any(char in url for char in '{}#'):
            raise MetadataError('LOOKUP_CSVW_UNSUPPORTED', 'CSVW table identity must be an explicit resource URL.')
        url = representation(urljoin(node['url'], url))
        if url is None:
            raise MetadataError('LOOKUP_CSVW_UNSUPPORTED', 'CSVW table identity needs a supported exact HTTPS resource.')
        schema = table.get('tableSchema')
        if not isinstance(schema, dict) or '@context' in schema:
            raise MetadataError('LOOKUP_CSVW_UNSUPPORTED', 'CSVW lookup evidence requires an inline schema with the fixed context.')
        result.append({'url': url, 'table': table, 'schema': schema, 'pointer': pointer})
    return result


def references(value):
    values = [value] if isinstance(value, str) else value
    if (not isinstance(values, list) or not 1 <= len(values) <= 16
            or any(not isinstance(v, str) or not v for v in values)
            or len(set(values)) != len(values)):
        raise MetadataError('LOOKUP_CSVW_INVALID', 'CSVW column references must be an ordered nonempty list of distinct names.')
    return values


def reviewed_relations(contract, child, lookup, parent, graph, grounding, accepted, documents):
    """Pinned implementation interpretations, never model-supplied approval.

    This proves the documented reference only. Original input uniqueness and
    coverage must still be checked; publisher prose cannot repair bad keys.
    """
    if documents is None:return []
    catalog = json.loads(REVIEWED.read_text())
    if catalog.get('version') != 'implementation-reviewed-lookup-claims-v1':
        raise MetadataError('LOOKUP_RULE_VERSION', 'Unsupported reviewed lookup rule version.')
    source = contract.get('source', {})
    allowed = set(applicable_documents(grounding, child['role'])) & set(applicable_documents(grounding, parent['role']))
    facts = []
    for claim in catalog['claims']:
        if (source.get('dataset_url') not in claim['dataset_urls']
                or representation(child.get('source_url')) != claim['child_url']
                or set(lookup['fields']) != set(claim['child_fields'])):continue
        try:
            coverage = source['coverage']
            if not (date.fromisoformat(claim['coverage']['from']) <= date.fromisoformat(coverage['from'])
                    <= date.fromisoformat(coverage['to']) <= date.fromisoformat(claim['coverage']['to'])):continue
        except (KeyError,TypeError,ValueError):continue
        for key in sorted(allowed):
            node = graph['nodes'][key]
            if node['url'] != claim['document_url'] or node['document_sha256'] != claim['document_sha256']:continue
            # Raw bytes already entered graph through trusted receipt checks.
            document = documents.get(key, {})
            if document.get('url') != node['url'] or document.get('sha256') != node['document_sha256']:continue
            refs = [verify_reference({**ref,'document_id':key},document) for ref in claim['references']]
            cited = all(any(entry.get('document_id') == key and
                           (covers_pointer(entry,ref['locator']['pointer']) if 'locator' in entry else
                            ' '.join(ref['quote'].split()) in ' '.join(entry.get('quote','').split()))
                           for entry in accepted.get('relations',[])) for ref in refs)
            facts.append({'document_id':key,'document_sha256':node['document_sha256'],
                          'child_url':claim['child_url'],'child_fields':claim['child_fields'],
                          'parent_url':claim['parent_url'],'parent_fields':claim['parent_fields'],
                          'allow_blank':claim['allow_blank'],'cited':cited,
                          'interpretation':'implementation_reviewed_pinned_relation','reviewed_claim_id':claim['id'],
                          'references':refs,'scope':claim['coverage'],'source_limits':claim['source_limits']})
    return facts


def review_lookup_relations(contract, graph, grounding, accepted, *, documents=None):
    issues, decisions = [], []
    parents = {r['role']: r for r in contract.get('lookup_tables', [])}
    for child in contract.get('resources', []):
        for lookup in child.get('lookups', []):
            role, name = child['role'], lookup['name']
            parent = parents[lookup['parent']]
            targets = [representation(r.get('source_url')) for r in (child, parent)]
            scopes = grounding.get('applicability', {}).get('roles', {})
            if any(url is None or scopes.get(r['role'], {}).get('source_url') != url
                   for r, url in zip((child, parent), targets)):
                issues.append({'code': 'LOOKUP_RESOURCE_IDENTITY_REQUIRED', 'role': role, 'lookup': name,
                               'message': 'Lookup relation evidence needs explicit publisher-bound child and parent source_url values.'})
                continue
            if lookup['on_missing'] != 'error':
                issues.append({'code': 'LOOKUP_MISSING_POLICY_UNSUPPORTED', 'role': role, 'lookup': name,
                               'message': 'A CSVW foreign key cannot authorize unmatched nonblank keys. Preserving unmatched rows requires a reviewed weak-link population rule.'})
                continue
            matches, conflicts = [], []
            for proof in reviewed_relations(contract,child,lookup,parent,graph,grounding,accepted,documents):
                if (proof['child_fields'] != lookup['fields'] or proof['parent_url'] != targets[1]
                        or proof['parent_fields'] != parent['key']):
                    conflicts.append(proof)
                elif lookup['allow_blank'] and not proof['allow_blank']:
                    issues.append({'code':'LOOKUP_NULLABILITY_UNGROUNDED','role':role,'lookup':name,
                                   'message':'The pinned relation interpretation does not authorize blank lookup keys.'})
                elif proof['cited']:matches.append(proof)
            for key in applicable_documents(grounding, role):
                node = graph['nodes'][key]
                for table in csvw_tables(node):
                    if table['url'] != targets[0]:
                        continue
                    foreign = table['schema'].get('foreignKeys', [])
                    if not isinstance(foreign, list) or len(foreign) > 64:
                        raise MetadataError('LOOKUP_CSVW_INVALID', 'Invalid or oversized CSVW foreign-key list.')
                    for index, relation in enumerate(foreign):
                        if not isinstance(relation, dict):
                            raise MetadataError('LOOKUP_CSVW_INVALID', 'A CSVW foreign key must be an object.')
                        fields = references(relation.get('columnReference'))
                        if fields != lookup['fields']:
                            # Same members in another order are a conflicting
                            # composite identity, not an interchangeable key.
                            if set(fields) != set(lookup['fields']):continue
                        reference = relation.get('reference')
                        if (not isinstance(reference, dict) or set(reference) != {'resource', 'columnReference'}
                                or not isinstance(reference.get('resource'), str)
                                or any(char in reference['resource'] for char in '{}#')):
                            raise MetadataError('LOOKUP_CSVW_UNSUPPORTED', 'Lookup proof supports exact CSVW resource references, not remote schemas or implicit target selection.')
                        target = representation(urljoin(node['url'], reference['resource']))
                        parent_fields = references(reference.get('columnReference'))
                        pointer = table['pointer'] + f'/tableSchema/foreignKeys/{index}'
                        proof = {'document_id': key, 'document_sha256': node['document_sha256'],
                                 'locator': {'kind': 'json-pointer', 'pointer': pointer},
                                 'child_url': table['url'], 'child_fields': fields,
                                 'parent_url': target, 'parent_fields': parent_fields}
                        if fields != lookup['fields'] or target != targets[1] or parent_fields != parent['key']:
                            conflicts.append(proof)
                            continue
                        if lookup['allow_blank']:
                            columns = table['schema'].get('columns', [])
                            if not isinstance(columns, list):
                                raise MetadataError('LOOKUP_CSVW_INVALID', 'CSVW columns must be an explicit list.')
                            definitions = [col for col in columns if isinstance(col, dict) and col.get('name') in fields]
                            # Explicit false is required in this finite subset;
                            # inherited/default required semantics are not guessed.
                            if any(len([col for col in definitions if col.get('name') == field]) != 1
                                   or not all(col.get('required') is False for col in definitions if col.get('name') == field)
                                   for field in fields):
                                issues.append({'code': 'LOOKUP_NULLABILITY_UNGROUNDED', 'role': role, 'lookup': name,
                                               'message': 'Optional lookup keys require an explicit required:false definition for every child key column.'})
                                continue
                        required = [pointer + '/columnReference', pointer + '/reference/resource', pointer + '/reference/columnReference']
                        if lookup['allow_blank']:
                            required.extend(table['pointer'] + f'/tableSchema/columns/{position}/required'
                                            for position, col in enumerate(columns) if col in definitions)
                        if all(any(entry.get('document_id') == key and 'locator' in entry and covers_pointer(entry, part)
                                   for entry in accepted.get('relations', [])) for part in required):
                            matches.append(proof)
            if conflicts or not matches:
                issues.append({'code': 'LOOKUP_RELATION_CONFLICT' if conflicts else 'LOOKUP_RELATION_UNGROUNDED',
                               'role': role, 'lookup': name, 'parent_role': parent['role'], 'conflicts': conflicts,
                               'message': 'A cited, scoped foreign key or pinned reviewed relation must bind the exact ordered child and parent fields and resource URLs. Field-name coincidence or observed matching values is insufficient.'})
            else:
                decisions.append({'role': role, 'lookup': name, 'parent_role': parent['role'],
                                  'status': 'scoped_foreign_key_bound', 'evidence': matches,
                                  'physical_uniqueness_and_coverage_required': True})
    return {'version': VERSION, 'ok': not issues, 'issues': issues, 'decisions': decisions,
            'limitation': 'Finite CSVW and exact version-pinned reviewed relations. Does not authorize parent count/category/CRS meanings, nullable partial composite keys, unmatched nonblank keys, upload authenticity or publication.'}
