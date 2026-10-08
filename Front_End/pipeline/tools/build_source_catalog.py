"""Build the dated catalogue from bounded, already fetched official receipts.

No network or model calls. Does not download historical data. Original receipts
stay in the supplied research directory; portable evidence objects are deduped.
"""
import argparse
import csv
import json
from pathlib import Path
import zipfile

from arsia_pipeline.source_knowledge import EvidenceStore, VERSION, file_hash


def build(research, output, project):
    output.mkdir(parents=True, exist_ok=True)
    objects = EvidenceStore(output/'evidence')
    evidence, payloads = {}, {}
    for path in sorted(research.glob('fetch-*.json')):
        if path.name == 'fetch-index.json': continue
        key = path.stem[6:]
        receipt = json.loads(path.read_text())
        entry = {k:receipt[k] for k in ('status','requested_url','final_url','fetched_at','sha256','size','etag','last_modified','error') if k in receipt}
        if receipt.get('status') == 'fetched':
            data = Path(receipt['__files'][0]['path']).read_bytes()
            assert objects.put(data) == receipt['sha256']
            entry['object'] = 'evidence/'+receipt['sha256']
            try: payloads[key] = json.loads(data)
            except ValueError: pass
        else: entry['requested_url'] = receipt.get('url',entry.get('requested_url'))
        evidence[key] = entry
    sources = []
    def base(key, state, publisher, url, coverage, revision, limits):
        value = {'id':key, 'jurisdiction':[state], 'publisher':publisher, 'entry_url':url,
                 'official_dataset_id':None, 'resources':[], 'coverage':coverage, 'revision':revision,
                 'access':{'method':'public HTTPS; no credentials', 'licence':None},
                 'limitations':limits, 'evidence':[], 'adapter_status':'research_only',
                 'cross_source_pooling':False}
        sources.append(value); return value
    def ckan(target, key, grain):
        d = payloads[key]['result']; target['official_dataset_id'] = d['id']
        target['evidence'].append(key)
        target['access']['licence'] = {'name':d.get('license_title'), 'url':d.get('license_url'), 'evidence':key}
        target['updated_at'] = d.get('metadata_modified')
        target['publisher_version'] = d.get('version') or None
        for i,r in enumerate(d.get('resources',[])):
            target['resources'].append({'id':r['id'],'name':r.get('name'),'url':r.get('url'),
                'format':r.get('format'),'grain':grain(r),'last_modified':r.get('last_modified'),
                'encoding':None,'delimiter':None,'sheet':None,'header_row':None,
                'evidence':{'id':key,'locator':f'/result/resources/{i}'},
                'fields':r.get('attributes',[])})
        return d
    nsw=base('nsw-crash-data','NSW','Transport for NSW','https://opendata.transport.nsw.gov.au/dataset/nsw-crash-data',
        'Observed catalogue: rolling releases 2016–2020 through 2020–2024.',
        'Annual overlapping five-year releases; latest revision supersedes overlap. Do not append snapshots.',
        ['Only reported eligible crashes; traffic units include pedestrians.', '2019–2023 traffic-unit title conflicts with description ending 2022.',
         'Catalogue XLS labels occur on XLSX URLs; verify file magic.', 'Public person/casualty unit records not established here; request pathway may be needed.',
         'Latitude/Longitude datum not established by inspected NSW manual; no range-based CRS inference.'])
    ckan(nsw,'nsw',lambda r:'dictionary' if r['format']=='PDF' else 'unit' if 'TRAFFIC UNIT' in r['name'] else 'crash')
    nsw['evidence'].append('nsw-dictionary');nsw['adapter_status']='existing_native_pinned_bytes_only'
    vic=base('vic-road-crash','VIC','Department of Transport and Planning','https://opendata.transport.vic.gov.au/dataset/victoria-road-crash-data',
        'Current portal starts 2012; each resource has its own reporting period and refresh date.',
        'Monthly, approximately seven-month lag; provisional fatal records can be changed or removed.',
        ['Legacy DataVic API returned 404; current Transport Victoria package has a different UUID.',
         'Accident/person/vehicle and flat lite export overlap: do not double count.',
         'Current public schema does not remove restrictions on the project’s frozen VIC profile.',
         'Dictionary labels differ from CSV headers; sample evidence required before alias binding.',
         'Seven ancillary tables are separate grains; not all fit current canonical-v2 one-crash-table model.'])
    ckan(vic,'vic-current',lambda r:{'Accident':'crash','Vehicle':'unit','Person':'person','Victorian Road Crash Data':'crash',
        'Node':'location','Accident Location':'location','DCA Chart and Sub DCA Codes':'dictionary'}.get(r['name'],'event_or_condition'))
    vic['evidence'] += ['vic','vic-sample'];vic['adapter_status']='existing_native_pinned_bytes_only'
    qld=base('qld-crash-data','QLD','Department of Transport and Main Roads','https://www.data.qld.gov.au/dataset/crash-data-from-queensland-roads',
        'Location export declares 2001–2025-06-30; PDO ends 2010. Other reportable-data cutoffs differ.',
        'Recent 12 months preliminary; IDs deidentified and may change between releases.',
        ['Current Crash_Longitude/Crash_Latitude explicitly GDA2020; historical GDA94 must not inherit current datum.',
         'Road casualties is a grouped count table, not one row per person (confirmed by five-row API sample).',
         'Do not use Crash_Ref_Number for cross-version incremental updates without stable-key evidence.',
         'Remaining thematic table grains require resource-level field/sample confirmation.'])
    ckan(qld,'qld',lambda r:'crash' if r['name']=='Road crash locations' else 'observation' if r['name']=='Road casualties' else 'thematic_grain_unverified')
    qld['evidence'] += ['qld-sample','qld-casualties-sample'];qld['adapter_status']='existing_native_pinned_bytes_only'
    sa=base('sa-road-crash','SA','Department for Infrastructure and Transport','https://data.sa.gov.au/data/dataset/road-crash-data',
        'Catalogue: annual 2012–2021 plus rolling 2018–2022, 2019–2023, 2020–2024 ZIPs.',
        'Dated as-at exports; dictionary changed to 2025-12-15. PDO scope changed in 2003, 2013, 2016 and 2017.',
        ['Catalogue CSV resources are ZIP archives with crash/unit/casualty tables.',
         'Current dictionary p2 binds ACCLOC_X/Y to EPSG:8059 (GDA2020, metres); earlier dictionaries require separate review.',
         'Road geometry and coding can change; supplied points do not establish positional precision.'])
    ckan(sa,'sa',lambda r:'dictionary' if r['format']=='PDF' else 'bundle_crash_unit_casualty')
    sa['evidence'].append('sa-dictionary');sa['adapter_status']='prior_autonomous_acceptance_requires_fresh_QA'
    wa=base('wa-open-crash','WA','Main Roads Western Australia','https://catalogue.data.wa.gov.au/dataset/mrwa-crash-information-last-5-years-',
        'Catalogue explicitly says 2019–2023 after temporary removal of 2024 records.',
        'Rolling last five calendar years; data may change. Do not infer coverage from title.',
        ['Current CKAN package lists zero resources but delegates dataset hosting to ArcGIS Hub.',
         'OpenData/RoadSafety_DataPortal/MapServer/2 returned a service-not-started error.',
         'CrashMap service is a separate observed resource; its CRS cannot be assigned to all WA files.'])
    d=ckan(wa,'wa',lambda r:'unknown');wa['evidence'] += ['wa-hub','wa-layer']
    wa['resources'].append({'id':'delegated-hub','name':'Official delegated ArcGIS Hub dataset','url':d['data_homepage'],'format':'ArcGIS Hub','grain':'crash','evidence':{'id':'wa','locator':'/result/data_homepage'}})
    wmap=base('wa-crashmap','WA','Main Roads Western Australia','https://gisservices.mainroads.wa.gov.au/arcgis/rest/services/CrashMap/CrashData/MapServer/0',
        'Layer labelled last five years; sample does not establish complete coverage.', 'Live service; object IDs not guaranteed stable across reloads.',
        ['No complete export performed; licence of this exact layer not established from its empty copyright field.',
         'SEVERITY renderer defines 1 Fatal, 2 Hospital, 3 Medical, 4 PDO Major, 5 PDO minor; not counts of deaths.'])
    wmap['evidence']=['wa-crashmap','wa-sample'];wmap['official_dataset_id']='CrashMap/CrashData/MapServer/0'
    tas=base('tas-crash-service','TAS','Department of State Growth','https://data.gov.au/data/dataset/8f7d9792-dde8-4d88-966a-1874c775640f',
        'Public layer says since 1 January 2009; five-row sample is not completeness evidence.',
        'Live service; no historical as-of transaction guarantee.',
        ['Two official catalogue records refer to this service; one lists CC BY 4.0, another licence not specified.',
         'Geometry CRS is 102100/latestWkid 3857, not a declaration about unrelated attributes.',
         'CRASH_DATE_TIME epoch uses published fixed Etc/GMT-10; service says no DST.',
         'Severity coded-value domains absent; additional definition evidence required before new adapter admission.'])
    ckan(tas,'tas-catalogue',lambda r:'spatial_service');tas['evidence'] += ['tas-layer','tas-item','tas-sample','tas-catalogue2']
    treport=base('tas-statistics','TAS','Tasmanian Transport Services','https://www.transport.tas.gov.au/road_safety_and_rules/crash_statistics',
        'Annual fatalities and serious-injury reports discovered for multiple years through 2025.',
        'Annual reports; unpublished details by data request.',
        ['Direct capture returned 403. Official web search result identified PDF/DOCX and request contact; no report table extraction verified.'])
    treport['resources']=[{'id':'annual-reports','url':treport['entry_url'],'format':'HTML/PDF/DOCX','grain':'observation'}];treport['evidence']=['tas']
    act=base('act-road-crash','ACT','Roads ACT, City and Environment Directorate','https://www.data.act.gov.au/Transport/ACT-Road-Crash-Data/6jn4-m8rx',
        'Description says 2015–2025; custom metadata says 2012–current; uploaded file observed 2015-01-01–2026-09-07.',
        'Updated every weeknight; annual historical review may alter records.',
        ['Only AFP Crash Report Form channels; not all ACT accidents.', 'Positions are indicative intersections/midblocks.',
         'Fatal severity counts crashes; deaths and casualty counts unavailable.',
         'Existing trusted QA lacks RDF/WGS84 vocabulary grounding. Research proof chain is not a QA exemption.'])
    d=payloads['act'];act['official_dataset_id']=d['id'];act['access']['licence']={'name':d['licenseId'],'evidence':'act'}
    act['evidence']=['act','w3c'];act['adapter_status']='blocked_CRS_UNGROUNDED'
    act['resources']=[{'id':'6jn4-m8rx','name':d['name'],'url':'https://www.data.act.gov.au/resource/6jn4-m8rx.csv','format':'CSV / Socrata API / RDF','grain':'crash',
        'headers':[c['name'] for c in d['columns'] if not c['fieldName'].startswith(':')],
        'fields':[{k:c.get(k) for k in ('name','fieldName','dataTypeName','description')} for c in d['columns']],
        'encoding':'UTF-8 (uploaded sample verified)','delimiter':',','header_row':1,'sheet':None,
        'key':['CRASH_ID'],'evidence':{'id':'act','locator':'/columns'}}]
    nt=base('nt-statistics','NT','Department of Logistics and Infrastructure','https://roadsafety.nt.gov.au/research-and-statistics',
        'Current road toll and annual reports; NT landing page links historical road toll back to 2011.',
        'Provisional toll and annual statistical reports; exact refresh not verified.',
        ['Portal searches for crash and road safety returned zero packages; not proof that no NT microdata exists.',
         'Direct report-page fetches returned 403; indexed official pages remain discoverable.',
         'No accessible row-level crash/person export or public crash API validated; request eligibility/terms unverified.'])
    nt['resources']=[{'id':'statistics-hub','url':nt['entry_url'],'format':'HTML/PDF','grain':'observation'}];nt['evidence']=['nt','nt-stats','nt-search','nt-road-search']
    old=base('ardd-legacy','AU','BITRE','https://data.gov.au/data/dataset/australian-road-deaths-database',
        'Legacy catalogue resource names end October 2023; not current national release.',
        'Monthly revisions historically; legacy mirror last metadata modification 2023.',
        ['Fatality and fatal-crash files have different row grains.', 'Do not replace current release by stale CKAN mirror.'])
    ckan(old,'ardd-catalogue',lambda r:'dictionary' if r['format']=='PDF' else 'crash' if 'Crashes' in r['name'] else 'casualty' if 'Fatalities' in r['name'] else 'calendar_lookup')
    au=base('ardd-current','AU','Bureau of Infrastructure and Transport Research Economics','https://datahub.roadsafety.gov.au/reporting/monthly-road-deaths',
        '1989–current. Data Hub links August 2026; infrastructure CKAN snapshot lists June 2026.',
        'Monthly, provisional revisions; heavy-vehicle flags quarterly. Separate fatal-crash file discontinued May 2025.',
        ['One row per killed person; Crash ID is not a person primary key.', 'Missing/unknown -9 must stay unknown.',
         'Fatal crash counts require distinct Crash ID using crash-level dimensions; road-user/age slices cannot be naively added.',
         'No geocoordinates in inspected dictionary; geographic categories are not crash points.',
         'Canonical-v2 cannot currently admit standalone casualty-only resources; a validated aggregation/table plan is required.'])
    ckan(au,'ardd-current',lambda r:'casualty' if 'Fatalities' in r['name'] else 'methodology')
    au['evidence'] += ['national-monthly','ardd-dictionary','ardd-discontinued','bitre']
    au['resources'].append({'id':'datahub-aug2026','name':'August 2026 workbook','url':'https://datahub.roadsafety.gov.au/sites/default/files/documents/bitre_fatalities_aug2026.xlsx','format':'XLSX','grain':'mixed_casualty_and_aggregate_sheets','downloaded':False,'evidence':{'id':'national-monthly','locator':'a[href$="bitre_fatalities_aug2026.xlsx"]'}})
    national=base('national-related','AU','Office of Road Safety / BITRE / AIHW','https://www.officeofroadsafety.gov.au/data-hub/data-catalogue',
        'Scope inventory of related national collections; individual historical files not exhaustively reviewed.',
        'Dataset-specific annual/monthly revisions.',
        ['National Crash Dashboard, hospitalisations and trauma registries are distinct populations.',
         'Hospital episodes, persons injured, deaths and crashes cannot be pooled as equivalent measures.',
         'No restricted microdata requested; dashboard underlying row data not verified.'])
    national['evidence']=['national-catalogue']
    national['resources']=[{'id':key,'name':name,'url':url,'format':'reports/dashboard','grain':'observation'} for key,name,url in [
        ('ncd','National Crash Dashboard','https://www.bitre.gov.au/statistics/safety'),
        ('rta','Road Trauma Australia annual summaries','https://www.bitre.gov.au/statistics/safety'),
        ('hospital','Hospitalised injuries from road crashes','https://www.bitre.gov.au/publications/ongoing/hospitalised-injury'),
        ('trauma','Severe injury / trauma registry cases','https://www.bitre.gov.au/publications/ongoing/severe-injury')]]
    # Preserve full field dictionaries and sample schemas separately from the
    # compact source list. API _id is an observation ID, never a source key.
    for source,key,resource_name in [(qld,'qld-sample','Road crash locations'),(qld,'qld-casualties-sample','Road casualties'),(vic,'vic-sample','Accident')]:
        r=next(x for x in source['resources'] if x['name']==resource_name)
        r['headers']=[f['id'] for f in payloads[key]['result']['fields'] if f['id']!='_id']
        r['fields']=payloads[key]['result']['fields'];r['schema_evidence']={'id':key,'locator':'/result/fields'}
        r.update(encoding='CSV bytes not downloaded; API JSON UTF-8',delimiter=None,header_row=1)
    for source,key in [(tas,'tas-layer'),(wmap,'wa-crashmap')]:
        d=payloads[key];source['resources'].append({'id':source['id']+'-layer-0','name':d['name'],
            'url':evidence[key]['requested_url'],'format':'ArcGIS JSON','grain':'crash',
            'fields':d['fields'],'headers':[f['name'] for f in d['fields'] if f['type']!='esriFieldTypeGeometry'],
            'geometry_crs':d['extent']['spatialReference'],'date_reference':d.get('dateFieldsTimeReference'),
            'evidence':{'id':key,'locator':'/fields'}})
    native=json.loads((project/'pipeline/arsia_pipeline/profiles/native-inputs.json').read_text())
    for s,state in [(nsw,'nsw'),(vic,'vic'),(qld,'qld')]:
        s['native_baseline']=[r for r in native['resources'] if r['source_id']=='official_'+state]
    for r in nsw['resources']:
        if '2020-2024' in r['name']:
            role='traffic_unit' if r['grain']=='unit' else 'crash'
            spec=next(x for x in nsw['native_baseline'] if x['resource_role']==role)
            r.update(headers=spec['header'],sheet=spec['sheet'],header_row=1,
                     schema_status='observed local pinned 2020–2024 file; not automatically inherited by later releases',
                     expected_sha256=spec['expected_sha256'],key=['Crash ID','Traffic unit ID'] if role=='traffic_unit' else ['Crash ID'])
    # Reuse the existing SA ZIP bytes by hash, without copying or downloading.
    cases=project/'artifacts/autonomous-imports/source-downloads/source-cases.json'
    if cases.exists():
        f=json.loads(cases.read_text())['cases']['sa']['upload'];assert file_hash(f['path'])==f['sha256']
        with zipfile.ZipFile(f['path']) as z:
            layout=[]
            for n in z.namelist():
                if n.lower().endswith('.csv'):
                    import io
                    with z.open(n) as h: headers=next(csv.reader(io.TextIOWrapper(h,encoding='utf-8-sig')))
                    layout.append({'member':n,'headers':headers,'bytes':z.getinfo(n).file_size})
        sa['representative_archive']={'sha256':f['sha256'],'members':layout,'source':'existing official download; inspected this run'}
    for s in sources:
        s.setdefault('publisher_version',None)
        for r in s['resources']:
            r['parser']={'encoding':r.get('encoding'),'delimiter':r.get('delimiter'),'sheet':r.get('sheet'),
                         'header_row':r.get('header_row'),'archive':'ZIP' if (r.get('url') or '').endswith('.zip') else None,
                         'status':'specified values observed or explicitly qualified; null means unverified/not applicable'}
    rdf_path=project/'artifacts/act-crs-diagnosis-20261001/official-sample.rdf'
    rdf_hash=objects.put(rdf_path.read_bytes())
    evidence['act-rdf-prior']={'status':'fetched','requested_url':'https://www.data.act.gov.au/resource/6jn4-m8rx.rdf?$limit=100&$order=crash_id',
        'final_url':'https://www.data.act.gov.au/resource/6jn4-m8rx.rdf?$limit=100&$order=crash_id',
        'sha256':rdf_hash,'size':rdf_path.stat().st_size,'object':'evidence/'+rdf_hash,
        'provenance':'Reused saved official response from prior ACT diagnosis, rehashed this run; not refetched.'}
    act['evidence'].append('act-rdf-prior')
    result={'schema_version':VERSION,'researched_at':'2026-10-01/2026-10-02 Australia/Sydney',
        'scope':'Publicly discoverable official sources; bounded metadata and samples; not exhaustive history.',
        'sources':sources,'evidence_index':evidence,
        'standards_links':[{'dataset_id':'act-road-crash','field':'Location','field_bindings':{'LONGITUDE':'x','LATITUDE':'y'},
            'publisher_evidence':'act','publisher_locator':'/columns',
            'adoption_evidence':'act-rdf-prior',
            'adoption_sha256':file_hash(project/'artifacts/act-crs-diagnosis-20261001/official-sample.rdf'),
            'namespace':'http://www.w3.org/2003/01/geo/wgs84_pos#','properties':['lat','long'],
            'standard_evidence':'w3c','role':'vocabulary_definition_not_dataset_authority',
            'status':'research_chain_only_not_implemented_in_trusted_QA','sample_rows':100,'sample_not_full_proof':True}]}
    (output/'catalog.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'sources':len(sources),'resources':sum(len(s['resources']) for s in sources),
                      'evidence':len(evidence),'unique_bytes':sum(p.stat().st_size for p in objects.root.iterdir())}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--research',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();build(a.research,a.output,Path(__file__).resolve().parents[2])
