"""Trusted inspection tools: bounded model metadata over complete local inputs.

Models receive structure, aggregate profiles and source documents, never whole
person-level records. These tools do not approve source meaning or publication.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime
from html.parser import HTMLParser
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import sqlite3
import stat
import tempfile
from urllib.parse import urlsplit
from uuid import uuid4
import zipfile

from .errors import NeedsInput, ValidationFailure
from .intakereaders import detect_format, detect_tables, iter_table
from .public_sources import official_host

MAX_ZIP_FILES = 128
MAX_ZIP_EXPANDED = 1024**3
MAX_DOCUMENT_TEXT = 4 * 1024**2


def _digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _is_blank(value):
    return value is None or value == ""


def _citation(text, start, end, document_id, url):
    """Mechanical text locations, never an assertion that a claim is supported."""
    return {"document_id": document_id, "quote": text[start:end],
            "start": start, "end": end, "url": url}


def _metadata_fields(value, text, document_id, url, search, offset, end):
    """Bounded official-style JSON field objects, with exact serialized quotes.

    Aliases are read only from the supplied structured metadata. This does not
    invent a mapping, classify source records, or grant evidence authority.
    """
    found = []
    def visit(node):
        if len(found) >= 12:
            return
        if isinstance(node, dict):
            for kind in ("columns", "fields"):
                for field in node.get(kind, []) if isinstance(node.get(kind), list) else []:
                    if not isinstance(field, dict):
                        continue
                    raw = field.get("fieldName") if kind == "columns" else field.get("name")
                    if not isinstance(raw, str) or not raw:
                        continue
                    alias = field.get("name") if kind == "columns" else field.get("alias")
                    searchable = " ".join(str(v) for v in (raw, alias, field.get("description", "")))
                    if search and search.casefold() not in searchable.casefold():
                        continue
                    encoded = json.dumps(field, ensure_ascii=False, indent=2)
                    # read_document's canonical pretty JSON adds two spaces
                    # per nesting level. Locate the complete original object.
                    position, rendered = -1, ""
                    for padding in range(0, 34, 2):
                        rendered = encoded.replace("\n", "\n" + " " * padding)
                        position = text.find(rendered)
                        if position >= 0:
                            break
                    if position < 0:
                        continue
                    if not search and not offset <= position < end:
                        continue
                    item = {"raw_name": raw, "alias": alias, "type": field.get("dataTypeName", field.get("type")),
                            "description": str(field.get("description", ""))[:600]}
                    if len(rendered) <= 2000:
                        item["citation"] = _citation(text, position, position + len(rendered), document_id, url)
                    found.append(item)
                    if len(found) >= 12:
                        break
            for child in node.values():
                if isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)
    visit(value)
    return found[:12]


class _TextHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"} and self.skip:
            self.skip -= 1
        elif tag in {"p", "div", "tr", "li", "h1", "h2", "h3", "br"}:
            self.parts.append("\n")

    def handle_data(self, text):
        if not self.skip:
            self.parts.append(text)


class IntakeTools:
    def __init__(self, files, work_dir, check_cancelled=lambda: None):
        self.root = Path(work_dir).resolve() / "intake-tools"
        self.root.mkdir(parents=True, exist_ok=True)
        self.check_cancelled = check_cancelled
        self.files = []
        self.register_files(files)

    def register_files(self, files):
        existing = {f["id"]: f for f in self.files}
        for file in files:
            if not isinstance(file.get("id"), str) or not file["id"]:
                raise ValidationFailure("Every input needs a trusted file ID.")
            if file["id"] in existing:
                if existing[file["id"]]["sha256"] != file["sha256"]:
                    raise ValidationFailure("File ID was rebound to different bytes.")
                continue
            path = Path(file["path"])
            if path.is_symlink() or not path.is_file():
                raise ValidationFailure("Registered file must be a regular non-symlink input.")
            self.files.append(dict(file))
            existing[file["id"]] = file

    def _file(self, file_id):
        matches = [f for f in self.files if f["id"] == file_id]
        if len(matches) != 1:
            raise ValidationFailure("Unknown file_id; arbitrary paths are not accepted.")
        file = matches[0]
        path = Path(file["path"])
        if path.is_symlink() or not path.is_file() or path.stat().st_size != file["size"] or _digest(path) != file["sha256"]:
            raise ValidationFailure("Input bytes changed after registration.")
        return file

    def _table(self, file, table_id=None, parser=None):
        hints = dict(parser or {})
        if table_id is not None:
            if hints.get('sheet', hints.get('table_id', table_id)) != table_id:
                raise ValidationFailure('Parser selection conflicts with table_id.')
            hints['table_id'] = table_id
        tables = detect_tables(file, hints, self.check_cancelled)
        selected = [t for t in tables if table_id is None or t["table_id"] == table_id]
        if len(selected) != 1:
            raise NeedsInput("Select a specific worksheet/table from inspect_bundle.", details={"tables": [t["table_id"] for t in tables]})
        return selected[0]

    def _expand_zip(self, file):
        from .archive_parser import inventory
        inventory(file, check_cancelled=self.check_cancelled)
        output = self.root / "expanded" / file["sha256"]
        marker = output / "manifest.json"
        def bind(descriptors):
            # Cached bytes are content-addressed, but task authority belongs to
            # this particular parent. A fetched comparison must not become an
            # uploaded fact, nor may a later upload inherit an evidence exemption.
            return [{**{k: v for k, v in item.items() if k != 'role'},
                     'id': 'zip-' + hashlib.sha256((file['id'] + '\n' + item['archive_member']).encode()).hexdigest()[:24],
                     'archive_file_id': file['id'],
                     **({'role': 'public_evidence'} if file.get('role') == 'public_evidence' else {})}
                    for item in descriptors]
        if marker.is_file():
            descriptors = json.loads(marker.read_text())["files"]
            for item in descriptors:
                if _digest(item["path"]) != item["sha256"]:
                    raise ValidationFailure("Previously extracted archive bytes changed.")
            return bind(descriptors)
        output.mkdir(parents=True, exist_ok=True)
        descriptors = []
        try:
            with zipfile.ZipFile(file["path"]) as archive:
                entries = [i for i in archive.infolist() if not i.is_dir()]
                if len(entries) > MAX_ZIP_FILES or sum(i.file_size for i in entries) > MAX_ZIP_EXPANDED:
                    raise ValidationFailure("ZIP exceeds the 128-file/1-GiB expanded limit.")
                names = set()
                for entry in entries:
                    self.check_cancelled()
                    name = entry.filename
                    member = PurePosixPath(name)
                    mode = (entry.external_attr >> 16) & 0xFFFF
                    if (not name or member.is_absolute() or "\\" in name or ":" in name or "\x00" in name
                            or any(p in {"", ".", ".."} for p in name.split("/")) or name in names
                            or stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in {0, stat.S_IFREG})
                            or entry.flag_bits & 1):
                        raise ValidationFailure("ZIP contains unsafe paths, links, duplicate names or encrypted members.")
                    if entry.file_size > 512 * 1024**2 or (entry.file_size > 1024**2 and entry.file_size > max(entry.compress_size, 1) * 1000):
                        raise ValidationFailure("ZIP member exceeds size/compression-ratio limits.")
                    names.add(name)
                    # Member path is retained as provenance only; use a generated
                    # leaf destination, never materialize attacker directories.
                    destination = output / (hashlib.sha256(name.encode()).hexdigest()[:20] + ".input")
                    if destination.exists():
                        raise ValidationFailure("Partial ZIP extraction exists; use a fresh attempt.")
                    sha, size = hashlib.sha256(), 0
                    with archive.open(entry) as source, destination.open("xb") as target:
                        while chunk := source.read(1024**2):
                            self.check_cancelled()
                            size += len(chunk)
                            if size > entry.file_size or size > 512 * 1024**2:
                                raise ValidationFailure("ZIP expanded beyond its declared size.")
                            sha.update(chunk)
                            target.write(chunk)
                    if size != entry.file_size:
                        raise ValidationFailure("ZIP member is truncated.")
                    if zipfile.is_zipfile(destination):
                        if detect_format({'path': str(destination)}, self.check_cancelled) != 'xlsx':
                            raise NeedsInput("Nested ZIP archives need a separate reviewed extraction step.")
                    destination.chmod(0o400)
                    descriptors.append({"id": "zip-" + hashlib.sha256((file["id"] + "\n" + name).encode()).hexdigest()[:24],
                                        "name": member.name, "path": str(destination), "sha256": sha.hexdigest(), "size": size,
                                        "archive_file_id": file["id"], "archive_member": name})
            marker.write_text(json.dumps({"archive_sha256": file["sha256"], "files": descriptors}, indent=2) + "\n")
            return bind(descriptors)
        except zipfile.BadZipFile as exc:
            raise ValidationFailure("ZIP checksum or structure is invalid.") from exc

    def inspect_bundle(self):
        derived = []
        for file in list(self.files):
            verified = self._file(file["id"])
            if detect_format(verified, self.check_cancelled) == "zip":
                derived.extend(self._expand_zip(verified))
        self.register_files(derived)
        resources = []
        for original in self.files:
            self.check_cancelled()
            file = self._file(original["id"])
            kind = detect_format(file)
            metadata = {"file_id": file["id"], "name": file["name"], "size": file["size"], "sha256": file["sha256"], "format": kind,
                        "archive_file_id": file.get("archive_file_id"), "archive_member": file.get("archive_member"),
                        "resource_origin": 'public_evidence' if file.get('role') == 'public_evidence' else 'uploaded_input'}
            if kind not in {"zip", "pdf"}:
                try:
                    tables = detect_tables(file, check_cancelled=self.check_cancelled)
                    metadata["tables"] = tables
                    metadata["structure_signature"] = hashlib.sha256(_json([{k: v for k, v in t.items() if k != "header_sampled_records"} for t in tables]).encode()).hexdigest()
                except (NeedsInput, ValidationFailure) as exc:
                    metadata.update(tables=[], inspection_issue=str(exc), details=getattr(exc, "details", {}))
            resources.append(metadata)
        from .table_classification import dictionary_review, dictionary_columns
        by_id = {file['id']: file for file in self.files}
        inventory = [(by_id[item['file_id']], table) for item in resources for table in item.get('tables', [])
                     if not by_id[item['file_id']].get('evidence_url') and by_id[item['file_id']].get('role') != 'public_evidence']
        for file, table in inventory:
            if dictionary_columns(table):
                try:
                    review = dictionary_review(file, table, inventory, self.check_cancelled)
                    if review:
                        table['dictionary_review'] = review
                except (NeedsInput, ValidationFailure):
                    pass # It remains unclassified; no rows or error values exposed.
        return {"resources": resources, "files": resources, "file_count": len(resources), "__files": derived,
                "source_identity_is_not_inferred": True, "raw_records_sent_to_model": 0}

    def profile_dataset(self, file_id, table_id=None, parser=None, max_rows=None):
        file = self._file(file_id)
        spec = self._table(file, table_id, parser)
        if max_rows is not None and (type(max_rows) is not int or not 1 <= max_rows <= 1000000):
            raise ValidationFailure("Profiling max_rows must be 1–1000000 or absent for full input.")
        stats = {}
        path = self.root / f"profile-{uuid4().hex}.sqlite"
        db = sqlite3.connect(path)
        db.execute("PRAGMA cache_size=-8192")
        db.execute("PRAGMA journal_mode=OFF")
        db.execute("CREATE TABLE vals(col TEXT, digest TEXT, value TEXT, n INTEGER, PRIMARY KEY(col,digest))")
        count = 0
        try:
            for locator, row in iter_table(file, spec, self.check_cancelled):
                if max_rows is not None and count >= max_rows:
                    break
                count += 1
                for name, value in row.items():
                    stat = stats.setdefault(name, {"observed": 0, "empty": 0, "types": Counter(), "numeric_min": None,
                                                   "numeric_max": None, "date_min": None, "date_max": None, "date_shapes": Counter(), "date_formats": Counter(), "date_ranges": {}})
                    stat["observed"] += 1
                    if _is_blank(value):
                        stat["empty"] += 1
                        continue
                    encoded = _json(value)
                    digest = hashlib.sha256(encoded.encode()).hexdigest()
                    # Native values stay in the task's disk index; the model
                    # receives only safe aggregate categories below.
                    db.execute("INSERT INTO vals VALUES(?,?,?,1) ON CONFLICT(col,digest) DO UPDATE SET n=n+1",
                               (name, digest, encoded if len(encoded) <= 400 else "null",))
                    text = str(value)
                    if isinstance(value, (dict, list)):
                        kind = "object" if isinstance(value, dict) else "array"
                    elif isinstance(value, bool):
                        kind = "boolean"
                    elif re.fullmatch(r"[-+]?[0-9]+", text):
                        kind = "integer"
                    elif re.fullmatch(r"[-+]?(?:[0-9]+\.[0-9]*|[0-9]*\.[0-9]+)(?:[eE][-+]?[0-9]+)?", text):
                        kind = "decimal"
                    else:
                        kind = "text"
                    stat["types"][kind] += 1
                    if kind in {"integer", "decimal"}:
                        number = float(text)
                        if math.isfinite(number):
                            stat["numeric_min"] = number if stat["numeric_min"] is None else min(number, stat["numeric_min"])
                            stat["numeric_max"] = number if stat["numeric_max"] is None else max(number, stat["numeric_max"])
                    if re.match(r"^\d{4}-\d{2}-\d{2}(?:[T ]|$)", text):
                        try:
                            parsed = datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
                            stat["date_min"] = parsed if stat["date_min"] is None else min(parsed, stat["date_min"])
                            stat["date_max"] = parsed if stat["date_max"] is None else max(parsed, stat["date_max"])
                            stat["date_shapes"]["ISO8601"] += 1
                        except ValueError:
                            stat["date_shapes"]["invalid_ISO_like"] += 1
                    elif re.match(r"^\d{1,2}/\d{1,2}/\d{4}", text):
                        stat["date_shapes"]["slash_date_requires_order_evidence"] += 1
                        for date_format in ("%d/%m/%Y", "%m/%d/%Y", "%d/%m/%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%m/%d/%Y %H:%M"):
                            try:
                                value_date = datetime.strptime(text, date_format).isoformat()
                                stat["date_formats"][date_format] += 1
                                bounds = stat["date_ranges"].setdefault(date_format, [value_date, value_date])
                                bounds[0], bounds[1] = min(bounds[0], value_date), max(bounds[1], value_date)
                            except ValueError:
                                pass
            db.commit()
            columns, keys = [], []
            for name, stat in stats.items():
                distinct, duplicated = db.execute("SELECT count(*),COALESCE(sum(n-1),0) FROM vals WHERE col=?", (name,)).fetchone()
                nulls = count - stat["observed"] + stat["empty"]
                safe = bool(re.search(r"severity|injury|inj_|month|year|unit.?type|casualty.?type|sex|road.?user|weather|surface", name, re.I))
                frequencies = []
                if distinct <= 40 and safe:
                    frequencies = [{"value": json.loads(v), "count": n} for v, n in db.execute("SELECT value,n FROM vals WHERE col=? ORDER BY n DESC,value", (name,))]
                columns.append({"name": name, "null_or_empty_count": nulls, "distinct_nonempty_count": distinct,
                                "duplicate_nonempty_count": duplicated, "types": dict(stat["types"]),
                                "numeric_min": stat["numeric_min"] if not re.search(r"(?:^|_)id$|number|crash.?id|crash.?ref", name, re.I) else None,
                                "numeric_max": stat["numeric_max"] if not re.search(r"(?:^|_)id$|number|crash.?id|crash.?ref", name, re.I) else None,
                                "date_min": stat["date_min"], "date_max": stat["date_max"], "date_shapes": dict(stat["date_shapes"]),
                                "consistent_date_format_candidates": [{"format": fmt, "range": stat["date_ranges"][fmt]} for fmt, n in stat["date_formats"].items() if n == count - nulls],
                                "frequencies": frequencies, "values_withheld": not bool(frequencies)})
                if distinct == count and not nulls:
                    keys.append([name])
            return {"file_id": file_id, "table": spec, "row_count": count, "complete": max_rows is None,
                    "columns": columns, "unique_column_candidates": keys,
                    "key_semantics_require_evidence": True, "row_samples": [], "raw_records_sent_to_model": 0}
        finally:
            db.close()
            path.unlink(missing_ok=True)

    def inspect_relations(self, child_file_id, child_fields, parent_file_id, parent_fields,
                          child_table_id=None, parent_table_id=None, allow_blank=False, child_parser=None, parent_parser=None):
        if (not isinstance(child_fields, list) or not isinstance(parent_fields, list) or not child_fields
                or len(child_fields) != len(parent_fields) or len(child_fields) > 12
                or any(not isinstance(field, str) or not field for field in child_fields + parent_fields)
                or len(set(child_fields)) != len(child_fields) or len(set(parent_fields)) != len(parent_fields)):
            raise ValidationFailure("Relations need equally sized, unique, ordered key field lists.")
        if type(allow_blank) is not bool:
            raise ValidationFailure("allow_blank must be a boolean; only entirely blank child keys can be optional.")
        child, parent = self._file(child_file_id), self._file(parent_file_id)
        cs, ps = self._table(child, child_table_id, child_parser), self._table(parent, parent_table_id, parent_parser)
        if not set(child_fields) <= set(cs["header"]) or not set(parent_fields) <= set(ps["header"]):
            raise ValidationFailure("Relation field is absent from the inspected source table.")
        path = self.root / f"relations-{uuid4().hex}.sqlite"
        db = sqlite3.connect(path)
        db.execute("PRAGMA cache_size=-8192")
        db.execute("PRAGMA journal_mode=OFF")
        db.execute("CREATE TABLE parents(k TEXT PRIMARY KEY,n INTEGER,children INTEGER DEFAULT 0)")
        metrics = {"parent_rows": 0, "parent_blank_keys": 0, "child_rows": 0, "child_blank_keys": 0,
                   "child_all_blank_keys": 0, "child_partial_blank_keys": 0,
                   "parent_invalid_keys": 0, "child_invalid_keys": 0,
                   "matched_children": 0, "unmatched_children": 0, "ambiguous_parent_children": 0,
                   "projected_inner_join_rows": 0, "join_extra_rows": 0}
        diagnostics = []

        def key_state(values):
            if any(isinstance(value, (list, dict, bool)) for value in values):
                return "invalid"
            empty = [_is_blank(value) or isinstance(value, str) and not value.strip() for value in values]
            return "all_blank" if all(empty) else "partial_blank" if any(empty) else "complete"

        try:
            for locator, row in iter_table(parent, ps, self.check_cancelled):
                metrics["parent_rows"] += 1
                values = [row.get(k) for k in parent_fields]
                state = key_state(values)
                if state == "invalid":
                    metrics["parent_invalid_keys"] += 1
                elif state != "complete":
                    metrics["parent_blank_keys"] += 1
                else:
                    db.execute("INSERT INTO parents(k,n) VALUES(?,1) ON CONFLICT(k) DO UPDATE SET n=n+1", (_json(values),))
            for locator, row in iter_table(child, cs, self.check_cancelled):
                metrics["child_rows"] += 1
                values = [row.get(k) for k in child_fields]
                state = key_state(values)
                if state == "invalid":
                    metrics["child_invalid_keys"] += 1
                    continue
                if state != "complete":
                    metrics["child_blank_keys"] += 1
                    metrics["child_" + state + "_keys"] += 1
                    continue
                key = _json(values)
                found = db.execute("SELECT n FROM parents WHERE k=?", (key,)).fetchone()
                if found is None:
                    metrics["unmatched_children"] += 1
                    if len(diagnostics) < 5:
                        diagnostics.append({"row_locator": locator, "reason": "missing_parent", "key_values_withheld": True})
                else:
                    # Count references even when the parent is ambiguous. A
                    # referenced duplicate group is not an unreferenced key.
                    db.execute("UPDATE parents SET children=children+1 WHERE k=?", (key,))
                    metrics["projected_inner_join_rows"] += found[0]
                    metrics["join_extra_rows"] += found[0] - 1
                    metrics["ambiguous_parent_children" if found[0] != 1 else "matched_children"] += 1
            metrics["duplicate_parent_key_groups"] = db.execute("SELECT count(*) FROM parents WHERE n>1").fetchone()[0]
            metrics["max_children_per_parent"] = db.execute("SELECT COALESCE(max(children),0) FROM parents").fetchone()[0]
            metrics["parents_without_children"] = db.execute("SELECT count(*) FROM parents WHERE children=0").fetchone()[0]
            valid = not any(metrics[k] for k in ("parent_blank_keys", "parent_invalid_keys", "child_invalid_keys",
                "child_partial_blank_keys", "unmatched_children", "ambiguous_parent_children", "duplicate_parent_key_groups")) and (allow_blank or not metrics["child_all_blank_keys"])
            return {"child_file_id": child_file_id, "parent_file_id": parent_file_id, "child_fields": child_fields,
                    "parent_fields": parent_fields, "metrics": metrics, "structurally_valid": valid,
                    "measurement_version": "relation-cardinality-v2", "complete": True,
                    "key_policy": "Exact scalar values; blank includes whitespace-only strings; optional means all components blank. No normalization or inferred null sentinels.",
                    "parent_count_scope": "Distinct nonblank valid parent key groups; duplicates are counted once in parents_without_children.",
                    "relationship_semantics_require_evidence": True, "diagnostics": diagnostics}
        finally:
            db.close()
            path.unlink(missing_ok=True)

    def read_document(self, file_id, table_id=None, max_chars=20000, offset=0, search=None, locator=None):
        if type(max_chars) is not int or not 100 <= max_chars <= 50000:
            raise ValidationFailure("Document response bound is 100–50000 characters.")
        if type(offset) is not int or not 0 <= offset <= MAX_DOCUMENT_TEXT or (search is not None and (not isinstance(search, str) or not 1 <= len(search) <= 300)):
            raise ValidationFailure("Document offset/search is outside its bounded range.")
        file = self._file(file_id)
        path, kind = Path(file["path"]), detect_format(file)
        # A CSV renamed .txt must not become a route for sending complete
        # personal records as "documentation". Actual delimited structure wins.
        delimited = False
        if kind == "csv":
            try:
                candidates = detect_tables(file)
                if candidates and len(candidates[0]["header"]) > 1:
                    rows = iter_table(file, candidates[0])
                    try:
                        delimited = next(rows, None) is not None
                    finally:
                        rows.close()
            except (NeedsInput, ValidationFailure):
                pass
        text = ""
        metadata = None
        dictionary_basis = None
        extraction = 'bounded-local-document-v1'
        if kind == "pdf":
            if file["size"] > 16 * 1024**2:
                raise ValidationFailure("PDF exceeds the 16-MiB source-document bound.")
            from .parser_guard import call
            pieces = call('pdf', [str(path)], self.check_cancelled)
            text = "\n\n".join(pieces)
        elif kind in {"xlsx", "xls"} or delimited or Path(file["name"]).suffix.lower() == ".csv":
            spec = self._table(file, table_id)
            from .table_classification import dictionary_review
            inventory = []
            for other in self.files:
                self.check_cancelled()
                other = self._file(other['id'])
                if other.get('evidence_url') or other.get('role') == 'public_evidence':
                    continue
                if detect_format(other) not in {'csv', 'xlsx', 'xls', 'json'}:
                    continue
                try:
                    inventory.extend((other, table) for table in detect_tables(other, check_cancelled=self.check_cancelled))
                except (NeedsInput, ValidationFailure):
                    continue
            review = dictionary_review(file, spec, inventory, self.check_cancelled)
            if not review:
                raise NeedsInput("This worksheet is not an identified dictionary; use aggregate profiling for data tables.")
            dictionary_basis = review
            pieces = ["\t".join(spec["header"])]
            for number, (_, row) in enumerate(iter_table(file, spec, self.check_cancelled), 1):
                if number > 10000:
                    raise ValidationFailure("Dictionary exceeds the 10000-row document bound.")
                pieces.append("\t".join(str(row.get(h) or "") for h in spec["header"]))
            text = "\n".join(pieces)
            extraction = 'schema-linked-dictionary-text-v1'
        else:
            if file["size"] > MAX_DOCUMENT_TEXT:
                raise ValidationFailure("Text document exceeds the 4-MiB extraction bound.")
            try:
                text = path.read_text(encoding="utf-8-sig")
            except UnicodeError as exc:
                raise NeedsInput("Document encoding needs an explicit publisher specification.") from exc
            if kind == "json":
                try:
                    value = json.loads(text)
                except ValueError as exc:
                    raise ValidationFailure("Invalid JSON source document.") from exc
                if isinstance(value, list) or isinstance(value, dict) and any(isinstance(value.get(k), list) for k in ("features", "records", "data", "objectIds")):
                    from .geometry_evidence import document_projection
                    projected = document_projection(value) if file.get('role') == 'public_evidence' and file.get('receipt_path') else None
                    if projected is None:
                        raise NeedsInput("JSON records are data, not a documentation tool response; use profile_dataset.")
                    value = projected
                    extraction = 'bounded-public-geometry-metadata-v1'
                def metadata_only(node):
                    if isinstance(node, dict):
                        return {k: metadata_only(v) for k, v in node.items() if k not in {"cachedContents", "cached_content", "sampleRows"}
                                and not (k in {"features", "records", "rows", "objectIds", "data"} and isinstance(v, list))}
                    if isinstance(node, list):
                        return [metadata_only(v) for v in node]
                    return node
                value = metadata_only(value)
                metadata = value
                text = json.dumps(value, ensure_ascii=False, indent=2)
            elif text.lstrip().startswith(("<!DOCTYPE", "<!doctype", "<html", "<HTML")):
                parser = _TextHTML()
                parser.feed(text)
                text = "".join(parser.parts)
        if not text.strip():
            raise NeedsInput("No extractable text is available; a scanned document needs an accessible text source.")
        if len(text) > MAX_DOCUMENT_TEXT:
            raise ValidationFailure("Extracted documentation exceeds the text bound.")
        directory = self.root / "documents"
        directory.mkdir(exist_ok=True)
        document_id = "doc-" + file["sha256"]
        if dictionary_basis:
            document_id += '-' + hashlib.sha256(dictionary_basis['table_id'].encode()).hexdigest()[:16]
        text_path = directory / f"{document_id}.txt"
        encoded = text.encode("utf-8")
        if text_path.exists() and text_path.read_bytes() != encoded:
            raise ValidationFailure("Immutable document extraction changed.")
        if not text_path.exists():
            text_path.write_bytes(encoded)
            text_path.chmod(0o400)
        url = file.get("evidence_url", file.get("url"))
        receipt = {"document_id": document_id, "file_id": file_id, "url": url, "final_url": url,
                   "sha256": file["sha256"], "text_sha256": hashlib.sha256(encoded).hexdigest(),
                   "text_path": str(text_path), "content_path": str(path), "fetched_at": file.get("fetched_at"),
                   "official": official_host(urlsplit(url).hostname) if url else False,
                   "receipt_path": file.get("receipt_path"),
                   "extraction": extraction, "untrusted_evidence": True}
        if dictionary_basis:
            receipt['dictionary_review'] = dictionary_basis
        receipt_path = directory / f"{document_id}.json"
        if not receipt_path.exists():
            receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
            receipt_path.chmod(0o400)
        public = {k: v for k, v in receipt.items() if not k.endswith("_path")}
        if locator is not None:
            from .evidence_references import reference, assert_documentation_locator
            from .metadata_extractors import MetadataError
            try:
                raw = path.read_bytes()
                assert_documentation_locator(raw, file['sha256'], locator)
                citation = reference(raw, file['sha256'], document_id, locator)
            except MetadataError as exc:
                raise NeedsInput(str(exc), [], {'reference_error': exc.code}) from exc
            return {**public, 'text': citation['quote'], 'reference': citation,
                    'citation_policy': 'Copy this hash-pinned reference into contract evidence; the host rechecks its location and field scope. It is not semantic approval.',
                    'truncated': False, '__documents': [receipt]}
        matches = [m.start() for m in re.finditer(re.escape(search), text, re.I)][:100] if search else []
        if search and matches:
            offset = max(0, next((m for m in matches if m >= offset), matches[0]) - 200)
        # Targeted searches return a small context page. Full text remains
        # immutable and accessible through explicit offset/max_chars calls.
        page_size = min(max_chars, 4000) if search else max_chars
        end = min(len(text), offset + page_size)
        fields = _metadata_fields(metadata, text, document_id, url, search, offset, end) if metadata is not None else []
        citations = [field["citation"] for field in fields if "citation" in field][:3]
        if not citations:
            positions = [m for m in matches if offset <= m < end][:3] or [offset]
            for position in positions:
                start = max(offset, position - 160)
                citation = _citation(text, start, min(end, start + 1000), document_id, url)
                if len(citation["quote"]) >= 12 and citation not in citations:
                    citations.append(citation)
        for field in fields:
            citation = field.pop("citation", None)
            field["citation_span_index"] = citations.index(citation) if citation in citations else None
        return {**public, "text": text[offset:end], "offset": offset, "next_offset": end, "match_offsets": matches,
                "citation_spans": citations, "field_definitions": fields,
                "citation_policy": "Copy document_id and quote exactly; these are text locations, not semantic approval. No ID abbreviations or inferred wording.",
                "truncated": end < len(text),
                "total_characters": len(text), "__documents": [receipt]}


PARSER_SCHEMA = {"type": "object", "properties": {"encoding": {"type": "string"}, "delimiter": {"type": "string"},
    "record_path": {"type": "string"}, "json_kind": {"type": "string"},
    "header_row": {"type": "integer", "minimum": 1, "maximum": 64},
    "parser_plan": {"type": "object"}}, "additionalProperties": False}
TOOL_SPECS = [
    {"type": "function", "name": "inspect_bundle", "description": "Identify uploaded formats/tables, safely expand ZIPs, return file IDs, headers and parser specifications. No data records are sent.",
     "parameters": {"type": "object", "properties": {}, "additionalProperties": False}},
    {"type": "function", "name": "profile_dataset", "description": "Profile a complete source table using a disk index. Returns exact counts/types/nulls/distincts and bounded non-personal categories, no row samples. Structure alone does not approve semantics.",
     "parameters": {"type": "object", "properties": {"file_id": {"type": "string"}, "table_id": {"type": "string"}, "parser": PARSER_SCHEMA,
         "max_rows": {"type": "integer", "minimum": 1, "maximum": 1000000}}, "required": ["file_id"], "additionalProperties": False}},
    {"type": "function", "name": "inspect_relations", "description": "Measure composite PK/FK completeness, duplicates, orphan coverage and join row multiplication across full tables without disclosing key values. allow_blank permits only entirely blank child keys; partial keys remain invalid. Structural matches do not authorize lookup semantics or publication.",
     "parameters": {"type": "object", "properties": {"child_file_id": {"type": "string"}, "parent_file_id": {"type": "string"},
         "child_fields": {"type": "array", "items": {"type": "string"}}, "parent_fields": {"type": "array", "items": {"type": "string"}},
         "child_table_id": {"type": "string"}, "parent_table_id": {"type": "string"}, "allow_blank": {"type": "boolean"},
         "child_parser": PARSER_SCHEMA, "parent_parser": PARSER_SCHEMA},
         "required": ["child_file_id", "parent_file_id", "child_fields", "parent_fields"], "additionalProperties": False}},
    {"type": "function", "name": "read_document", "description": "Read source documentation with search/pagination, or an exact locator: json-pointer {kind,pointer}; xml-expanded-path {kind,segments:[[expandedTag,childIndex],...]}; pdf-text-range {kind,page_from,page_to,start,end} (1-based pages, text offsets in pages joined with two newlines). A locator returns a hash-pinned reference for contract evidence instead of requiring a long quote. Source/field scope is independently checked; no semantic approval.",
     "parameters": {"type": "object", "properties": {"file_id": {"type": "string"}, "table_id": {"type": "string"},
         "max_chars": {"type": "integer", "minimum": 100, "maximum": 50000}, "offset": {"type": "integer", "minimum": 0},
         "search": {"type": "string", "maxLength": 300}, "locator": {"type": "object"}}, "required": ["file_id"], "additionalProperties": False}},
]


def dispatch(name, arguments, files, work_dir, check_cancelled=lambda: None):
    if name not in {item["name"] for item in TOOL_SPECS}:
        raise ValidationFailure("Unknown intake tool.")
    return getattr(IntakeTools(files, work_dir, check_cancelled), name)(**arguments)
