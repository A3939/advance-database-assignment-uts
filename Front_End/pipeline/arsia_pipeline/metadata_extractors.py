"""Bounded, deterministic metadata extraction from verified response bytes.

These facts grant no authority. The host must bind their locators to the
publisher, dataset, resource and claim before using them for admission. No
network, JSON-LD context loading, entity resolution or model code is used.
"""
from hashlib import sha256
from html.parser import HTMLParser
import json
import math

from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

VERSION = 'raw-metadata-v1'
MAX_BYTES = 4 * 1024**2
MAX_NODES = 100000
MAX_DEPTH = 64
RDF = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
GEO = 'http://www.w3.org/2003/01/geo/wgs84_pos#'


class MetadataError(ValueError):
    def __init__(self, code, message, details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise MetadataError('METADATA_DUPLICATE_KEY', 'Metadata contains duplicate JSON members.')
        result[key] = value
    return result


def _constant(value):
    raise MetadataError('METADATA_NONFINITE', 'Metadata contains a nonfinite JSON constant.')


def _token(key):
    return str(key).replace('~', '~0').replace('/', '~1')


def _bounded_json(value):
    pending = [(value, 0)]
    count = 0
    while pending:
        node, depth = pending.pop()
        count += 1
        if depth > MAX_DEPTH or count > MAX_NODES:
            raise MetadataError('METADATA_LIMIT', 'Metadata exceeds the node/depth bound.')
        if isinstance(node, dict):
            pending.extend((v, depth + 1) for v in node.values())
        elif isinstance(node, list):
            pending.extend((v, depth + 1) for v in node)
        elif isinstance(node, float) and not math.isfinite(node):
            raise MetadataError('METADATA_NONFINITE', 'Metadata contains an out-of-range numeric value.')


def _json(raw):
    try:
        value = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_pairs, parse_constant=_constant)
        _bounded_json(value)
        return value
    except (UnicodeError, RecursionError, json.JSONDecodeError) as exc:
        raise MetadataError('METADATA_INVALID_JSON', 'Invalid JSON metadata.') from exc


