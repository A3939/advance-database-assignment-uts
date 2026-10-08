import copy
import hashlib
import json

import pytest

from arsia_pipeline.evidence_graph import build_graph
from arsia_pipeline.metadata_extractors import GEO, RDF
from arsia_pipeline.rdf_geography import prove_coordinates, CoordinateBindingError
from arsia_pipeline.evidence_grounding import ground_contract


def fixture(tmp_path, *, dataset='wxyz-9876', prefix='geo', raw=None):
    host = 'roads.example.gov.au'
    ns = 'https://' + host + '/resource/_' + dataset + '/'
    source = 'https://' + host + '/resource/' + dataset
    fields = [('event_id', 'EVENT'), ('date', 'Date'), ('east', 'Lon'), ('north', 'Lat'), ('place', 'Position')]
    metadata = {'id': dataset, 'columns': [{'fieldName': f, 'name': name,
                'dataTypeName': 'location' if f == 'place' else 'text'} for f, name in fields]}
    rdf = f'''<r:RDF xmlns:r="{RDF}" xmlns:{prefix}="{GEO}" xmlns:d="{ns}"
      xmlns:b="https://{host}/resource/" xmlns:s="http://www.w3.org/2000/01/rdf-schema#">
    <b:_{dataset} r:about="{ns}row-a1_b2"><s:member r:resource="{ns[:-1]}"/>
    <d:event_id>001</d:event_id><d:east>149.1</d:east><d:north>-35.2</d:north>
    <d:place><{prefix}:Point><{prefix}:long>149.1</{prefix}:long><{prefix}:lat>-35.2</{prefix}:lat></{prefix}:Point></d:place></b:_{dataset}></r:RDF>'''
    docs = {'schema': {'url': f'https://{host}/api/views/{dataset}.json', 'content_bytes': json.dumps(metadata).encode(), 'text': json.dumps(metadata)},
            'rdf': {'url': source + '.rdf?$limit=1', 'content_bytes': rdf.encode(), 'text': rdf}}
    path = tmp_path / 'renamed.data'
    path.write_text(raw or 'EVENT,Date,Lon,Lat,Position\n001,2024-01-01,149.100000000004,-35.2,"(-35.2, 149.1)"\n002,2024-01-02,150,-36,"(-36, 150)"\n')
    file = {'id': 'upload', 'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    resource = {'role': 'event', 'file_id': 'upload', 'grain': 'crash', 'key': ['EVENT'],
                'mapping': {'date': {'field': 'Date'}, 'geography': {'x_field': 'Lon', 'y_field': 'Lat', 'crs': 'EPSG:4326'}}}
    contract = {'source': {'dataset_url': source}, 'resources': [resource]}
    accepted = {name: [{'document_id': 'schema'}] for name in ('source_identity', 'grain', 'date', 'geography')}
    return contract, [file], docs, accepted


@pytest.mark.parametrize('dataset,prefix', [('wxyz-9876', 'geo'), ('abcd-2468', 'xyz')])
def test_protocol_rule_is_not_an_act_or_prefix_exception(tmp_path, dataset, prefix):
    contract, files, docs, accepted = fixture(tmp_path, dataset=dataset, prefix=prefix)
    graph = build_graph(contract['source']['dataset_url'], docs, {'schema'})
    proofs = prove_coordinates(contract, files, docs, graph)
    proof, = proofs
    assert proof['upload_rows_compared'] == 2 and proof['matched_official_keys'] == 1
    assert proof['maximum_axis_delta_degrees'] == '4E-12'
    assert ground_contract(contract, docs, accepted, graph=graph, coordinate_proofs=proofs)['ok']
    assert not ground_contract(contract, docs, accepted, graph=graph)['ok']


@pytest.mark.parametrize('suffix', ['row-a1-b2_c3', 'row-a1.b2~c3'])
def test_record_subject_accepts_unreserved_uri_characters(tmp_path, suffix):
    contract, files, docs, _ = fixture(tmp_path)
    docs['rdf']['content_bytes'] = docs['rdf']['content_bytes'].replace(b'row-a1_b2', suffix.encode())
    graph = build_graph(contract['source']['dataset_url'], docs, {'schema'})
    assert prove_coordinates(contract, files, docs, graph)[0]['matched_official_keys'] == 1


