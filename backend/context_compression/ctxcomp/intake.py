"""B1: read explicit attachments, name copies, and register lossless source snapshots.

No table segmentation, unit conversion, missing-value replacement or scientific
eligibility decisions occur here. Reference-only contents remain local.
"""
import csv
import hashlib
import io
import json
import math
import re
import zipfile
from datetime import date, datetime, time, timezone
from pathlib import Path, PurePosixPath
from .io import document, read_json, write_json, digest, leaves

ALLOWED = {'.md', '.txt', '.pdf', '.docx', '.xlsx', '.csv', '.json'}
MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 256 * 1024 * 1024
MAX_CELLS = 500000
CHUNK_CHARS = 24000


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scalar(value):
    if isinstance(value, (datetime, date, time)):
        return {'type': type(value).__name__, 'iso': value.isoformat()}
    if isinstance(value, float) and not math.isfinite(value):
        return {'type': 'nonfinite', 'raw': str(value)}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise ValueError(f'Unsupported cell value type: {type(value).__name__}')


def parse_file(path):
    suffix = path.suffix.lower()
    if suffix in {'.md', '.txt', '.pdf', '.docx'}:
        source = document(path, 'temporary', 'ATTACHMENT')
        return {'kind': 'document', 'text': source['text']}
    if suffix == '.json':
        return {'kind': 'json', 'value': read_json(path)}
    if suffix == '.csv':
        # Preserve duplicate headers, ragged rows and empty fields for B2 QC.
        text = path.read_text(encoding='utf-8-sig')
        rows = list(csv.reader(io.StringIO(text, newline='')))
        if sum(map(len, rows)) > MAX_CELLS:
            raise ValueError('CSV cell limit exceeded; no partial read published')
        return {'kind': 'csv', 'rows': rows, 'encoding': 'utf-8-sig'}
    if suffix == '.xlsx':
        from openpyxl import load_workbook
        formula_book = load_workbook(path, read_only=False, data_only=False)
        cache_book = load_workbook(path, read_only=False, data_only=True)
        try:
            if sum(s.max_row * s.max_column for s in formula_book) > MAX_CELLS:
                raise ValueError('Workbook cell limit exceeded; no partial read published')
            sheets = []
            for sheet in formula_book:
                cells = []
                for row in sheet.iter_rows():
                    for cell in row:
                        if cell.value is None and not cell.comment:
                            continue
                        value = scalar(cell.value)
                        item = {'cell': cell.coordinate, 'row': cell.row, 'column': cell.column,
                                'value': value, 'data_type': cell.data_type}
                        if cell.data_type == 'f':
                            item['cached_value'] = scalar(cache_book[sheet.title][cell.coordinate].value)
                            item['formula_evaluated'] = False
                        if cell.comment:
                            item['comment'] = cell.comment.text
                        cells.append(item)
                sheets.append({'name': sheet.title, 'rows': sheet.max_row, 'columns': sheet.max_column,
                               'visibility': sheet.sheet_state, **hidden_lines(sheet), 'cells': cells,
                               'merged_ranges': [str(r) for r in sheet.merged_cells.ranges],
                               'tables': [table_record(sheet.tables[name]) for name in sheet.tables],
                               'blank_cells': 'Absent cell coordinates are empty; not observations.'})
            return {'kind': 'xlsx', 'sheets': sheets}
        finally:
            formula_book.close()
            cache_book.close()
    raise ValueError(f'Unsupported attachment type: {suffix}')


def table_record(table):
    """An Excel table's range with its header and totals row counts (Excel omits them at 1 and 0)."""
    header = table.headerRowCount
    totals = table.totalsRowCount
    return {'name': table.name, 'ref': table.ref, 'header_row_count': 1 if header is None else int(header),
            'totals_row_count': 0 if totals is None else int(totals)}


def hidden_lines(sheet):
    """Hidden row and column numbers (1-based) inside the used range, so a visible table that hides rows or
    columns, such as excluded animals or scratch calculations, can be flagged like a hidden sheet."""
    rows = sorted(n for n, d in sheet.row_dimensions.items() if d.hidden and 1 <= n <= sheet.max_row)
    # A column dimension can cover a span (min..max), as Excel stores hidden B:D as one entry.
    columns = sorted({n for d in sheet.column_dimensions.values() if d.hidden and d.min
                      for n in range(d.min, min(d.max or d.min, sheet.max_column) + 1)})
    return {'hidden_rows': rows, 'hidden_columns': columns}


