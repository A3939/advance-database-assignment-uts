"""Bounded ArcGIS representation proof, used by the existing evidence graph/QA.

No network, dataset names, business mappings or source-specific exceptions.
Protocol references and limits: docs/ARCGIS-REPRESENTATION-SUPPORT.md.
"""
import hashlib
import math
import re
from datetime import date, datetime, timezone, timedelta
from urllib.parse import urlsplit, urlunsplit, parse_qsl
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from .metadata_extractors import MetadataError

VERSION = 'arcgis-bounded-representation-v1'
IDENT = r'[A-Za-z_][A-Za-z0-9_]*'
PARAMS = {'where','outfields','returngeometry','outsr','f','resultoffset','resultrecordcount','orderbyfields','returncountonly'}


def reject(code, message):
    raise MetadataError(code, message)


def object_id_field(metadata, layer_url):
    """Exact OID declaration; MapServer permits the typed-field-only form.

    FeatureServer layer metadata declares objectIdField. A query's
    objectIdFieldName is an additional consistency constraint, not a guess.
    """
    parts = urlsplit(layer_url)
    target = re.search(r'/(FeatureServer|MapServer)/(0|[1-9][0-9]*)/?$', parts.path)
    if not target or parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        reject('ARCGIS_ID_UNSUPPORTED', 'OID discovery requires an explicit ArcGIS layer.')
    fields = metadata.get('fields')
    if not isinstance(fields, list) or any(not isinstance(f, dict) or not isinstance(f.get('name'), str) for f in fields):
        reject('ARCGIS_ID_UNSUPPORTED', 'OID discovery requires named official fields.')
    names = [f['name'] for f in fields]
    if len(set(names)) != len(names):
        reject('ARCGIS_ID_CONFLICT', 'Official fields contain duplicate names.')
    candidates = [f['name'] for f in fields if f.get('type') == 'esriFieldTypeOID']
    if len(candidates) != 1:
        reject('ARCGIS_ID_UNSUPPORTED', 'Exactly one official esriFieldTypeOID field is required.')
    oid = candidates[0]
    if not re.fullmatch(IDENT, oid):
        reject('ARCGIS_ID_UNSUPPORTED', 'OID is not a supported literal field identifier.')
    for key in ('objectIdField', 'objectIdFieldName'):
        if key in metadata and metadata[key] != oid:
            reject('ARCGIS_ID_CONFLICT', key + ' conflicts with the exact typed OID field.')
    if 'objectIdField' not in metadata and target[1] != 'MapServer':
        reject('ARCGIS_ID_UNSUPPORTED', 'FeatureServer layer metadata must declare objectIdField.')
    if metadata.get('OIDFieldContainsHashValue'):
        reject('ARCGIS_ID_UNSUPPORTED', 'Hashed object identifiers are not supported.')
    return oid


def endpoint(url):
    if not isinstance(url, str):return None
    p = urlsplit(url)
    m = re.fullmatch(r'(.+/(?:FeatureServer|MapServer))(?:/(0|[1-9][0-9]*)(/query)?)?', p.path)
    if not m:return None
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.port not in (None,443) or p.fragment or '%' in p.path or '..' in p.path.split('/'):
        reject('ARCGIS_URL_UNSUPPORTED', 'ArcGIS evidence requires an unambiguous HTTPS service/layer/query URL.')
    service = urlunsplit(('https',p.netloc.lower(),m[1],'',''))
    return {'service':service,'layer':service+'/'+m[2] if m[2] is not None else None,
            'id':int(m[2]) if m[2] is not None else None,'kind':'query' if m[3] else 'layer' if m[2] is not None else 'service'}


def parameters(url):
    query=urlsplit(url).query
    if re.search(r'%(?![a-fA-F0-9]{2})',query):reject('ARCGIS_QUERY_UNSUPPORTED','Malformed percent encoding.')
    try:pairs=parse_qsl(query,keep_blank_values=True,strict_parsing=True,encoding='utf-8',errors='strict')
    except (ValueError,UnicodeError):reject('ARCGIS_QUERY_UNSUPPORTED','Malformed query parameters.')
    params={}
    for key,value in pairs:
        key=key.lower()
        if key in params:reject('ARCGIS_QUERY_UNSUPPORTED','Repeated query parameter: '+key)
        if not value or '%' in value:reject('ARCGIS_QUERY_UNSUPPORTED','Empty or double-encoded query parameter.')
        params[key]=value
    return params


