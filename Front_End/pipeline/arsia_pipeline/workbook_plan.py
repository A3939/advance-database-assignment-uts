"""A bounded, replayable XLSX layout plan, not a business-grain classifier.

Only a single contiguous table per sheet is supported. The optional prose
prefix has a deliberately narrow grammar: a labelled title, parenthesized or
labelled annotations, then a blank separator and a multi-column header. Other
regions must not be selected with arbitrary skip/end-row parameters.
"""
import hashlib
import json
import re

from .errors import UnsupportedCapability, ValidationFailure

VERSION = 'xlsx-parser-plan-v1'
MAX_PREFIX_ROWS = 64
MAX_PREFIX_CHARACTERS = 32768


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def input_digest(path, file, cancelled):
    sha = hashlib.sha256()
    with path.open('rb') as stream:
        while chunk := stream.read(1024 * 1024):
            cancelled()
            sha.update(chunk)
    value = sha.hexdigest()
    if isinstance(file, dict) and file.get('sha256') and file['sha256'] != value:
        raise ValidationFailure('Workbook bytes differ from the admitted input hash.')
    return value


def _trim(values):
    while values and values[-1] is None:
        values.pop()
    return values


def _title(values):
    return (len(values) == 1 and isinstance(values[0], str)
            and re.fullmatch(r'[^:\n\r]{3,160}:\s+[^\n\r]{2,512}', values[0]) is not None)


def _annotation(values):
    if len(values) != 1 or not isinstance(values[0], str):
        return False
    text = values[0]
    return bool(re.fullmatch(r'\([^\n\r]{3,2048}\)', text) or
                re.fullmatch(r'(?:Note|Notes|Source|Updated|Published|Coverage):\s+[^\n\r]{3,2048}', text, re.I))


def _layout(sheet, header, cell_value, cancelled):
    sheet.reset_dimensions()
    rows = sheet.iter_rows()
    prefix = []
    title = None
    for number in range(1, MAX_PREFIX_ROWS + 1):
        cancelled()
        cells = next(rows, None)
        if cells is None:
            if title is not None:
                # A one-column table whose column name contains a colon remains
                # a table; no prefix is discarded without the complete grammar.
                return title[0], header(title[1]), prefix[:title[0] - 1]
            return None, [], prefix
        values = _trim([cell_value(c.value, c.data_type) for c in cells])
        if sum(len(str(v)) for _, vs in prefix for v in vs) + sum(len(str(v)) for v in values) > MAX_PREFIX_CHARACTERS:
            raise UnsupportedCapability('WORKBOOK_HEADER_REGION_UNSUPPORTED', 'Workbook header/preamble exceeds the bounded layout plan.')
        if not values:
            prefix.append((number, values))
            continue
        if title is None:
            if _title(values):
                title = (number, values)
                prefix.append(title)
                continue
            return number, header(values), prefix
        if len(values) > 1:
            nonempty = [(n, v) for n, v in prefix if v]
            if (len(nonempty) < 2 or not prefix or prefix[-1][1] or
                    any(not _annotation(v) for _, v in nonempty[1:])):
                raise UnsupportedCapability('WORKBOOK_HEADER_REGION_UNSUPPORTED',
                                            'Multiple workbook regions or an unclassified prefix need a reviewed layout; rows cannot be skipped.')
            return number, header(values), prefix
        # Keep looking only to distinguish the narrow metadata prefix from an
        # ordinary one-column table. These values are never returned to the model.
        prefix.append((number, values))
    if title is not None:
        return title[0], header(title[1]), prefix[:title[0] - 1]
    # Do not silently omit a sheet whose first 64 rows happen to be blank.
    for number, cells in enumerate(rows, MAX_PREFIX_ROWS + 1):
        if number % 1000 == 0:
            cancelled()
        if any(c.value is not None for c in cells):
            raise UnsupportedCapability('WORKBOOK_HEADER_REGION_UNSUPPORTED', 'Nonempty worksheet starts beyond the supported header region.')
    return None, [], prefix


def describe_workbook(book, file_sha256, header, cell_value, cancelled):
    result = []
    for sheet in book.worksheets:
        number, names, prefix = _layout(sheet, header, cell_value, cancelled)
        plan = {'version': VERSION, 'input_sha256': file_sha256, 'format': 'xlsx',
                'sheet': sheet.title, 'sheet_state': sheet.sheet_state,
                'epoch': book.epoch.isoformat(), 'header_row': number,
                'columns': [{'column': i, 'name': name} for i, name in enumerate(names, 1)],
                'prefix': [{'row': row, 'nonempty_cells': len(values), 'values_sha256': _hash(values)}
                           for row, values in prefix],
                'prefix_sha256': _hash(prefix), 'header_sha256': _hash(names),
                'data_start_row': number + 1 if number else None,
                'data_end_row': None, 'empty': number is None,
                'blank_rows': 'preserve_internal_omit_empty_tail',
                'formula_policy': 'reject', 'date_policy': 'workbook_epoch_iso8601'}
        plan['plan_sha256'] = _hash(plan)
        result.append({'table_id': sheet.title, 'sheet': sheet.title, 'format': 'xlsx', 'header': names,
                       'header_row': number, 'sheet_state': sheet.sheet_state, 'empty': number is None,
                       'parser_plan': plan, 'date_cells': 'workbook calendar dates normalized to ISO 8601'})
    return result


def validate_hint(table, hints):
    """A hint may pin an observed plan, never move the selected region."""
    if not hints:
        return
    if any(key in hints for key in ('skip_rows', 'skipRows', 'end_row', 'start_row', 'range', 'usecols', 'nrows')):
        raise UnsupportedCapability('WORKBOOK_ROW_FILTER_UNSUPPORTED', 'Arbitrary workbook row/column filtering is not an admitted parser plan.')
    for key in ('format', 'header', 'header_row', 'parser_plan'):
        if key in hints and hints[key] != table[key]:
            raise ValidationFailure('Workbook parser hint differs from the independently observed layout.', details={'field': key, 'table_id': table['table_id']})
    if 'header_row' in hints and type(hints['header_row']) is not int and hints['header_row'] is not None:
        raise ValidationFailure('Workbook header row must be an integer or null for an empty sheet.')
