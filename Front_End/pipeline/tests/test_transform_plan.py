import copy
import hashlib
import json
import math
from types import SimpleNamespace

import pytest

from arsia_pipeline import transform_plan as plans
from arsia_pipeline.canonical import geography, ContractError


@pytest.fixture(autouse=True)
def clear_plans():
    plans._selected.cache_clear()
    yield
    plans._selected.cache_clear()


def test_wgs84_exact_axis_order_raw_values_and_plan_receipt():
    result = geography({'X':'149.123456789','Y':'-35.123456789'}, {'x_field':'X','y_field':'Y','crs':'EPSG:4326'}, True)
    plan = plans.plan('EPSG:4326')
    assert result['coordinates'] == [149.12345679,-35.12345679]
    assert result['raw_coordinates'] == ['149.123456789','-35.123456789']
    assert result['transform_operation_sha256'] == plan['operation_sha256']
    assert plan['operation']['ballpark'] is False
    assert plan['operation']['accuracy_metres'] == 0
    assert plan['operation']['declared_source_axes'][0]['direction'] == 'north'
    assert plan['operation']['input_order'].startswith('x,y')
    assert plan['runtime']['network'] is False
    assert len(plan['runtime']['database_sha256']) == 64


def test_projected_conversion_against_independent_analytic_mercator():
    x,y = 15000000,-4000000
    lon,lat,sha = plans.transform('EPSG:3857',x,y)
    assert abs(lon-math.degrees(x/6378137)) < 1e-10
    assert abs(lat-math.degrees(2*math.atan(math.exp(y/6378137))-math.pi/2)) < 1e-10
    assert sha == plans.plan('EPSG:3857')['operation_sha256']


def test_sa_projection_origin_and_accuracy_not_rounding_precision():
    lon,lat,_ = plans.transform('EPSG:8059',1000000,2000000)
    assert abs(lon-135)<1e-10 and abs(lat+32)<1e-10
    operation = plans.plan('EPSG:8059')['operation']
    assert operation['accuracy_metres'] == 3
    assert operation['grids'] == []
    assert any(s['accuracy_metres'] is None for s in operation['steps'])
    assert plans._accuracy(-1) is None and plans._accuracy(float('nan')) is None


def test_same_version_different_database_bytes_does_not_mask_operation_change():
    host={'crash':plans.plan('EPSG:4326')}
    executor=copy.deepcopy(host)
    executor['crash']['runtime']['database_sha256']='f'*64
    plans.compare_plans(host,executor)  # Both exact dependency receipts retained.
    executor['crash']['operation']['definition']='proj=noop'
    with pytest.raises(plans.TransformError) as exc:plans.compare_plans(host,executor)
    assert exc.value.code == 'TRANSFORM_RUNTIME_MISMATCH'


def test_network_enablement_is_refused_even_after_plan_cached(monkeypatch):
    import pyproj.network
    plans.plan('EPSG:4326')
    monkeypatch.setattr(pyproj.network,'is_network_enabled',lambda:True)
    with pytest.raises(plans.TransformError) as exc:plans.transform('EPSG:4326',149,-35)
    assert exc.value.code == 'TRANSFORM_NETWORK_ENABLED'


def test_missing_best_grid_does_not_silently_fall_back(monkeypatch):
    import pyproj.transformer
    monkeypatch.setattr(pyproj.transformer,'TransformerGroup',lambda *a,**kw:SimpleNamespace(
        best_available=False,unavailable_operations=[SimpleNamespace(grids=[SimpleNamespace(short_name='required.tif',available=False)])]))
    with pytest.raises(plans.TransformError) as exc:plans.plan('EPSG:4326')
    assert exc.value.code == 'TRANSFORM_RESOURCE_MISSING'
    assert exc.value.details['unavailable_grids'] == ['required.tif']


