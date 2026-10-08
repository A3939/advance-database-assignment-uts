"""Public evidence retrieval with pinned DNS addresses and immutable receipts.

Downloaded text is untrusted evidence, never executable instructions. No tokens,
cookies, proxies or private host access are delegated to generated adapters.
"""
from __future__ import annotations

from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from collections import deque
import hashlib
from html.parser import HTMLParser
import http.client
import ipaddress
import json
from pathlib import Path
import re
import socket
import ssl
import time
import threading
from urllib.parse import quote, unquote, urlencode, urljoin, urlsplit, urlunsplit
from uuid import uuid4

from .errors import BudgetExhausted, ImportCancelled, NeedsInput, ValidationFailure

MAX_DOWNLOAD = 512 * 1024**2
MAX_REDIRECTS = 5
OFFICIAL_SEEDS = (
    ("SA", "https://data.sa.gov.au/data/api/3/action/package_show?id=road-crash-data"),
    ("ACT", "https://www.data.act.gov.au/api/views/6jn4-m8rx.json"),
    ("TAS", "https://data.stategrowth.tas.gov.au/ags/rest/services/PUBLIC/CDM_CRASH/FeatureServer/0?f=pjson"),
    ("WA", "https://catalogue.data.wa.gov.au/dataset"),
    ("NT", "https://data.nt.gov.au/dataset/"),
    ("NSW", "https://data.nsw.gov.au/data/dataset"),
    ("VIC", "https://discover.data.vic.gov.au/dataset"),
    ("QLD", "https://www.data.qld.gov.au/dataset"),
)


def official_host(host):
    return bool(host) and (host.lower().endswith(".gov.au") or host.lower() == "gov.au")


def validate_public_url(url, resolver=socket.getaddrinfo):
    """Validate URL and *all* DNS answers; return a connect address, not a name.

    The caller connects to a returned numeric address while retaining the
    original hostname for TLS verification/SNI. Re-resolution cannot bypass
    this decision. Every redirect is separately validated.
    """
    if not isinstance(url, str) or len(url) > 8192 or any(ord(c) < 33 for c in url):
        raise ValidationFailure("Public URL is malformed or contains control characters.")
    parts = urlsplit(url)
    try:
        port = parts.port
    except ValueError as exc:
        raise ValidationFailure("Invalid public URL port.") from exc
    if parts.scheme != "https" or not parts.hostname or parts.username or parts.password or port not in (None, 443):
        raise ValidationFailure("Public retrieval allows credential-free HTTPS URLs on port 443 only.")
    host = parts.hostname.rstrip(".").lower()
    if host in {"localhost", "metadata.google.internal"} or host.endswith((".localhost", ".local", ".internal")):
        raise ValidationFailure("Local and metadata hosts are prohibited.")
    try:
        answers = resolver(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise NeedsInput("Public source DNS resolution failed; the source may be temporarily unavailable.") from exc
    addresses = sorted({answer[4][0].split("%", 1)[0] for answer in answers})
    if not addresses:
        raise ValidationFailure("Public host has no usable address.")
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if not ip.is_global or ip.is_multicast or ip.is_unspecified:
            raise ValidationFailure("Public retrieval rejected a local, private, reserved or metadata address.")
    # Fragments do not form part of the fetched resource/evidence identity.
    normalized = urlunsplit(("https", parts.netloc, parts.path or "/", parts.query, ""))
    return normalized, host, addresses


class _PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self, host, address, timeout, context):
        super().__init__(host, port=443, timeout=timeout, context=context)
        self.address = address

    def connect(self):
        raw = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def _context():
    # Use OS trust when present (including the macOS framework Python case),
    # retaining certificate and hostname verification. Never disable TLS checks.
    ca = Path("/etc/ssl/cert.pem")
    return ssl.create_default_context(cafile=str(ca) if ca.is_file() else None)


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            href = dict(attrs).get("href")
            if href and len(self.links) < 300:
                self.links.append(href)


