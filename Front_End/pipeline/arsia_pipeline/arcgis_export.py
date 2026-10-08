"""Preserve a query page's geometry scope when streaming a derived export.

A layer extent cannot relabel explicit returned geometry. Page-level references
are inherited by each geometry before the page envelope is removed. References
on individual geometries remain authoritative there. QA subsequently decides
whether the observed references can share one supported transformation plan.
"""
from collections import Counter

from .errors import NeedsInput, UnsupportedCapability, ValidationFailure
from .geometry_evidence import reference_evidence

VERSION = 'arcgis-page-geometry-preservation-v1'


def export_prefix(metadata, oid):
    return {'objectIdFieldName': oid, 'geometryType': metadata.get('geometryType'),
            'dateFieldsTimeReference': metadata.get('dateFieldsTimeReference'), 'fields': metadata.get('fields', []),
            **{key: metadata[key] for key in ('hasZ', 'hasM') if key in metadata}}


def spatial_reference(value):
    if value is None:
        return None
    if not isinstance(value, dict) or not reference_evidence(value, ''):
        raise NeedsInput('ArcGIS geometry has no supported explicit spatial-reference definition.', [],
                         {'code': 'ARCGIS_GEOMETRY_REFERENCE_MISSING'})
    return value


def preserve_page(metadata, page, *, requested_reference=None):
    """Return bounded page features with inherited geometry metadata made local.

    ``requested_reference`` must be the outSR actually sent by the trusted
    fetcher, never an inferred extent or a model assertion. Missing response
    references may use that explicit request; absent both, stop without guessing.
    Does not reinterpret coordinate numbers or decode quantized responses.
    """
    if page.get('transform') is not None:
        raise UnsupportedCapability('ARCGIS_QUANTIZED_GEOMETRY_UNSUPPORTED',
                                    'ArcGIS query returned a quantization transform; its coordinates need a reviewed decoder.')
    if page.get('geometryType') and metadata.get('geometryType') and page['geometryType'] != metadata['geometryType']:
        raise ValidationFailure('ArcGIS query geometry type differs from the selected layer metadata.',
                                details={'code': 'ARCGIS_GEOMETRY_TYPE_CONFLICT'})
    if 'dateFieldsTimeReference' in page and page['dateFieldsTimeReference'] != metadata.get('dateFieldsTimeReference'):
        raise ValidationFailure('ArcGIS query date reference differs from the selected layer metadata.',
                                details={'code': 'ARCGIS_DATE_REFERENCE_CONFLICT'})
    reference = spatial_reference(page.get('spatialReference'))
    fallback = spatial_reference(requested_reference) if requested_reference is not None else None
    features = page.get('features')
    if not isinstance(features, list):
        raise ValidationFailure('ArcGIS query features must be a list.')
    result, origins = [], Counter()
    for feature in features:
        if not isinstance(feature, dict) or not isinstance(feature.get('attributes'), dict):
            raise ValidationFailure('ArcGIS query contains an invalid feature or attribute object.')
        geometry = feature.get('geometry')
        if geometry is None:
            result.append(feature); origins['null_geometry'] += 1
            continue
        if not isinstance(geometry, dict):
            raise ValidationFailure('ArcGIS query contains an invalid geometry object.')
        if geometry.get('transform') is not None:
            raise UnsupportedCapability('ARCGIS_QUANTIZED_GEOMETRY_UNSUPPORTED',
                                        'ArcGIS geometry includes a quantization transform requiring a reviewed decoder.')
        local = spatial_reference(geometry.get('spatialReference'))
        chosen = local or reference or fallback
        if chosen is None:
            raise NeedsInput('ArcGIS returned geometry without a reference or an explicit outSR request; a layer extent alone cannot identify this response.', [],
                             {'code': 'ARCGIS_GEOMETRY_REFERENCE_MISSING'})
        origin = 'feature' if local is not None else 'page' if reference is not None else 'requested_outSR'
        origins[origin] += 1
        result.append(feature if local is not None else {**feature, 'geometry': {**geometry, 'spatialReference': chosen}})
    return result, {'version': VERSION, 'reference_origins': dict(origins),
                    'coordinates_modified': False, 'page_spatial_reference': reference,
                    'requested_outSR': fallback}
