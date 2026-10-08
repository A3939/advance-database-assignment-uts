"""Explicit local capability restrictions, never exemptions from source/row QA."""
from .errors import ValidationFailure


def geography_limited(resource):
    limits = resource.get('capability_limits', {})
    if not isinstance(limits, dict) or set(limits) - {'geography'}:
        raise ValidationFailure('Only the reviewed geography restriction is currently supported')
    if 'geography' not in limits:
        return False
    value = limits['geography']
    if (not isinstance(value, dict) or set(value) != {'reason', 'requested'}
            or not isinstance(value['reason'], str) or not 12 <= len(value['reason']) <= 2000
            or type(value['requested']) is not bool):
        raise ValidationFailure('Geography restriction must preserve a reason and whether the capability was requested')
    if resource.get('mapping', {}).get('geography'):
        raise ValidationFailure('A restricted geography cannot also declare a coordinate projection')
    return True


def limitations(contract):
    return [{'role':r['role'], 'capability':'geography', 'status':'unverified',
             'requested':r['capability_limits']['geography']['requested'],
             'reason':r['capability_limits']['geography']['reason'],
             'actual':'Raw fields retained; no coordinate conversion or map capability',
             'target_satisfied':not r['capability_limits']['geography']['requested']}
            for r in contract.get('resources', []) if geography_limited(r)]