def parse(url):
    ep=endpoint(url)
    if not ep or ep['kind']!='query':return None
    p=parameters(url)
    if set(p)-PARAMS:reject('ARCGIS_QUERY_UNSUPPORTED','Unsupported query parameters: '+', '.join(sorted(set(p)-PARAMS)))
    where=p.get('where','');interval=None
    if not re.fullmatch(r'1\s*=\s*1',where):
        m=re.fullmatch(rf"({IDENT})\s*>=\s*DATE\s+'(\d{{4}}-\d{{2}}-\d{{2}})'\s+AND\s+({IDENT})\s*<\s*DATE\s+'(\d{{4}}-\d{{2}}-\d{{2}})'",where,re.I)
        if not m or m[1]!=m[3]:reject('ARCGIS_FILTER_UNSUPPORTED','Supported filters are 1=1 or one field with >= DATE start AND < DATE end.')
        try:
            start,end=date.fromisoformat(m[2]),date.fromisoformat(m[4])
            if start>=end:raise ValueError()
        except ValueError:reject('ARCGIS_FILTER_UNSUPPORTED','Invalid date interval.')
        interval={'field':m[1],'from':m[2],'until_exclusive':m[4]}
    count=p.get('returncountonly','false').lower()
    if count not in ('true','false'):reject('ARCGIS_QUERY_UNSUPPORTED','Invalid returnCountOnly.')
    fmt=p.get('f','').lower()
    if fmt not in ('json','pjson','geojson') or count=='true' and fmt=='geojson':reject('ARCGIS_FORMAT_UNSUPPORTED','Explicit JSON/GeoJSON output required.')
    fields=p.get('outfields','*')
    if fields!='*' and (not fields or any(not re.fullmatch(IDENT,f) for f in fields.split(',')) or len(set(fields.split(',')))!=len(fields.split(','))):
        reject('ARCGIS_PROJECTION_UNSUPPORTED','Projection must be * or distinct literal field names.')
    geometry=p.get('returngeometry','true').lower()
    if geometry not in ('true','false'):reject('ARCGIS_QUERY_UNSUPPORTED','Invalid returnGeometry.')
    sr=p.get('outsr')
    if sr is not None and not re.fullmatch(r'[1-9][0-9]{0,5}',sr):reject('ARCGIS_CRS_UNSUPPORTED','Only numeric output WKID is supported.')
    if fmt=='geojson' and sr not in (None,'4326'):reject('ARCGIS_CRS_UNSUPPORTED','GeoJSON proof supports only RFC7946 output (outSR omitted or4326).')
    order=[]
    for term in p.get('orderbyfields','').split(',') if 'orderbyfields' in p else []:
        m=re.fullmatch(rf'({IDENT})(?:\s+(ASC|DESC))?',term,re.I)
        if not m:reject('ARCGIS_ORDER_UNSUPPORTED','Only literal field ordering is supported.')
        order.append([m[1],(m[2] or 'ASC').upper()])
    numbers={}
    for key,default in [('resultoffset',0),('resultrecordcount',None)]:
        v=p.get(key)
        if v is not None and not re.fullmatch(r'0|[1-9][0-9]*',v):reject('ARCGIS_PAGINATION_UNSUPPORTED','Pagination must use nonnegative integers.')
        numbers[key]=int(v) if v is not None else default
    if numbers['resultoffset']!=0 or numbers['resultrecordcount'] is not None and not 1<=numbers['resultrecordcount']<=20000:
        reject('ARCGIS_PAGINATION_UNSUPPORTED','This rule supports only the first bounded response, at most20000 requested rows; multi-page exports use the existing export verifier.')
    if count=='true' and set(p)-{'where','returncountonly','f'}:reject('ARCGIS_QUERY_UNSUPPORTED','Count evidence accepts only where/returnCountOnly/f.')
    return {**ep,'parameters':p,'interval':interval,'row_filter':interval or {'all':True},'fields':fields,
            'format':fmt,'output_wkid':int(sr) if sr else (4326 if fmt=='geojson' else None),
            'return_geometry':geometry=='true','count_only':count=='true','order':order,**numbers,'rule_version':VERSION}


def definition(url,value):
    ep=endpoint(url)
    if not ep or ep['kind']=='query':return None
    p=parameters(url)
    if set(p)-{'f'} or p.get('f','json').lower() not in ('json','pjson'):return None
    if not isinstance(value,dict):return None
    if ep['kind']=='layer':
        if type(value.get('id')) is not int or value['id']!=ep['id'] or not isinstance(value.get('fields'),list):return None
    elif not isinstance(value.get('layers'),list):return None
    return ep