def _xml(raw):
    try:
        root = ElementTree.fromstring(raw, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    except (DefusedXmlException, ElementTree.ParseError) as exc:
        raise MetadataError('METADATA_UNSAFE_XML', 'Invalid XML or forbidden DTD/entity declarations.') from exc
    stack = [(root, 0)]
    count = 0
    while stack:
        element, depth = stack.pop()
        count += 1
        if depth > MAX_DEPTH or count > MAX_NODES:
            raise MetadataError('METADATA_LIMIT', 'XML metadata exceeds the node/depth bound.')
        stack.extend((child, depth + 1) for child in element)
    return root


def _rdf_facts(root):
    """Actual property use, not a namespace declaration or vocabulary mention."""
    points = []
    if root.tag != '{' + RDF + '}RDF':
        return points
    for record_index, record in enumerate(root):
        for property_index, prop in enumerate(record):
            # A location is a property containing one inline spatial object.
            # Other RDF serializations are unsupported, never guessed.
            for object_index, obj in enumerate(prop):
                if obj.tag not in {'{' + GEO + '}SpatialThing', '{' + GEO + '}Point'}:
                    continue
                latitude = [(i, n) for i, n in enumerate(obj) if n.tag == '{' + GEO + '}lat']
                longitude = [(i, n) for i, n in enumerate(obj) if n.tag == '{' + GEO + '}long']
                if not latitude and not longitude:
                    continue
                if len(latitude) != 1 or len(longitude) != 1 or len(latitude[0][1]) or len(longitude[0][1]):
                    raise MetadataError('RDF_COORDINATE_CONFLICT', 'RDF spatial object needs one literal latitude and longitude.')
                base = [[root.tag, 0], [record.tag, record_index], [prop.tag, property_index], [obj.tag, object_index]]
                literals, references = {}, {}
                for child in record:
                    if not len(child):
                        target = child.attrib.get('{' + RDF + '}resource')
                        if target is not None:
                            references.setdefault(child.tag, []).append(target)
                        else:
                            literals.setdefault(child.tag, []).append(child.text or '')
                points.append({
                    'subject': record.attrib.get('{' + RDF + '}about'),
                    'record_type': record.tag, 'property': prop.tag, 'namespace': GEO,
                    'latitude': latitude[0][1].text or '', 'longitude': longitude[0][1].text or '',
                    'latitude_locator': {'kind': 'xml-expanded-path', 'path': base + [[latitude[0][1].tag, latitude[0][0]]]},
                    'longitude_locator': {'kind': 'xml-expanded-path', 'path': base + [[longitude[0][1].tag, longitude[0][0]]]},
                    'record_literals': literals,
                    'record_references': references,
                })
    return points


class _HTMLFacts(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.json_ld, self.errors = [], [], []
        self.script, self.parts = False, []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag in {'a', 'link'} and attrs.get('href'):
            self.links.append({'href': attrs['href'], 'rel': attrs.get('rel', ''),
                               'role': 'discovery_candidate', 'line': self.getpos()[0]})
        if tag == 'script':
            self.script = attrs.get('type', '').lower() == 'application/ld+json'
            self.parts = []

    def handle_data(self, data):
        if self.script:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.script:
            try:
                self.json_ld.append(_json(''.join(self.parts).encode()))
            except MetadataError as exc:
                self.errors.append({'code': exc.code, 'message': str(exc)})
            self.script, self.parts = False, []


def extract(raw):
    if not isinstance(raw, bytes):
        raise TypeError('Metadata extraction requires original bytes')
    if len(raw) > MAX_BYTES:
        raise MetadataError('METADATA_LIMIT', 'Metadata exceeds the byte bound; use a scoped response.')
    stripped = raw.lstrip(b'\xef\xbb\xbf \r\n\t')
    result = {'extractor_version': VERSION, 'document_sha256': sha256(raw).hexdigest(),
              'authority': 'none_requires_scoped_host_verification'}
    if stripped.startswith((b'{', b'[')):
        return {**result, 'format': 'json', 'value': _json(raw)}
    html = stripped[:512].lower()
    if html.startswith((b'<!doctype html', b'<html', b'<head', b'<body')):
        parser = _HTMLFacts()
        try:
            parser.feed(raw.decode('utf-8-sig'))
        except UnicodeError as exc:
            raise MetadataError('METADATA_ENCODING', 'HTML metadata needs an explicit supported encoding.') from exc
        return {**result, 'format': 'html', 'links': parser.links,
                'json_ld': parser.json_ld, 'errors': parser.errors}
    if stripped.startswith(b'<'):
        root = _xml(raw)
        return {**result, 'format': 'rdf_xml' if root.tag == '{' + RDF + '}RDF' else 'xml',
                'rdf_points': _rdf_facts(root)}
    return {**result, 'format': 'opaque'}


def resolve_locator(raw, expected_sha256, locator):
    """Resolve against the hash-checked original, never against model text."""
    if not isinstance(raw, bytes) or len(raw) > MAX_BYTES or sha256(raw).hexdigest() != expected_sha256:
        raise MetadataError('EVIDENCE_HASH_MISMATCH', 'Evidence bytes do not match the pinned document.')
    if not isinstance(locator, dict):
        raise MetadataError('EVIDENCE_LOCATOR_INVALID', 'Evidence locator must be structured.')
    if locator.get('kind') == 'pdf-text-range':
        from . import parser_guard
        if parser_guard.required():
            import base64
            return parser_guard.call('pdf_locator', [base64.b64encode(raw).decode('ascii'), expected_sha256, locator])
    try:
        if locator.get('kind') == 'json-pointer':
            node = _json(raw)
            pointer = locator['pointer']
            if pointer == '':
                return node
            if not isinstance(pointer, str) or not pointer.startswith('/'):
                raise ValueError()
            for part in pointer[1:].split('/'):
                # RFC 6901 permits only ~0 and ~1 escapes.
                import re
                if re.search(r'~(?![01])', part):
                    raise ValueError()
                token = part.replace('~1', '/').replace('~0', '~')
                if isinstance(node, list):
                    if not re.fullmatch(r'0|[1-9][0-9]*', token):
                        raise ValueError()
                    node = node[int(token)]
                else:
                    node = node[token]
            return node
        if locator.get('kind') == 'xml-expanded-path':
            root = _xml(raw)
            path = locator.get('segments', locator.get('path'))
            if 'segments' in locator and 'path' in locator and locator['segments'] != locator['path']:
                raise ValueError()
            if not path or path[0] != [root.tag, 0]:
                raise ValueError()
            node = root
            for tag, index in path[1:]:
                if type(index) is not int or index < 0:
                    raise ValueError()
                node = node[index]
                if node.tag != tag:
                    raise ValueError()
            if len(node):
                raise ValueError()
            return node.text or ''
        if locator.get('kind') == 'pdf-text-range':
            import io
            from pypdf import PdfReader
            import pypdf.filters
            pypdf.filters.ZLIB_MAX_OUTPUT_LENGTH = 16 * 1024**2
            if not raw.startswith(b'%PDF-'):
                raise ValueError()
            first, last = locator['page_from'], locator['page_to']
            start, end = locator['start'], locator['end']
            if any(type(n) is not int for n in (first, last, start, end)) or not (1 <= first <= last <= 300 and last-first < 4 and 0 <= start < end and end-start <= 12000):
                raise ValueError()
            from pypdf.errors import PdfReadError
            try:
                reader = PdfReader(io.BytesIO(raw))
                if reader.is_encrypted or len(reader.pages) > 300 or last > len(reader.pages):
                    raise ValueError()
                text = '\n\n'.join(reader.pages[i].extract_text() or '' for i in range(first-1, last))
            except PdfReadError as exc:
                raise MetadataError('EVIDENCE_PDF_INVALID', 'Pinned PDF cannot be parsed safely.') from exc
            if len(text) > MAX_BYTES or end > len(text):
                raise ValueError()
            return text[start:end]
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        raise MetadataError('EVIDENCE_LOCATOR_INVALID', 'Evidence locator does not address the pinned value.') from exc
    raise MetadataError('EVIDENCE_LOCATOR_UNSUPPORTED', 'Unsupported evidence locator kind.')
