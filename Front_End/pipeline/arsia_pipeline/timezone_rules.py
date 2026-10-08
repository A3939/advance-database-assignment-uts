"""Pinned CLDR names and TZif semantics shared by host and sandbox.

No network or system timezone fallback. Windows names never imply dataset
applicability: callers must supply the exact official field metadata.
"""
import hashlib
import io
import json
import re
import struct
import zipfile
from datetime import datetime,timezone
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION='arcgis-time-reference-v2'
RULES=Path(__file__).parent/'knowledge/timezones'
MANIFEST_SHA='858195f199422a680b109b91fd8136d9ab824c6cc54d63b9dfadc4fc9cde7af4'

class TimeReferenceError(ValueError):
    def __init__(self,code,message):super().__init__(message);self.code=code

def fail(code,message):raise TimeReferenceError(code,message)

@lru_cache(maxsize=1)
def bundle():
    try:
        raw=(RULES/'manifest.json').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=MANIFEST_SHA:fail('TIMEZONE_RULE_INTEGRITY','Timezone manifest changed; rebuild and independently validate the trusted implementation.')
        manifest=json.loads(raw);data={n:(RULES/n).read_bytes() for n in manifest['files']}
        if any(hashlib.sha256(data[n]).hexdigest()!=v for n,v in manifest['files'].items()):fail('TIMEZONE_RULE_INTEGRITY','Pinned timezone resource hash mismatch.')
        zones=zipfile.ZipFile(io.BytesIO(data['tzdb.zip']))
        names={};aliases={}
        for row in json.loads(data['windowsZones.json'])['supplemental']['windowsZones']['mapTimezones']:
            item=row['mapZone']
            if item['_territory']=='001':
                if item['_other'] in names or ' ' in item['_type']:fail('TIMEZONE_RULE_INTEGRITY','Ambiguous CLDR default mapping.')
                names[item['_other']]=item['_type']
        for line in zones.read('tzdata.zi').decode().splitlines():
            parts=line.split()
            if parts and parts[0]=='L':aliases[parts[2]]=parts[1]
        return manifest,zones,names,aliases
    except (OSError,KeyError,ValueError,zipfile.BadZipFile) as e:
        if isinstance(e,TimeReferenceError):raise
        fail('TIMEZONE_RULE_INTEGRITY','Pinned timezone resources are unavailable or invalid.')

def canonical_zone(name):
    if not isinstance(name,str) or not name or name.startswith('/') or '..' in name.split('/'):fail('ARCGIS_TIME_UNSUPPORTED','Invalid IANA timezone name.')
    _,zones,_,aliases=bundle();seen=set()
    while name in aliases:
        if name in seen:fail('TIMEZONE_RULE_INTEGRITY','Alias cycle in pinned tzdb.')
        seen.add(name);name=aliases[name]
    if name not in zones.namelist() or not zones.read(name).startswith(b'TZif'):fail('ARCGIS_TIME_UNSUPPORTED','Unknown IANA timezone in pinned tzdb.')
    return 'UTC' if name=='Etc/UTC' else name

@lru_cache(maxsize=512)
def pinned_zone(name):
    name=canonical_zone(name);return ZoneInfo.from_file(io.BytesIO(bundle()[1].read(name)),key=name)

def tzif_identity(name):
    name=canonical_zone(name);return {'tzdb_version':bundle()[0]['tzdb_version'],'tzif_sha256':hashlib.sha256(bundle()[1].read(name)).hexdigest(),'iana':name}

def _transitions(raw):
    # RFC8536 TZif v1/v2/v3: inspect every encoded transition, no daily sampling.
    def header(p):
        if raw[p:p+4]!=b'TZif':fail('TIMEZONE_RULE_INTEGRITY','Bad TZif header.')
        return struct.unpack('>6I',raw[p+20:p+44])
    def size(c,width):
        g,s,l,t,k,n=c;return t*(width+1)+k*6+n+l*(width+4)+s+g
    c=header(0);p=0;width=4
    if raw[4:5] in (b'2',b'3',b'4'):p=44+size(c,4);c=header(p);width=8
    count=c[3];start=p+44;end=start+size(c,width)
    ts=struct.unpack('>'+('q' if width==8 else 'l')*count,raw[start:start+count*width]) if count else ()
    return ts,raw[end:].strip(b'\n').decode('ascii')