def relation(parent,child):
    """A protocol edge still requires verified publisher authority in the caller."""
    a=definition(parent['url'],parent['facts'].get('value'));b=definition(child['url'],child['facts'].get('value'))
    qa=parse(parent['url']);qb=parse(child['url'])
    if a and a['kind']=='service' and b and b['kind']=='layer' and a['service']==b['service']:
        for i,layer in enumerate(parent['facts']['value']['layers']):
            if isinstance(layer,dict) and type(layer.get('id')) is int and layer['id']==b['id']:
                return {'predicate':'service_declares_layer','locator':{'kind':'json-pointer','pointer':f'/layers/{i}/id'}}
    # Both directions identify the same layer definition, not a general URL-prefix rule.
    layer,query=(a,qb) if a and a['kind']=='layer' else (b,qa)
    if layer and query and layer['layer']==query['layer']:
        response=child['facts'].get('value') if qb else parent['facts'].get('value')
        if isinstance(response,dict) and (isinstance(response.get('features'),list) or type(response.get('count')) is int):
            return {'predicate':'layer_query_representation' if qb else 'query_layer_definition',
                    'locator':{'kind':'json-pointer','pointer':'/id'},'query':query}
    return None


def time_reference(metadata,field,service_kind='MapServer',interval=None):
    from .timezone_rules import resolve_time_reference,TimeReferenceError
    try:return resolve_time_reference(metadata,field,service_kind,interval)
    except TimeReferenceError as exc:reject(exc.code,str(exc))


def timezone_for(metadata,field,service_kind='MapServer',interval=None):
    return time_reference(metadata,field,service_kind,interval)['iana']