class PublicSources:
    def __init__(self, work_dir, check_cancelled=lambda: None, *, resolver=socket.getaddrinfo, connection_factory=None, source_hints=None,
                 request_limits=None, charge_bytes=None):
        self.root = Path(work_dir).resolve() / "public-evidence"
        self.root.mkdir(parents=True, exist_ok=True)
        self.check_cancelled = check_cancelled
        self.resolver = resolver
        self.connection_factory = connection_factory or _PinnedHTTPS
        # Trusted orchestration may supply original filenames, never raw rows.
        self.source_hints = [str(value)[:240] for value in (source_hints or [])[:24]]
        self.request_limits = request_limits
        self.charge_bytes = charge_bytes
        self._charge_lock = threading.Lock()

    def fetch_public_source(self, url, max_bytes=16 * 1024**2, timeout_seconds=60):
        """Stream a public HTTPS resource, validating every hop and actual bytes."""
        if type(max_bytes) is not int or not 1 <= max_bytes <= MAX_DOWNLOAD:
            raise ValidationFailure("Public download size must be between 1 byte and 512 MiB.")
        if not isinstance(timeout_seconds, (int, float)) or not 1 <= timeout_seconds <= 300:
            raise ValidationFailure("Public download timeout must be between 1 and 300 seconds.")
        if self.request_limits:
            max_bytes, timeout_seconds = self.request_limits(max_bytes, timeout_seconds)
        started = time.monotonic()
        fetched_at = datetime.now(timezone.utc).isoformat()
        request_id = uuid4().hex
        temporary = self.root / f"{request_id}.partial"
        redirects = []
        current = url
        connection = None
        receipt = {"request_id": request_id, "requested_url": url, "fetched_at": fetched_at,
                   "access": "public_no_credentials", "trust": "untrusted_source_evidence"}
        try:
            for hop in range(MAX_REDIRECTS + 1):
                self.check_cancelled()
                current, host, addresses = validate_public_url(current, self.resolver)
                remaining = timeout_seconds - (time.monotonic() - started)
                if remaining <= 0:
                    raise ValidationFailure("Public source total download timeout exceeded.")
                connection = self.connection_factory(host, addresses[0], min(remaining, 30), _context())
                parts = urlsplit(current)
                target = parts.path + ("?" + parts.query if parts.query else "")
                connection.request("GET", target, headers={"User-Agent": "ARSIA-Local-Evidence/1.0", "Accept-Encoding": "identity",
                                                           "Accept": "*/*", "Connection": "close"})
                response = connection.getresponse()
                if response.status in {301, 302, 303, 307, 308}:
                    location = response.getheader("Location")
                    if not location or hop == MAX_REDIRECTS:
                        raise ValidationFailure("Public source redirect limit or invalid redirect.")
                    next_url = urljoin(current, location)
                    redirects.append({"url": current, "status": response.status, "location": next_url})
                    connection.close()
                    connection = None
                    current = next_url
                    continue
                if response.status in {401, 403}:
                    raise NeedsInput(f"Official/public source denied access (HTTP {response.status}); no restriction was bypassed.",
                                     ["Use an accessible official export or upload the relevant public documentation."], {"url": current})
                if response.status != 200:
                    raise NeedsInput(f"Public source returned HTTP {response.status}.", details={"url": current})
                encoding = response.getheader("Content-Encoding", "identity").lower()
                if encoding not in {"", "identity"}:
                    raise ValidationFailure("Server ignored identity encoding; compressed transfer is not accepted.")
                declared = response.getheader("Content-Length")
                if declared is not None and (not declared.isdigit() or int(declared) > max_bytes):
                    raise ValidationFailure("Public response exceeds the declared download limit.")
                digest, size = hashlib.sha256(), 0
                with temporary.open("xb") as stream:
                    while True:
                        self.check_cancelled()
                        if time.monotonic() - started > timeout_seconds:
                            raise ValidationFailure("Public source total download timeout exceeded.")
                        chunk = response.read(min(64 * 1024, max_bytes - size + 1))
                        if not chunk:
                            break
                        if self.charge_bytes:
                            with self._charge_lock:
                                self.charge_bytes(len(chunk))
                        size += len(chunk)
                        if size > max_bytes:
                            raise ValidationFailure("Public response exceeds the actual download limit.")
                        digest.update(chunk)
                        stream.write(chunk)
                if declared is not None and int(declared) != size:
                    raise ValidationFailure("Public response ended before its declared length.")
                sha = digest.hexdigest()
                archive = self.root / "sha256" / sha
                archive.parent.mkdir(exist_ok=True)
                if archive.exists():
                    with archive.open("rb") as existing:
                        existing_sha = hashlib.file_digest(existing, "sha256").hexdigest()
                    if existing_sha != sha:
                        raise ValidationFailure("Public evidence archive hash mismatch.")
                    temporary.unlink()
                else:
                    temporary.rename(archive)
                    archive.chmod(0o400)
                name = Path(unquote(parts.path)).name or "source-document"
                mime = response.getheader("Content-Type", "application/octet-stream")
                receipt.update(status="fetched", final_url=current, redirects=redirects, sha256=sha, size=size,
                               content_type=mime, etag=response.getheader("ETag"), last_modified=response.getheader("Last-Modified"),
                               requested_host_official=official_host(urlsplit(url).hostname), final_host_official=official_host(host),
                               elapsed_seconds=round(time.monotonic() - started, 4))
                file = {"id": "public-" + sha[:24], "name": name, "path": str(archive), "sha256": sha, "size": size,
                        "evidence_url": current, "requested_url": url, "fetched_at": fetched_at,
                        "role": "public_evidence", "content_type": mime,
                        "receipt_path": str(self.root / f"{request_id}.json")}
                receipt_path = self.root / f"{request_id}.json"
                receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
                receipt_path.chmod(0o400)
                result = {**receipt, "file_id": file["id"], "name": name, "__files": [file]}
                if size <= 4 * 1024**2 and any(t in mime for t in ("json", "pdf", "html", "text/plain")):
                    from .intake_tools import IntakeTools
                    try:
                        document = IntakeTools([file], self.root, self.check_cancelled).read_document(file["id"])
                        result["documents"] = [{k: v for k, v in document.items() if k not in {"text", "__documents"}}]
                        result["__documents"] = document["__documents"]
                    except (NeedsInput, ValidationFailure):
                        # Data JSON and non-extractable text remain downloadable
                        # evidence; they never acquire a fabricated document.
                        pass
                return result
            raise ValidationFailure("Public redirect limit exceeded.")
        except BaseException as exc:
            receipt.update(status="failed", final_url=current, redirects=redirects,
                           error_type=type(exc).__name__, error=str(exc)[:400])
            receipt_path = self.root / f"{request_id}.json"
            # Extraction is independent of the completed fetch; do not rewrite
            # an already sealed network receipt after later local failure.
            if not receipt_path.exists():
                receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
                receipt_path.chmod(0o400)
            raise
        finally:
            if connection is not None:
                connection.close()
            if temporary.exists():
                temporary.unlink()

    def fetch_arcgis_layer(self, layer_url, max_records=500000):
        """Read all advertised IDs and verify a complete bounded layer export.

        The two ID inventories establish observed completeness, not a database
        transaction or a historical snapshot; that limitation is in the receipt.
        """
        if type(max_records) is not int or not 1 <= max_records <= 500000:
            raise ValidationFailure("ArcGIS record limit must be 1–500000.")
        parts = urlsplit(layer_url)
        if not re.search(r"/(?:FeatureServer|MapServer)/[0-9]+/?$", parts.path):
            raise ValidationFailure("ArcGIS URL must identify an explicit public layer.")
        base = urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/"), "", ""))
        validate_public_url(base, self.resolver)
        def fetch_json(url, limit=16 * 1024**2):
            receipt = self.fetch_public_source(url, max_bytes=limit, timeout_seconds=180)
            value = json.loads(Path(receipt["__files"][0]["path"]).read_text("utf-8"))
            if not isinstance(value, dict) or value.get("error"):
                raise NeedsInput("ArcGIS service did not return a successful public query.")
            return receipt, value
        metadata_receipt, metadata = fetch_json(base + "?f=pjson")
        from .arcgis_query import object_id_field
        oid = object_id_field(metadata, base)
        page_size = min(int(metadata.get("maxRecordCount", 1000)), 2000)
        if not oid or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", oid) or page_size < 1:
            raise NeedsInput("ArcGIS layer has no usable published object identifier.")
        from .arcgis_export import preserve_page, spatial_reference, export_prefix
        # Make the desired geometry reference explicit. A service/map default
        # is not necessarily its layer extent reference. Explicit response
        # references are still preserved, never overwritten by this request.
        extent = metadata.get('extent')
        requested_reference = spatial_reference(extent.get('spatialReference') if isinstance(extent, dict) else None)
        query_url = base + "/query?"
        ids_args = {"where": "1=1", "returnIdsOnly": "true", "f": "json"}
        ids_receipt, inventory = fetch_json(query_url + urlencode(ids_args))
        ids = inventory.get("objectIds")
        if not isinstance(ids, list) or not all(type(v) is int for v in ids) or len(set(ids)) != len(ids):
            raise ValidationFailure("ArcGIS ID inventory is missing, invalid or duplicated.")
        if len(ids) > max_records:
            raise NeedsInput("ArcGIS layer exceeds the configured record limit.")
        ordered = sorted(ids)
        # Query explicit IDs rather than offsets so insertion/deletion cannot
        # silently shift a later page. Keep URLs below the public-fetch bound.
        batches = [ordered[i:i + min(page_size, 450)] for i in range(0, len(ordered), min(page_size, 450))]
        def page(batch):
            self.check_cancelled()
            args = {"objectIds": ",".join(map(str, batch)), "outFields": "*", "returnGeometry": "true", "f": "json"}
            if requested_reference is not None:
                args['outSR'] = json.dumps(requested_reference, separators=(',', ':'))
            for dimension in ('Z', 'M'):
                if metadata.get('has' + dimension) is True:
                    args['return' + dimension] = 'true'
            receipt, result = fetch_json(query_url + urlencode(args))
            features = result.get("features")
            if result.get("exceededTransferLimit") or not isinstance(features, list):
                raise ValidationFailure("ArcGIS page is incomplete or transfer-limited.")
            features, geometry_receipt = preserve_page(metadata, result, requested_reference=requested_reference)
            observed = [f.get("attributes", {}).get(oid) for f in features]
            if not all(type(value) is int for value in observed) or len(observed) != len(set(observed)) or set(observed) != set(batch):
                raise ValidationFailure("ArcGIS page IDs do not match the requested inventory.")
            return receipt, features, geometry_receipt
        def pages():
            pool = ThreadPoolExecutor(max_workers=4)
            iterator = iter(batches)
            pending = deque(pool.submit(page, batch) for batch in list(next(iterator, None) for _ in range(4)) if batch is not None)
            try:
                while pending:
                    yield pending.popleft().result()
                    batch = next(iterator, None)
                    if batch is not None:
                        pending.append(pool.submit(page, batch))
            finally:
                for future in pending:
                    future.cancel()
                pool.shutdown(wait=True, cancel_futures=True)
        export_id = uuid4().hex
        output = self.root / f"arcgis-{export_id}.partial"
        page_receipts, total_bytes = [], 0
        try:
            with output.open("x", encoding="utf-8") as stream:
                # Geometry references are local to each feature, inherited from
                # its exact page. Never attach an extent CRS over all pages.
                prefix = export_prefix(metadata, oid)
                stream.write(json.dumps(prefix, ensure_ascii=False)[:-1] + ',"features":[')
                first = True
                # Keep at most four pages in flight and consume in ID order.
                # A failed page never launches the remaining layer's requests.
                page_stream = pages()
                try:
                    for receipt, features, geometry_receipt in page_stream:
                        total_bytes += receipt["size"]
                        if total_bytes > 2 * 1024**3:
                            raise ValidationFailure("ArcGIS export exceeds the 2-GiB total bound.")
                        page_receipts.append({k: receipt[k] for k in ("request_id", "final_url", "sha256", "size", "fetched_at")} | {'geometry_preservation': geometry_receipt})
                        for feature in sorted(features, key=lambda f: f["attributes"][oid]):
                            stream.write(("" if first else ",") + json.dumps(feature, ensure_ascii=False, separators=(",", ":"), allow_nan=False))
                            first = False
                finally:
                    page_stream.close()
                stream.write("]}")
            after_receipt, after = fetch_json(query_url + urlencode(ids_args))
            after_ids = after.get("objectIds")
            count_receipt, count = fetch_json(query_url + urlencode({"where": "1=1", "returnCountOnly": "true", "f": "json"}))
            if not isinstance(after_ids, list) or not all(type(value) is int for value in after_ids) or len(after_ids) != len(set(after_ids)) or set(after_ids) != set(ids) or type(count.get('count')) is not int or count['count'] != len(ids):
                raise ValidationFailure("ArcGIS layer changed during retrieval; a coherent export must be retried.")
            with output.open("rb") as stream:
                sha = hashlib.file_digest(stream, "sha256").hexdigest()
            archive = self.root / "sha256" / sha
            if archive.exists():
                with archive.open("rb") as existing:
                    if hashlib.file_digest(existing, "sha256").hexdigest() != sha:
                        raise ValidationFailure("Derived ArcGIS archive hash mismatch.")
                output.unlink()
            else:
                output.rename(archive)
                archive.chmod(0o400)
            receipt_path = self.root / f"arcgis-{export_id}.json"
            receipt = {"status": "fetched", "requested_url": base, "final_url": base, "fetched_at": metadata_receipt["fetched_at"],
                       "sha256": sha, "size": archive.stat().st_size, "record_count": len(ids), "object_id_field": oid,
                       "derivation": "verified_arcgis_all_object_ids_v2", "page_count": len(page_receipts), "pages": page_receipts,
                       "metadata_sha256": metadata_receipt["sha256"], "initial_ids_sha256": ids_receipt["sha256"],
                       "final_ids_sha256": after_receipt["sha256"], "count_sha256": count_receipt["sha256"],
                       "final_host_official": official_host(parts.hostname),
                       "consistency": "All IDs match before/after and exact count; field edits during live retrieval cannot be excluded."}
            receipt['requests'] = {label: {key: item[key] for key in ('request_id', 'final_url', 'sha256', 'size', 'fetched_at')}
                                   for label, item in (('metadata', metadata_receipt), ('initial_ids', ids_receipt),
                                                       ('final_ids', after_receipt), ('count', count_receipt))}
            receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
            receipt_path.chmod(0o400)
            descriptor = {"id": "arcgis-" + sha[:24], "name": "arcgis-layer.json", "path": str(archive), "sha256": sha,
                          "size": receipt["size"], "evidence_url": base, "fetched_at": receipt["fetched_at"], "receipt_path": str(receipt_path)}
            return {k: v for k, v in receipt.items() if k != "pages"} | {"file_id": descriptor["id"], "__files": [descriptor] + metadata_receipt["__files"],
                    "__documents": metadata_receipt.get("__documents", [])}
        finally:
            output.unlink(missing_ok=True)

    def discover_source_docs(self, query="", urls=None):
        """Cross-catalogue discovery; supplied URLs remain hypotheses.

        Filename dataset identifiers route through the national catalogue and
        its published official links. No identifier is mapped to a state in code.
        """
        if not isinstance(query, str) or len(query) > 300:
            raise ValidationFailure("Discovery query must contain at most 300 characters.")
        urls = urls or []
        if not isinstance(urls, list) or len(urls) > 5:
            raise ValidationFailure("Discovery accepts at most five starting URLs.")
        for url in urls:
            if not isinstance(url, str) or not official_host(urlsplit(url).hostname):
                raise ValidationFailure("Source-document discovery starts from official .gov.au pages.")
        hint_text = " ".join([*self.source_hints, query, *urls])
        identifiers = list(dict.fromkeys(match.lower() for match in re.findall(r"(?<![A-Za-z0-9])([a-zA-Z0-9]{4}-[a-zA-Z0-9]{4})(?![A-Za-z0-9])", hint_text)
                                        if re.search(r"[a-zA-Z]", match)))[:3]
        national = "https://data.gov.au/data/api/3/action/package_search?"
        candidates = [national + urlencode({"q": '"' + identifier + '"', "rows": 10}) for identifier in identifiers]
        candidates.extend(urls)
        words = set(re.findall(r"[A-Za-z]+", query.upper())) if query else set()
        state_names = {"SA": "south australia", "ACT": "australian capital territory", "TAS": "tasmania", "WA": "western australia",
                       "NT": "northern territory", "NSW": "new south wales", "VIC": "victoria", "QLD": "queensland"}
        selected = [(state, url) for state, url in OFFICIAL_SEEDS if state in words or state_names[state] in query.lower()]
        candidates.extend(url for _, url in selected)
        # Even an explicit URL does not suppress independent discovery.
        candidates.append(national + urlencode({"q": query or "road crash", "rows": 10}))
        candidates = list(dict.fromkeys(candidates))
        links, documents, internal, failures, evidence = [], [], [], [], []
        source_candidates, fetched = [], set()
        while candidates and len(fetched) < 8:
            url = candidates.pop(0)
            if url in fetched:
                continue
            fetched.add(url)
            try:
                result = self.fetch_public_source(url, max_bytes=8 * 1024**2, timeout_seconds=45)
                descriptor = result.pop("__files")[0]
                evidence.extend(result.pop("__documents", []))
                internal.append(descriptor)
                documents.append(result)
                content = Path(descriptor["path"]).read_text(encoding="utf-8", errors="replace")
                if "json" in result["content_type"] or content.lstrip().startswith(("{", "[")):
                    data = json.loads(content)
                    packages = data.get("result", {}).get("results", []) if isinstance(data, dict) and isinstance(data.get("result"), dict) else []
                    for package in packages[:20]:
                        if not isinstance(package, dict):
                            continue
                        resources = [r for r in package.get("resources", []) if isinstance(r, dict)]
                        resource_urls = [r["url"] for r in resources if isinstance(r.get("url"), str) and r["url"].startswith("https://") and official_host(urlsplit(r["url"]).hostname)]
                        origin = package.get("original_harvest_source", {})
                        landing = origin.get("href") if isinstance(origin, dict) else None
                        identity_match = package.get("name", "").lower() in identifiers or any(identifier in " ".join(resource_urls).lower() for identifier in identifiers)
                        source_candidates.append({"title": package.get("title"), "catalogue_dataset_id": package.get("id"),
                            "dataset_name": package.get("name"), "publisher": package.get("organization", {}).get("title"),
                            "landing_url": landing, "resource_urls": resource_urls[:12], "identifier_match": identity_match,
                            "discovered_from": result["final_url"], "requires_schema_and_semantic_match": True})
                        if identity_match:
                            follow = []
                            for resource_url in resource_urls + ([landing] if isinstance(landing, str) else []):
                                parsed = urlsplit(resource_url)
                                match = re.search(r"/(?:api/(?:v3/)?views|resource|d)/([a-z0-9]{4}-[a-z0-9]{4})(?:[./?]|$)", parsed.path)
                                if match and official_host(parsed.hostname):
                                    follow.append("https://" + parsed.netloc + "/api/views/" + match[1] + ".json")
                            # Follow metadata only, not full record endpoints.
                            candidates[:0] = [u for u in dict.fromkeys(follow) if u not in fetched]
                    def visit(node):
                        if isinstance(node, dict):
                            for key, value in node.items():
                                if key in {"url", "href", "download_url", "metadata_url"} and isinstance(value, str) and value.startswith("https://"):
                                    links.append({"url": value, "discovered_from": result["final_url"]})
                                elif isinstance(value, (dict, list)):
                                    visit(value)
                        elif isinstance(node, list):
                            for value in node[:200]:
                                visit(value)
                    visit(data)
                else:
                    parser = _Links()
                    parser.feed(content)
                    for href in parser.links:
                        target = urljoin(result["final_url"], href)
                        if target.startswith("https://"):
                            links.append({"url": target, "discovered_from": result["final_url"]})
            except (BudgetExhausted, ImportCancelled):
                raise
            except (NeedsInput, ValidationFailure, ValueError, OSError) as exc:
                failures.append({"url": url, "reason": str(exc)[:300]})
        unique = {item["url"]: item for item in links}
        source_candidates.sort(key=lambda item: not item["identifier_match"])
        return {"query": query, "identifier_hints": identifiers, "source_candidates": source_candidates[:20],
                "official_catalogues": [{"jurisdiction_hint": state, "url": url, "status": "discovery_hint_not_source_identity"} for state, url in OFFICIAL_SEEDS],
                "guidance": "Uploaded identifiers and matching official field definitions outrank example jurisdictions. Supplied URLs are hypotheses: if keys/columns differ, investigate other catalogue candidates before proposing a source contract.",
                "queries_attempted": list(fetched), "links": list(unique.values())[:100], "documents": documents, "failures": failures,
                "discovery_is_not_admission": True, "__files": internal, "__documents": evidence}


