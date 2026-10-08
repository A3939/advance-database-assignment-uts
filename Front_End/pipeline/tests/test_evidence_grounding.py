import json
import unittest

from arsia_pipeline.evidence_grounding import ground_contract


def contract(dataset_url="https://data.example.gov.au/d/abcd-1234"):
    return {"source": {"dataset_url": dataset_url}, "resources": [{"role": "crash", "grain": "crash", "key": ["crash_id"],
        "mapping": {"date": {"field": "crash_date"}, "severity": {"field": "crash_severity"}}}], "relations": []}


def claims(document):
    return {name: [{"document_id": document, "quote": "Caller verified this quote against immutable bytes."}]
            for name in ("source_identity", "grain", "date", "severity", "counts", "relations", "geography")}


def socrata_document(dataset="abcd-1234", fields=None):
    fields = fields or ["crash_id", "crash_date", "crash_severity"]
    return {"url": "https://data.example.gov.au/api/views/" + dataset + ".json",
            "text": json.dumps({"id": dataset, "name": "Road events", "columns": [{"fieldName": f, "name": f.upper(), "description": "Official definition"} for f in fields]})}


class GroundingTests(unittest.TestCase):
    def test_original_bytes_not_lossy_text_supply_structured_field_binding(self):
        doc = socrata_document()
        doc['content_bytes'] = doc['text'].encode()
        doc['text'] = 'Publisher road event metadata; extracted text omitted the column schema.'
        result = ground_contract(contract(), {'official': doc}, claims('official'))
        self.assertTrue(result['ok'], result)
        self.assertTrue(all(binding['evidence'][0]['mode'] == 'official_structured_field'
                            for binding in result['field_bindings']))

    def test_ambiguous_raw_metadata_blocks_even_if_extracted_text_looks_valid(self):
        doc = socrata_document()
        doc['content_bytes'] = b'{"id":"abcd-1234","id":"xxxx-yyyy"}'
        result = ground_contract(contract(), {'official': doc}, claims('official'))
        self.assertFalse(result['ok'])
        self.assertEqual(result['issues'][0]['code'], 'METADATA_DUPLICATE_KEY')

    def test_same_dataset_id_structured_fields_ground(self):
        result = ground_contract(contract(), {"official": socrata_document()}, claims("official"))
        self.assertTrue(result["ok"], result)
        self.assertEqual(len(result["field_bindings"]), 3)

    def test_unrelated_official_dictionary_cannot_ground_actual_fields(self):
        wrong = socrata_document(fields=["REPORT_ID", "Crash Date Time", "CSEF Severity"])
        result = ground_contract(contract(), {"wrong": wrong}, claims("wrong"))
        self.assertFalse(result["ok"])
        self.assertEqual({issue.get("field") for issue in result["issues"]}, {"crash_id", "crash_date", "crash_severity"})

    def test_shared_government_host_is_not_source_identity(self):
        result = ground_contract(contract(), {"other": socrata_document("xxxx-yyyy")}, claims("other"))
        self.assertFalse(result["ok"])
        self.assertIn("SOURCE_IDENTITY_UNBOUND", {issue["code"] for issue in result["issues"]})

    def test_identity_and_unconnected_foreign_dictionary_cannot_be_combined(self):
        docs = {"identity": socrata_document(fields=["REPORT_ID"]), "foreign": socrata_document("xxxx-yyyy")}
        evidence = claims("foreign")
        evidence["source_identity"] = claims("identity")["source_identity"]
        result = ground_contract(contract(), docs, evidence)
        self.assertFalse(result["ok"])
        self.assertNotIn("foreign", result["connected_documents"])

    def test_ckan_resource_link_and_pdf_normalized_fields(self):
        url = "https://data.example.gov.au/data/dataset/road-crashes"
        pdf = "https://data.example.gov.au/files/dictionary.pdf"
        docs = {"catalogue": {"url": "https://data.example.gov.au/data/api/3/action/package_show?id=road-crashes", "text": json.dumps({"result": {
                    "id": "catalogue-uuid", "name": "road-crashes", "resources": [{"url": pdf}]}})},
                "pdf": {"url": pdf, "text": "REPORT_ID Unique number assigned to an individual crash.\nCrash Date The date of the crash.\nCSEF Severity Road crash severity."}}
        value = contract(url)
        value["resources"][0]["key"] = ["report_id"]
        value["resources"][0]["mapping"]["severity"]["field"] = "CSEF_Severity"
        evidence = claims("pdf")
        evidence["source_identity"] = claims("catalogue")["source_identity"]
        result = ground_contract(value, docs, evidence)
        self.assertTrue(result["ok"], result)

    def test_alias_requires_official_structured_association(self):
        doc = socrata_document(fields=["when", "crash_id", "crash_severity"])
        doc["text"] = doc["text"].replace('"name": "WHEN"', '"name": "Crash Date"')
        result = ground_contract(contract(), {"official": doc}, claims("official"))
        self.assertTrue(result["ok"])
        doc["text"] = doc["text"].replace('"name": "Crash Date"', '"name": "WHEN"')
        value = contract()
        value["field_aliases"] = {"when": "crash_date"}
        self.assertFalse(ground_contract(value, {"official": doc}, claims("official"))["ok"])

    def test_normalized_alias_collision_cannot_choose_last_official_field(self):
        doc = socrata_document()
        data = json.loads(doc['text'])
        data['columns'].append({'fieldName': 'different_time', 'name': 'CRASH DATE'})
        doc['text'] = json.dumps(data)
        result = ground_contract(contract(), {'official': doc}, claims('official'))
        self.assertFalse(result['ok'])
        self.assertTrue(any(issue.get('field') == 'crash_date' for issue in result['issues']))

    def test_nested_neighbour_or_historical_schema_cannot_supply_current_fields(self):
        for nested_key in ('other_layer', 'previous_version', 'resources', 'result'):
            with self.subTest(nested_key=nested_key):
                doc = socrata_document(fields=['unrelated_id'])
                value = json.loads(doc['text'])
                value[nested_key] = {'fields': [{'name': name} for name in ('crash_id', 'crash_date', 'crash_severity')]}
                doc['text'] = json.dumps(value)
                result = ground_contract(contract(), {'official': doc}, claims('official'))
                self.assertFalse(result['ok'])
                self.assertEqual({i.get('field') for i in result['issues']}, {'crash_id', 'crash_date', 'crash_severity'})

    def test_json_without_schema_cannot_fall_back_to_text_matching_payload(self):
        doc = socrata_document()
        value = json.loads(doc['text'])
        value['unrelated_payload'] = value.pop('columns')
        doc['text'] = json.dumps(value)
        self.assertFalse(ground_contract(contract(), {'official': doc}, claims('official'))['ok'])

    def test_scoped_ckan_package_fields_work_but_child_resource_fields_do_not(self):
        url = 'https://data.example.gov.au/dataset/road-events'
        package = {'name': 'road-events', 'fields': [{'name': f} for f in ('crash_id', 'crash_date', 'crash_severity')]}
        doc = {'url': 'https://data.example.gov.au/api/3/action/package_show?id=road-events', 'text': json.dumps({'result': package})}
        self.assertTrue(ground_contract(contract(url), {'official': doc}, claims('official'))['ok'])
        package['resources'] = [{'id': 'other-year', 'fields': package.pop('fields')}]
        doc['text'] = json.dumps({'result': package})
        self.assertFalse(ground_contract(contract(url), {'official': doc}, claims('official'))['ok'])

    def test_search_catalogue_does_not_bridge_unrelated_datasets(self):
        first = "https://data.example.gov.au/d/abcd-1234"
        second = "https://other.example.gov.au/d/xxxx-yyyy"
        docs = {"search": {"url": "https://data.gov.au/data/api/3/action/package_search?q=road", "text": json.dumps({"result": {"results": [
                    {"name": "first", "resources": [{"url": first}]}, {"name": "second", "resources": [{"url": second}]}]}})},
                "actual": socrata_document(), "foreign": {"url": second, "text": socrata_document()["text"]}}
        evidence = claims("foreign")
        evidence["source_identity"] = claims("search")["source_identity"]
        result = ground_contract(contract(), docs, evidence)
        self.assertFalse(result["ok"])
        self.assertNotIn("foreign", result["connected_documents"])

    def test_geography_requires_explicit_crs_not_just_lat_lon(self):
        value = contract()
        value["resources"][0]["mapping"]["geography"] = {"x_field": "longitude", "y_field": "latitude", "crs": "EPSG:4326"}
        doc = socrata_document(fields=["crash_id", "crash_date", "crash_severity", "longitude", "latitude"])
        result = ground_contract(value, {"official": doc}, claims("official"))
        self.assertIn("CRS_UNGROUNDED", {issue["code"] for issue in result["issues"]})

    def test_layer_geometry_wkid_does_not_ground_unrelated_attribute_coordinates(self):
        value = contract()
        value["resources"][0]["mapping"]["geography"] = {"x_field": "site_x", "y_field": "site_y", "crs": "EPSG:4326"}
        doc = socrata_document(fields=["crash_id", "crash_date", "crash_severity", "site_x", "site_y"])
        body = json.loads(doc["text"])
        body.update(geometryType="esriGeometryPoint", spatialReference={"wkid": 4326})
        doc["text"] = json.dumps(body)
        result = ground_contract(value, {"official": doc}, claims("official"))
        self.assertIn("CRS_UNGROUNDED", {issue["code"] for issue in result["issues"]})

    def test_broad_catalogue_neighbour_crs_cannot_ground_an_explicit_mapping(self):
        source = "https://data.example.gov.au/data/dataset/actual"
        value = contract(source)
        value["resources"][0]["mapping"]["geography"] = {"x_field": "site_x", "y_field": "site_y", "crs": "EPSG:3112"}
        fields = ["crash_id", "crash_date", "crash_severity", "site_x", "site_y"]
        doc = {"url": "https://data.example.gov.au/api/3/action/package_search?q=events", "text": json.dumps({"result": {"results": [
            {"name": "actual", "fields": [{"name": f} for f in fields]},
            {"name": "unrelated", "notes": "site_x site_y coordinates use CRS EPSG:3112"}]}})}
        result = ground_contract(value, {"official": doc}, claims("official"))
        self.assertIn("CRS_UNGROUNDED", {issue["code"] for issue in result["issues"]})


if __name__ == "__main__":
    unittest.main()
