import copy
import hashlib
import json

import pytest

from arsia_pipeline.geography_review import coordinate_pairs, review_geography
from arsia_pipeline.errors import NeedsInput


def fixture():
    contract = {"source": {"dataset_url": "https://data.example.gov.au/dataset/events"},
        "resources": [{"role": "events", "grain": "crash", "file_id": "uploaded", "key": ["ID"],
                       "mapping": {"date": {"field": "DATE"}}}], "evidence": {}}
    text = "Event_X Event_Y\nX and Y coordinate projection: EPSG:3112. This coordinate system applies to reported events."
    documents = {"dictionary": {"url": "https://data.example.gov.au/dictionary.pdf", "text": text}}
    return contract, documents, {"connected_documents": ["dictionary"]}, {"events": ["ID", "DATE", "Event_X", "Event_Y"]}


def test_omitted_documented_geography_returns_exact_actionable_evidence():
    c, docs, grounding, fields = fixture()
    result = review_geography(c, docs, grounding, fields)
    issue = result["issues"][0]
    assert not result["ok"] and issue["code"] == "CAPABILITY_REVIEW_REQUIRED"
    assert issue["fields"] == {"x_field": "Event_X", "y_field": "Event_Y"}
    evidence = issue["official_evidence"][0]
    assert evidence["crs"] == "EPSG:3112"
    assert docs["dictionary"]["text"][evidence["start"]:evidence["end"]] == evidence["quote"]


@pytest.mark.parametrize("change", ["unconnected", "missing_actual_field", "no_crs", "remote_crs", "partial_name", "no_coordinate_declaration"])
def test_incomplete_or_unrelated_evidence_never_infers_capability(change):
    c, docs, grounding, fields = fixture()
    if change == "unconnected": grounding["connected_documents"] = []
    if change == "missing_actual_field": fields["events"].remove("Event_Y")
    if change == "no_crs": docs["dictionary"]["text"] = "Event_X Event_Y are coordinates."
    if change == "remote_crs": docs["dictionary"]["text"] = "Event_X Event_Y\n" + "other fields " * 300 + "Projection EPSG:3112"
    if change == "partial_name": docs["dictionary"]["text"] = "OTHER_Event_X OTHER_Event_Y coordinate projection EPSG:3112"
    if change == "no_coordinate_declaration": docs["dictionary"]["text"] = "Event_X Event_Y unrelated EPSG:3112 citation"
    assert review_geography(c, docs, grounding, fields)["ok"]


def test_model_unsupported_text_cannot_bypass_known_source_facts():
    c, docs, grounding, fields = fixture()
    c["definitions"] = {"geography": "No CRS established; unavailable."}
    c["capability_review"] = {"geography": "confirmed unsupported"}
    assert not review_geography(c, docs, grounding, fields)["ok"]


def test_mapped_coordinate_pair_resolves_review_without_requiring_duplicate_representation():
    c, docs, grounding, fields = fixture()
    fields["events"] += ["longitude", "latitude"]
    c["resources"][0]["mapping"]["geography"] = {"x_field": "Event_X", "y_field": "Event_Y", "crs": "EPSG:3112"}
    assert review_geography(c, docs, grounding, fields)["ok"]


def test_only_actual_axis_pairs_are_candidates():
    assert coordinate_pairs(["Event_X", "Event_Y", "Other_Y"]) == [("Event_X", "Event_Y")]
    assert coordinate_pairs(["east count", "north count", "X1", "Y2"]) == []
    assert coordinate_pairs(["longitude", "latitude"]) == [("longitude", "latitude")]


def test_structured_trusted_geometry_metadata_is_supported_without_invented_field_alias():
    c, docs, grounding, fields = fixture()
    fields["events"] = ["__geometry_x", "__geometry_y"]
    docs["dictionary"]["text"] = json.dumps({"geometryType": "esriGeometryPoint", "fields": [{"name": "ID"}],
        "extent": {"spatialReference": {"wkid": 4326}}})
    result = review_geography(c, docs, grounding, fields)
    assert not result["ok"]
    evidence = result["issues"][0]["official_evidence"][0]
    assert evidence["authority"] == "ArcGIS WKID" and evidence["code"] == "4326"
    assert "crs" not in evidence


def test_geometry_crs_cannot_be_assigned_to_ordinary_local_grid_attributes():
    from arsia_pipeline.geography_review import coordinate_evidence
    c, docs, grounding, fields = fixture()
    fields["events"] = ["site_x", "site_y"]
    docs["dictionary"]["text"] = json.dumps({"geometryType": "esriGeometryPoint", "spatialReference": {"wkid": 4326},
        "fields": [{"name": "site_x", "description": "Station local grid x measurement"},
                   {"name": "site_y", "description": "Station local grid y measurement"}]})
    assert review_geography(c, docs, grounding, fields)["ok"]
    assert coordinate_evidence("dictionary", docs["dictionary"], "site_x", "site_y") == []


