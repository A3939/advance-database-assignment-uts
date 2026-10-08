"""Resource/temporal applicability, separate from publisher authority.

Input nodes are already byte-verified and publisher-connected. A proposal can
select an official resource URL, but cannot invent a scope or temporal fact.
Unscoped legacy documents retain that explicit limitation; timestamps do not
become semantic validity dates. This is a bounded Schema.org JSON-LD subset,
not a generic RDF/JSON-LD processor and never loads remote contexts.
"""
from datetime import date
import re

from .metadata_extractors import MetadataError

VERSION = 'resource-temporal-applicability-v1'
SCHEMA = ('https://schema.org/', 'http://schema.org/')
CONTEXTS = {'https://schema.org', 'https://schema.org/', 'http://schema.org', 'http://schema.org/'}
TYPES = {'Dataset', 'DataDownload', 'CreativeWork', 'DigitalDocument', 'TechArticle', 'DefinedTermSet'}


def _schema_object(value):
    """Expand only exact built-in schema terms; reject context redefinition."""
    if not isinstance(value, dict):
        return None
    context = value.get('@context')
    if context is None:
        if not any(key.startswith(SCHEMA) for key in value):
            return None
        vocab, prefixes = None, {}
    elif isinstance(context, str) and context in CONTEXTS:
        vocab, prefixes = 'https://schema.org/', {}
    elif isinstance(context, dict) and all(isinstance(v, str) for v in context.values()):
        vocab = context.get('@vocab')
        prefixes = {k:v for k,v in context.items() if not k.startswith('@')}
        if vocab is not None and vocab not in SCHEMA or any(v not in SCHEMA for v in prefixes.values()) or any(k.startswith('@') and k!='@vocab' for k in context):
            raise MetadataError('JSONLD_CONTEXT_UNSUPPORTED', 'Evidence scope needs a reviewed context; term redefinitions are not supported.')
    else:
        raise MetadataError('JSONLD_CONTEXT_UNSUPPORTED', 'Evidence scope cannot load or interpret this JSON-LD context.')
    def expand(key):
        if key.startswith('@'):return key
        if key.startswith(SCHEMA):return 'schema:'+key.split('schema.org/',1)[1]
        if ':' in key:
            prefix, local = key.split(':',1)
            return 'schema:'+local if prefix in prefixes else key
        return 'schema:'+key if vocab else key
    result={}
    for key,item in value.items():
        expanded=expand(key)
        if expanded in result:
            raise MetadataError('EVIDENCE_SCOPE_CONFLICT', 'Equivalent metadata properties have multiple declarations.')
        result[expanded]=item
    types=value.get('@type',[])
    types=[types] if isinstance(types,str) else types
    if not isinstance(types,list) or any(not isinstance(item,str) for item in types):
        raise MetadataError('EVIDENCE_SCOPE_INVALID', 'JSON-LD types must be explicit identifiers.')
    if not any(expand(item).removeprefix('schema:') in TYPES and expand(item).startswith('schema:') for item in types):
        if any(key in result for key in ('schema:temporalCoverage','schema:about')):
            raise MetadataError('EVIDENCE_SCOPE_UNSUPPORTED', 'Scope declarations need a supported explicit CreativeWork/Dataset type.')
        return None
    return result


def _urls(value):
    from .evidence_graph import representation
    items=value if isinstance(value,list) else [value]
    urls=[]
    for item in items:
        if isinstance(item,dict) and set(item)=={'@id'}:item=item['@id']
        url=representation(item)
        if url is None:
            raise MetadataError('EVIDENCE_SCOPE_UNSUPPORTED', 'Resource applicability requires exact HTTPS about identifiers.')
        urls.append(url)
    return sorted(set(urls))


