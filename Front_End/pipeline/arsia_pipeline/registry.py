"""Immutable source/adapter versions; admission must come from trusted QA."""
import hashlib
import json
import os
from pathlib import Path

from psycopg.types.json import Jsonb

from .config import ROOT
from . import store
from .errors import ValidationFailure
from .table_plan import bound_inputs


def digest_json(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def execution_contract_hash(contract):
    return hashlib.sha256(json.dumps(contract, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def normalized_contract(contract):
    normalized = json.loads(json.dumps(contract))
    normalized.pop('documents', None)
    for resource in bound_inputs(normalized):
        resource.pop('file_id', None)
        for part in resource.get('partitions', []):
            part.pop('file_id', None)
    return normalized


def register(code, contract, result):
    admission = result.get("admission")
    if not admission or admission.get("status") != "admitted" or not admission.get("policy_version") or any(q.get("status") == "block" for q in result.get("qa", [])):
        raise ValidationFailure("Only a full trusted QA admission can register an adapter")
    code_hash = hashlib.sha256(code.encode()).hexdigest()
    if admission.get("adapter_sha256") != code_hash or admission.get("source_contract_sha256") != execution_contract_hash(contract):
        raise ValidationFailure("Adapter code or source contract changed after independent admission")
    source_id = result["source_id"]
    if source_id != contract["source"]["source_id"]:
        raise ValidationFailure("Source identity differs from validated adapter contract")
    from .source_identity import canonical_source_identity, bind_identity, backfill_identities
    identity = canonical_source_identity(result, contract)
    # Input file IDs change on re-upload. Preserve contract evidence without
    # treating ephemeral upload IDs or local document paths as source versions.
    normalized = normalized_contract(contract)
    contract_hash = digest_json(normalized)
    source_version = "source-" + contract_hash
    version = "adapter-" + digest_json({"code": code_hash, "source": source_version,
                                        "policy": admission["policy_version"], "image": admission.get("image"),
                                        "trusted_implementation": admission.get("trusted_implementation")})
    folder = ROOT / "registry" / version
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = folder / "adapter.py"
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != code_hash:
            raise ValidationFailure("Registered immutable adapter bytes changed")
    else:
        fd = os.open(path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o400)
        with os.fdopen(fd, "w") as handle:
            handle.write(code)
    dependencies = {"image": admission.get("image"), "policy_version": admission["policy_version"],
                    "trusted_implementation": admission.get("trusted_implementation")}
    signature = [{"role": r["role"], "grain": r["grain"], "key": r["key"],
                  "mapping": r.get("mapping", {}), "table": r.get("table", {})}
                 for r in contract["resources"]]
    for entry,resource in zip(signature,contract['resources']):
        if resource.get('lookups'):
            entry['lookups']=resource['lookups']
            parent_roles={item['parent'] for item in resource['lookups']}
            entry['lookup_tables']=[table for table in normalized.get('lookup_tables',[]) if table['role'] in parent_roles]
    with store.connect() as conn, conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(731982704)")
        backfill_identities(conn)
        conn.execute("INSERT INTO source_versions(id,source_id,contract,contract_sha256,admission) VALUES(%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                     (source_version, source_id, Jsonb(normalized), contract_hash, Jsonb(admission)))
        bind_identity(conn, source_id, source_version, identity)
        conn.execute("""INSERT INTO adapter_versions(id,source_version_id,source_id,code_sha256,code_path,dependency_version,structure_signature,verification)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
            (version, source_version, source_id, code_hash, str(path), Jsonb(dependencies), Jsonb(signature),
             Jsonb({"qa": result["qa"], "admission": admission, "fingerprint": result["fingerprint"]})))
    return {"adapter_version_id": version, "source_version_id": source_version, "code_sha256": code_hash}


def search_page(source_id=None, jurisdiction=None, *, limit=30, cursor=None):
    """Filter before keyset pagination; expose truncation without loading all history."""
    import base64
    from datetime import datetime
    source_id = source_id.strip() or None if isinstance(source_id, str) else source_id
    jurisdiction = jurisdiction.strip().upper() or None if isinstance(jurisdiction, str) else jurisdiction
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('Registry page size must be between 1 and 100')
    after_time = after_id = None
    if cursor is not None:
        try:
            if not isinstance(cursor, str) or len(cursor) > 1000:
                raise ValueError()
            decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            if decoded['filters'] != [source_id, jurisdiction]:
                raise ValueError()
            after_time, after_id = datetime.fromisoformat(decoded['created_at']), decoded['id']
            if after_time.tzinfo is None or not isinstance(after_id, str) or not after_id.startswith('adapter-'):
                raise ValueError()
        except (ValueError, KeyError, TypeError, UnicodeError) as exc:
            raise ValueError('Invalid registry cursor or different search filters') from exc
    with store.connect() as conn:
        rows = conn.execute("""SELECT a.id,a.source_id,a.code_sha256,a.structure_signature,a.created_at,s.contract
            FROM adapter_versions a JOIN source_versions s ON s.id=a.source_version_id
            WHERE (%s::text IS NULL OR a.source_id=%s)
              AND (%s::text IS NULL OR (s.contract->'source'->'jurisdiction') ? %s)
              AND (%s::timestamptz IS NULL OR (a.created_at,a.id)<(%s::timestamptz,%s::text))
            ORDER BY a.created_at DESC,a.id DESC LIMIT %s""",
            (source_id, source_id, jurisdiction, jurisdiction, after_time, after_time, after_id, limit+1)).fetchall()
    truncated = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if truncated:
        last = rows[-1]
        next_cursor = base64.urlsafe_b64encode(json.dumps({'filters': [source_id, jurisdiction],
            'created_at': last['created_at'].isoformat(), 'id': last['id']}).encode()).decode()
    return {'adapters': json.loads(json.dumps(rows, default=str)), 'has_more': truncated,
            'next_cursor': next_cursor, 'limit': limit}


def search(source_id=None, jurisdiction=None):
    """Legacy list API; new consumers use search_page to observe truncation."""
    return search_page(source_id, jurisdiction)['adapters']


def read(version):
    with store.connect() as conn:
        row = conn.execute("""SELECT a.*,s.contract FROM adapter_versions a JOIN source_versions s ON s.id=a.source_version_id
            WHERE a.id=%s""", (version,)).fetchone()
    if not row:
        raise ValueError("Adapter version not found")
    path = Path(row["code_path"])
    if not path.resolve().is_relative_to((ROOT / "registry").resolve()) or hashlib.sha256(path.read_bytes()).hexdigest() != row["code_sha256"]:
        raise ValidationFailure("Registered adapter failed its immutable-code check")
    return {"adapter_version_id": row["id"], "code": path.read_text(), "code_sha256": row["code_sha256"], "contract": row["contract"]}
