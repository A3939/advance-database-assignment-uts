"""Register sources and load native records on the caller's PostgreSQL connection."""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from uuid import UUID, uuid4

from .config import ID, SHA256
from .models import IntakeError


SOURCE_FIELDS = ("source_id", "jurisdiction_code", "source_name", "publisher")
RESOURCE_FIELDS = ("resource_id", "source_id", "resource_role", "entity_kind")
L1_FIELDS = {"source_id", "resource_id", "file_sha256", "parser_version", "row_locator", "payload"}
FILE_FIELDS = {"source_id", "resource_id", "resource_role", "entity_kind", "file_sha256",
               "parser_version", "locator_version", "format", "encoding", "sheet", "header_row", "header", "raw_count"}
VERSION = re.compile(r"[A-Za-z0-9._-]+\Z")


def _text(value, field, *, allow_empty=False):
    if not isinstance(value, str) or "\x00" in value or (not allow_empty and not value.strip()):
        raise IntakeError("RAW_INPUT", "Expected native text without NUL", field=field)
    try:
        value.encode("utf-8")
    except UnicodeError as exc:
        raise IntakeError("RAW_INPUT", "Text is not valid UTF-8", field=field) from exc
    return value


def _fields(value, required, allowed=None):
    if not isinstance(value, dict) or not required <= value.keys() or value.keys() - (allowed or required):
        raise IntakeError("RAW_INPUT", "Missing or unexpected fields", expected=sorted(required))


def _identifier(value, kind):
    prefix = "official_" if kind == "official" else "syn_"
    if not isinstance(value, str) or not ID.fullmatch(value) or not value.startswith(prefix) or value == prefix:
        raise IntakeError("RAW_NAMESPACE", "Source and resource IDs must match dataset_kind", dataset_kind=kind)


def _json_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise IntakeError("RAW_INPUT", "Duplicate JSON member", field=key)
        result[key] = value
    return result


def _nonfinite(value):
    raise IntakeError("RAW_INPUT", "Non-finite JSON number", value=value)


def _decode(data):
    try:
        if isinstance(data, bytes):
            data = data.decode("utf-8")
        return json.loads(data, object_pairs_hook=_json_object, parse_constant=_nonfinite)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise IntakeError("RAW_INPUT", "Invalid UTF-8 JSON input") from exc


def _read(path):
    try:
        return _decode(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError) as exc:
        raise IntakeError("RAW_INPUT", "Cannot read prepared input", path=str(path)) from exc


def _sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _position(file, locator):
    _text(locator, "row_locator")
    if file["format"] == "csv":
        if re.fullmatch(r"csv:[1-9][0-9]*", locator):
            return int(locator[4:])
    else:
        position = _decode(locator)
        if (isinstance(position, list) and len(position) == 2 and position[0] == file["sheet"]
                and type(position[1]) is int and position[1] >= 2
                and json.dumps(position, ensure_ascii=False) == locator):
            return position[1]
    raise IntakeError("RAW_INPUT", "Invalid native row locator", resource_id=file["resource_id"], row_locator=locator)


@dataclass(frozen=True)
class RawRecordResult:
    raw_record_id: UUID
    inserted: bool


@dataclass(frozen=True)
class RawLoadResult:
    run_id: str
    dataset_kind: str
    raw_count: int
    inserted_count: int
    reused_count: int