def read_error_class(exc, suffix):
    """A coarse, user-facing class for a failed read; the raw reason is always kept alongside."""
    text = str(exc).casefold()
    if 'unsupported' in text:
        return 'UNSUPPORTED_FORMAT', 'Convert the file to MD, TXT, PDF, DOCX, CSV, XLSX or JSON.'
    if 'no extractable text' in text or ('empty document' in text):
        return 'NO_EXTRACTABLE_TEXT', 'The file has no readable text (for example a scanned PDF). Supply checked OCR text.'
    if 'limit exceeded' in text or 'exceeds' in text:
        return 'LIMIT_EXCEEDED', 'Split the file into smaller explicit files; nothing is truncated silently.'
    if isinstance(exc, UnicodeDecodeError) or 'codec' in text or 'decode' in text:
        return 'ENCODING_ERROR', 'Save the text or CSV file as UTF-8.'
    if isinstance(exc, (zipfile.BadZipFile, KeyError)) or 'not a zip file' in text or 'eof marker' in text or 'invalid' in text:
        return 'CORRUPT_OR_INVALID_FILE', 'The file appears damaged or is not a valid ' + suffix.lstrip('.').upper() + ' file. Re-export or re-save it.'
    return 'READ_FAILED', ''


def source_lines(snapshot):
    kind = snapshot['kind']
    if kind == 'document':
        return snapshot['text'].splitlines(keepends=True)
    if kind == 'xlsx':
        return [json.dumps({'sheet': sheet['name'], **cell}, ensure_ascii=False) + '\n'
                for sheet in snapshot['sheets'] for cell in sheet['cells']]
    if kind == 'csv':
        return [json.dumps({'record_number': i + 1, 'values': row}, ensure_ascii=False) + '\n'
                for i, row in enumerate(snapshot['rows'])]
    return [json.dumps({'pointer': pointer, 'value': value}, ensure_ascii=False) + '\n'
            for pointer, value in leaves(snapshot['value'])]


def chunks(lines):
    text = ''.join(lines)
    # Fixed text chunks are content pagination only, never table boundaries.
    return [text[i:i + CHUNK_CHARS] for i in range(0, len(text), CHUNK_CHARS)]


def inputs_from(package=None, paths=()):
    if package and paths:
        raise ValueError('Use a ZIP package or explicit files, not both')
    if package:
        package = Path(package).resolve(strict=True)
        with zipfile.ZipFile(package) as archive:
            members = [x for x in archive.infolist() if not x.is_dir()]
            if len(members) > 100 or sum(x.file_size for x in members) > MAX_TOTAL:
                raise ValueError('Package size/count limit exceeded')
            seen = set()
            for item in sorted(members, key=lambda x: x.filename.casefold()):
                member = PurePosixPath(item.filename)
                if (member.is_absolute() or '..' in member.parts or '\\' in item.filename
                        or ':' in item.filename or item.filename.casefold() in seen
                        or (item.external_attr >> 16) & 0o170000 == 0o120000):
                    raise ValueError(f'Unsafe/duplicate ZIP entry: {item.filename}')
                seen.add(item.filename.casefold())
                if member.suffix.lower() not in ALLOWED or item.file_size > MAX_FILE:
                    raise ValueError(f'Unsupported/oversized ZIP entry: {item.filename}')
                yield item.filename, archive.read(item), {'package': str(package), 'entry': item.filename}
    else:
        files = sorted({Path(p).resolve(strict=True) for p in paths}, key=lambda p: str(p).casefold())
        if len(files) > 100 or sum(p.stat().st_size for p in files) > MAX_TOTAL:
            raise ValueError('Attachment size/count limit exceeded')
        for path in files:
            if not path.is_file() or path.suffix.lower() not in ALLOWED or path.stat().st_size > MAX_FILE:
                raise ValueError(f'Unsupported/oversized attachment: {path}')
            yield path.name, path.read_bytes(), {'path': str(path)}


