"""Canonical-v2 projection shared by the SDK and independently replayed by QA.

This module has no host, database or network access. Source semantics are an
explicit versioned contract, never hidden state-specific branches.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfoNotFoundError
from .timezone_rules import pinned_zone,canonical_zone,TimeReferenceError
from .date_bounds import MIN_YEAR, MAX_YEAR

import hashlib
import json
import math


class ContractError(ValueError):
    pass


def stable_json(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(",",":"),allow_nan=False)


def field(row,name):
    if not isinstance(name,str):raise ContractError("A source field must be a string")
    if name in row:return row[name]
    value=row
    for part in name.split("."):
        if isinstance(value,dict) and part in value:value=value[part]
        elif isinstance(value,list) and part.isdigit() and int(part)<len(value):value=value[int(part)]
        else:raise ContractError(f"Missing declared source field: {name}")
    return value


def missing(value,contract):
    return value is None or value=="" or value in contract.get("null_values",[])


def source_key(row,fields,contract,allow_blank=False):
    values=[field(row,k) for k in fields]
    if allow_blank and all(missing(v,contract) for v in values):return None
    if any(missing(v,contract) for v in values):raise ContractError("Incomplete source key; no identifiers are invented")
    if any(isinstance(v,(list,dict,bool)) for v in values):raise ContractError("Key components must be scalar source identifiers")
    return stable_json(values)


def number(value,contract):
    if missing(value,contract):return None
    if isinstance(value,bool):raise ContractError("Boolean is not a source count")
    try:n=Decimal(str(value))
    except InvalidOperation:raise ContractError("Count is not a declared nonnegative integer") from None
    if not n.is_finite() or n<0 or n!=n.to_integral_value() or n>2**31-1:
        raise ContractError("Count is outside the supported nonnegative integer range")
    return int(n)


def count_fields(spec):
    if spec is None:return []
    if not isinstance(spec,dict):raise ContractError("Count mapping requires a field or sum_fields object")
    if set(spec)=={"field"} and isinstance(spec['field'],str) and spec['field']:return [spec['field']]
    if set(spec)=={"sum_fields"} and isinstance(spec["sum_fields"],list) and spec["sum_fields"]:
        if len(spec['sum_fields'])>32 or any(not isinstance(k,str) or not k for k in spec['sum_fields']):
            raise ContractError('Count sums require 1–32 explicit source fields')
        if len(set(spec['sum_fields']))!=len(spec['sum_fields']):
            raise ContractError('Count sum repeats a source field')
        return spec['sum_fields']
    raise ContractError("Unsupported count expression; unknown totals cannot be supplied as constants")


def count_value(row,spec,contract):
    fields=count_fields(spec)
    if spec is None:return None
    if 'field' in spec:return number(field(row,fields[0]),contract)
    values=[number(field(row,k),contract) for k in fields]
    # Missing-value sentinels interpret raw cells, not computed totals.
    return None if None in values else number(sum(values),{})


def date_value(row,spec,contract):
    if not isinstance(spec,dict):raise ContractError("Declare a supported occurrence-date specification")
    precision=spec.get("precision","day")
    if precision not in {"day","month","year"}:raise ContractError("Invalid date precision")
    raw=None
    if spec.get("year_field"):
        raw={"year":field(row,spec["year_field"])}
        year=number(raw["year"],contract)
        month=None
        if spec.get("month_field"):
            raw["month"]=field(row,spec["month_field"])
            native=str(raw["month"])
            if spec.get("month_values"):
                if native not in spec["month_values"]:raise ContractError("Unregistered textual month")
                month=int(spec["month_values"][native])
            else:month=number(raw["month"],contract)
        if year is None:raise ContractError("Occurrence year is missing")
        if month is not None and not 1<=month<=12:raise ContractError("Invalid occurrence month")
        value=f"{year:04d}"+(f"-{month:02d}" if month else "")
        precision="month" if month else "year"
    else:
        raw=field(row,spec.get("field"))
        if missing(raw,contract):raise ContractError("Occurrence date is missing")
        kind=spec.get("kind","text")
        if kind in {"epoch_ms","epoch_s"}:
            try:
                parsed=datetime.fromtimestamp(float(raw)/(1000 if kind=="epoch_ms" else 1),tz=timezone.utc)
                if spec.get('timezone'):parsed=parsed.astimezone(pinned_zone(spec['timezone']))
            except (ValueError,TypeError,OverflowError,OSError,ZoneInfoNotFoundError,TimeReferenceError):raise ContractError("Invalid source timestamp or timezone") from None
        else:
            formats=spec.get("formats",[])
            if not isinstance(formats,list) or not formats:raise ContractError("An explicit date format is required")
            interpretations=set()
            for fmt in formats:
                if not isinstance(fmt,str) or len(fmt)>80:raise ContractError("Invalid date format")
                try:interpretations.add(datetime.strptime(str(raw),fmt))
                except ValueError:pass
            if len(interpretations)!=1:raise ContractError("Occurrence date is invalid or has conflicting interpretations")
            parsed=next(iter(interpretations))
        year,month=parsed.year,parsed.month
        value=parsed.date().isoformat()
        if precision=="month":value=value[:7]
        if precision=="year":value=value[:4];month=None
    if not MIN_YEAR<=year<=MAX_YEAR:raise ContractError("Occurrence year is outside the supported contract range")
    return {"year":year,"month":month,"occurrence_date":value,"date_precision":precision,
            "raw_date":raw,"timezone":canonical_zone(spec.get("timezone","UTC")) if spec.get("kind","").startswith("epoch") else spec.get("timezone")}


def geography(row,spec,enabled):
    unavailable={"coordinates":None,"region":None,"geography_status":"unsupported","geography_reason":"No evidence-backed geographic contract"}
    if not isinstance(spec,dict):return unavailable
    region=field(row,spec["region_field"]) if spec.get("region_field") else None
    if not enabled or not spec.get("crs") or not spec.get("x_field") or not spec.get("y_field"):
        return {**unavailable,"region":region,"region_type":spec.get("region_type")}
    x,y=field(row,spec["x_field"]),field(row,spec["y_field"])
    if x in (None,"") or y in (None,"") or x in spec.get('null_values',[]) or y in spec.get('null_values',[]):
        return {**unavailable,"region":region,"geography_status":"unknown","geography_reason":"Source coordinate missing"}
    from .transform_plan import transform, TransformError
    try:
        lon,lat,operation_sha=transform(spec["crs"],x,y)
    except TransformError as exc:raise ContractError(exc.code+': '+str(exc)) from exc
    if not math.isfinite(lon) or not math.isfinite(lat) or not 95<=lon<=170 or not -60<=lat<=-5:
        raise ContractError("Transformed point is outside the broad Australian domain")
    # PROJ on macOS/Linux can differ by a few floating-point ULPs even with
    # identical versions and operations. Canonical WGS84 uses 8 decimal places
    # (~1.1 mm latitude); raw source coordinates remain exact. QA still requires
    # exact equality of the independently recomputed canonical representation.
    return {"coordinates":[round(lon,8),round(lat,8)],"raw_coordinates":[x,y],"crs":spec["crs"],"coordinate_crs":"EPSG:4326",
            "transform_operation_sha256":operation_sha,
            "region":region,"region_type":spec.get("region_type"),"location_precision":spec.get("precision"),
            "geography_status":"available","geography_reason":None}


def project(contract,role,locator,row):
    resources={r["role"]:r for r in contract["resources"]}
    resource=resources[role];grain=resource["grain"];mapping=resource.get("mapping",{})
    key=source_key(row,resource["key"],contract)
    source=contract["source"]
    canonical_id=hashlib.sha256(stable_json([source["source_id"],grain,role,key]).encode()).hexdigest()
    output={"record_id":key,"canonical_id":canonical_id,"source_id":source["source_id"],"jurisdiction":source["jurisdiction"],
            "resource_role":role,"raw_key":json.loads(key),"row_locator":locator,"extensions":row,
            "transformation_version":contract.get("contract_version"),"availability":{}}
    for relation in contract.get("relations",[]):
        if relation["child"]!=role:continue
        parent=resources[relation["parent"]]
        parent_key=source_key(row,relation["fields"],contract,relation.get("allow_blank",False))
        output.setdefault("relations",{})[relation["parent"]]=parent_key
        if parent["grain"]=="crash":output["crash_id"]=parent_key
        if parent["grain"]=="unit":output["unit_record_id"]=parent_key
    if grain in {"crash","observation"}:
        output.update(date_value(row,mapping.get("date"),contract))
        output.update(geography(row,mapping.get("geography"),bool(contract.get("evidence",{}).get("geography"))))
    if grain=="crash":
        severity=mapping.get("severity")
        if severity is None:
            output.update(raw_severity=None,severity='unavailable',severity_label='Unavailable',
                          is_fatal_crash=None,standard_severity=None)
            output['availability']['severity']={'status':'unsupported',
                'reason':contract.get('definitions',{}).get('severity','No supported source severity classification supplied')}
        elif not isinstance(severity,dict):
            raise ContractError('Severity mapping must be an object when supplied')
        else:
            native=field(row,severity["field"]);text="" if native is None else str(native)
            if text not in severity.get("categories",{}):raise ContractError("Unregistered source severity category")
            definition=severity["categories"][text]
            if not isinstance(definition,dict) or not isinstance(definition.get('code'),str) or not definition['code'] or not isinstance(definition.get('label'),str) or not definition['label'] or (definition.get('is_fatal_crash') is not None and type(definition['is_fatal_crash']) is not bool):
                raise ContractError('Severity definitions require a label, code, and boolean or unknown fatal flag')
            output.update(raw_severity=native,severity=definition["code"],severity_label=definition["label"],
                          is_fatal_crash=definition["is_fatal_crash"],standard_severity=definition.get("standard_code"))
        for name in ("fatalities","casualties"):
            output[name]=count_value(row,mapping.get(name),contract)
            output["availability"][name]={"status":"unsupported" if name not in mapping else "unknown" if output[name] is None else "available",
                "reason":contract.get("definitions",{}).get(name) if output[name] is None else None}
        inclusive=contract.get("definitions",{}).get("casualties_includes_fatalities") is True
        if inclusive and output["fatalities"] is not None and output["casualties"] is not None and output["fatalities"]>output["casualties"]:
            raise ContractError("Deaths cannot exceed casualties under the declared inclusive casualty definition")
        if output['is_fatal_crash'] is not None and output['fatalities'] is not None and output['is_fatal_crash'] != (output['fatalities']>0):
            raise ContractError('Fatal crash classification conflicts with known source fatalities')
        for name in ("declared_units","declared_casualties"):
            if name in mapping:output[name]=count_value(row,mapping[name],contract)
    elif grain=="unit":
        output.update(unit_type=field(row,mapping["unit_type"]) if mapping.get("unit_type") else None,count_eligible=True)
        if 'declared_casualties' in mapping:
            output['declared_casualties']=count_value(row,mapping['declared_casualties'],contract)
    elif grain=="casualty":
        injury=mapping.get("injury")
        if injury:
            native=field(row,injury["field"]);text="" if native is None else str(native)
            if text not in injury.get("categories",{}):raise ContractError("Unregistered casualty injury code")
            if injury['categories'][text].get('is_fatal') is not None and type(injury['categories'][text]['is_fatal']) is not bool:
                raise ContractError('Casualty fatal classification must be boolean or unknown')
            output.update(raw_injury=native,is_fatal=injury["categories"][text]["is_fatal"])
        else:output["is_fatal"]=None
    elif grain=="observation":
        output["metrics"]={name:count_value(row,spec,contract) for name,spec in mapping.get("metrics",{}).items()}
        output["dimensions"]={name:field(row,col) for name,col in mapping.get("dimensions",{}).items()}
    else:raise ContractError("Unsupported record grain")
    return output
