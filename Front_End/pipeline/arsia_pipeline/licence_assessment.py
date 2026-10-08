"""Track exact-resource declarations separately from permission to redistribute.

This recognizes structured publisher licence URI fields only. Free text,
dataset-wide inheritance and arbitrary legal interpretation remain unverified.
"""
from .evidence_graph import representation, identity
from .evidence_references import verify_reference
from .metadata_extractors import resolve_locator, MetadataError

VERSION = 'resource-licence-status-v1'
URIS = {'https://creativecommons.org/licenses/by/4.0/': 'CC-BY-4.0',
        'https://creativecommons.org/licenses/by/3.0/au/': 'CC-BY-3.0-AU',
        'https://creativecommons.org/publicdomain/zero/1.0/': 'CC0-1.0'}
FIELDS = {'license_url', 'licence_url', 'license', 'licence'}


def assess(contract, documents=None, graph=None):
    documents, graph = documents or {}, graph or {}
    # Use the host graph's verified closure, never a contract-supplied list.
    authorized = set(graph.get('authorized', set()))
    resources = []
    for resource in contract.get('resources', []):
        declaration = resource.get('licence', {})
        if not isinstance(declaration, dict): declaration = {'text': declaration}
        uri = representation(resource.get('source_url'))
        result = {'role': resource.get('role'), 'resource_url': uri, 'status': 'unknown',
                  'declared_text': declaration.get('text', contract.get('source', {}).get('licence')),
                  'declared_status': declaration.get('status'), 'evidence': [], 'rejected_evidence': [],
                  'processing_scope': 'local_research_only', 'redistribution': 'not_assessed'}
        found = set()
        for entry in declaration.get('evidence', []) if isinstance(declaration.get('evidence', []), list) else []:
            try:
                if not isinstance(entry, dict): raise ValueError('Malformed licence reference')
                doc = documents.get(entry.get('document_id'))
                if not doc or entry.get('document_id') not in authorized or not uri:
                    raise ValueError('Document lacks publisher authority for this resource')
                checked = verify_reference(entry, doc)
                locator = entry['locator']
                pointer = locator.get('pointer', '')
                if locator.get('kind') != 'json-pointer' or pointer.rsplit('/', 1)[-1] not in FIELDS:
                    raise ValueError('A structured publisher licence URI field is required')
                parent = resolve_locator(doc['content_bytes'], doc['sha256'], {'kind': 'json-pointer', 'pointer': pointer.rsplit('/', 1)[0]})
                # Resource records must explicitly name this exact distribution.
                # A direct ArcGIS layer definition can apply to its query exports.
                scoped = isinstance(parent, dict) and representation(parent.get('url')) == uri
                direct = (identity(doc['url']) or {}).get('kind') == 'arcgis_layer' and identity(doc['url']) == identity(uri) and pointer.count('/') == 1
                if not (scoped or direct): raise ValueError('Licence is not bound to this exact resource')
                value = checked['quote']
                if value not in URIS: raise ValueError('Unreviewed licence declaration; preserve for review')
                found.add(value)
                result['evidence'].append({**checked, 'fetched_at': doc.get('fetched_at'), 'resource_url': uri})
            except (KeyError, TypeError, ValueError, MetadataError) as exc:
                result['rejected_evidence'].append(str(exc))
        if len(found) > 1:
            result['status'] = 'conflicting'
        elif len(found) == 1:
            result.update(status='verified', licence_uri=next(iter(found)), licence_id=URIS[next(iter(found))])
        # Explicit restrictions are conservative declarations, never grants.
        if declaration.get('status') in {'restricted', 'conflicting'}:
            result['status'] = declaration['status']
            result['restriction_verified'] = False
        result['limitation'] = ('Publisher declaration and exact resource binding verified; reuse obligations and external redistribution remain unassessed.'
                               if result['status'] == 'verified' else 'No verified grant for this exact resource. Source-wide text does not establish permission.')
        resources.append(result)
    return {'version': VERSION, 'resources': resources, 'scope': 'local_research_only', 'redistribution': 'not_assessed'}