def intake_files(directory, package=None, paths=(), reference_only=(), opaque_references=False):
    root = Path(directory)
    if root.exists() and any(root.iterdir()):
        raise ValueError('Intake output is not empty; preserve previous runs')
    root.mkdir(parents=True, exist_ok=True)
    from .rules import intake_agent_contract
    agent_contract = intake_agent_contract()
    write_json(root / 'agent_contract.json', agent_contract)
    from . import coverage
    sources, inventory, files = [], [], []
    gaps, assessed, not_assessed = [], [], []
    for n, (name, content, origin) in enumerate(inputs_from(package, paths), 1):
        identifier = f'F{n:04d}'
        suffix = PurePosixPath(name).suffix.lower()
        relative = 'files/' + identifier + suffix
        target = root / relative
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(content)
        is_reference = (name in reference_only or PurePosixPath(name).name in reference_only
                        or bool(re.search(r'benchmark|holdout', PurePosixPath(name).name, re.I)))
        opaque = is_reference and opaque_references
        try:
            snapshot = ({'kind': suffix[1:] if suffix in {'.json', '.xlsx', '.csv'} else 'document',
                         'content_access': 'BYTES_HASHED_ONLY_REFERENCE_CONTENT_NOT_PARSED'} if opaque else parse_file(target))
        except Exception as exc:
            correction = ('Check the reported parser error and supply a readable replacement in a supported format; '
                          'use UTF-8 for text/CSV or checked OCR text for scanned documents where needed. '
                          'Then explicitly rerun with a new run directory.')
            error_class, specific = read_error_class(exc, suffix)
            write_json(root / 'read_error.json', {
                'at': datetime.now(timezone.utc).isoformat(),
                'rule_id': 'IN001', 'former_rule_id': 'CC013', 'status': 'READ_FAILED', 'id': identifier,
                'original_name': name, 'origin': origin, 'raw_path': relative,
                'error_type': type(exc).__name__, 'error_class': error_class, 'reason': str(exc),
                'corrective_action': specific + ' ' + correction if specific else correction,
                'qc_status': 'NOT_RUN', 'fit_ready': False})
            raise ValueError(f'IN001 (formerly CC013) could not read {name}: {exc}. {correction}') from exc
        read_status = 'BYTES_READ_ONLY' if opaque else 'READ_COMPLETE'
        snapshot_path = 'parsed/' + identifier + '.json'
        write_json(root / snapshot_path, snapshot)
        is_reference = (name in reference_only or PurePosixPath(name).name in reference_only
                        or bool(re.search(r'benchmark|holdout', PurePosixPath(name).name, re.I)))
        role = 'REFERENCE_ONLY' if is_reference else 'PRIMARY_SOURCE'
        if is_reference:
            # IN007: protected or deferred content is outside the current stage's coverage check.
            coverage_status = 'NOT_ASSESSED_REFERENCE_ONLY'
            not_assessed.append({'file_id': identifier, 'reason': 'REFERENCE_ONLY content is not permitted at this stage'})
        else:
            found = coverage.file_gaps(identifier, name, file_hash(target), target)
            gaps.extend(found); assessed.append(identifier)
            coverage_status = 'GAPS_DETECTED' if found else 'NO_GAPS_DETECTED'
        summary = {'id': identifier, 'original_name': name, 'working_name': target.name,
                   'kind': snapshot['kind'], 'read_status': read_status, 'qc_status': 'NOT_RUN',
                   'role': role, 'coverage_status': coverage_status}
        if snapshot['kind'] == 'xlsx' and not opaque:
            summary['sheets'] = [{'name': s['name'], 'rows': s['rows'], 'columns': s['columns']} for s in snapshot['sheets']]
        if snapshot['kind'] == 'csv' and not opaque:
            summary['source_record_count_including_header'] = len(snapshot['rows'])
        description = json.dumps(summary, ensure_ascii=False, sort_keys=True)
        inventory.append({'id': identifier, 'description': description, 'read_status': read_status,
                          'qc_status': 'NOT_RUN', 'role': role})
        sources.append({'id': identifier, 'name': name, 'role': 'FILE_REGISTRY', 'text': description,
                        'file_id': identifier, 'original_sha256': file_hash(target)})
        ids = [identifier]
        content_chunks = [] if opaque else chunks(source_lines(snapshot))
        for index, text in enumerate(content_chunks, 1):
            sid = f'{identifier}_P{index:04d}'
            source = {'id': sid, 'name': name, 'role': role, 'file_id': identifier,
                      'text': text, 'original_sha256': file_hash(target)}
            write_json(root / 'source_text' / (sid + '.json'), source)
            if not is_reference:
                sources.append(source)
                ids.append(sid)
        files.append({**summary, 'origin': origin, 'raw_path': relative, 'sha256': file_hash(target),
                      'bytes': len(content), 'snapshot_path': snapshot_path, 'snapshot_sha256': file_hash(root / snapshot_path),
                      'source_ids': ids, 'parsed_content_chunks': len(content_chunks),
                      'content_sent_to_context': not is_reference})
    if not files:
        raise ValueError('No supported files supplied')
    status = 'REGISTERED_WITH_DEFERRED_READS' if any(f['read_status'] == 'BYTES_READ_ONLY' for f in files) else 'READ_COMPLETE'
    coverage_report = coverage.report(gaps, assessed, not_assessed)
    write_json(root / 'coverage_report.json', coverage_report)
    manifest = {'schema_version': '1.0', 'stage': 'B1_ATTACHMENT_INTAKE', 'status': status,
                'scientific_qc': 'NOT_RUN', 'files': files,
                'package_sha256': file_hash(package) if package else None,
                'coverage': {'rule_id': 'IN001', 'status': coverage_report['status'],
                             'detector_version': coverage.DETECTOR_VERSION, 'gap_ids': [g['id'] for g in gaps],
                             'report_path': 'coverage_report.json', 'report_sha256': digest(coverage_report)}}
    passed = 'PASS_WITH_DEFERRED_READS' if status != 'READ_COMPLETE' else 'PASS'
    report = {'schema_version': '1.0', 'stage': 'intake',
              'status': 'SOURCE_INCOMPLETE' if gaps else passed,
              'scope': 'Technical file reads only; proposal selection and the workflow receipt gate compression.',
              'agent_contract_sha256': digest(agent_contract),
              'coverage': {'status': coverage_report['status'], 'gap_count': len(gaps),
                           'next_action': ('Confirm each IN001 gap is irrelevant to this task, or supply corrected files in a new run. '
                                           'Compression stays blocked until every gap is resolved.') if gaps else None},
              'files': [{**{k: f[k] for k in ('id', 'original_name', 'raw_path', 'sha256', 'role', 'read_status', 'qc_status',
                                              'coverage_status')},
                         'fit_ready': False} for f in files], 'scientific_release': False}
    write_json(root / 'readability_report.json', report)
    manifest['intake_audit'] = {'agent_contract.json': file_hash(root / 'agent_contract.json'),
                              'readability_report.json': file_hash(root / 'readability_report.json'),
                              'coverage_report.json': file_hash(root / 'coverage_report.json')}
    manifest['manifest_sha256'] = digest(manifest)
    write_json(root / 'manifest.json', manifest)
    write_json(root / 'source_registry.json', sources)
    write_json(root / 'inventory.json', inventory)
    return {'manifest': manifest, 'sources': sources, 'inventory': inventory}