@pytest.mark.parametrize('change', ['wrong_key', 'reversed_axes', 'other_location', 'other_dataset', 'namespace_only', 'forged_contract_proof', 'wrong_record_type', 'wrong_subject', 'wrong_membership'])
def test_missing_actual_source_binding_never_admits(tmp_path, change):
    contract, files, docs, accepted = fixture(tmp_path)
    if change == 'wrong_key': docs['rdf']['content_bytes'] = docs['rdf']['content_bytes'].replace(b'>001<', b'>999<')
    if change == 'reversed_axes':
        contract['resources'][0]['mapping']['geography'].update(x_field='Lat', y_field='Lon')
    if change == 'other_location': docs['rdf']['content_bytes'] = docs['rdf']['content_bytes'].replace(b'd:place', b'd:unrelated')
    if change == 'other_dataset': docs['rdf']['url'] = docs['rdf']['url'].replace('wxyz-9876', 'abcd-2468')
    if change == 'wrong_record_type': docs['rdf']['content_bytes'] = docs['rdf']['content_bytes'].replace(b'b:_wxyz-9876', b'b:_abcd-2468')
    if change == 'wrong_subject': docs['rdf']['content_bytes'] = docs['rdf']['content_bytes'].replace(b'/row-a1_b2', b'/../row-a1_b2')
    if change == 'wrong_membership': docs['rdf']['content_bytes'] = docs['rdf']['content_bytes'].replace(b'/resource/_wxyz-9876"', b'/resource/_abcd-2468"')
    if change == 'namespace_only': docs['rdf']['content_bytes'] = f'<r:RDF xmlns:r="{RDF}" xmlns:g="{GEO}"/>'.encode()
    if change == 'forged_contract_proof':
        contract['coordinate_proofs'] = [{'crs': 'EPSG:4326', 'confirmed': True}]
        docs.pop('rdf')
    graph = build_graph(contract['source']['dataset_url'], docs, {'schema'})
    try:
        proofs = prove_coordinates(contract, files, docs, graph)
    except CoordinateBindingError:
        return
    assert not ground_contract(contract, docs, accepted, graph=graph, coordinate_proofs=proofs)['ok']


def test_full_upload_comparison_does_not_stop_at_official_sample(tmp_path):
    contract, files, docs, accepted = fixture(tmp_path, raw='EVENT,Date,Lon,Lat,Position\n001,2024-01-01,149.1,-35.2,"(-35.2, 149.1)"\n002,2024-01-02,151,-36,"(-36, 150)"\n')
    graph = build_graph(contract['source']['dataset_url'], docs, {'schema'})
    with pytest.raises(CoordinateBindingError) as error:
        prove_coordinates(contract, files, docs, graph)
    assert error.value.code == 'RDF_UPLOAD_COORDINATE_CONFLICT'
    assert error.value.details['row_locator'] == 'csv:2'


def test_changed_input_is_not_replaced_by_official_data(tmp_path):
    contract, files, docs, accepted = fixture(tmp_path)
    files[0]['sha256'] = '0' * 64
    graph = build_graph(contract['source']['dataset_url'], docs, {'schema'})
    with pytest.raises(CoordinateBindingError) as error:
        prove_coordinates(contract, files, docs, graph)
    assert error.value.code == 'RDF_INPUT_CHANGED'


def test_other_datum_is_not_accepted_as_wgs84(tmp_path):
    contract, files, docs, accepted = fixture(tmp_path)
    graph = build_graph(contract['source']['dataset_url'], docs, {'schema'})
    proofs = prove_coordinates(contract, files, docs, graph)
    contract['resources'][0]['mapping']['geography']['crs'] = 'EPSG:4283'
    assert not ground_contract(contract, docs, accepted, graph=graph, coordinate_proofs=proofs)['ok']