def verify_response(query,metadata,response):
    """Validate one finite response, never award snapshot/deletion authority."""
    if not isinstance(response,dict) or 'error' in response:reject('ARCGIS_RESPONSE_INVALID','Query returned no feature response.')
    rows=response.get('features')
    if query['count_only'] or not isinstance(rows,list) or not rows:reject('ARCGIS_RESPONSE_UNSUPPORTED','Admission requires a nonempty feature response, not counts.')
    if query['format']=='geojson' and response.get('type')!='FeatureCollection':reject('ARCGIS_RESPONSE_INVALID','Format does not match requested GeoJSON.')
    if query['format']!='geojson' and response.get('type')=='FeatureCollection':reject('ARCGIS_RESPONSE_INVALID','Format does not match requested ArcGIS JSON.')
    exceeded=response.get('exceededTransferLimit',False)
    if type(exceeded) is not bool or exceeded:reject('ARCGIS_RESPONSE_TRUNCATED','Response is truncated or has an invalid transfer-limit marker.')
    limit=query['resultrecordcount'] or metadata.get('maxRecordCount')
    if type(limit) is not int or limit<=0:reject('ARCGIS_RESPONSE_UNSUPPORTED','No bounded query or service limit is known.')
    if len(rows)>limit or len(rows)==limit and response.get('exceededTransferLimit') is not False:
        reject('ARCGIS_RESPONSE_TRUNCATED','A full page without explicit end marker cannot prove this export ended.')
    fields={f['name']:f for f in metadata['fields'] if isinstance(f,dict) and isinstance(f.get('name'),str)}
    # Geometry is returned in the feature geometry member, not properties /
    # attributes. Only the protocol type (never a field name) identifies it.
    attributes={name for name, field in fields.items() if field.get('type')!='esriFieldTypeGeometry'}
    projected=attributes if query['fields']=='*' else set(query['fields'].split(','))
    if not projected<=set(fields) or any(term[0] not in fields for term in query['order']):reject('ARCGIS_FIELD_CONFLICT','Query references fields absent from this layer definition.')
    oid=object_id_field(metadata, query['layer'])
    for key in ('objectIdField', 'objectIdFieldName'):
        if key in response and response[key] != oid:
            reject('ARCGIS_ID_CONFLICT', 'Response OID declaration conflicts with layer metadata.')
    interval=query['interval'];zone=None
    if interval:
        f=fields.get(interval['field'],{})
        if f.get('type')!='esriFieldTypeDate':reject('ARCGIS_TIME_UNSUPPORTED','Date range currently supports only esriFieldTypeDate.')
        time_proof=time_reference(metadata,interval['field'],query['service'].rsplit('/',1)[-1],interval)
        zone=time_proof['iana']
    ids=set();dates=[]
    from .timezone_rules import pinned_zone
    from .geometry_evidence import geometry_metadata
    from .geography_review import coordinate_crs_matches
    point,refs=geometry_metadata(response)
    if query['return_geometry'] and not point:reject('ARCGIS_GEOMETRY_UNSUPPORTED','This admission rule requires point geometry.')
    expected=query['output_wkid']
    if expected and refs and not all(coordinate_crs_matches(r,'EPSG:'+str(expected)) for r in refs):reject('ARCGIS_OUTPUT_CRS_CONFLICT','Returned coordinate declarations contradict the requested output CRS.')
    if query['return_geometry'] and not refs:reject('ARCGIS_OUTPUT_CRS_UNBOUND','Response coordinate system is not declared by its format or content.')
    for row in rows:
        if not isinstance(row,dict):reject('ARCGIS_RESPONSE_INVALID','Invalid feature.')
        attrs=row.get('properties' if query['format']=='geojson' else 'attributes')
        if not isinstance(attrs,dict):reject('ARCGIS_RESPONSE_INVALID','Missing feature attributes.')
        key=attrs.get(oid,row.get('id'))
        if type(key) is not int or key in ids:reject('ARCGIS_OBJECT_ID_CONFLICT','Missing, noninteger or duplicate object ID.')
        if oid in attrs and 'id' in row and row['id']!=key:reject('ARCGIS_OBJECT_ID_CONFLICT','GeoJSON feature ID conflicts with the object ID attribute.')
        ids.add(key)
        if not (projected-{oid})<=set(attrs) or set(attrs)-set(fields):reject('ARCGIS_FIELD_CONFLICT','Response fields differ from the requested layer projection.')
        if interval:
            v=attrs.get(interval['field'])
            if type(v) not in (int,float) or not math.isfinite(v):reject('ARCGIS_DATE_INVALID','Date filter field must contain UTC epoch milliseconds.')
            try:d=datetime.fromtimestamp(v/1000,timezone.utc).astimezone(pinned_zone(zone)).date().isoformat()
            except (ValueError,OverflowError,OSError):reject('ARCGIS_DATE_INVALID','Invalid epoch milliseconds.')
            if not interval['from']<=d<interval['until_exclusive']:reject('ARCGIS_RANGE_CONFLICT','Response date falls outside its requested local date interval.')
            dates.append(d)
    return {'row_count':len(rows),'object_id_field':oid,'unique_ids':len(ids),
            'requested_range':interval,'observed_date_range':{'from':min(dates),'to':max(dates)} if dates else None,
            'date_timezone':zone,'time_reference_proof':time_proof if interval else None,'output_wkid':expected,'axis_order':'longitude,latitude' if query['format']=='geojson' else 'x,y',
            'completeness':'bounded_response_only','deletion_authority':False,
            'service_version':metadata.get('currentVersion'),'service_editing_info':metadata.get('editingInfo'),
            'rule_version':VERSION}


