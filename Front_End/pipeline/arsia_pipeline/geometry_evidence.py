"""Geometry-scoped metadata interpretation, without network or model input.

An extent's reference may describe a layer but never overrides a query's
returned geometry. Standard GeoJSON semantics apply to geometry only.
"""
VERSION = 'scoped-geometry-metadata-v1'


def reference_evidence(reference, locator):
    if not isinstance(reference, dict):
        return []
    result = [{'authority': 'ArcGIS WKID', 'code': str(reference[key]), 'metadata_key': key,
               'locator': locator + '/' + key}
              for key in ('wkid', 'latestWkid') if type(reference.get(key)) in (int, str) and str(reference[key]).isdigit()]
    if isinstance(reference.get('wkt'), str) and reference['wkt'].strip():
        result.append({'crs': reference['wkt'], 'authority': 'WKT', 'locator': locator + '/wkt'})
    return result


def geometry_metadata(data):
    if not isinstance(data, dict):
        return False, []
    if data.get('type') == 'FeatureCollection':
        features = data.get('features')
        if not isinstance(features, list) or 'spatialReference' in data or 'geometryType' in data:
            return False, []
        from .intakereaders import _feature_row
        from .errors import ValidationFailure, NeedsInput
        spec = {'json_kind': 'geojson', 'geojson_default_crs': 'OGC:CRS84' if 'crs' not in data else None}
        try:
            for feature in features:
                if not isinstance(feature, dict):
                    return False, []
                row = _feature_row(feature, spec)
                geometry = row['__geometry']
                if geometry is not None and geometry.get('type') != 'Point':
                    return False, []
        except (ValidationFailure, NeedsInput):
            return False, []
        if 'crs' not in data:
            return True, [{'crs': 'OGC:CRS84', 'mode': 'rfc7946_geometry', 'rule_id': 'rfc7946-section-4',
                           'axis_order': ['longitude', 'latitude'], 'locator': '/type'}]
        legacy = data['crs']
        if isinstance(legacy, dict) and legacy.get('type') == 'name' and isinstance(legacy.get('properties'), dict):
            name = legacy['properties'].get('name')
            if isinstance(name, str):
                return True, [{'crs': name, 'mode': 'legacy_geojson_named_crs', 'locator': '/crs/properties/name'}]
        return True, []
    point = data.get('geometryType') == 'esriGeometryPoint'
    references = reference_evidence(data.get('spatialReference'), '/spatialReference')
    if isinstance(data.get('features'), list):
        for index, feature in enumerate(data['features']):
            if not isinstance(feature, dict):
                return False, []
            geom = feature.get('geometry')
            if geom is None:
                continue
            if not isinstance(geom, dict) or any(k in geom for k in ('rings', 'paths', 'points')) or not {'x', 'y'} <= geom.keys():
                return False, []
            point = True
            references.extend(reference_evidence(geom.get('spatialReference'), f'/features/{index}/geometry/spatialReference'))
    elif not references and isinstance(data.get('extent'), dict):
        references = reference_evidence(data['extent'].get('spatialReference'), '/extent/spatialReference')
    return point, references


def geojson_fields(data):
    if not isinstance(data, dict) or data.get('type') != 'FeatureCollection' or not isinstance(data.get('features'), list):
        return None
    return sorted({key for f in data['features'] if isinstance(f, dict) and isinstance(f.get('properties'), dict)
                   for key in f['properties']})


def document_projection(data):
    """Schema and geometry semantics only; never return source feature values."""
    if not isinstance(data, dict) or not isinstance(data.get('features'), list):
        return None
    geojson = data.get('type') == 'FeatureCollection'
    if not geojson and not (data.get('geometryType', '').startswith('esriGeometry') or 'spatialReference' in data):
        return None
    point, references = geometry_metadata(data)
    attribute_key = 'properties' if geojson else 'attributes'
    fields = sorted({field for feature in data['features'] if isinstance(feature, dict)
                     and isinstance(feature.get(attribute_key), dict) for field in feature[attribute_key]})
    return {'projection_version': VERSION, 'type': 'FeatureCollection metadata' if geojson else 'ArcGIS geometry metadata',
            'fields': [{'name': field} for field in fields], 'point_geometry_supported': point,
            'geometry_coordinate_references': references, 'observed_feature_count': len(data['features']),
            'raw_records_returned': 0, 'scope': 'Finite fetched representation; not evidence of full dataset coverage.'}
