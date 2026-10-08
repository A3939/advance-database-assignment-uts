import io
import hashlib
import json
from pathlib import Path
import socket
import tempfile
import unittest

from arsia_pipeline.errors import NeedsInput, ValidationFailure
from arsia_pipeline.public_sources import PublicSources, validate_public_url


def resolver(host, port, **kwargs):
    ip = "127.0.0.1" if host == "private.test" else "8.8.8.8"
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port))]


class Response:
    def __init__(self, body=b"document", status=200, headers=None):
        self.stream = io.BytesIO(body)
        self.status = status
        self.headers = {"Content-Length": str(len(body)), "Content-Type": "text/plain", **(headers or {})}

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read(self, size):
        return self.stream.read(size)


class PublicTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.connections = []

    def tearDown(self):
        self.tmp.cleanup()

    def tool(self, responses):
        test = self
        class Connection:
            def __init__(self, host, address, timeout, context):
                test.connections.append((host, address, timeout, context.check_hostname))
                self.response = responses.pop(0)
            def request(self, method, target, headers):
                self.headers = headers
                test.assertNotIn("Authorization", headers)
                test.assertNotIn("Cookie", headers)
            def getresponse(self):
                return self.response
            def close(self):
                pass
        return PublicSources(self.root, resolver=resolver, connection_factory=Connection)

    def test_public_dns_pinned_and_receipt_hash(self):
        result = self.tool([Response()]).fetch_public_source("https://source.gov.au/doc")
        self.assertEqual(self.connections[0][:2], ("source.gov.au", "8.8.8.8"))
        self.assertTrue(self.connections[0][3])
        descriptor = result["__files"][0]
        self.assertTrue(Path(descriptor["receipt_path"]).is_file())
        self.assertEqual(result["__documents"][0]["receipt_path"], descriptor["receipt_path"])
        self.assertEqual(Path(descriptor["path"]).read_bytes(), b"document")

    def test_private_local_credentials_and_mixed_dns_rejected(self):
        for url in ["http://source.gov.au", "https://private.test", "https://localhost/a", "https://u:p@source.gov.au", "https://source.gov.au:444/a"]:
            with self.assertRaises(ValidationFailure):
                validate_public_url(url, resolver)
        def mixed(*args, **kwargs):
            return resolver("source.gov.au", 443) + resolver("private.test", 443)
        with self.assertRaises(ValidationFailure):
            validate_public_url("https://source.gov.au", mixed)

    def test_redirect_to_private_rejected_before_connection(self):
        tool = self.tool([Response(status=302, headers={"Location": "https://private.test/secrets"})])
        with self.assertRaises(ValidationFailure):
            tool.fetch_public_source("https://source.gov.au/doc")
        self.assertEqual(len(self.connections), 1)
        receipt = json.loads(next((self.root / "public-evidence").glob("*.json")).read_text())
        self.assertEqual(receipt["status"], "failed")

    def test_declared_actual_and_truncated_length_rejected(self):
        for response in [Response(b"123456"), Response(b"123456", headers={"Content-Length": None}), Response(b"12", headers={"Content-Length": "3"})]:
            with self.assertRaises(ValidationFailure):
                self.tool([response]).fetch_public_source("https://source.gov.au/doc", max_bytes=4)
        self.assertFalse(list((self.root / "public-evidence").glob("*.partial")))

    def test_access_denied_has_no_bypass(self):
        for status in (401, 403):
            with self.assertRaises(NeedsInput):
                self.tool([Response(status=status)]).fetch_public_source("https://source.gov.au/doc")
        self.assertEqual(len(self.connections), 2)

    def test_redirect_hop_limit(self):
        responses = [Response(status=302, headers={"Location": "/again"}) for _ in range(6)]
        with self.assertRaises(ValidationFailure):
            self.tool(responses).fetch_public_source("https://source.gov.au/doc")
        self.assertEqual(len(self.connections), 6)

    def arcgis_tool(self, incomplete=False, changed=False, page_reference=None, quantized=False, for_admission=False):
        tool = PublicSources(self.root, resolver=resolver)
        calls = []
        def fake_fetch(url, **kwargs):
            from datetime import datetime, timezone
            from urllib.parse import parse_qs, urlsplit
            query = parse_qs(urlsplit(url).query)
            calls.append(query)
            if "/query?" not in url:
                value = {"objectIdField": "ID", "maxRecordCount": 2, "fields": [{"name": "ID", "type": "esriFieldTypeOID"}],
                         "geometryType": "esriGeometryPoint", "extent": {"spatialReference": {"wkid": 3857}}}
                if for_admission:
                    value['extent']['spatialReference'] = {'wkid': 4326}
                    value['fields'] += [{'name': 'DATE'}, {'name': 'SEVERITY', 'domain': {'type': 'codedValue', 'codedValues': [{'code': 'Minor', 'name': 'Minor injury'}]}}]
            elif "returnIdsOnly" in query:
                value = {"objectIds": [1, 2, 3] + ([4] if changed and len(calls) > 3 else [])}
            elif "returnCountOnly" in query:
                value = {"count": 3}
            else:
                self.assertEqual(json.loads(query['outSR'][0]), {'wkid': 4326 if for_admission else 3857})
                ids = [int(v) for v in query["objectIds"][0].split(",")]
                value = {"features": [{"attributes": {"ID": i, "SEVERITY": "Minor"}, "geometry": {"x": i, "y": i}} for i in ids]}
                if for_admission:
                    for feature in value['features']:
                        feature['attributes']['DATE'] = '2024-01-01'
                        feature['geometry'] = {'x': 149.1, 'y': -35.2}
                if page_reference is not None: value['spatialReference'] = page_reference
                if quantized: value['transform'] = {'scale': [1, 1], 'translate': [100, 100]}
                if incomplete:
                    value["features"].pop()
            encoded = json.dumps(value).encode()
            sha = hashlib.sha256(encoded).hexdigest()
            path = tool.root / "sha256" / sha
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(encoded)
            descriptor = {"id": sha, "name": "source.json", "path": str(path), "sha256": sha, "size": len(encoded)}
            return {"request_id": sha[:12], "final_url": url, "sha256": sha, "size": len(encoded), "fetched_at": datetime.now(timezone.utc).isoformat(), "__files": [descriptor]}
        tool.fetch_public_source = fake_fetch
        return tool

    def test_arcgis_complete_snapshot_validates_inventory_and_count(self):
        result = self.arcgis_tool().fetch_arcgis_layer("https://source.gov.au/FeatureServer/0")
        self.assertEqual((result["record_count"], result["page_count"]), (3, 2))
        value = json.loads(Path(result["__files"][0]["path"]).read_text())
        self.assertEqual([f["attributes"]["ID"] for f in value["features"]], [1, 2, 3])
        self.assertIn("field edits", result["consistency"])
        self.assertNotIn('spatialReference', value)
        self.assertTrue(all(f['geometry']['spatialReference'] == {'wkid': 3857} for f in value['features']))
        self.assertEqual(result['derivation'], 'verified_arcgis_all_object_ids_v2')

    def test_arcgis_explicit_returned_reference_survives_combination(self):
        result = self.arcgis_tool(page_reference={'wkid': 4326}).fetch_arcgis_layer('https://source.gov.au/FeatureServer/0')
        value = json.loads(Path(result['__files'][0]['path']).read_text())
        self.assertTrue(all(f['geometry']['spatialReference'] == {'wkid': 4326} for f in value['features']))
        from arsia_pipeline.intakereaders import detect_tables
        table, = detect_tables(result['__files'][0])
        self.assertEqual(table['geometry_spatial_references'][0]['reference'], {'wkid': 4326})
        from arsia_pipeline.capability_preflight import geometry_blockers
        resource = {'role': 'crash', 'mapping': {'geography': {'x_field': '__geometry_x', 'y_field': '__geometry_y', 'crs': 'EPSG:3857'}}}
        self.assertEqual(geometry_blockers(resource, table)[0]['code'], 'GEOMETRY_CRS_CONFLICT')

    def test_arcgis_quantized_page_blocks_without_a_derived_success_receipt(self):
        from arsia_pipeline.errors import UnsupportedCapability
        with self.assertRaises(UnsupportedCapability):
            self.arcgis_tool(quantized=True).fetch_arcgis_layer('https://source.gov.au/FeatureServer/0')
        self.assertFalse(list((self.root / 'public-evidence').glob('arcgis-*.json')))

    def test_arcgis_missing_records_or_live_change_fail(self):
        for kwargs in ({"incomplete": True}, {"changed": True}):
            with self.assertRaises(ValidationFailure):
                self.arcgis_tool(**kwargs).fetch_arcgis_layer("https://source.gov.au/FeatureServer/0")
        self.assertFalse(list((self.root / "public-evidence").glob("*.partial")))

    def test_discovery_identifier_outranks_wrong_state_url(self):
        tool = PublicSources(self.root, resolver=resolver, source_hints=["ab12-cd34.csv"])
        requested = []
        def fake_fetch(url, **kwargs):
            requested.append(url)
            if "package_search" in url and "ab12-cd34" in url:
                value = {"result": {"results": [{"id": "published-package", "name": "ab12-cd34", "title": "Environmental observations",
                    "organization": {"title": "Official environmental agency"}, "resources": [{"url": "https://portal.example.gov.au/api/v3/views/ab12-cd34/export.csv"}]}]}}
            else:
                value = {"title": "Metadata", "description": "Official description"}
            encoded = json.dumps(value).encode()
            path = self.root / (hashlib.sha256(encoded).hexdigest() + ".json")
            path.write_bytes(encoded)
            descriptor = {"id": path.stem, "path": str(path), "name": path.name, "sha256": path.stem, "size": len(encoded)}
            return {"final_url": url, "content_type": "application/json", "__files": [descriptor], "__documents": []}
        tool.fetch_public_source = fake_fetch
        result = tool.discover_source_docs(query="SA road crash", urls=["https://data.sa.gov.au/wrong-hypothesis"])
        self.assertEqual(result["source_candidates"][0]["title"], "Environmental observations")
        self.assertTrue(result["source_candidates"][0]["identifier_match"])
        self.assertIn("https://portal.example.gov.au/api/views/ab12-cd34.json", requested)
        self.assertTrue(any("package_search" in url for url in requested))
        self.assertEqual(len(result["official_catalogues"]), 8)

    def test_year_range_is_not_a_socrata_identifier(self):
        tool = PublicSources(self.root, resolver=resolver, source_hints=["2020-2024_counts.csv"])
        def denied(url, **kwargs):
            raise NeedsInput("Public catalogue temporarily unavailable")
        tool.fetch_public_source = denied
        result = tool.discover_source_docs(query="road counts", urls=["https://data.example.gov.au/dictionary"])
        self.assertEqual(result["identifier_hints"], [])
        self.assertGreaterEqual(len(result["queries_attempted"]), 2)
        self.assertTrue(result["official_catalogues"])


if __name__ == "__main__":
    unittest.main()