def restrictions(node):
    value=node['facts'].get('value')
    from .lookup_evidence import CONTEXT, csvw_tables
    if isinstance(value, dict) and value.get('@context') == CONTEXT:
        return {'temporal':None, 'about':sorted({table['url'] for table in csvw_tables(node)}),
                'document_version':None}
    # Embedded JSON-LD can contain several works, not necessarily this document.
    # It remains discovery until a separate subject-binding rule is implemented.
    scoped=_schema_object(value)
    result={'temporal':None,'about':[], 'document_version':None}
    if not scoped:return result
    if 'schema:about' in scoped:result['about']=_urls(scoped['schema:about'])
    temporal=scoped.get('schema:temporalCoverage')
    if temporal is not None:
        if not isinstance(temporal,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}/\d{4}-\d{2}-\d{2}',temporal):
            raise MetadataError('EVIDENCE_TIME_SCOPE_UNSUPPORTED', 'This policy supports explicit day-resolution ISO start/end intervals; open, coarse or textual periods need a reviewed interpretation.')
        try:
            start,end=map(date.fromisoformat,temporal.split('/'))
            if start>=end:raise ValueError()
        except ValueError as exc:
            raise MetadataError('EVIDENCE_TIME_SCOPE_INVALID', 'Invalid evidence temporal interval.') from exc
        result['temporal']={'from':start.isoformat(),'until_exclusive':end.isoformat(),'declared':temporal}
    version=scoped.get('schema:version')
    if version is not None:
        if type(version) not in (str,int,float) or len(str(version))>256:
            raise MetadataError('EVIDENCE_VERSION_INVALID', 'Document version must be a bounded scalar.')
        # A document version is not automatically a dataset/data-file version.
        result['document_version']=version
    return result


def build_applicability(contract, graph):
    from .evidence_graph import representation
    nodes=graph['nodes']; authorized=graph['authorized']
    source_url=representation(contract.get('source',{}).get('dataset_url'))
    official_resources={link['target_url'] for node in nodes.values() if node['publisher'] and node['document_id'] in authorized
                        for link in node['distributions'] if link['predicate']=='distributes_resource'}
    # metadata_url is an explicit per-resource association, never dataset-wide.
    described={}
    for node in nodes.values():
        if node['document_id'] not in authorized or not node['publisher']:continue
        for package,_ in node['scoped_packages']:
            for resource in package.get('resources',[]) if isinstance(package.get('resources'),list) else []:
                if not isinstance(resource,dict):continue
                metadata=representation(resource.get('metadata_url'));url=representation(resource.get('url'))
                if metadata and url:described.setdefault(metadata,set()).add(url)
    from .arcgis_query import parse, definition
    protocol_resources={nodes[k]['url'] for k in authorized if parse(nodes[k]['url'])}
    facts={key:restrictions(nodes[key]) for key in authorized}
    roles={};issues=[]
    from .table_plan import input_resources
    for resource in input_resources(contract):
        role=resource['role'];context=resource.get('source_url')
        selected=representation(context) if context is not None else None
        from .source_binding import provider_export
        provider_resource=bool(selected and graph.get('anchors') and provider_export(selected,source_url))
        if context is not None and (selected is None or selected not in official_resources|protocol_resources|{source_url} and not provider_resource):
            issues.append({'code':'RESOURCE_IDENTITY_UNBOUND','role':role,'message':'Proposed resource source_url is not an exact publisher-distributed resource or the declared dataset URL.'})
        target=selected or source_url
        coverage=contract.get('source',{}).get('coverage',{})
        try:
            lower=date.fromisoformat(coverage['from']);upper=date.fromisoformat(coverage['to'])
        except (KeyError,TypeError,ValueError):lower=upper=None
        query=parse(target)
        records=[];applicable=[];coordinate_documents=[]
        for key in sorted(authorized):
            node=nodes[key];scope=facts[key];reasons=[]
            bindings=described.get(node['url'],set())
            descriptor=definition(node['url'],node['facts'].get('value'))
            other_query=parse(node['url'])
            if query:
                if descriptor and descriptor['kind']=='layer' and descriptor['layer']!=query['layer']:reasons.append('RESOURCE_SCOPE_MISMATCH')
                if other_query and other_query!=query:reasons.append('REPRESENTATION_SCOPE_MISMATCH')
            if bindings and target not in bindings:
                reasons.append('RESOURCE_SCOPE_MISMATCH' if selected else 'RESOURCE_SCOPE_REQUIRED')
            if scope['about'] and target not in scope['about'] and source_url not in scope['about']:
                reasons.append('RESOURCE_SCOPE_MISMATCH')
            interval=scope['temporal']
            if interval:
                start=date.fromisoformat(interval['from']);end=date.fromisoformat(interval['until_exclusive'])
                if lower is None or upper is None:reasons.append('EVIDENCE_TIME_SCOPE_REQUIRED')
                elif upper<start or lower>=end:reasons.append('EVIDENCE_TIME_SCOPE_DISJOINT')
                elif lower<start or upper>=end:reasons.append('EVIDENCE_TIME_SCOPE_PARTIAL')
            if not reasons:
                applicable.append(key)
                # A verified layer defines fields; its extent CRS describes storage, not a query's output.
                if not query or other_query==query:coordinate_documents.append(key)
            records.append({'document_id':key,'document_sha256':node['document_sha256'],'applies':not reasons,'reasons':reasons,
                            'resource_urls':sorted(bindings),'declared_scope':scope,
                            'scope_status':'restricted' if bindings or scope['about'] or interval else 'legacy_dataset_scope_unspecified'})
        roles[role]={'source_url':target,'selected_resource_explicitly':context is not None,
                     'applicable_documents':applicable,'coordinate_documents':coordinate_documents,'documents':records}
    return {'version':VERSION,'roles':roles,'issues':issues,
            'limitation':'Legacy unscoped documents retain dataset scope. A download date or newer document version never overrides conflicting definitions; temporal coverage is not snapshot completeness or source positional accuracy.'}


