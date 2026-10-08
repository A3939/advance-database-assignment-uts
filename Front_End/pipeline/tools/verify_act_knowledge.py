"""Independent ACT source profiling and finite RDF/CSV evidence join.

Does not call canonical.project, assign QA admission, or publish data. The
explicit sample paths are read-only; only a fresh report file is created.
"""
import argparse
from collections import Counter
import csv
from datetime import datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import re

from defusedxml import ElementTree


def verify(csv_path,rdf_path,output):
    ids=set();severities=Counter();years=Counter();missing=Counter();dates=[];points={};n=0;deltas=0;maxdelta=Decimal(0)
    with csv_path.open(encoding='utf-8-sig',newline='') as stream:
        for row in csv.DictReader(stream):
            n+=1;ident=row['CRASH_ID'];assert ident and ident not in ids;ids.add(ident)
            day=datetime.strptime(row['CRASH_DATE'],'%d/%m/%Y').date();dates.append(day);years[str(day.year)]+=1
            datetime.strptime(row['CRASH_TIME'],'%I:%M %p')
            severities[row['CRASH_SEVERITY']]+=1
            missing.update(k for k,v in row.items() if not v)
            x,y=Decimal(row['LONGITUDE']),Decimal(row['LATITUDE']);assert x.is_finite() and y.is_finite()
            assert -180<=x<=180 and -90<=y<=90
            values=re.findall(r'-?\d+(?:\.\d+)?',row['Location']);assert len(values)==2
            lat,lon=map(Decimal,values);delta=max(abs(lat-y),abs(lon-x));deltas+=int(delta!=0);maxdelta=max(maxdelta,delta)
            points[ident]=(x,y)
    namespaces={'ds':'https://www.data.act.gov.au/resource/_6jn4-m8rx/',
                'geo':'http://www.w3.org/2003/01/geo/wgs84_pos#'}
    matched=0
    for record in ElementTree.parse(rdf_path).getroot():
        ident=record.findtext('ds:crash_id',namespaces=namespaces)
        assert ident in points
        x=Decimal(record.findtext('ds:x',namespaces=namespaces));y=Decimal(record.findtext('ds:y',namespaces=namespaces))
        lat=Decimal(record.findtext('ds:location/geo:SpatialThing/geo:lat',namespaces=namespaces))
        lon=Decimal(record.findtext('ds:location/geo:SpatialThing/geo:long',namespaces=namespaces))
        assert max(abs(x-lon),abs(y-lat),abs(x-points[ident][0]),abs(y-points[ident][1]))<=Decimal('0.0000001')
        matched+=1
    assert matched==100
    report={'status':'source_profile_passed_not_admission','input_sha256':hashlib.sha256(csv_path.read_bytes()).hexdigest(),
        'rows':n,'unique_crash_ids':len(ids),'severities':dict(severities),'years':dict(sorted(years.items())),
        'observed_coverage':[str(min(dates)),str(max(dates))],'missing_fields':dict(missing),
        'location_nonzero_delta_rows':deltas,'max_axis_delta_degrees':str(maxdelta),
        'rdf_sha256':hashlib.sha256(rdf_path.read_bytes()).hexdigest(),'rdf_sample_matched':matched,
        'claims':['WGS84 vocabulary properties actually occur under this dataset Location, not merely a namespace declaration.',
                  'RDF x/y, geo:long/lat and uploaded coordinates agree for these 100 matched IDs.'],
        'limits':['Finite RDF sample does not establish all-row official certification.',
                  'No administrative boundary or positional accuracy validation.',
                  'Existing trusted QA RDF vocabulary grounding remains unimplemented; no ACT publication.',
                  'Fatal crash count does not establish deaths or casualties.'], 'model_calls':0}
    with output.open('x') as stream:json.dump(report,stream,indent=2)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('csv',type=Path);p.add_argument('rdf',type=Path);p.add_argument('output',type=Path)
    a=p.parse_args();verify(a.csv,a.rdf,a.output)
