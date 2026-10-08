"""Scoped publisher authority derived from verified bytes, never link proximity.

Research catalogue entries and model-proposed roles are not inputs here.
Only explicit provider distributions authorize external resources. A backlink,
navigation link or shared government host cannot grant authority.
"""
import hashlib
import json
from urllib.parse import urlsplit, urlunsplit, parse_qsl

from .metadata_extractors import extract, MetadataError, GEO
from .source_identity import url_identity

VERSION = 'scoped-evidence-graph-v3'
MAX_DOCUMENTS = 256


def identity(url):
    return url_identity(url, allow_delegated=True, preserve_host=True)


def representation(url):
    """Preserve query scope and exact host/path; ignore only the fragment."""
    if not isinstance(url, str):
        return None
    try:
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password or parsed.port not in (None, 443):
            return None
        return urlunsplit(('https', parsed.netloc.lower(), parsed.path or '/', parsed.query, ''))
    except ValueError:
        return None


def _provider_definition(url):
    """Dataset definitions can explain representations, not assert their extent."""
    p = urlsplit(url)
    query = dict(parse_qsl(p.query, keep_blank_values=True))
    if '/api/views/' in p.path:
        return not query
    if p.path.endswith('/package_show'):
        return set(query) <= {'id'}
    if identity(url) and identity(url)['kind'] == 'arcgis_layer':
        return set(query) <= {'f'}
    return False


def _pointer(*parts):
    return '/' + '/'.join(str(p).replace('~', '~0').replace('/', '~1') for p in parts)


def _packages(value):
    if not isinstance(value, dict):
        return []
    root = value.get('result', value)
    prefix = ('result',) if 'result' in value else ()
    if isinstance(root, dict) and isinstance(root.get('results'), list):
        return [(p, prefix + ('results', i)) for i, p in enumerate(root['results']) if isinstance(p, dict)]
    return [(root, prefix)] if isinstance(root, dict) else []


def _scoped_packages(value, own_url, source_url):
    """Search neighbours never supply fields, links or claims to this dataset."""
    wanted, own = identity(source_url), identity(own_url)
    path = urlsplit(own_url).path.rstrip('/')
    if not (own and own['kind'] == 'ckan' or path.endswith('/3/action/package_search')):
        return []
    host = urlsplit(own_url).hostname
    result = []
    for package, pointer in _packages(value):
        aliases = {package.get(k) for k in ('id', 'name') if isinstance(package.get(k), str)}
        own_match = wanted and wanted['kind'] == 'ckan' and wanted['host'] == host and wanted['dataset'] in aliases
        direct = (own == wanted and _provider_definition(own_url) and len(_packages(value)) == 1
                  and (not aliases or own['dataset'] in aliases))
        distributed = any(isinstance(r, dict) and representation(r.get('url')) == representation(source_url)
                          for r in (package.get('resources', []) if isinstance(package.get('resources'), list) else []))
        if own_match or direct or distributed:
            result.append((package, pointer))
    return result


def _distributions(package, pointer):
    for i, resource in enumerate(package.get('resources', []) if isinstance(package.get('resources'), list) else []):
        if not isinstance(resource, dict):
            continue
        for field in ('url', 'metadata_url'):
            url = representation(resource.get(field))
            if url:
                yield {'target_url': url, 'predicate': 'distributes_resource' if field == 'url' else 'describes_resource',
                       'resource_id': resource.get('id'),
                       'locator': {'kind': 'json-pointer', 'pointer': _pointer(*pointer, 'resources', i, field)}}


def _normative(url):
    # Exact reviewed resources only. This role cannot ground source/field claims.
    if representation(url) in {'https://www.w3.org/2003/01/geo/wgs84_pos', 'https://www.w3.org/2003/01/geo/'}:
        return {'namespace': GEO, 'rule_id': 'rdf-basic-geo-wgs84-v1'}
    return None


