"""Source-specific independent acceptance checks; never imported by an Agent.

These intentionally use publisher fields, Python's standard library and explicit
expected meanings, not canonical.project, adapter SDK or the proposed contract.
"""
from collections import Counter
import csv
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import io
import json
import math
from pathlib import Path
import zipfile


def tas(source, candidate):
    raw=json.loads(source.read_bytes(),parse_float=Decimal)
    expected={f['properties']['ID']:f for f in raw['features']}
    assert len(expected)==len(raw['features'])
    labels={'Fatal':('fatal',True),'Serious':('serious',False), 'Minor':('minor',False),
            'First Aid':('first_aid',False),'Property Damage Only':('property_damage_only',False),
            'Not known':('not_known',None)}
    seen=set();groups=Counter();unknown=0;deaths=0
    with candidate.open() as stream:
        for line in stream:
            row=json.loads(line);key,=json.loads(row['record_id']);assert key not in seen;seen.add(key)
            feature=expected[key];props=feature['properties'];coords=feature['geometry']['coordinates']
            actual=datetime.fromtimestamp(props['CRASH_DATE_TIME']/1000,timezone(timedelta(hours=10)))
            assert (row['occurrence_date'],row['year'],row['month'])==(actual.date().isoformat(),actual.year,actual.month)
            assert row['raw_severity']==props['SEVERITY']
            assert (row['severity'],row['is_fatal_crash'])==labels[props['SEVERITY']]
            assert row['fatalities'] is None and row['casualties'] is None
            assert {k:row['extensions'][k] for k in props}==props
            assert row['extensions']['__geometry']['type']==feature['geometry']['type']
            # The streaming reader preserves JSON decimals as exact strings.
            assert [Decimal(str(v)) for v in row['extensions']['__geometry']['coordinates']]==coords
            for value,original in zip(row['coordinates'],coords,strict=True):
                assert abs(Decimal(str(value))-Decimal(str(original)))<=Decimal('.000000005')
            groups[(actual.year,props['SEVERITY'])]+=1
            unknown+=int(props['SEVERITY']=='Not known');deaths+=int(props['SEVERITY']=='Fatal')
    assert seen==expected.keys()
    return {'rows':len(seen),'fatal_crashes':None if unknown else deaths,'known_fatal_crashes':deaths,
        'unknown_fatal_classifications':unknown,'year_severity':[{'year':y,'severity':s,'count':n} for (y,s),n in sorted(groups.items())],
        'raw_fields_preserved':True,'person_counts_unknown':True,
        'scope':'All uploaded features; fixed UTC+10 from the official layer definition. No population-completeness or position-accuracy claim.'}


def _lambert_gda2020(x,y):
    """Independent inverse LCC (GRS80); DIT dictionary specifies these constants.

    This checks the projection math, not a metre-level GDA2020/WGS84 epoch shift.
    The current product uses the reviewed nominal WGS84 operation.
    """
    a=6378137.;f=1/298.257222101;e=math.sqrt(2*f-f*f)
    p1,p2,p0=map(math.radians,(-28,-36,-32))
    def t(p):return math.tan(math.pi/4-p/2)/((1-e*math.sin(p))/(1+e*math.sin(p)))**(e/2)
    def m(p):return math.cos(p)/math.sqrt(1-e*e*math.sin(p)**2)
    n=math.log(m(p1)/m(p2))/math.log(t(p1)/t(p2));F=m(p1)/(n*t(p1)**n)
    r0=a*F*t(p0)**n;xx=x-1000000.;yy=r0-(y-2000000.)
    r=math.copysign(math.hypot(xx,yy),n)
    angle=math.atan2(math.copysign(1,n)*xx,math.copysign(1,n)*yy)
    tt=(r/(a*F))**(1/n);p=math.pi/2-2*math.atan(tt)
    for _ in range(15):p=math.pi/2-2*math.atan(tt*((1-e*math.sin(p))/(1+e*math.sin(p)))**(e/2))
    return 135+math.degrees(angle/n),math.degrees(p)