def test_grid_must_exist_inside_packaged_dependency_root(tmp_path,monkeypatch):
    import pyproj.datadir
    monkeypatch.setattr(pyproj.datadir,'get_data_dir',lambda:str(tmp_path))
    grid=SimpleNamespace(short_name='operation.tif',available=True)
    with pytest.raises(plans.TransformError):plans._grid(grid)
    path=tmp_path/'operation.tif';path.write_bytes(b'immutable fixture grid')
    assert plans._grid(grid)['sha256'] == hashlib.sha256(path.read_bytes()).hexdigest()
    grid.short_name='../operation.tif'
    with pytest.raises(plans.TransformError):plans._grid(grid)


@pytest.mark.parametrize('crs',['/tmp/untrusted.wkt','+proj=longlat +datum=WGS84','EPSG:4979','EPSG:7912'])
def test_paths_and_unsupported_3d_or_epoch_crs_do_not_run(crs):
    with pytest.raises(plans.TransformError):plans.plan(crs)


@pytest.mark.parametrize('point',[(True,-35),('nan',-35),('inf',-35),(149,'not-a-number')])
def test_nonfinite_boolean_invalid_source_coordinates_block(point):
    with pytest.raises(plans.TransformError) as exc:plans.transform('EPSG:4326',*point)
    assert exc.value.code == 'TRANSFORM_COORDINATE_INVALID'


def test_operation_area_and_broad_australian_domain_are_separate():
    assert plans._contains({'bounds':[170,-45,-170,-15]},175,-30)
    assert plans._contains({'bounds':[170,-45,-170,-15]},-175,-30)
    assert not plans._contains({'bounds':[170,-45,-170,-15]},149,-30)
    with pytest.raises(ContractError):geography({'x':0,'y':0},{'x_field':'x','y_field':'y','crs':'EPSG:4326'},True)
    with pytest.raises(plans.TransformError) as exc:plans.transform('EPSG:4326',181,-35)
    assert exc.value.code == 'TRANSFORM_OUTSIDE_AREA'


def test_qa_requires_host_recorded_probe_not_adapter_self_report(tmp_path):
    from test_canonical_v2 import envelope
    from arsia_pipeline.trusted_qa import validate_candidate
    from arsia_pipeline.errors import ValidationFailure
    c,f,run=envelope(tmp_path)
    c['resources'][0]['mapping']['geography']={'x_field':'DEATHS','y_field':'INJURED','crs':'EPSG:4326'}
    run['contract_sha256']=hashlib.sha256(json.dumps(c,sort_keys=True,separators=(',',':')).encode()).hexdigest()
    run['image']='sha256:test'
    run['reported']={'transform_plans':plans.contract_plans(c)}
    with pytest.raises(ValidationFailure) as exc:validate_candidate(run,c,[f],'code-sha',tmp_path)
    assert exc.value.qa[0]['code'] == 'TRANSFORM_RUNTIME_MISMATCH'


def test_probe_never_mounts_adapter_inputs_and_cleans_only_its_container(monkeypatch):
    from arsia_pipeline import isolated_executor as executor
    calls=[]; receipt={'crash':plans.plan('EPSG:4326')}
    def docker(args,timeout=30):
        calls.append(args)
        return SimpleNamespace(returncode=0 if args[0]=='run' else 1,stdout=json.dumps(receipt) if args[0]=='run' else '',stderr='')
    monkeypatch.setattr(executor,'docker',docker)
    executor._probe_transforms.cache_clear()
    actual=executor.probe_transforms('sha256:fixture',{'resources':[{'role':'crash','mapping':{'geography':{'crs':'EPSG:4326'}}}]})
    assert actual == receipt
    command=calls[0]
    assert '--network=none' in command and '--read-only' in command
    assert '--mount' not in command and '--volume' not in command
    assert 'adapter.py' not in ' '.join(command)
    assert calls[-1][0]=='inspect'
    executor._probe_transforms.cache_clear()