def bind_uploads(contract,files,documents,graph,check_cancelled):
    """Only host-verified receipt bytes may bind an uploaded ArcGIS representation."""
    from pathlib import Path
    from .table_plan import input_resources
    # Semantic-only callers cannot claim upload admission; preflight/full QA
    # always supply admitted files and run contract validation first.
    if files is None:return []
    receipts=[]
    admitted={f['id']:f for f in files or []}
    for resource in input_resources(contract):
        check_cancelled()
        url=resource.get('source_url') or contract.get('source',{}).get('dataset_url')
        q=parse(url);ep=endpoint(url)
        if not q and not ep:continue
        role=resource['role'];file=admitted.get(resource.get('file_id'))
        if not q:
            options=[parse(graph['nodes'][k]['url']) for k in graph['authorized']
                     if file and documents[k].get('receipt_sha256') and documents[k].get('sha256')==file.get('sha256')]
            options=[v for v in options if v and v['layer']==ep.get('layer') and not v['count_only']]
            if ep['kind']!='layer' or len(options)!=1:
                reject('ARCGIS_UPLOAD_UNBOUND','A layer/service URL alone does not identify uploaded bytes. Cite the exact registered query representation.')
            q=options[0]
        candidates=[k for k in graph['authorized'] if parse(graph['nodes'][k]['url'])==q and documents[k].get('receipt_sha256')]
        layers=[k for k in graph['authorized'] if (definition(graph['nodes'][k]['url'],graph['nodes'][k]['facts'].get('value')) or {}).get('layer')==q['layer']]
        if not file or not candidates or not layers:reject('ARCGIS_UPLOAD_UNBOUND','Exact query response and matching layer require registered host receipts.')
        sha=hashlib.sha256(Path(file['path']).read_bytes()).hexdigest()
        if sha!=file['sha256']:reject('ARCGIS_UPLOAD_HASH_CONFLICT','Uploaded bytes changed after admission.')
        matching=[k for k in candidates if documents[k]['sha256']==sha]
        representation=None
        if not matching:
            from .representation_binding import compare_json_document
            for key in candidates:
                comparison=compare_json_document(file,documents[key],check_cancelled)
                if comparison['equivalent']:
                    matching.append(key);representation=comparison
        if not matching:reject('ARCGIS_UPLOAD_UNBOUND','Uploaded content is not a complete lossless representation of a verified response for this exact query; historical files need separate provenance.')
        proofs=[]
        for layer in layers:
            metadata=graph['nodes'][layer]['facts']['value']
            proof=verify_response(q,metadata,graph['nodes'][matching[0]]['facts']['value'])
            mapping=resource.get('mapping',{}).get('date',{})
            field=mapping.get('field')
            if field:
                declared=next((f for f in metadata['fields'] if f.get('name')==field),{})
                if declared.get('type')!='esriFieldTypeDate' or mapping.get('kind')!='epoch_ms':reject('ARCGIS_DATE_MAPPING_CONFLICT','ArcGIS Date fields require epoch_ms mapping; other date types need a reviewed rule.')
                from .timezone_rules import canonical_zone
                if canonical_zone(mapping.get('timezone','UTC'))!=timezone_for(metadata,field,q['service'].rsplit('/',1)[-1],q['interval']):reject('ARCGIS_TIMEZONE_CONFLICT','Mapping timezone disagrees with the official field time reference.')
            update=contract.get('update',{})
            # A verified bounded representation can support observed-record
            # analysis under any declared update mode. It grants no completeness
            # or deletion authority: publication checks actual removed membership
            # and retained-history compatibility in its atomic transaction.
            if update.get('mode') not in {'snapshot', 'partition', 'incremental'}:
                reject('ARCGIS_UPDATE_UNSUPPORTED', 'Declare an explicit supported update mode.')

            if q['interval']:
                end=(date.fromisoformat(q['interval']['until_exclusive'])-timedelta(days=1)).isoformat()
                for extent in (contract.get('source',{}).get('coverage',{}),update):
                    if not q['interval']['from']<=extent.get('from','')<=extent.get('to','')<=end:reject('ARCGIS_UPDATE_RANGE_CONFLICT','Declared coverage/update interval exceeds the official query interval.')
            count_checks=[]
            for key in graph['authorized']:
                other=parse(graph['nodes'][key]['url'])
                if other and other['count_only'] and other['layer']==q['layer'] and other['row_filter']==q['row_filter']:
                    count=graph['nodes'][key]['facts'].get('value',{}).get('count')
                    if type(count) is not int or count!=proof['row_count']:reject('ARCGIS_COUNT_CONFLICT','Official count disagrees with the fixed feature response; possible service change/truncation. Do not refetch until counts match.')
                    count_checks.append({'document_id':key,'sha256':documents[key]['sha256'],'fetched_at':documents[key].get('fetched_at'),'count':count})
            proofs.append({**proof,'layer_document':layer,'layer_sha256':documents[layer]['sha256'],'count_cross_checks':count_checks})
        doc=documents[matching[0]]
        receipts.append({'role':role,'file_id':file['id'],'upload_sha256':sha,'response_document':matching[0],
            'predicate':'verified_response_representation_binds_upload' if representation else 'verified_response_bytes_bind_upload',
            'representation_replay':representation,'response_sha256':doc['sha256'],'receipt_sha256':doc['receipt_sha256'],
            'requested_url':doc.get('requested_url'),'final_url':doc['url'],'redirects':doc.get('redirects',[]),
            'fetched_at':doc.get('fetched_at'),'query':q,'proofs':proofs,'rule_version':VERSION,
            'locator':{'kind':'json-pointer','pointer':'/features'},'claim_scope':['physical_fields','geometry','date_representation','bounded_rows']})
    return receipts