def _boundary(text,zone):
    try:local=datetime.fromisoformat(text)
    except (ValueError,TypeError):fail('ARCGIS_TIME_UNSUPPORTED','Invalid timezone proof boundary.')
    if local.tzinfo is not None:fail('ARCGIS_TIME_UNSUPPORTED','Expected a local date boundary.')
    matches=set()
    for fold in (0,1):
        aware=local.replace(tzinfo=zone,fold=fold);utc=aware.astimezone(timezone.utc)
        if utc.astimezone(zone).replace(tzinfo=None)==local:matches.add(utc.timestamp())
    if len(matches)!=1:fail('ARCGIS_TIME_UNSUPPORTED','Ambiguous or nonexistent local query boundary.')
    return matches.pop()

def no_dst_proof(name,interval):
    if not isinstance(interval,dict) or not interval.get('from') or not interval.get('until_exclusive'):fail('ARCGIS_TIME_UNSUPPORTED','No-DST equivalence requires a bounded query interval.')
    zone=pinned_zone(name);lo=_boundary(interval['from'],zone);hi=_boundary(interval['until_exclusive'],zone)
    if hi<=lo:fail('ARCGIS_TIME_UNSUPPORTED','Invalid timezone proof interval.')
    transitions,tail=_transitions(bundle()[1].read(canonical_zone(name)))
    fixed_tail=bool(re.fullmatch(r'(?:<[+\-A-Za-z0-9]+>|[A-Za-z]{3,})[+\-]?\d{1,3}(?::\d{1,2}){0,2}',tail))
    if (not transitions or hi>transitions[-1]) and not fixed_tail:fail('ARCGIS_TIME_UNSUPPORTED','No-DST equivalence beyond explicit TZif transitions is unproven for this recurring zone.')
    points=[lo,hi]+[t for t in transitions if lo<=t<=hi]
    if any(datetime.fromtimestamp(t,timezone.utc).astimezone(zone).dst().total_seconds()!=0 for t in points):fail('ARCGIS_DST_CONFLICT','IANA daylight-saving rules conflict with a no-DST declaration in this interval.')
    return {'interval':interval,'utc_bounds':[lo,hi],'checked_transition_points':len(points),'tail':tail,'method':'all_TZif_transitions_plus_endpoints_and_fixed_tail','no_dst_equivalent':True}


def standard_time_equivalence(explicit,mapped,interval):
    """Compare a no-DST IANA declaration with Windows *standard* time.

    A CLDR Windows mapping names a geographic zone with seasonal rules. The
    publisher's respectsDaylightSaving=false changes that Windows meaning.
    Comparing entire TZif byte identities would falsely reject a fixed IANA
    zone representing the declared standard time. Proof is interval scoped;
    no current-offset sampling or state-name exception is used.
    """
    proof=no_dst_proof(explicit,interval)
    zone=pinned_zone(explicit);windows=pinned_zone(mapped)
    lo,hi=proof['utc_bounds'];points={lo,hi}
    transitions,tail=_transitions(bundle()[1].read(canonical_zone(mapped)))
    other,_=_transitions(bundle()[1].read(canonical_zone(explicit)))
    for value in (*transitions,*other):
        if lo<=value<=hi:points.update(t for t in (value-1,value) if lo<=t<=hi)
    for value in points:
        instant=datetime.fromtimestamp(value,timezone.utc)
        old=instant.astimezone(windows);new=instant.astimezone(zone)
        if old.utcoffset()-old.dst()!=new.utcoffset():
            fail('ARCGIS_TIMEZONE_CONFLICT','IANA offset differs from Windows standard time within the declared interval.')
    # TZif v2+ POSIX footer explicitly names the recurring rule's standard
    # offset. Its sign is reversed relative to UTC. This handles future DST
    # transitions without pretending that daily samples prove equivalence.
    if not transitions or hi>transitions[-1]:
        match=re.match(r'^(?:<[+\-A-Za-z0-9]+>|[A-Za-z]{3,})([+\-]?)(\d{1,3})(?::(\d{1,2}))?(?::(\d{1,2}))?(?:$|[A-Za-z<])',tail)
        if not match:fail('ARCGIS_TIME_UNSUPPORTED','Windows standard offset beyond explicit TZif transitions is unproven.')
        sign,hours,minutes,seconds=match.groups()
        if int(hours)>24 or int(minutes or 0)>59 or int(seconds or 0)>59:fail('TIMEZONE_RULE_INTEGRITY','Invalid POSIX standard offset.')
        offset=(1 if sign=='-' else -1)*(int(hours)*3600+int(minutes or 0)*60+int(seconds or 0))
        future=[value for value in points if not transitions or value>=transitions[-1]]
        if any(datetime.fromtimestamp(value,timezone.utc).astimezone(zone).utcoffset().total_seconds()!=offset for value in future):
            fail('ARCGIS_TIMEZONE_CONFLICT','IANA offset differs from the pinned Windows standard-time footer.')
    return {**proof,'windows_iana':mapped,'windows_tzif':tzif_identity(mapped),
            'windows_tail':tail,'comparison_points':len(points),'standard_time_equivalent':True,
            'method':'all_encoded_transition_sides_plus_POSIX_standard_offset_no_DST'}

