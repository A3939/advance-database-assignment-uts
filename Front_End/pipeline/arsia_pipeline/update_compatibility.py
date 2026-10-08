"""Identity and conservative semantic guard for retained-history composition.

Publication passes the previous admitted source contract and invokes this
inside its release transaction before copying a candidate.
"""
import json
import hashlib

from .errors import NeedsInput


def identity_signature(contract):
    """Ignore upload IDs and descriptions, preserve identity field order/types."""
    resources = contract.get("resources", [])
    result = {
        "resources": sorted([{
            "role": resource["role"], "grain": resource["grain"], "key": resource["key"],
        } for resource in resources], key=lambda value: value["role"]),
        "relations": sorted([{
            "child": relation.get("child"), "parent": relation.get("parent"),
            "fields": relation.get("fields"), "allow_blank": bool(relation.get("allow_blank", False)),
        } for relation in contract.get("relations", [])], key=lambda value: json.dumps(value, sort_keys=True)),
    }
    if contract.get('lookup_tables'):
        result['lookup_keys']=sorted([{'role':r['role'],'key':r['key']} for r in contract['lookup_tables']],key=lambda value:value['role'])
        result['lookup_relations']=sorted([{'child':r['role'],'name':lookup['name'],'parent':lookup['parent'],'fields':lookup['fields']}
            for r in resources for lookup in r.get('lookups',[])],key=lambda value:json.dumps(value,sort_keys=True))
    return result


def _stable(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _unordered(values):
    return sorted({_stable(value) for value in values})


def semantics_signature(contract):
    """Preserve meaning-bearing rules; exclude upload IDs and coverage bounds.

    Format order is irrelevant: canonical dates reject multiple interpretations.
    Null markers and sum operands are unordered, but repeated operands are NOT
    discarded. No model-written compatibility/alias declaration authorizes a
    semantic change. New aliases need reviewed equivalence or a full snapshot.
    """
    resources = []
    for resource in contract.get('resources', []):
        mapping = json.loads(_stable(resource.get('mapping', {})))
        date = mapping.get('date')
        if isinstance(date, dict) and isinstance(date.get('formats'), list):
            date['formats'] = _unordered(date['formats'])
        def sums(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == 'sum_fields' and isinstance(item, list):
                        value[key] = sorted(item, key=_stable)
                    else:
                        sums(item)
            elif isinstance(value, list):
                for item in value:
                    sums(item)
        sums(mapping)
        resources.append({'role': resource['role'], 'mapping': mapping})
    result = {'contract_version': contract.get('contract_version'),
            'jurisdiction': _unordered(contract.get('source', {}).get('jurisdiction', [])),
            'resources': sorted(resources, key=lambda value: value['role']),
            'null_values': _unordered(contract.get('null_values', [])),
            'definitions': contract.get('definitions', {})}
    if contract.get('lookup_tables'):
        result['lookup_tables']=sorted([{k:v for k,v in r.items() if k not in {'file_id','table','partitions'}}
                                       for r in contract['lookup_tables']],key=lambda value:value['role'])
        result['lookup_bindings']=sorted([{'role':r['role'],'lookups':r.get('lookups',[])} for r in contract.get('resources',[])],key=lambda value:value['role'])
    return result


def grounded_definitions(admission):
    """Compare host-derived structured definitions, not mutable document IDs.

    This detects known definition drift even if the proposed mapping is the
    same. Equality is not proof that an unobserved publisher change is absent.
    Text-only bindings cannot yet provide structured semantic equivalence.
    """
    grounding = (admission or {}).get('evidence', {}).get('grounding')
    if grounding is None:
        return None
    records = []
    for binding in grounding.get('field_bindings', []):
        facts = []
        for evidence in binding.get('evidence', []):
            facts.append({key: evidence.get(key) for key in ('mode', 'official_field', 'description')})
        records.append({'role': binding['role'], 'claim': binding['claim'],
                        'field': binding['field'], 'definitions': _unordered(facts)})
    return _unordered(records)


def require_compatible_update(previous_contract, candidate_contract, mode, *, previous_admission=None, candidate_admission=None):
    """A full snapshot may rekey; retained-history composition may not."""
    if mode == "snapshot":
        return
    if mode not in {"partition", "incremental"}:
        raise ValueError("Unknown source update mode")
    if not previous_contract or not previous_contract.get("resources"):
        raise NeedsInput("The published source has no admitted identity contract. Supply a complete evidenced snapshot before composing updates.")
    old = identity_signature(previous_contract)
    new = identity_signature(candidate_contract)
    if old != new:
        raise NeedsInput(
            "This update changes resource roles, grains, complete keys or relationships. A partition or incremental merge would mix incompatible record identities. Supply a complete evidenced snapshot to change them.",
            details={"update_mode": mode, "previous_identity": old, "candidate_identity": new,
                     "required_transition": "complete_snapshot"},
        )
    previous = semantics_signature(previous_contract)
    candidate = semantics_signature(candidate_contract)
    changed = [key for key in previous if previous[key] != candidate[key]]
    old_definitions = grounded_definitions(previous_admission)
    new_definitions = grounded_definitions(candidate_admission)
    if old_definitions != new_definitions:
        changed.append('official_field_definitions')
    if changed:
        raise NeedsInput(
            'Semantic compatibility with retained history is not established: date, category, count, geography, missing-value or official field definitions changed. Supply a complete evidenced snapshot to recompute the source, or use a distinct reviewed source version.',
            details={'code': 'UPDATE_SEMANTICS_UNPROVEN', 'update_mode': mode,
                     'changed_components': changed, 'required_transition': 'complete_snapshot_or_distinct_source',
                     'previous_semantics_sha256': hashlib.sha256(_stable(previous).encode()).hexdigest(),
                     'candidate_semantics_sha256': hashlib.sha256(_stable(candidate).encode()).hexdigest(),
                     'limitation': 'A changed definition is unproven compatibility, not automatically a scientific contradiction. No model assertion or newer timestamp overrides this guard.'},
        )