class RawLoader:
    """One caller-managed unit of work; creates no connection or transaction.

    After any exception the caller must roll back the unit, including registration.
    Identical registration is reusable; metadata changes need an explicit review.
    """

    def __init__(self, connection, *, dataset_kind, sources, files):
        self.connection = connection
        self._check_connection()
        if dataset_kind not in {"official", "synthetic"}:
            raise IntakeError("RAW_NAMESPACE", "Unknown dataset_kind")
        self.dataset_kind = dataset_kind
        self.sources, self.files = {}, {}
        for source in sources:
            _fields(source, set(SOURCE_FIELDS), set(SOURCE_FIELDS) | {"release_label", "release_scope", "resource_ids"})
            for field in SOURCE_FIELDS:
                _text(source[field], field)
            _identifier(source["source_id"], dataset_kind)
            if source["source_id"] in self.sources:
                raise IntakeError("RAW_INPUT", "Duplicate source registration")
            self.sources[source["source_id"]] = dict(source)
        for file in files:
            _fields(file, FILE_FIELDS)
            for field in RESOURCE_FIELDS + ("parser_version", "locator_version", "file_sha256"):
                _text(file[field], field)
            for field in ("source_id", "resource_id"):
                _identifier(file[field], dataset_kind)
            if file["source_id"] not in self.sources or file["resource_id"] in self.files:
                raise IntakeError("RAW_INPUT", "Unregistered source or repeated resource")
            if file["entity_kind"] not in {"crash", "unit", "person_raw", "node_raw"}:
                raise IntakeError("RAW_INPUT", "Unsupported entity_kind")
            if not SHA256.fullmatch(file["file_sha256"]) or not VERSION.fullmatch(file["parser_version"]):
                raise IntakeError("RAW_INPUT", "Invalid file hash or parser version")
            if type(file["raw_count"]) is not int or file["raw_count"] < 0 or type(file["header_row"]) is not int or file["header_row"] != 1:
                raise IntakeError("RAW_INPUT", "Invalid raw_count or header_row")
            header = file["header"]
            if not isinstance(header, list) or not header:
                raise IntakeError("RAW_INPUT", "Expected an ordered header list")
            for field in header:
                _text(field, "header")
            if len(set(header)) != len(header):
                raise IntakeError("RAW_INPUT", "Repeated header field")
            if file["format"] == "csv":
                valid = file["encoding"] == "utf-8" and file["sheet"] is None and file["locator_version"] == "csv-logical-v1"
            elif file["format"] == "xlsx":
                _text(file["sheet"], "sheet")
                valid = file["encoding"] is None and file["locator_version"] == "xlsx-physical-v1"
            else:
                valid = False
            if not valid:
                raise IntakeError("RAW_INPUT", "Unsupported native format or locator contract")
            self.files[file["resource_id"]] = {**file, "header": list(header)}
        if not self.files or set(self.sources) != {f["source_id"] for f in self.files.values()}:
            raise IntakeError("RAW_INPUT", "Every selected source needs its resources")
        for source in self.sources.values():
            if "resource_ids" in source:
                expected = {f["resource_id"] for f in self.files.values() if f["source_id"] == source["source_id"]}
                ids = source["resource_ids"]
                if not isinstance(ids, list) or any(not isinstance(i, str) for i in ids) or len(ids) != len(expected) or set(ids) != expected:
                    raise IntakeError("RAW_INPUT", "Source resource list does not match selected files")
        self._registered = False

    def _check_connection(self):
        if getattr(self.connection, "autocommit", None) is not False:
            raise IntakeError("RAW_AUTOCOMMIT", "Raw loading requires a caller-managed transaction with autocommit disabled")

    def register(self):
        self._check_connection()
        with self.connection.cursor() as cursor:
            for source in sorted(self.sources.values(), key=lambda s: s["source_id"]):
                values = tuple(source[f] for f in SOURCE_FIELDS)
                cursor.execute("""INSERT INTO meta.source (source_id, jurisdiction_code, source_name, publisher)
                                  VALUES (%s, %s, %s, %s) ON CONFLICT (source_id) DO NOTHING""", values)
                cursor.execute("""SELECT source_id, jurisdiction_code, source_name, publisher
                                  FROM meta.source WHERE source_id = %s""", (source["source_id"],))
                if cursor.fetchone() != values:
                    raise IntakeError("REGISTRATION_CONFLICT", "Existing source registration differs", source_id=source["source_id"])
            for file in sorted(self.files.values(), key=lambda f: f["resource_id"]):
                values = tuple(file[f] for f in RESOURCE_FIELDS)
                cursor.execute("""INSERT INTO meta.resource (resource_id, source_id, resource_role, entity_kind)
                                  VALUES (%s, %s, %s, %s) ON CONFLICT (resource_id) DO NOTHING""", values)
                cursor.execute("""SELECT resource_id, source_id, resource_role, entity_kind
                                  FROM meta.resource WHERE resource_id = %s""", (file["resource_id"],))
                if cursor.fetchone() != values:
                    raise IntakeError("REGISTRATION_CONFLICT", "Existing resource registration differs", resource_id=file["resource_id"])
        self._registered = True

    def load_record(self, record):
        self._check_connection()
        if not self._registered:
            raise IntakeError("RAW_REGISTRATION", "Register sources and resources before loading rows")
        _fields(record, L1_FIELDS)
        resource = record["resource_id"]
        if not isinstance(resource, str) or resource not in self.files:
            raise IntakeError("RAW_INPUT", "Record does not belong to a selected resource")
        file = self.files[resource]
        for field in ("source_id", "file_sha256", "parser_version"):
            if record[field] != file[field]:
                raise IntakeError("RAW_INPUT", "Record identity differs from file metadata", resource_id=resource, field=field)
        locator = record["row_locator"]
        _position(file, locator)
        payload = record["payload"]
        _fields(payload, set(file["header"]))
        for key, value in payload.items():
            if value is not None:
                _text(value, key, allow_empty=True)
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        identity = (resource, record["file_sha256"], record["parser_version"], locator)
        with self.connection.cursor() as cursor:
            cursor.execute("""INSERT INTO raw.record
                (raw_record_id, resource_id, source_id, file_sha256, parser_version, row_locator, payload)
                VALUES (%s::uuid, %s, %s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (resource_id, file_sha256, parser_version, row_locator) DO NOTHING
                RETURNING raw_record_id""",
                (str(uuid4()), resource, record["source_id"], record["file_sha256"], record["parser_version"], locator, encoded))
            inserted = cursor.fetchone()
            if inserted is not None:
                return RawRecordResult(UUID(str(inserted[0])), True)
            # A separate statement sees a concurrent winner at READ COMMITTED.
            cursor.execute("""SELECT raw_record_id, source_id, payload = %s::jsonb
                FROM raw.record WHERE resource_id = %s AND file_sha256 = %s
                AND parser_version = %s AND row_locator = %s""", (encoded, *identity))
            existing = cursor.fetchone()
            if existing is None:
                raise IntakeError("RAW_IDENTITY", "Conflicting record is no longer visible; roll back and retry the unit", resource_id=resource, row_locator=locator)
            if existing[1] != record["source_id"] or existing[2] is not True:
                raise IntakeError("RAW_PAYLOAD_CONFLICT", "Existing raw identity has a different source or payload",
                                  resource_id=resource, file_sha256=record["file_sha256"],
                                  parser_version=record["parser_version"], row_locator=locator,
                                  raw_record_id=str(existing[0]))
            return RawRecordResult(UUID(str(existing[0])), False)


