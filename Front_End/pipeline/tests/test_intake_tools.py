import hashlib
import base64
import json
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch
import zipfile
import zlib

from openpyxl import Workbook

from arsia_pipeline.errors import NeedsInput, ValidationFailure
from arsia_pipeline.intakereaders import detect_tables, iter_table
from arsia_pipeline.intake_tools import IntakeTools


class IntakeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def file(self, name, content):
        path = self.root / name
        path.write_bytes(content if isinstance(content, bytes) else content.encode())
        return {"id": name, "name": name, "path": str(path), "size": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def test_csv_semicolon_utf16_multiline_locators(self):
        file = self.file("renamed", 'ID;Value\n1;"two\nlines"\n2;last\n'.encode("utf-16"))
        spec = detect_tables(file)[0]
        self.assertEqual((spec["encoding"], spec["delimiter"]), ("utf-16", ";"))
        rows = list(iter_table(file, spec))
        self.assertEqual(rows, [("csv:1", {"ID": "1", "Value": "two\nlines"}), ("csv:2", {"ID": "2", "Value": "last"})])

    def test_legacy_encoding_requires_declared_parser(self):
        file = self.file("legacy.csv", 'ID,Name\n1,André\n'.encode("cp1252"))
        with self.assertRaises(NeedsInput):
            detect_tables(file)
        rows = list(iter_table(file, {"format": "csv", "encoding": "cp1252"}))
        self.assertEqual(rows[0][1]["Name"], "André")

    def test_csv_duplicate_header_and_width_fail(self):
        with self.assertRaises(ValidationFailure):
            detect_tables(self.file("dup.csv", "ID,ID\n1,2\n"))
        file = self.file("wide.csv", "ID,Value\n1,2,3\n")
        with self.assertRaises(ValidationFailure):
            list(iter_table(file))

    def test_xlsx_magic_without_extension_and_internal_blank(self):
        book = Workbook()
        sheet = book.active
        sheet.title = "Events"
        sheet.append(["ID", "Count"])
        sheet.append(["A", 2])
        sheet.append([None, None])
        sheet.append(["B", 0])
        path = self.root / "opaque"
        book.save(path)
        rows = list(iter_table(path))
        self.assertEqual(rows[1], ('["Events",3]', {"ID": None, "Count": None}))
        self.assertEqual(rows[2][1], {"ID": "B", "Count": "0"})

    def test_xlsx_formula_rejected(self):
        book = Workbook()
        book.active.append(["ID", "Count"])
        book.active.append(["A", "=1+2"])
        path = self.root / "f.xlsx"
        book.save(path)
        with self.assertRaises(ValidationFailure):
            list(iter_table(path))

    def test_actual_legacy_xls_calendar_dates(self):
        # Synthetic BIFF8 workbook generated with xlwt 1.3.0; compressed so
        # production and regression environments need only the xlrd reader.
        encoded = "eNrtWE1oE0EU/maTND+0+TMVWqGEglVrexAvXtptNbV4SKle/EGwqc1BKhuJUdCL1ZqjIHhSRCjUg5eqF39QQcGDB6GiB0EQEj16EhQ8tFnfe7sraVVoUAuV+ZZ58+bNvJ23M+/N7Myr+URl5m57FcvQDx9qdhhNdTJFKewV4qB622bWy0OUbI01hXCIJrIpgEctL4M8hzzfVRi4439GFPhA6TBOYKRg5dOriJ1iQ06xDX1EFa6TJIo2sSop9KjQdUJvS8vHQgdEckloH7WtqEOYN0e6d7hefMDolLoo+L33ReedSLahFS/Yi89dVk7bAAaLx3LH11hFh78Zs6AJHc5b+SKXY7iJCHCQ0JvN9mYyFaRosmfx1U4DX7yofprW8tWVK5D821J58DfyEE3icvkVww9MwR6TICmTU4f9TiAPnc5bpZML1J4FnMjF92SIyeRK+QCwq3DKKpHjDEZ4YZeFIL5kIWiRAGkmOoGY8AkJkzhZsnDr8+vs+Kh5RCRTsvg7W8RGtgg2zrMGKUelxhDqo9Qt/FahF+StG4RvF5oiH6a8a7TVZXZPS5uLUttF/WwXvDE31fGbiS9/2vugo/zR3EL83HD1bGrurTmDTtqyJkifn2n0qB517Srjoenlyl1O3gtt+2lpCRlx13bb3QdjWORgIiSEOiUeHfWjZLhjxdrqF9pKtHk8nlD/bF0SN56zlqPdbyRxTwZtoG4LjkBDQ0NDQ0NDQ0PjD6DcX3Ofe0QIuL/+QfdeZ5FSTV+T/LfYhwI9JTokDsGivIgzDfnPegSU9y61Qh3vvpCxn3ovYhLjYsdkw/5LRzdV/z0rVoz/vRBqtP9aI3b+4/6/A3M0zs0="
        file = self.file("legacy-no-extension", zlib.decompress(base64.b64decode(encoded)))
        self.assertEqual(detect_tables(file)[0]["format"], "xls")
        self.assertEqual(list(iter_table(file))[0][1], {"ID": "A", "Date": "2024-02-29T00:00:00", "Count": "2"})

    def test_json_bom_geojson_and_arcgis(self):
        geo = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"ID": "x"},
                "geometry": {"type": "Point", "coordinates": [149.1, -35.2]}}]}
        file = self.file("renamed.geo", b"\xef\xbb\xbf" + json.dumps(geo).encode())
        spec = detect_tables(file)[0]
        self.assertEqual(spec["geojson_default_crs"], "OGC:CRS84")
        row = list(iter_table(file, spec))[0][1]
        self.assertEqual(row["__geometry_x"], "149.1")
        arc = self.file("arc", json.dumps({"spatialReference": {"wkid": 102100, "latestWkid": 3857},
                "features": [{"attributes": {"ID": 1}, "geometry": {"x": 3, "y": 4}}]}))
        self.assertEqual(detect_tables(arc)[0]["spatial_reference"], 3857)
        self.assertEqual(list(iter_table(arc))[0][1]["__geometry_y"], 4)

    def test_json_duplicates_and_late_fields(self):
        duplicate = self.file("duplicate.json", '[{"ID":1,"ID":2}]')
        with self.assertRaises(ValidationFailure):
            list(iter_table(duplicate))
        rows = [{"ID": i} for i in range(100)] + [{"ID": 101, "late": "preserved"}]
        file = self.file("late.json", json.dumps(rows))
        self.assertEqual(list(iter_table(file))[-1][1]["late"], "preserved")

    def test_zip_traversal_and_symlink_rejected(self):
        for name, member, mode in [("traverse", "../outside.csv", 0), ("link", "link", stat.S_IFLNK | 0o777)]:
            path = self.root / (name + ".zip")
            with zipfile.ZipFile(path, "w") as archive:
                info = zipfile.ZipInfo(member)
                info.external_attr = mode << 16
                archive.writestr(info, "ID\n1\n")
            file = self.file(name + ".bin", path.read_bytes())
            with self.assertRaises(ValidationFailure):
                IntakeTools([file], self.root / name).inspect_bundle()
        self.assertFalse((self.root / "outside.csv").exists())

    def test_zip_extract_hash_immutable_and_rename(self):
        path = self.root / "archive.zip"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("folder/events.csv", "ID,Year\nA,2024\n")
        file = self.file("bundle", path.read_bytes())
        tools = IntakeTools([file], self.root / "work")
        result = tools.inspect_bundle()
        child = result["__files"][0]
        self.assertEqual(child["archive_member"], "folder/events.csv")
        self.assertEqual(tools.profile_dataset(child["id"])["row_count"], 1)
        self.assertEqual(tools.inspect_bundle()["__files"][0]["sha256"], child["sha256"])
        Path(child["path"]).chmod(0o600)
        Path(child["path"]).write_text("changed")
        with self.assertRaises(ValidationFailure):
            tools.profile_dataset(child["id"])

    def test_profiles_do_not_disclose_person_rows(self):
        file = self.file("people.csv", "ID,Name,Year,Severity\n01,Private Alice,2024,Fatal\n02,Private Bob,2024,Minor\n")
        result = IntakeTools([file], self.root).profile_dataset(file["id"])
        self.assertNotIn("Private Alice", json.dumps(result))
        self.assertEqual(result["row_samples"], [])
        self.assertEqual(result["row_count"], 2)
        severity = next(c for c in result["columns"] if c["name"] == "Severity")
        self.assertEqual({x["value"] for x in severity["frequencies"]}, {"Fatal", "Minor"})

    def test_composite_relations_actual_orphans_not_join_count(self):
        parent = self.file("p.csv", "Crash,Unit\nA,1\nA,2\nB,1\n")
        child = self.file("c.csv", "Crash,Unit,Person\nA,1,x\nA,1,y\nB,2,z\n")
        result = IntakeTools([parent, child], self.root).inspect_relations("c.csv", ["Crash", "Unit"], "p.csv", ["Crash", "Unit"])
        self.assertEqual(result["metrics"]["matched_children"], 2)
        self.assertEqual(result["metrics"]["unmatched_children"], 1)
        self.assertFalse(result["structurally_valid"])
        self.assertNotIn('"z"', json.dumps(result))

    def test_relation_nullable_composite_only_all_blank_is_optional(self):
        parent = self.file("p.csv", "Crash,Unit\nA,1\n")
        child = self.file("c.csv", "Crash,Unit\nA,\n,\nA,1\n")
        result = IntakeTools([parent, child], self.root).inspect_relations(
            "c.csv", ["Crash", "Unit"], "p.csv", ["Crash", "Unit"], allow_blank=True)
        self.assertFalse(result["structurally_valid"])
        self.assertEqual(result["metrics"]["child_partial_blank_keys"], 1)
        self.assertEqual(result["metrics"]["child_all_blank_keys"], 1)
        self.assertEqual(result["metrics"]["matched_children"], 1)
        child = self.file("c.csv", "Crash,Unit\n,\nA,1\n")
        result = IntakeTools([parent, child], self.root).inspect_relations(
            "c.csv", ["Crash", "Unit"], "p.csv", ["Crash", "Unit"], allow_blank=True)
        self.assertTrue(result["structurally_valid"])

    def test_relation_duplicate_parent_reference_reports_join_multiplication(self):
        parent = self.file("p.csv", "ID\n01\n01\n02\n03\n03\n")
        child = self.file("c.csv", "ID\n01\n01\n02\n04\n")
        result = IntakeTools([parent, child], self.root).inspect_relations("c.csv", ["ID"], "p.csv", ["ID"])
        metrics = result["metrics"]
        self.assertFalse(result["structurally_valid"])
        self.assertEqual(metrics["ambiguous_parent_children"], 2)
        self.assertEqual(metrics["matched_children"], 1)
        self.assertEqual(metrics["parents_without_children"], 1)
        self.assertEqual(metrics["projected_inner_join_rows"], 5)
        self.assertEqual(metrics["join_extra_rows"], 2)
        self.assertEqual(metrics["duplicate_parent_key_groups"], 2)

    def test_relation_rejects_nonscalar_json_keys(self):
        for key in (True, ["A"], {"id": "A"}):
            with self.subTest(key=key):
                parent = self.file("p.json", json.dumps([{"ID": key}]))
                child = self.file("c.json", json.dumps([{"ID": key}]))
                result = IntakeTools([parent, child], self.root).inspect_relations("c.json", ["ID"], "p.json", ["ID"])
                self.assertFalse(result["structurally_valid"])
                self.assertEqual(result["metrics"]["parent_invalid_keys"], 1)
                self.assertEqual(result["metrics"]["child_invalid_keys"], 1)

    def test_relation_arguments_are_typed_and_identifiers_are_not_normalized(self):
        parent = self.file("p.csv", "ID\n001\n1\n")
        child = self.file("c.csv", "ID\n001\n")
        tools = IntakeTools([parent, child], self.root)
        for fields in ([None], [["ID"]], [True], [""]):
            with self.subTest(fields=fields), self.assertRaises(ValidationFailure):
                tools.inspect_relations("c.csv", fields, "p.csv", ["ID"])
        for allow_blank in ("false", 1, None):
            with self.subTest(allow_blank=allow_blank), self.assertRaises(ValidationFailure):
                tools.inspect_relations("c.csv", ["ID"], "p.csv", ["ID"], allow_blank=allow_blank)
        result = tools.inspect_relations("c.csv", ["ID"], "p.csv", ["ID"])
        self.assertTrue(result["structurally_valid"])
        self.assertEqual(result["metrics"]["parents_without_children"], 1)

    def test_document_receipt_and_search(self):
        file = self.file("metadata.json", json.dumps({"description": "Year denotes year of crash.", "cachedContents": {"top": "Private Person"}}))
        file.update(evidence_url="https://data.example.gov.au/dataset", receipt_path="/trusted/receipt.json", fetched_at="2026-10-01")
        tools = IntakeTools([file], self.root)
        result = tools.read_document(file["id"], search="year")
        self.assertNotIn("Private Person", result["text"])
        self.assertTrue(result["match_offsets"])
        self.assertEqual(result["__documents"][0]["receipt_path"], "/trusted/receipt.json")
        self.assertTrue(result["official"])
        self.assertEqual(hashlib.sha256(Path(result["__documents"][0]["text_path"]).read_bytes()).hexdigest(), result["text_sha256"])

    def test_renamed_csv_is_not_documentation(self):
        file = self.file("dictionary.txt", "ID,Name\n1,Private Person\n")
        with self.assertRaises(NeedsInput):
            IntakeTools([file], self.root).read_document(file["id"])

    def test_structured_citations_are_exact_saved_text_with_raw_alias_binding(self):
        file = self.file("catalogue.json", json.dumps({"columns": [
            {"fieldName": "crash_id", "name": "Crash identifier", "dataTypeName": "text", "description": "Identifier for each crash."},
            {"fieldName": "crash_date", "name": "Date of crash", "dataTypeName": "calendar_date", "description": "Date the crash occurred."}],
            "cachedContents": {"sampleRows": ["Private Person"]}}))
        tools = IntakeTools([file], self.root)
        result = tools.read_document(file["id"], search="crash_date")
        text = Path(result["__documents"][0]["text_path"]).read_text()
        self.assertEqual(len(result["field_definitions"]), 1)
        self.assertEqual(result["field_definitions"][0]["alias"], "Date of crash")
        self.assertNotIn("Private Person", json.dumps(result))
        for span in result["citation_spans"]:
            self.assertEqual(span["document_id"], result["document_id"])
            self.assertEqual(span["quote"], text[span["start"]:span["end"]])
            self.assertIn('"fieldName": "crash_date"', span["quote"])

    def test_long_document_search_is_bounded_and_keeps_exact_quote_offsets(self):
        body = "Introduction. " * 5000 + "COUNT means source-reported casualties." + " Later context." * 1000
        file = self.file("dictionary.txt", body)
        tools = IntakeTools([file], self.root)
        result = tools.read_document(file["id"], search="COUNT means")
        self.assertGreater(result["offset"], 50000)
        self.assertLessEqual(len(result["text"]), 4000)
        self.assertEqual(result["next_offset"], result["offset"] + len(result["text"]))
        self.assertTrue(result["truncated"])
        self.assertEqual(result["citation_spans"][0]["quote"], body[result["citation_spans"][0]["start"]:result["citation_spans"][0]["end"]])
        self.assertIn("COUNT means", result["citation_spans"][0]["quote"])

    def test_arcgis_field_citations_do_not_invent_aliases(self):
        file = self.file("layer.json", json.dumps({"fields": [{"name": "CRASH_DATE", "type": "esriFieldTypeDate"},
                {"name": "ID", "alias": "Object identifier", "type": "esriFieldTypeOID"}]}))
        result = IntakeTools([file], self.root).read_document(file["id"], search="CRASH_DATE")
        self.assertIsNone(result["field_definitions"][0]["alias"])
        self.assertEqual(result["field_definitions"][0]["type"], "esriFieldTypeDate")
        self.assertIn('"name": "CRASH_DATE"', result["citation_spans"][0]["quote"])


if __name__ == "__main__":
    unittest.main()