def resolve_time_reference(metadata,field,service_kind='MapServer',interval=None):
    if service_kind not in {'MapServer','FeatureServer'}:fail('ARCGIS_TIME_UNSUPPORTED','Unreviewed ArcGIS service kind.')
    for flag in ('datesInUnknownTimezone','datesInUnknownTimeZone'):
        if flag in metadata and type(metadata[flag]) is not bool:fail('ARCGIS_TIME_UNSUPPORTED','Invalid Unknown timezone flag.')
        if metadata.get(flag):fail('ARCGIS_TIME_UNSUPPORTED','Unknown service timezone is not supported.')
    edit=metadata.get('editFieldsInfo') or {};ti=metadata.get('timeInfo') or {}
    if field in [edit.get('creationDateField'),edit.get('editDateField'),ti.get('startTimeField'),ti.get('endTimeField')]:fail('ARCGIS_TIME_UNSUPPORTED','Editor-tracking/time-aware field overrides need a reviewed per-field rule.')
    fields=[x for x in metadata.get('fields',[]) if isinstance(x,dict) and x.get('name')==field]
    if fields and (len(fields)!=1 or fields[0].get('type')!='esriFieldTypeDate'):fail('ARCGIS_TIME_UNSUPPORTED','Only ordinary esriFieldTypeDate is supported.')
    ref=metadata.get('dateFieldsTimeReference');proof=None
    if ref is None:zone='UTC';reason='REST_missing_or_null_default_UTC';dst='protocol_UTC_default'
    else:
        if not isinstance(ref,dict):fail('ARCGIS_TIME_UNSUPPORTED','Invalid date time reference.')
        explicit=ref.get('timeZoneIANA');windows=ref.get('timeZone');dst=ref.get('respectsDaylightSaving','unspecified')
        if 'respectsDaylightSaving' in ref and type(dst) is not bool:fail('ARCGIS_TIME_UNSUPPORTED','respectsDaylightSaving must be boolean when present.')
        if 'timeZoneIANA' in ref and (not isinstance(explicit,str) or not explicit):fail('ARCGIS_TIME_UNSUPPORTED','Invalid explicit IANA declaration.')
        mapped=None
        if 'timeZone' in ref:
            if not isinstance(windows,str) or not windows:fail('ARCGIS_TIME_UNSUPPORTED','Invalid Windows timezone declaration.')
            if windows.upper() in ('UTC','ETC/UTC'):mapped='UTC'
            else:mapped=bundle()[2].get(windows)
            if mapped is None:fail('ARCGIS_TIME_UNSUPPORTED','Unknown Windows timezone in pinned CLDR.')
            mapped=canonical_zone(mapped)
        zone=canonical_zone(explicit) if explicit else mapped
        if not zone:fail('ARCGIS_TIME_UNSUPPORTED','No timezone declaration.')
        if explicit and mapped and tzif_identity(zone)['tzif_sha256']!=tzif_identity(mapped)['tzif_sha256']:
            if dst is False:proof=standard_time_equivalence(zone,mapped,interval)
            else:fail('ARCGIS_TIMEZONE_CONFLICT','Windows and IANA declarations disagree in the pinned historical rules.')
        reason='explicit_IANA' if explicit else 'CLDR_001_default_no_territory_inference'
        if proof is None and (dst is False or (dst=='unspecified' and not explicit and zone!='UTC')):proof=no_dst_proof(zone,interval)
    return {'version':VERSION,'iana':zone,'raw_reference':ref,'locator':'/dateFieldsTimeReference','field':field,'field_type':'esriFieldTypeDate',
        'service_kind':service_kind,'interpretation':'UTC_epoch_milliseconds_to_local_date','selection_reason':reason,'respectsDaylightSaving':dst,
        'dst_proof':proof,'mapping':{k:bundle()[0][k] for k in ['cldr_release','cldr_commit','tzdb_version','files']},'tzdb':tzif_identity(zone)}