def build_graph(source_url, documents, cited_source_ids, *, cited_ids=None, resource_urls=(), check_cancelled=None):
    if len(documents) > MAX_DOCUMENTS:
        raise MetadataError('EVIDENCE_GRAPH_LIMIT', 'Too many documents in one scoped proof.')
    check_cancelled=check_cancelled or (lambda:None)
    cited_ids=set(cited_source_ids) | set(cited_ids or ())
    missing=cited_ids-set(documents)
    if missing:raise MetadataError('EVIDENCE_REFERENCE_MISSING','Referenced documents lack verified host bytes: '+', '.join(sorted(missing)))
    targets={representation(u) for u in [source_url,*resource_urls]}-{None}
    identities=[identity(u) for u in [source_url,*resource_urls] if identity(u) is not None]
    proposed = identity(source_url)
    parse_errors={}
    nodes, edges = {}, []
    for key, doc in sorted(documents.items()):
        check_cancelled()
        url = doc.get('url', '')
        canonical = representation(url)
        if canonical is None:
            continue
        raw = doc.get('content_bytes')
        if raw is None:
            raw = doc.get('text', '').encode('utf-8')
        try:
            facts = extract(raw)
            from .arcgis_query import endpoint, parse, definition
            arcgis=endpoint(url)
            query=parse(url) if arcgis and arcgis['kind']=='query' else None
            layer_definition=definition(url,facts.get('value')) if arcgis and not query else None
            value = facts.get('value')
            host = urlsplit(url).hostname or ''
            publisher = host.endswith('.gov.au') and doc.get('publisher_verified', True) is True
            packages = _scoped_packages(value, url, source_url)
            links = [link for package, pointer in packages for link in _distributions(package, pointer)]
            own_identity = identity(url)
            if own_identity and isinstance(value, dict) and _provider_definition(url):
                if own_identity['kind'] == 'socrata' and 'id' in value and value['id'] != own_identity['dataset']:
                    raise MetadataError('SOURCE_METADATA_ID_CONFLICT', 'Socrata metadata body and endpoint identify different datasets.')
                if own_identity['kind'] == 'arcgis_layer' and 'id' in value and str(value['id']) != own_identity['dataset'].rsplit('/', 1)[-1]:
                    raise MetadataError('SOURCE_METADATA_ID_CONFLICT', 'ArcGIS metadata body and endpoint identify different layers.')
                if own_identity['kind'] == 'ckan':
                    package = value.get('result', value)
                    if isinstance(package, dict):
                        declared = {package[k] for k in ('id', 'name') if isinstance(package.get(k), str)}
                        if declared and own_identity['dataset'] not in declared:
                            raise MetadataError('SOURCE_METADATA_ID_CONFLICT', 'CKAN metadata body and endpoint identify different packages.')
            aliases = []
            for package, _ in packages:
                aliases.extend({'kind': 'ckan', 'host': host, 'dataset': package[k]} for k in ('id', 'name')
                               if isinstance(package.get(k), str) and package.get('resources') is not None)
            source_matches = proposed is not None and (own_identity == proposed or proposed in aliases or
                               any(link['target_url'] == representation(source_url) for link in links))
            # The document must be cited for source identity as well as identifying
            # this specific source; an unrelated government receipt is not an anchor.
            anchor = publisher and key in cited_source_ids and source_matches and (not arcgis or query is not None or layer_definition is not None)
            nodes[key] = {'document_id': key, 'url': canonical, 'document_sha256': facts['document_sha256'],
                          'identity': own_identity, 'publisher': publisher, 'anchor': anchor,
                          'role': 'normative_vocabulary' if _normative(url) else 'discovery_candidate',
                          'normative': _normative(url), 'aliases': aliases, 'distributions': links,
                          'scope': {'dataset': proposed}, 'facts': facts,
                          'receipt': {k: doc.get(k) for k in ('receipt_sha256','requested_url','redirects','fetched_at')},
                          'scoped_packages': packages}
        except MetadataError as exc:
            # Expected bounded document errors only. Cancellation, resource,
            # integrity and programming failures never become research noise.
            parse_errors[key]={'code':exc.code,'message':str(exc)}
            host=urlsplit(url).hostname or ''
            nodes[key]={'document_id':key,'url':canonical,'document_sha256':hashlib.sha256(raw).hexdigest(),
                'identity':identity(url),'publisher':host.endswith('.gov.au') and doc.get('publisher_verified',True) is True,
                'anchor':False,'role':'quarantined_research','normative':_normative(url),'aliases':[],
                'distributions':[],'scope':{'dataset':proposed},'facts':{},'receipt':{},'scoped_packages':[]}
    anchors = {key for key, node in nodes.items() if node['anchor']}
    authorized = set(anchors)
    for key in sorted(anchors):
        nodes[key]['role'] = 'publisher_dataset'
    changed = True
    while changed:
        changed = False
        for child_id, child in nodes.items():
            if child_id in parse_errors or child_id in authorized or child['normative']:
                continue
            for parent_id in sorted(authorized):
                parent = nodes[parent_id]
                # Only actual provider metadata or the same provider dataset's
                # response establishes a representation relation. Neither is
                # treated as evidence of complete rows or snapshot coverage.
                same_dataset = (child['publisher'] and parent['publisher'] and child['identity'] is not None
                                and child['identity']['kind'] in {'socrata', 'ckan', 'arcgis_layer'}
                                and child['identity'] in [parent['identity'], *parent['aliases']])
                if same_dataset and child['identity']['kind']=='arcgis_layer':
                    same_dataset=bool(definition(parent['url'],parent['facts'].get('value')) and definition(child['url'],child['facts'].get('value')))
                link = next((link for link in parent['distributions'] if link['target_url'] == child['url']), None) if parent['publisher'] else None
                from .arcgis_query import relation
                protocol = relation(parent, child) if parent['publisher'] and child['publisher'] else None
                if same_dataset or link or protocol:
                    predicate = link['predicate'] if link else protocol['predicate'] if protocol else 'same_provider_dataset'
                    edges.append({'from': parent_id, 'to': child_id, 'predicate': predicate,
                                  'scope': {'dataset': proposed, 'representation_url': child['url']},
                                  'locator': link['locator'] if link else protocol['locator'] if protocol else None,
                                  'rule_version': protocol['query']['rule_version'] if protocol and 'query' in protocol else VERSION,
                                  'input_documents': [{'document_id':n['document_id'],'sha256':n['document_sha256'],
                                      'final_url':n['url'],**n['receipt']} for n in (parent,child)],
                                  **({'query':protocol['query']} if protocol and 'query' in protocol else {})})
                    authorized.add(child_id)
                    child['role'] = 'delegated_resource' if link else 'publisher_representation'
                    changed = True
                    break
    # A normative definition only becomes usable when an authorized response
    # actually uses that precise vocabulary. Still never grants field authority.
    for parent_id in sorted(authorized):
        namespaces = {p['namespace'] for p in nodes[parent_id]['facts'].get('rdf_points', [])}
        for child_id, node in nodes.items():
            if node['normative'] and node['normative']['namespace'] in namespaces:
                edges.append({'from': parent_id, 'to': child_id, 'predicate': 'uses_vocabulary',
                              'scope': {'dataset': proposed, 'namespace': node['normative']['namespace']},
                              'rule_id': node['normative']['rule_id']})
    # Relevance is host-derived, not the Agent's choice of research labels.
    # Errors deferred above are now promoted if cited, same-resource official,
    # or reached by a typed dependency. Unrelated parse errors grant no authority.
    reasons={k:set() for k in nodes}
    for k,n in nodes.items():
        if k in cited_ids:reasons[k].add('explicit_claim_reference')
        if n['url'] in targets:reasons[k].add('exact_resource_representation')
        if n['publisher'] and n['identity'] is not None and n['identity'] in identities:reasons[k].add('same_resource_official_conflict_candidate')
        if k in authorized:reasons[k].add('authorized_typed_dependency')
    for parent_id in sorted(authorized):
        parent=nodes[parent_id]
        for k,n in nodes.items():
            if parent['publisher'] and any(d['target_url']==n['url'] for d in parent['distributions']):reasons[k].add('explicit_publisher_dependency')
            # A service's explicit membership also makes a malformed child
            # definition relevant before that definition can grant authority.
            from .arcgis_query import endpoint,definition
            a=definition(parent['url'],parent['facts'].get('value'));child=endpoint(n['url'])
            if parent['publisher'] and n['publisher'] and a and a['kind']=='service' and child and child['kind']=='layer' and a['service']==child['service']:
                if any(isinstance(x,dict) and type(x.get('id')) is int and x['id']==child['id'] for x in parent['facts']['value']['layers']):reasons[k].add('service_declares_layer')
    for edge in edges:reasons[edge['to']].add('typed_dependency:'+edge['predicate'])
    selection={'version':VERSION,'documents':[{'document_id':k,'sha256':n['document_sha256'],
        'role':n['role'],'selected':bool(reasons[k]),'reasons':sorted(reasons[k]) or ['unrelated_research_no_authority'],
        'parse_status':'error' if k in parse_errors else 'parsed','error':parse_errors.get(k),
        'blocking':bool(reasons[k]) and k in parse_errors} for k,n in sorted(nodes.items())]}
    for row in selection['documents']:
        if row['blocking']:
            error=parse_errors[row['document_id']];exc=MetadataError(error['code'],error['message'])
            exc.details={'document_id':row['document_id'],'selection':selection,'impact':'required_or_related_evidence_blocked'}
            raise exc
    # Diagnostics for excluded research are separate from admission proof identity.
    selected={k for k in nodes if reasons[k]}
    # Internal facts contain limited source samples. Only proof metadata is
    # returned to the model/UI; callers use facts on the host for validation.
    proof_nodes = [{k: node[k] for k in ('document_id', 'url', 'document_sha256', 'role', 'scope')}
                   for key,node in sorted(nodes.items()) if key in selected]
    proof = {'version': VERSION, 'source_identity': proposed, 'nodes': proof_nodes, 'edges': sorted(edges,key=lambda e:json.dumps(e,sort_keys=True)),
             'source_anchor_documents': sorted(anchors), 'authorized_documents': sorted(authorized)}
    proof['proof_sha256'] = hashlib.sha256(json.dumps(proof, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'proof': proof, 'nodes': nodes, 'authorized': authorized, 'anchors': anchors, 'selection':selection}
