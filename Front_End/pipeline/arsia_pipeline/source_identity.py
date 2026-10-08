"""Canonical identities derived from independently admitted official evidence."""
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit, urlunsplit, parse_qsl, urlencode

from .config import ROOT
from .errors import NeedsInput, ValidationFailure

SOCRATA = re.compile(r"^[a-z0-9]{4}-[a-z0-9]{4}$")


def url_identity(url, *, allow_delegated=False, preserve_host=False):
    """Parse a provider identity; delegated use requires an upstream proof.

    Existing registry identities retain their historical www normalization.
    New evidence graphs request exact hosts and separately record delegation;
    merely enabling this parser never establishes publisher authority.
    """
    if not isinstance(url, str):
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if not preserve_host:
        host = host.removeprefix("www.")
    try:
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme != "https" or not host or (not allow_delegated and not host.endswith(".gov.au")) or parsed.username or parsed.password or port not in (None, 443):
        return None
    # Dataset identity is the layer; query scope remains in the separately
    # verified representation proof. Unsupported queries never normalize away.
    from .arcgis_query import parse
    from .metadata_extractors import MetadataError
    try:query=parse(url)
    except MetadataError:return None
    if query:
        return url_identity(query['layer'],allow_delegated=allow_delegated,preserve_host=preserve_host)
    parts = [unquote(part) for part in parsed.path.rstrip("/").split("/") if part]
    for index, part in enumerate(parts):
        if part.lower() in {"featureserver", "mapserver"} and len(parts) == index+2 and parts[-1].isdigit():
            # Service paths can be case-sensitive; retain their spelling.
            service = "/".join(parts[:index] + [part.lower(), str(int(parts[-1]))])
            return {"kind": "arcgis_layer", "host": host, "dataset": service}
    if len(parts) >= 3 and parts[-3:] == ["3", "action", "package_show"]:
        identity = parse_qs(parsed.query).get("id", [None])[0]
        if identity:
            return {"kind": "ckan", "host": host, "dataset": identity}
    if "dataset" in parts:
        position = parts.index("dataset")
        if position+1 < len(parts) and parts[position+1]:
            return {"kind": "ckan", "host": host, "dataset": parts[position+1]}
    # Match actual provider endpoints, not an ID-looking directory anywhere
    # in a path (or a CKAN package whose name happens to have that shape).
    candidate = None
    if len(parts) >= 3 and parts[:2] == ['api', 'views']:
        if len(parts) == 3 or len(parts) == 4 and parts[3].lower() in {'rows.csv', 'rows.json', 'rows.xml', 'rows.rdf'}:
            candidate = parts[2]
    elif len(parts) == 2 and parts[0] in {'resource', 'd'}:
        candidate = parts[1]
    elif len(parts) == 3 and parts[0] not in {'api', 'resource', 'dataset', 'data'}:
        candidate = parts[-1]  # Socrata category/title/<dataset> display page.
    if candidate:
        code = re.sub(r"\.(?:json|csv|geojson|xml|rdf)$", "", candidate, flags=re.I).lower()
        if SOCRATA.fullmatch(code):
            return {"kind": "socrata", "host": host, "dataset": code}
    # Other providers may expose a specific official resource/page without a
    # known portal API. Only an identical admitted source URL can bind it.
    if parts and parts[-1].lower() not in {"data", "catalog", "catalogue", "dataset", "datasets", "index.html"} and not re.search(r"\.(pdf|md|txt|docx?)$", parts[-1], re.I):
        query = urlencode(sorted(parse_qsl(parsed.query, keep_blank_values=True)))
        return {"kind": "official_url", "host": host, "dataset": "/" + "/".join(parts) + ("?"+query if query else "")}
    # A generic portal or document URL is not a dataset identity.
    return None


def _ckan_aliases(contract, proof):
    """Read only hash-verified receipts already admitted for source identity."""
    aliases = {}
    proof_hashes = {entry.get("sha256") for entry in proof}
    for document in contract.get("documents", []):
        if document.get("sha256") not in proof_hashes or not document.get("receipt_path"):
            continue
        receipt_path = Path(document["receipt_path"]).resolve()
        if not receipt_path.is_relative_to(ROOT.resolve()) or not receipt_path.is_file():
            continue
        receipt = json.loads(receipt_path.read_text())
        identity = url_identity(receipt.get("final_url"))
        if not identity or identity["kind"] != "ckan" or receipt.get("status") != "fetched":
            continue
        digest = receipt.get("sha256")
        if digest != document.get("sha256"):
            continue
        content = receipt_path.parent/"sha256"/str(digest)
        if not content.is_file() or content.stat().st_size > 4*1024**2 or hashlib.sha256(content.read_bytes()).hexdigest() != digest:
            continue
        try:
            envelope = json.loads(content.read_text())
        except (ValueError, UnicodeError):
            continue
        value = envelope.get("result", {})
        if envelope.get("success") is not True or not isinstance(value, dict):
            continue
        identifier, name = value.get("id"), value.get("name")
        if isinstance(identifier, str) and isinstance(name, str) and identifier and name:
            aliases[(identity["host"], identifier)] = identifier
            aliases[(identity["host"], name)] = identifier
    return aliases


def canonical_source_identity(result, contract):
    from .independent_versions import bind_identity
    return bind_identity(_dataset_identity(result, contract), result, contract)


def _dataset_identity(result, contract):
    """Return one provider identity; never trust a model-provided alias list.

    Full QA owns source proof. This function additionally checks that the
    registered dataset URI resolves to that admitted provider identity.
    """
    if result.get("admission", {}).get("status") != "admitted":
        raise ValidationFailure("Source identity binding requires full independent admission")
    return _identity_from_proof(result["admission"].get("evidence", {}), contract)