def verify_intake(manifest_path):
    path = Path(manifest_path).resolve(strict=True)
    manifest = read_json(path)
    if digest({k: v for k, v in manifest.items() if k != 'manifest_sha256'}) != manifest['manifest_sha256']:
        raise ValueError('Intake manifest changed')
    if len({f['id'] for f in manifest['files']}) != len(manifest['files']):
        raise ValueError('Duplicate file IDs')
    for name, checksum in manifest.get('intake_audit', {}).items():
        if name not in {'agent_contract.json', 'readability_report.json', 'coverage_report.json'}:
            raise ValueError('Unexpected intake audit file')
        if file_hash(path.parent / name) != checksum:
            raise ValueError('Intake audit changed: ' + name)
    for item in manifest['files']:
        for field, checksum in [('raw_path', 'sha256'), ('snapshot_path', 'snapshot_sha256')]:
            target = (path.parent / item[field]).resolve(strict=True)
            if not target.is_relative_to(path.parent) or file_hash(target) != item[checksum]:
                raise ValueError(f'Changed or unsafe intake file: {item["id"]} {field}')
    return manifest


def inventory_sources(sources, inventory):
    """Make declarations citeable, without following their paths or claiming QC."""
    result = list(sources)
    by_id = {s['id']: s for s in result}
    for entry in inventory:
        if entry['id'] in by_id:
            if entry['description'] not in by_id[entry['id']]['text']:
                raise ValueError('Inventory/source ID collision: ' + entry['id'])
            continue
        result.append({'id': entry['id'], 'name': 'inventory:' + entry['id'],
                       'role': 'INVENTORY_DECLARATION', 'text': entry['description']})
    return result
