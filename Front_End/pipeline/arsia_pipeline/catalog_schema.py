"""Validate research catalogue structure and scoped evidence references.

Validation does not convert research metadata into source admission or licence
permission. External standards require a dataset adoption link, not a suffix.
"""
import re
from urllib.parse import urlsplit

GRAINS = {'crash','unit','person','casualty','observation','dictionary','methodology',
          'spatial_service','location','event_or_condition','calendar_lookup',
          'bundle_crash_unit_casualty','mixed_casualty_and_aggregate_sheets','thematic_grain_unverified'}
STATES = {'NSW','VIC','QLD','SA','WA','TAS','ACT','NT','AU'}


def validate_catalog(value):
    def require(ok, message):
        if not ok:
            raise ValueError('Invalid knowledge catalogue: '+message)
    def url(text):
        require(isinstance(text,str), 'URL must be text')
        parsed=urlsplit(text)
        require(parsed.scheme in {'https','http'} and bool(parsed.hostname) and not parsed.username and not parsed.password, 'invalid public URL')
    require(isinstance(value,dict) and isinstance(value.get('sources'),list) and isinstance(value.get('evidence_index'),dict),'sources/evidence_index types')
    evidence=value['evidence_index']
    for key, item in evidence.items():
        require(isinstance(key,str) and isinstance(item,dict) and item.get('status') in {'fetched','failed'},'evidence status')
        if item['status']=='fetched':
            require(bool(re.fullmatch('[a-f0-9]{64}',str(item.get('sha256','')))),'evidence hash')
            require(type(item.get('size')) is int and item['size']>=0,'evidence size')
            url(item['final_url'])
    sources={}
    for source in value['sources']:
        require(isinstance(source,dict),'source object')
        for field in ('id','publisher','jurisdiction','entry_url','resources','coverage','revision','access','limitations','evidence'):
            require(field in source,'missing source field '+field)
        ident=source['id']
        require(isinstance(ident,str) and ident and ident not in sources,'duplicate or invalid dataset identity')
        sources[ident]=source
        require(isinstance(source['jurisdiction'],list) and bool(source['jurisdiction']) and set(source['jurisdiction'])<=STATES,'jurisdiction')
        require(isinstance(source['resources'],list) and isinstance(source['limitations'],list),'resources/limitations')
        require(isinstance(source['evidence'],list) and all(e in evidence for e in source['evidence']),'source evidence reference')
        url(source['entry_url'])
        resources=set()
        for resource in source['resources']:
            require(isinstance(resource,dict) and isinstance(resource.get('id'),str) and resource['id'] not in resources,'duplicate or invalid resource identity')
            resources.add(resource['id'])
            url(resource.get('url'))
            require(resource.get('grain') in GRAINS,'resource grain')
            require(isinstance(resource.get('format'),str) and bool(resource['format']),'resource format')
            ref=resource.get('evidence')
            if ref:
                require(isinstance(ref,dict) and ref.get('id') in evidence and isinstance(ref.get('locator'),str) and bool(ref['locator']),'resource evidence reference/locator')
            fields=resource.get('fields',[])
            require(isinstance(fields,list),'field list')
            names=[]
            for field in fields:
                require(isinstance(field,dict),'field object')
                name=next((field[k] for k in ('fieldName','db_name','name','id') if field.get(k)),None)
                require(isinstance(name,str),'field identity')
                names.append(name)
            require(len(names)==len(set(names)),'duplicate field identity')
            headers=resource.get('headers',[])
            require(isinstance(headers,list) and all(isinstance(h,str) for h in headers) and len(headers)==len(set(headers)),'physical headers')
            licence=resource.get('licence')
            if licence:
                require(licence.get('status') in {'unknown','declared_unverified','verified','restricted'},'licence status')
                require(licence.get('resource_url')==resource['url'],'licence resource scope')
                require(all(e in evidence for e in licence.get('evidence_ids',[])),'licence evidence reference')
                if licence['status']=='verified':
                    require(bool(licence.get('evidence_ids')) and bool(licence.get('verification')),'verified licence requires scoped verification')
    for link in value.get('standards_links',[]):
        require(link.get('dataset_id') in sources,'standard dataset scope')
        for key in ('publisher_evidence','adoption_evidence','standard_evidence'):
            require(link.get(key) in evidence,'standard adoption reference')
        adoption=evidence[link['adoption_evidence']]
        require(adoption.get('sha256')==link.get('adoption_sha256'),'standard adoption hash')
        source=sources[link['dataset_id']]
        names={h for r in source['resources'] for h in r.get('headers',[])}
        require(link.get('field') in names and set(link.get('field_bindings',{}))<=names,'standard field scope')
    return value
