"""Full, schema-linked dictionary classification; never publisher authority.

Table headers alone cannot exclude input rows or permit a document read. A
dictionary has exactly a field-name column and a definition column, unique
field identifiers all belonging to an actual other table, and bounded textual
definitions on every row. Category lookups and arbitrary name/description
tables are deliberately outside this dictionary grammar.
"""
import hashlib
import json
from pathlib import Path

from .intakereaders import iter_table

VERSION = 'schema-linked-table-classification-v1'
FIELD_COLUMNS = {'field', 'field_name', 'column', 'column_name', 'variable'}
DEFINITION_COLUMNS = {'description', 'definition', 'meaning'}


def document_object(file):
    """Recognize a small metadata-only JSON grammar, not arbitrary reader errors.

    Unsupported positional records or an unknown envelope must not turn into an
    ignored attachment. Rich provider metadata fetched as evidence has its own
    scoped receipt path; this check is for otherwise unassigned uploaded JSON.
    """
    path = Path(file['path'])
    if path.stat().st_size > 4 * 1024**2:
        return False
    from .intakereaders import _pairs
    try:
        obj = json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=_pairs)
    except (ValueError, UnicodeError):
        return False
    if not isinstance(obj, dict) or not obj or set(obj) - {'title','name','description','notes','publisher','licence','license','url','fields','columns'}:
        return False
    for key, value in obj.items():
        if key not in {'fields','columns'}:
            if not isinstance(value, str):
                return False
        else:
            if not isinstance(value, list) or not 1 <= len(value) <= 2048:
                return False
            for field in value:
                if (not isinstance(field, dict) or set(field) - {'name','fieldName','alias','description','definition','type','dataTypeName'}
                        or not isinstance(field.get('fieldName', field.get('name')), str)
                        or not all(isinstance(v, str) for v in field.values())):
                    return False
    return bool(obj.get('fields') or obj.get('columns') or len(obj.get('description', '')) >= 12)


def dictionary_columns(table):
    if len(table['header']) != 2:
        return None
    field = [h for h in table['header'] if h.lower().replace(' ', '_') in FIELD_COLUMNS]
    definition = [h for h in table['header'] if h.lower().replace(' ', '_') in DEFINITION_COLUMNS]
    return (field[0], definition[0]) if len(field) == len(definition) == 1 else None


def dictionary_review(file, table, inventory, cancelled=lambda: None):
    columns = dictionary_columns(table)
    if not columns:
        return None
    candidates = [(other, spec) for other, spec in inventory
                  if (other['id'], spec['table_id']) != (file['id'], table['table_id'])
                  and not spec.get('empty') and not dictionary_columns(spec)]
    fields = set()
    sha = hashlib.sha256()
    characters = 0
    count = 0
    for locator, row in iter_table(file, table, cancelled):
        count += 1
        if count > 10000:
            return None
        name, definition = (row[key] for key in columns)
        if (not isinstance(name, str) or name not in set().union(*(set(spec['header']) for _, spec in candidates))
                or name in fields or not isinstance(definition, str) or not 12 <= len(definition.strip()) <= 8192
                or '\x00' in definition):
            return None
        fields.add(name)
        candidates = [(other, spec) for other, spec in candidates if name in spec['header']]
        if not candidates:
            return None
        characters += len(name) + len(definition)
        if characters > 4 * 1024**2:
            return None
        sha.update((json.dumps([locator, row], sort_keys=True, ensure_ascii=False, separators=(',', ':')) + '\n').encode())
    if not count:
        return None
    return {'version': VERSION, 'purpose': 'dictionary', 'file_sha256': file['sha256'], 'table_id': table['table_id'],
            'field_column': columns[0], 'definition_column': columns[1], 'row_count': count,
            'rows_sha256': sha.hexdigest(), 'describes': [{'file_sha256': sha, 'table_id': name, 'fields': sorted(fields)}
                                                        for sha, name in sorted({(other['sha256'], spec['table_id']) for other, spec in candidates})],
            'basis': 'Every dictionary row uniquely describes an observed field of the same other physical table.',
            'publisher_authority': False, 'semantic_admission': False}
