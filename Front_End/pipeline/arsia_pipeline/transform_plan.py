"""Reviewed, offline 2-D coordinate operations; no generated pipeline execution.

The semantic operation is separate from each installation's dependency receipt:
wheel builds can have different proj.db bytes with identical selected operations.
QA compares operation hashes AND records both runtimes and the executor image.
"""
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import warnings

VERSION = 'offline-transform-plan-v1'
POLICY = 'illustrative-map-best-available-no-ballpark-v1'


class TransformError(ValueError):
    def __init__(self, code, message, *, kind='environment_dependency', details=None):
        super().__init__(message)
        self.code, self.kind, self.details = code, kind, details or {}


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _offline():
    from pyproj import network
    if network.is_network_enabled():
        raise TransformError('TRANSFORM_NETWORK_ENABLED', 'Coordinate operations require offline PROJ; the import cannot download grids.')


def _accuracy(value):
    return float(value) if value is not None and math.isfinite(value) and value >= 0 else None


def _area(value):
    if value is None:
        return None
    return {'name': value.name, 'bounds': list(value.bounds)}


def _contains(area, lon, lat):
    if area is None:
        return True
    west, south, east, north = area['bounds']
    return south <= lat <= north and (west <= lon <= east if west <= east else lon >= west or lon <= east)


def _grid(grid):
    from pyproj import datadir
    # Only packaged, immutable dependencies are supported. No URL, user cache,
    # optional @grid fallback or source-supplied filesystem path is admitted.
    name = grid.short_name
    root = Path(datadir.get_data_dir()).resolve()
    if not isinstance(name, str) or Path(name).name != name or name.startswith('@'):
        raise TransformError('TRANSFORM_RESOURCE_UNSUPPORTED', 'Grid is not a packaged dependency.', details={'grid': str(name)[:120]})
    path = (root / name).resolve()
    if not grid.available or not path.is_relative_to(root) or not path.is_file():
        raise TransformError('TRANSFORM_RESOURCE_MISSING', 'The selected operation requires a grid in the reviewed executor image.', details={'grid': name})
    return {'name': name, 'sha256': _sha(path), 'bytes': path.stat().st_size}


@lru_cache(maxsize=32)
def _selected(source):
    import pyproj
    from pyproj import CRS, Transformer, database, datadir
    from pyproj.transformer import TransformerGroup
    from pyproj.exceptions import CRSError, ProjError
    _offline()
    if not isinstance(source, str) or not source or len(source) > 32768:
        raise TransformError('TRANSFORM_CRS_INVALID', 'CRS must be a bounded authority identifier or WKT.', kind='evidence_conflict')
    # CRS.from_user_input also accepts local files. Restrict the text entrypoint.
    text = source.strip()
    if not (text.upper().startswith(('EPSG:', 'ESRI:', 'OGC:', 'URN:OGC:DEF:CRS:', 'HTTP://WWW.OPENGIS.NET/DEF/CRS/', 'HTTPS://WWW.OPENGIS.NET/DEF/CRS/', 'GEOGCS[', 'PROJCS[', 'GEOGCRS[', 'GEODCRS[', 'PROJCRS['))):
        raise TransformError('TRANSFORM_CRS_UNSUPPORTED', 'Only reviewed authority identifiers and geographic/projected WKT are supported.', kind='unsupported_capability')
    try:
        crs = CRS.from_user_input(source)
    except CRSError as exc:
        raise TransformError('TRANSFORM_CRS_INVALID', 'Declared source CRS cannot be parsed.', kind='evidence_conflict') from exc
    if crs.is_bound or crs.is_compound or len(crs.axis_info) != 2 or not (crs.is_projected or crs.is_geographic):
        raise TransformError('TRANSFORM_DIMENSION_UNSUPPORTED', 'This coordinate plan supports unbound two-dimensional geographic/projected CRS only.', kind='unsupported_capability')
    if 'DYNAMIC[' in crs.to_wkt():
        raise TransformError('TRANSFORM_EPOCH_REQUIRED', 'Dynamic CRS needs an explicit epoch-aware execution plan.', kind='unsupported_capability')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('ignore', UserWarning)
            group = TransformerGroup(crs, 'EPSG:4326', always_xy=True, allow_ballpark=False)
    except ProjError as exc:
        raise TransformError('TRANSFORM_UNAVAILABLE', 'No supported offline coordinate operation could be constructed.') from exc
    if not group.best_available:
        missing = sorted({grid.short_name for op in group.unavailable_operations for grid in op.grids if not grid.available})
        raise TransformError('TRANSFORM_RESOURCE_MISSING', 'The preferred coordinate operation is unavailable; no lower-quality fallback was used.', details={'unavailable_grids': missing[:32]})
    if not group.transformers:
        raise TransformError('TRANSFORM_UNAVAILABLE', 'No non-ballpark operation is available for this CRS.')
    selected = group.transformers[0]
    if any(op.has_ballpark_transformation for op in selected.operations):
        raise TransformError('TRANSFORM_BALLPARK_REFUSED', 'Ballpark transformations are not supported.')
    grids = {grid.short_name: _grid(grid) for op in selected.operations for grid in op.grids}
    operation = {
        'version': VERSION, 'policy': POLICY,
        'source_crs_wkt': crs.to_wkt(), 'target_crs': 'EPSG:4326',
        'declared_source_axes': [{'name': axis.name, 'direction': axis.direction, 'unit': axis.unit_name,
                                  'unit_conversion_factor': axis.unit_conversion_factor} for axis in crs.axis_info],
        'input_order': 'x,y (longitude,latitude or easting,northing)', 'output_order': 'longitude,latitude',
        'definition': selected.definition, 'description': selected.description,
        'operation_id': selected.to_json_dict().get('id'),
        'steps': [{'id': op.to_json_dict().get('id'), 'name': op.name, 'accuracy_metres': _accuracy(op.accuracy),
                   'area_of_use': _area(op.area_of_use)} for op in selected.operations],
        'source_area_of_use': _area(crs.area_of_use), 'area_of_use': _area(selected.area_of_use),
        'accuracy_metres': _accuracy(selected.accuracy), 'ballpark': False,
        'grids': [grids[key] for key in sorted(grids)],
        'accuracy_scope': 'Operation estimate only; source positional accuracy is independent. Unknown stays null; no fixed accuracy guarantee.',
    }
    db = Path(datadir.get_data_dir()) / 'proj.db'
    if not db.is_file():
        raise TransformError('TRANSFORM_RESOURCE_MISSING', 'Installed PROJ database could not be pinned.')
    runtime = {'pyproj': pyproj.__version__, 'proj': pyproj.proj_version_str, 'network': False,
               'database_sha256': _sha(db), 'database_metadata': {
                   key: database.get_database_metadata(key) for key in ('EPSG.VERSION', 'EPSG.DATE', 'PROJ.VERSION', 'DATABASE.LAYOUT.VERSION.MAJOR', 'DATABASE.LAYOUT.VERSION.MINOR')}}
    try:
        # Freeze the selected operation: no per-point silent operation switching.
        transformer = Transformer.from_pipeline(selected.definition)
    except ProjError as exc:
        raise TransformError('TRANSFORM_UNAVAILABLE', 'Selected operation could not be frozen for execution.') from exc
    receipt = {'operation': operation, 'operation_sha256': hashlib.sha256(_json(operation).encode()).hexdigest(), 'runtime': runtime}
    return transformer, receipt


