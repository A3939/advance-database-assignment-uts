"""Hash-pinned references into immutable documents, without authority inflation.

Resolved values are evidence candidates. Graph, field scope and semantic gates
still decide applicability. These functions never fetch or read host paths.
"""
import hashlib
import json

from .metadata_extractors import MetadataError, VERSION as EXTRACTOR_VERSION, resolve_locator

VERSION = 'pinned-evidence-reference-v1'


def reference(raw, sha256, document_id, locator):
    value = resolve_locator(raw, sha256, locator)
    if locator.get('kind') == 'xml-expanded-path':
        # "path" is intentionally redacted by the existing host-path filter.
        # Expanded XML segments are semantic identifiers, not filesystem paths.
        locator = {'kind': 'xml-expanded-path', 'segments': locator.get('segments', locator.get('path'))}
    quote = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
    if not quote.strip() or len(quote) > 12000:
        raise MetadataError('EVIDENCE_REFERENCE_BOUND', 'Choose a nonempty, narrower evidence location (up to 12000 characters).')
    value_sha = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
    return {'document_id': document_id, 'document_sha256': sha256, 'locator': locator,
            'value_sha256': value_sha, 'quote': quote, 'reference_version': VERSION, 'extractor_version': EXTRACTOR_VERSION}


def verify_reference(entry, document):
    if entry.get('document_sha256') != document['sha256']:
        raise MetadataError('EVIDENCE_HASH_MISMATCH', 'Structured references must pin the registered original document hash.')
    resolved = reference(document['content_bytes'], document['sha256'], entry['document_id'], entry['locator'])
    if 'value_sha256' in entry and entry['value_sha256'] != resolved['value_sha256']:
        raise MetadataError('EVIDENCE_VALUE_MISMATCH', 'The resolved evidence value changed or its proposed hash is wrong.')
    if 'quote' in entry and entry['quote'] != resolved['quote']:
        raise MetadataError('EVIDENCE_VALUE_MISMATCH', 'The proposed quote does not equal the hash-pinned structured value.')
    return {**resolved, 'sha256': document['sha256'], 'url': document['url']}


def covers_pointer(entry, pointer):
    """Both paths must address the same schema field, never an adjacent object."""
    if 'locator' not in entry:
        return True
    locator = entry['locator']
    if locator.get('kind') != 'json-pointer' or not isinstance(pointer, str):
        return False
    cited = locator.get('pointer')
    if not isinstance(cited, str):
        return False
    return cited == pointer or pointer.startswith(cited + '/') or cited.startswith(pointer + '/')


def assert_documentation_locator(raw, sha256, locator):
    """A new reference read must not bypass the document tool's row redaction."""
    if not isinstance(locator, dict):
        raise MetadataError('EVIDENCE_LOCATOR_INVALID', 'Evidence locator must be structured.')
    if locator.get('kind') != 'json-pointer':
        return
    from .metadata_extractors import _json
    value = _json(raw)
    if isinstance(value, list):
        raise MetadataError('EVIDENCE_RECORDS_WITHHELD', 'Record arrays must be profiled instead of returned as documentation.')
    pointer = locator.get('pointer', '')
    # Compare the resolved selection with its metadata-only projection. A
    # schema column is fine; an ancestor containing cached rows is not.
    selected = resolve_locator(raw, sha256, locator)
    def sensitive(node):
        if isinstance(node, dict):
            return any(key in {'cachedContents', 'cached_content', 'sampleRows'}
                       or key in {'features', 'records', 'rows', 'objectIds', 'data'} and isinstance(item, list)
                       or sensitive(item) for key, item in node.items())
        return isinstance(node, list) and any(sensitive(item) for item in node)
    decoded = [part.replace('~1', '/').replace('~0', '~') for part in pointer.split('/')[1:]]
    if any(part in {'features', 'records', 'rows', 'objectIds', 'data', 'cachedContents', 'cached_content', 'sampleRows'} for part in decoded) or sensitive(selected):
        raise MetadataError('EVIDENCE_RECORDS_WITHHELD', 'Raw or cached record values cannot be returned by a documentation reference.')