def test_broad_search_neighbours_cannot_supply_crs_for_actual_package():
    c, docs, grounding, fields = fixture()
    docs["dictionary"]["text"] = json.dumps({"result": {"results": [
        {"name": "actual", "fields": ["Event_X", "Event_Y"]},
        {"name": "unrelated", "notes": "Event_X Event_Y coordinates use CRS EPSG:3112"}]}})
    assert review_geography(c, docs, grounding, fields)["ok"]


def test_esri_wkid_preserves_authority_and_uses_unambiguous_database_equivalence():
    from arsia_pipeline.geography_review import coordinate_evidence, coordinate_crs_matches
    doc = {"text": json.dumps({"geometryType": "esriGeometryPoint", "fields": [{"name": "ID"}],
            "spatialReference": {"wkid": 102100, "latestWkid": 3857}})}
    evidence = coordinate_evidence("layer", doc, "__geometry_x", "__geometry_y")
    assert {e["code"] for e in evidence} == {"102100", "3857"}
    assert all(e["authority"] == "ArcGIS WKID" and "crs" not in e for e in evidence)
    assert all(coordinate_crs_matches(e, "EPSG:3857") for e in evidence)
    assert not any(coordinate_crs_matches(e, "EPSG:4326") for e in evidence)


def test_qa_proof_rechecks_receipt_connected_dictionary_and_real_headers(tmp_path, monkeypatch):
    from arsia_pipeline import config
    from arsia_pipeline.trusted_qa import _proof, TRUSTED_FILES, POLICY
    monkeypatch.setattr(config, "ROOT", tmp_path)
    c, _, _, _ = fixture()
    dictionary_url = "https://data.example.gov.au/dictionary.pdf"
    text = "ID identifies a reported event. DATE records the event date. Event_X Event_Y\nX and Y coordinate projection: EPSG:3112."
    catalogue = json.dumps({"result": {"name": "events", "notes": "Complete reported event snapshot", "resources": [{"url": dictionary_url}, {"url": "https://data.example.gov.au/events.csv"}]}})
    (tmp_path / "sha256").mkdir()
    c["documents"] = []
    for doc_id, url, content in [("dictionary", dictionary_url, text),
            ("catalogue", "https://data.example.gov.au/api/3/action/package_show?id=events", catalogue)]:
        sha = hashlib.sha256(content.encode()).hexdigest()
        (tmp_path / "sha256" / sha).write_text(content)
        receipt = tmp_path / (doc_id + ".json")
        receipt.write_text(json.dumps({"status": "fetched", "final_url": url, "final_host_official": True, "sha256": sha}))
        c["documents"].append({"document_id": doc_id, "receipt_path": str(receipt)})
    c["evidence"] = {claim: [{"document_id": "dictionary", "quote": text}] for claim in ("grain", "date")}
    c["evidence"].update({claim: [{"document_id": "catalogue", "quote": catalogue}] for claim in ("source_identity", "coverage_update")})
    path = tmp_path / "events.csv"
    path.write_text("ID,DATE,Event_X,Event_Y\n1,2024-01-01,150,-35\n")
    files = [{"id": "uploaded", "name": path.name, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "size": path.stat().st_size}]
    from source_binding_fixture import add_reference
    add_reference(files,tmp_path)
    with pytest.raises(NeedsInput) as error:
        _proof(c, tmp_path, files)
    assert error.value.details["capability_review"]["issues"][0]["fields"]["x_field"] == "Event_X"
    assert "geography_review.py" in TRUSTED_FILES and "metadata_extractors.py" in TRUSTED_FILES
    assert POLICY == "canonical-v2-auto-admission-26"
    # Explicit restriction preserves the unresolved finding and requested target.
    c['resources'][0]['capability_limits']={'geography':{'requested':True,'reason':'Coordinate evidence needs further investigation before mapping.'}}
    limited=_proof(c,tmp_path,files)
    assert limited['capability_review']['status']=='limited'
    assert limited['capability_review']['limited_issues'][0]['code']=='CAPABILITY_REVIEW_REQUIRED'
    assert limited['capability_limits'][0]['target_satisfied'] is False
    c['resources'][0].pop('capability_limits')
    c["resources"][0]["mapping"]["geography"] = {"x_field": "Event_X", "y_field": "Event_Y", "crs": "EPSG:3112"}
    c["evidence"]["geography"] = [{"document_id": "dictionary", "quote": text}]
    assert _proof(c, tmp_path, files)["capability_review"]["ok"]
    # Source evidence is still checked before the omission gate; changing bytes
    # invalidates the receipt rather than becoming model-controlled authority.
    receipt = tmp_path / "dictionary.json"
    receipt_value = json.loads(receipt.read_text())
    (tmp_path / "sha256" / receipt_value["sha256"]).write_text("Altered dictionary")
    from arsia_pipeline.errors import ValidationFailure
    with pytest.raises(ValidationFailure) as corrupted:
        _proof(c, tmp_path, files)
    assert corrupted.value.details['blockers'][0]['code']=='EVIDENCE_INTEGRITY'