def plan(source):
    _offline()
    return json.loads(_json(_selected(source)[1]))


def transform(source, x, y):
    _offline()
    transformer, receipt = _selected(source)
    try:
        if isinstance(x, bool) or isinstance(y, bool) or not math.isfinite(float(x)) or not math.isfinite(float(y)):
            raise ValueError()
        lon, lat = transformer.transform(float(x), float(y), errcheck=True)
    except Exception as exc:
        raise TransformError('TRANSFORM_COORDINATE_INVALID', 'Source coordinate cannot be transformed using the frozen operation.', kind='source_quality_block') from exc
    op = receipt['operation']
    if not math.isfinite(lon) or not math.isfinite(lat) or not all(_contains(area, lon, lat) for area in [op['source_area_of_use'], op['area_of_use'], *[step['area_of_use'] for step in op['steps']]]):
        raise TransformError('TRANSFORM_OUTSIDE_AREA', 'Coordinate is outside the frozen operation or source CRS area of use.', kind='source_quality_block')
    return lon, lat, receipt['operation_sha256']


def contract_plans(contract):
    return {resource['role']: plan(spec['crs']) for resource in contract.get('resources', [])
            if (spec := resource.get('mapping', {}).get('geography')) and spec.get('crs')}


def compare_plans(host, executor):
    if not isinstance(executor, dict) or host.keys() != executor.keys():
        raise TransformError('TRANSFORM_RUNTIME_MISMATCH', 'Executor coordinate plan receipt is missing or covers different roles.')
    for role, expected in host.items():
        observed = executor[role]
        if not isinstance(observed, dict) or expected['operation'] != observed.get('operation') or expected['operation_sha256'] != observed.get('operation_sha256'):
            raise TransformError('TRANSFORM_RUNTIME_MISMATCH', 'Host and executor selected different coordinate operations.', details={'role': role})
        runtime = observed.get('runtime', {})
        if runtime.get('network') is not False or not isinstance(runtime.get('database_sha256'), str) or len(runtime['database_sha256']) != 64:
            raise TransformError('TRANSFORM_RUNTIME_MISMATCH', 'Executor dependency receipt is incomplete.', details={'role': role})