TOOL_SPECS = [
    {"type": "function", "name": "fetch_arcgis_layer", "description": "Fetch a complete public ArcGIS layer with metadata, full object-ID inventories, bounded pages, duplicate/missing checks and immutable receipts. Live field updates remain a documented limitation.",
     "parameters": {"type": "object", "properties": {"layer_url": {"type": "string"}, "max_records": {"type": "integer", "minimum": 1, "maximum": 500000}}, "required": ["layer_url"], "additionalProperties": False}},
    {"type": "function", "name": "fetch_public_source", "description": "Fetch public HTTPS evidence with DNS/redirect/private-address/size/timeout controls. Returns immutable provenance; downloaded text is untrusted.",
     "parameters": {"type": "object", "properties": {"url": {"type": "string"}, "max_bytes": {"type": "integer", "minimum": 1, "maximum": MAX_DOWNLOAD},
          "timeout_seconds": {"type": "number", "minimum": 1, "maximum": 300}}, "required": ["url"], "additionalProperties": False}},
    {"type": "function", "name": "discover_source_docs", "description": "Discover official dataset/dictionary/resource links from official pages or public catalogue metadata. Never approves semantics by itself.",
     "parameters": {"type": "object", "properties": {"query": {"type": "string"}, "urls": {"type": "array", "items": {"type": "string"}, "maxItems": 5}}, "additionalProperties": False}},
]