def sa(data, directory):
    specs={'crash':('_Crash.csv',['REPORT_ID'],'crashes.jsonl'),
           'unit':('_Units.csv',['REPORT_ID','Unit No'],'units.jsonl'),
           'casualty':('_Casualty.csv',['REPORT_ID','UND_UNIT_NUMBER','CASUALTY_NUMBER'],'casualties.jsonl')}
    expected={role:{} for role in specs};lineage={role:{} for role in specs}
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for name in archive.namelist():
            for role,(suffix,fields,_) in specs.items():
                if not name.endswith(suffix):continue
                with archive.open(name) as stream:
                    for index,row in enumerate(csv.DictReader(io.TextIOWrapper(stream,encoding='utf-8-sig')),1):
                        key=tuple(row[k] for k in fields);assert key not in expected[role]
                        expected[role][key]=row;lineage[role][key]='csv:'+str(index)
    counts={};groups=Counter();unit_counts=Counter();person_counts=Counter();fatal_counts=Counter();max_delta=0
    labels={'1: PDO':'property_damage_only','2: MI':'minor_injury','3: SI':'serious_injury','4: Fatal':'fatal'}
    for role,(_,_,filename) in specs.items():
        seen=set()
        with (Path(directory)/filename).open() as stream:
            for line in stream:
                row=json.loads(line);key=tuple(json.loads(row['record_id']));assert key not in seen;seen.add(key)
                raw=expected[role][key];assert row['extensions']==raw
                assert row['raw_key']==list(key) and row['row_locator']==lineage[role][key]
                if role=='crash':
                    dt=datetime.strptime(raw['Crash Date Time'],'%d/%m/%Y %H:%M:%S')
                    assert (row['occurrence_date'],row['year'],row['month'])==(dt.date().isoformat(),dt.year,dt.month)
                    assert row['severity']==labels[raw['CSEF Severity']]
                    assert row['is_fatal_crash']==(raw['CSEF Severity']=='4: Fatal')
                    assert row['fatalities']==int(raw['Total Fats']) and row['casualties']==int(raw['Total Cas'])
                    assert row['declared_units']==int(raw['Total Units'])
                    if raw['ACCLOC_X'] and raw['ACCLOC_Y']:
                        assert row['raw_coordinates']==[raw['ACCLOC_X'],raw['ACCLOC_Y']]
                        lon,lat=_lambert_gda2020(float(raw['ACCLOC_X']),float(raw['ACCLOC_Y']))
                        max_delta=max(max_delta,abs(row['coordinates'][0]-lon),abs(row['coordinates'][1]-lat))
                        assert max_delta<2e-7
                    else:assert row['coordinates'] is None
                    groups[(dt.year,raw['CSEF Severity'])]+=1
                else:
                    assert tuple(json.loads(row['crash_id']))==(raw['REPORT_ID'],)
                    assert (raw['REPORT_ID'],) in expected['crash']
                    if role=='unit':
                        assert row['unit_type']==raw['Unit Type'];assert row['declared_casualties']==int(raw['No Of Cas'])
                        unit_counts[(raw['REPORT_ID'],)]+=1
                    else:
                        parent=(raw['REPORT_ID'],raw['UND_UNIT_NUMBER'])
                        assert tuple(json.loads(row['unit_record_id']))==parent and parent in expected['unit']
                        assert row['is_fatal']==(raw['Injury Extent']=='Fatal')
                        person_counts[(raw['REPORT_ID'],)]+=1;fatal_counts[(raw['REPORT_ID'],)]+=int(raw['Injury Extent']=='Fatal')
        assert seen==expected[role].keys();counts[role]=len(seen)
    for key,row in expected['crash'].items():
        assert int(row['Total Units'])==unit_counts[key]
        assert int(row['Total Cas'])==person_counts[key]
        assert int(row['Total Fats'])==fatal_counts[key]
    return {'rows':counts['crash'],'fatal_crashes':sum(int(r['Total Fats'])>0 for r in expected['crash'].values()),
        'fatalities':sum(fatal_counts.values()),'casualties':sum(person_counts.values()),'grains':counts,
        'year_severity':[{'year':y,'severity':s,'count':n} for (y,s),n in sorted(groups.items())],
        'max_inverse_projection_delta_degrees':max_delta,'raw_fields_preserved':True,'all_parent_relations_verified':True,
        'scope':'Every raw key/date/count/category/relationship, original locator and inverse projected coordinate. Nominal datum operation only; not survey or geodetic epoch accuracy.'}