def applicable_documents(grounding, role):
    scope=grounding.get('applicability',{}).get('roles',{}).get(role)
    return scope['applicable_documents'] if scope is not None else grounding.get('connected_documents',[])


def schema_subjects(node, source_url=None):
    """Select physical schemas within already publisher-scoped CKAN packages.

    Only an explicit exact resource URL can select an embedded resource. Never
    recursively search nested dictionaries, record attributes or other tables.
    Keep duplicate matching descriptors: their conflicting definitions must be
    reviewed, not hidden by first/last-item selection.
    """
    from .evidence_graph import representation
    packages = node.get('scoped_packages', [])
    if not packages:
        return [(node['facts'].get('value'), [])]
    target = representation(source_url) if source_url is not None else None
    matches = []
    if target is not None:
        for package, path in packages:
            resources = package.get('resources', [])
            if not isinstance(resources, list):continue
            for position, resource in enumerate(resources):
                if isinstance(resource, dict) and representation(resource.get('url')) == target:
                    matches.append((resource, [*path, 'resources', position]))
    return matches or packages


def schema_fields(subject, path):
    """Finite field descriptor shapes with original byte-addressable pointers."""
    from .metadata_extractors import _token
    if not isinstance(subject, dict):return
    prefix = '/' + '/'.join(_token(part) for part in path) if path else ''
    for collection in ('fields', 'columns', 'attributes'):
        items = subject.get(collection, [])
        if not isinstance(items, list):continue
        for index, item in enumerate(items):
            if not isinstance(item, dict):continue
            native = (item.get('db_name') if collection == 'attributes' else
                      item.get('fieldName', item.get('field_name', item.get('name'))))
            if not isinstance(native, str) or not native:continue
            aliases = sorted({value for value in (native, item.get('name'), item.get('alias'))
                              if isinstance(value, str) and value})
            yield native, aliases, item, f'{prefix}/{collection}/{index}'