class _PreparedRun:
    def __init__(self, run_dir):
        self.path = Path(run_dir).resolve()
        self.run = _read(self.path / "run.json")
        if not isinstance(self.run, dict) or self.run.get("status") != "prepared" or self.run.get("output_version") != "intake-output-v1":
            raise IntakeError("RAW_PREPARED", "Only completed intake-output-v1 runs can be loaded")
        self.kind = self.run.get("dataset_kind")
        if self.path.parent.name != "runs" or self.path.parent.parent.name != self.kind:
            raise IntakeError("RAW_PREPARED", "Keep the prepared run inside its dataset-kind output tree")
        self.root = self.path.parent.parent.parent
        catalog = _read(self.path / "files.json")
        _fields(catalog, {"files"})
        self.files = catalog["files"]
        provenance = _read(self.path / "provenance.json")
        _fields(provenance, {"run_id", "dataset_kind", "files"})
        if provenance.get("dataset_kind") != self.kind or provenance.get("run_id") != self.run.get("run_id"):
            raise IntakeError("RAW_PROVENANCE", "Provenance belongs to a different run")
        self.summaries = self._index(self.run.get("files"))
        self.provenance = self._index(provenance.get("files"))
        if not isinstance(self.files, list) or set(self._index(self.files)) != set(self.summaries) or set(self.summaries) != set(self.provenance):
            raise IntakeError("RAW_PREPARED", "Prepared resource lists disagree")

    @staticmethod
    def _index(items):
        if not isinstance(items, list) or any(not isinstance(x, dict) or not isinstance(x.get("resource_id"), str) for x in items):
            raise IntakeError("RAW_PREPARED", "Invalid prepared resource list")
        result = {x["resource_id"]: x for x in items}
        if len(result) != len(items):
            raise IntakeError("RAW_PREPARED", "Repeated prepared resource")
        return result

    def check_files(self):
        total = 0
        for file in self.files:
            rid, digest = file["resource_id"], file["file_sha256"]
            summary, provenance = self.summaries[rid], self.provenance[rid]
            expected_archive = f"{self.kind}/archive/sha256/{digest[:2]}/{digest}"
            expected_records = f"records/{rid}.jsonl"
            if (provenance.get("file_sha256") != digest or provenance.get("archive_relpath") != expected_archive
                    or summary.get("file_sha256") != digest or summary.get("records_path") != expected_records
                    or summary.get("header") != file["header"] or summary.get("raw_count") != file["raw_count"]):
                raise IntakeError("RAW_PROVENANCE", "Prepared metadata and provenance disagree", resource_id=rid)
            archive, records = self.root / expected_archive, self.path / expected_records
            if archive.is_symlink() or not archive.resolve().is_relative_to(self.root) or records.is_symlink() or not records.resolve().is_relative_to(self.path):
                raise IntakeError("RAW_PROVENANCE", "Prepared paths must stay inside their output tree", resource_id=rid)
            try:
                if archive.stat().st_size != summary.get("input_bytes") or _sha256(archive) != digest:
                    raise IntakeError("RAW_PROVENANCE", "Archived source bytes have changed", resource_id=rid)
                if _sha256(records) != summary.get("records_sha256"):
                    raise IntakeError("RAW_PREPARED", "Prepared record bytes have changed", resource_id=rid)
            except OSError as exc:
                raise IntakeError("RAW_PREPARED", "Prepared records or source archive are missing", resource_id=rid) from exc
            total += file["raw_count"]
        if self.run.get("raw_count") != total:
            raise IntakeError("RAW_PREPARED", "Prepared total differs from file counts")

    def records(self):
        for file in self.files:
            rid = file["resource_id"]
            summary = self.summaries[rid]
            digest, count, previous = hashlib.sha256(), 0, 0
            with (self.path / summary["records_path"]).open("rb") as stream:
                for line in stream:
                    digest.update(line)
                    record = _decode(line)
                    _fields(record, L1_FIELDS)
                    if record["resource_id"] != rid:
                        raise IntakeError("RAW_PREPARED", "Row is in the wrong resource file", resource_id=rid)
                    # A prepared file must retain each position once, in source order.
                    locator = record["row_locator"]
                    position = _position(file, locator)
                    if position <= previous:
                        raise IntakeError("RAW_PREPARED", "Repeated or out-of-order native locator", resource_id=rid, row_locator=locator)
                    previous, count = position, count + 1
                    yield record
            if count != file["raw_count"] or digest.hexdigest() != summary["records_sha256"]:
                raise IntakeError("RAW_PREPARED", "Prepared records changed during loading or have an incorrect count", resource_id=rid)


def load_prepared(connection, run_dir, sources, *, on_record=None):
    """Load one prepared run without committing; callbacks also see uncommitted IDs.

    Keep the complete intake output tree so file hashes still resolve to archives.
    The caller must roll back on any exception, including callback or stream errors.
    """
    run = _PreparedRun(run_dir)
    loader = RawLoader(connection, dataset_kind=run.kind, sources=sources, files=run.files)
    run.check_files()
    loader.register()
    inserted = reused = 0
    with closing(run.records()) as records:
        for record in records:
            result = loader.load_record(record)
            inserted += result.inserted
            reused += not result.inserted
            if on_record is not None:
                on_record(record, result)
    return RawLoadResult(run.run["run_id"], run.kind, inserted + reused, inserted, reused)