def test_removing_geography_cannot_discard_proven_rdf_coordinates(tmp_path):
    from arsia_pipeline.geography_review import review_geography
    contract, files, docs, accepted = fixture(tmp_path)
    del contract['resources'][0]['mapping']['geography']
    before = copy.deepcopy(contract)
    graph = build_graph(contract['source']['dataset_url'], docs, {'schema'})
    proofs = prove_coordinates(contract, files, docs, graph, include_omitted=True)
    grounding = ground_contract(contract, docs, accepted, graph=graph, coordinate_proofs=proofs)
    assert grounding['ok']
    review = review_geography(contract, docs, grounding, {'event': ['EVENT', 'Date', 'Lon', 'Lat', 'Position']})
    assert not review['ok'] and review['issues'][0]['code'] == 'CAPABILITY_REVIEW_REQUIRED'
    assert contract == before


def test_rdf_binding_honors_cancellation(tmp_path):
    contract, files, docs, accepted = fixture(tmp_path)
    graph = build_graph(contract['source']['dataset_url'], docs, {'schema'})
    class Cancelled(Exception): pass
    def cancel(): raise Cancelled()
    with pytest.raises(Cancelled):
        prove_coordinates(contract, files, docs, graph, check_cancelled=cancel)


def test_real_receipt_boundary_and_omission_gate(tmp_path, monkeypatch):
    from arsia_pipeline import config
    from arsia_pipeline.trusted_qa import _proof
    from arsia_pipeline.errors import NeedsInput
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    contract, files, docs, accepted = fixture(tmp_path)
    (tmp_path / 'sha256').mkdir()
    contract['documents'] = []
    for key, doc in docs.items():
        sha = hashlib.sha256(doc['content_bytes']).hexdigest()
        (tmp_path / 'sha256' / sha).write_bytes(doc['content_bytes'])
        receipt = tmp_path / (key + '.json')
        receipt.write_text(json.dumps({'status': 'fetched', 'final_url': doc['url'], 'final_host_official': True, 'sha256': sha}))
        contract['documents'].append({'document_id': key, 'receipt_path': str(receipt)})
    contract['evidence'] = {claim: [{'document_id': 'schema', 'quote': docs['schema']['text']}]
                            for claim in ('source_identity', 'grain', 'date', 'geography', 'coverage_update')}
    from source_binding_fixture import add_reference
    files[0]['size']=__import__('pathlib').Path(files[0]['path']).stat().st_size
    add_reference(files,tmp_path,'https://roads.example.gov.au/api/views/wxyz-9876/rows.csv?accessType=DOWNLOAD')
    proof = _proof(contract, tmp_path, files)
    assert proof['grounding']['coordinate_proofs'][0]['matched_official_keys'] == 1
    del contract['resources'][0]['mapping']['geography']
    with pytest.raises(NeedsInput) as error:
        _proof(contract, tmp_path, files)
    assert error.value.details['capability_review']['issues'][0]['code'] == 'CAPABILITY_REVIEW_REQUIRED'
    # An unverified RDF body can never become host-derived field authority.
    rdf_sha = hashlib.sha256(docs['rdf']['content_bytes']).hexdigest()
    (tmp_path / 'sha256' / rdf_sha).write_bytes(b'altered')
    contract['resources'][0]['mapping']['geography'] = {'x_field': 'Lon', 'y_field': 'Lat', 'crs': 'EPSG:4326'}
    # Corrupt registered bytes now fail the unconditional host integrity gate,
    # before the source-level CRS gate. Preserve the rejection and strengthen
    # its cause assertion; this does not grant authority to corrupted evidence.
    from arsia_pipeline.errors import ValidationFailure
    with pytest.raises(ValidationFailure) as error:
        _proof(contract, tmp_path, files)
    assert error.value.qa[0]['code'] == 'EVIDENCE_INTEGRITY'
    assert error.value.qa[0]['status'] == 'block'
    assert error.value.qa[0]['metrics']['document_id'] == 'rdf'

    from arsia_pipeline.capability_preflight import classified_blockers
    diagnosis=classified_blockers(error.value,operation='preflight')[0]
    assert diagnosis['kind']=='environment_dependency' and diagnosis['responsible_party']=='system'