def _identity_from_proof(evidence, contract):
    """Resolve provider identity from host-checked evidence; never an admission.

    Preflight may propose a namespace using this pure resolver. Registration
    still calls _dataset_identity and requires full independent admission.
    """
    proof = evidence.get("source_identity", [])
    urls = [entry.get("url") for entry in proof if isinstance(entry, dict)]
    aliases = _ckan_aliases(contract, proof)
    def canonical(value):
        if value and value["kind"] == "ckan":
            value = {**value, "dataset": aliases.get((value["host"], value["dataset"]), value["dataset"])}
        return value
    identities = [canonical(url_identity(url)) for url in urls]
    identities = {json.dumps(value, sort_keys=True, separators=(",", ":")): value for value in identities if value}
    proposed = canonical(url_identity(contract.get("source", {}).get("dataset_url")))
    if not proposed:
        # New external resources require the exact publisher-delegation proof
        # produced by current full QA. Historical URL-only admissions do not
        # gain this permission merely because the provider parser recognizes it.
        graph = evidence.get('grounding', {}).get('evidence_graph', {})
        delegated = url_identity(contract.get('source', {}).get('dataset_url'), allow_delegated=True, preserve_host=True)
        from .evidence_graph import representation, VERSION as GRAPH_VERSION
        source_url = representation(contract.get('source', {}).get('dataset_url'))
        nodes = {node['document_id']: node for node in graph.get('nodes', [])}
        targets = {key for key, node in nodes.items() if node.get('url') == source_url}
        edges = graph.get('edges', [])
        if (delegated and graph.get('version') in {'scoped-evidence-graph-v1', GRAPH_VERSION} and graph.get('source_identity') == delegated
                and graph.get('source_anchor_documents')
                and any(edge.get('predicate') in {'distributes_resource', 'describes_resource'}
                        and edge.get('to') in targets and edge.get('from') in graph.get('authorized_documents', []) for edge in edges)):
            encoded = json.dumps(delegated, sort_keys=True, separators=(',', ':'))
            return {'identity_key': 'official-dataset-' + hashlib.sha256(encoded.encode()).hexdigest(), **delegated}
    if not proposed:
        raise NeedsInput("The official dataset identity is not recognized for registry deduplication. Supply its specific official dataset or resource URL; a generic portal or manual is not sufficient.")
    encoded = json.dumps(proposed, sort_keys=True, separators=(",", ":"))
    if encoded not in identities:
        raise NeedsInput("The proposed dataset URL does not match the independently admitted source-identity evidence.",
                         details={"proposed_dataset": proposed, "evidenced_datasets": list(identities.values())})
    return {"identity_key": "official-dataset-" + hashlib.sha256(encoded.encode()).hexdigest(), **proposed}


def bind_identity(conn, source_id, source_version_id, identity):
    """Call inside the same registry transaction as immutable version inserts."""
    from psycopg.types.json import Jsonb
    conn.execute("""INSERT INTO source_identities(identity_key,source_id,first_source_version_id,identity)
        VALUES(%s,%s,%s,%s) ON CONFLICT(identity_key) DO NOTHING""",
        (identity["identity_key"], source_id, source_version_id, Jsonb(identity)))
    existing = conn.execute("SELECT source_id FROM source_identities WHERE identity_key=%s", (identity["identity_key"],)).fetchone()
    if existing["source_id"] != source_id:
        raise NeedsInput("This official dataset already has a stable source identity. Use the existing source_id and revalidate the candidate instead of creating a duplicate source.",
                         details={"existing_source_id": existing["source_id"], "dataset_identity": identity})


def backfill_identities(conn):
    """Bind already-admitted versions when upgrading an existing local DB."""
    rows = conn.execute("""SELECT s.id,s.source_id,s.contract,s.admission FROM source_versions s
        WHERE s.admission->>'status'='admitted'
          AND NOT EXISTS(SELECT 1 FROM source_identities i WHERE i.first_source_version_id=s.id)
        ORDER BY s.created_at,s.id""").fetchall()
    for row in rows:
        # Pre-autonomy and synthetic test admissions have no official identity
        # proof. They do not acquire one merely because migration ran.
        if not row["admission"].get("evidence", {}).get("source_identity"):
            continue
        contract = dict(row["contract"])
        if contract.get('version_scope'):
            value = contract['version_scope']
            key = value['family_identity_key'] + ':independent:' + value['input_sha256']
            existing = conn.execute('SELECT source_id FROM source_identities WHERE identity_key=%s', (key,)).fetchone()
            if not existing or existing['source_id'] != row['source_id']:
                raise NeedsInput('Independent version identity receipt is missing; preserve the registry for engineering review.')
            continue  # Created atomically by this policy; never infer an alias.
        try:
            identity = canonical_source_identity({"admission": row["admission"]}, contract)
        except NeedsInput:
            # CKAN UUID/name equivalence may require its original host receipt.
            checkpoint = conn.execute("""SELECT a.checkpoint FROM agent_sessions a JOIN batches b ON b.job_id=a.job_id
                WHERE b.source_version_id=%s ORDER BY b.created_at LIMIT 1""", (row["id"],)).fetchone()
            if not checkpoint:
                raise
            contract["documents"] = list(checkpoint["checkpoint"].get("documents", {}).values())
            identity = canonical_source_identity({"admission": row["admission"]}, contract)
        bind_identity(conn, row["source_id"], row["id"], identity)
