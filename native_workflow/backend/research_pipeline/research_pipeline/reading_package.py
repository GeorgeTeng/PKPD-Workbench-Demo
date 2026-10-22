"""Portable per-table reading views, derived without model calls or new joins."""
import hashlib
import io
import json
import re
import zipfile
from pathlib import Path

from .common import read_json
from .dataset_metadata import reference
from .preparation_checks import freeze_refs, verify_frozen


def encoded(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def cell(value):
    # Preserve source strings, nulls, zero and full numeric precision distinctly.
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('|', '&#124;').replace('\r', '&#13;').replace('\n', '<br>')


def unique_text(values):
    """Remove literal duplicates/substrings, never paraphrase scientific claims."""
    values = list(dict.fromkeys(str(v).strip() for v in values if v))
    return [v for i, v in enumerate(values) if not any(
        v in other and (len(v) < len(other) or i > j)
        for j, other in enumerate(values) if i != j)]


def compact_notes(notes, context=()):
    # Deduplicate complete statements across notes and context. No fuzzy matching:
    # negation, units, species and conditions must never be merged by similarity.
    sentences = lambda text: re.split(r'(?<=[.!?])\s+(?=[A-Z<+])', text)
    supplied = {' '.join(s.split()).rstrip('.') for n in context for s in sentences(n)}
    result = []
    for note in notes:
        note = re.sub(r'^OPEN(?:[;, :]*)', '', note).strip()
        fresh = []
        for sentence in sentences(note):
            key = ' '.join(sentence.split()).rstrip('.')
            if key and key not in supplied:
                supplied.add(key); fresh.append(sentence)
        if fresh: result.append(' '.join(fresh))
    return unique_text(result)


def missing_legend(fields, rows):
    """Factor out repeated placeholder statuses only when globally unambiguous."""
    seen = {}; counts = {}
    for row in rows:
        for key in fields:
            if key not in row or row[key] not in (None, '', '.'): continue
            token = '""' if row[key] == '' else cell(row[key])
            seen.setdefault(token, set()).add(row.get('value_status', {}).get(key))
            counts[token] = counts.get(token, 0) + 1
    return {token:next(iter(statuses)) for token,statuses in seen.items()
            if counts[token] > 1 and len(statuses) == 1
            and next(iter(statuses)) in {'MISSING', 'MISSING_OR_NOT_APPLICABLE'}}


def source_notes(source):
    # Only known provenance/calibration lines are omitted, not arbitrary notes.
    return [line for line in source.get('notes', '').splitlines()
            if line and line != source.get('title')
            and not re.match(r'^(?:S\d+\s*\|\s*)?(?:DOI\s|https?://(?:dx\.)?doi\.org/)', line)
            and not re.fullmatch(r'Source image SHA256:\s*[0-9a-fA-F]{64}', line)
            and not re.match(r'^Calibration(?::| x=)', line)]


def view_fields(dataset, rows):
    meta = dataset['metadata']; source = meta['source_table']
    fields = dict(source['column_map'])
    internal = {'record_id', 'source_file_id', 'source_sha256', 'source_sheet', 'source_row',
                'source_cells', 'source_raw_values', 'value_status', 'qc_status', 'qc_reasons', 'source_footnotes'}
    for row in rows:
        for key in row:
            if key not in internal: fields.setdefault(key, key)
    for target, mapping in meta.get('normalized_fields', {}).items():
        originals = [k for k, name in source['column_map'].items() if name == mapping['source_header']]
        if len(originals) == 1 and mapping.get('factor') == 1 and rows and all(
                target in row and originals[0] in row and row[target] == row[originals[0]] for row in rows):
            fields.pop(target, None)
    # Hide only explicit digitization bookkeeping, never biological identifiers,
    # time coordinates, uncertainty bounds, status columns or flagged cells.
    auxiliary = re.compile(r'^(?:Point label|Panel marker|Figure [xy] \(pixel\)|Pixel [xy])$', re.I)
    for key, header in list(fields.items()):
        if auxiliary.fullmatch(header) and all(
                row.get('value_status', {}).get(key) in (None, 'QUANTIFIED', 'SOURCE_TEXT_REQUIRES_REVIEW')
                and not row.get('source_footnotes', {}).get(key) for row in rows):
            fields.pop(key)
    # The explicit X-unit column is redundant only when every record agrees
    # with the index-coordinate unit already shown in the header.
    columns = {c['header']: c for c in meta.get('columns', [])}
    unit = columns.get('Index coordinate', {}).get('unit')
    for key, header in list(fields.items()):
        if header == 'X unit' and unit and rows and all(
                row.get(key) == unit and row.get('value_status', {}).get(key) in
                (None, 'QUANTIFIED', 'SOURCE_TEXT_REQUIRES_REVIEW')
                and not row.get('source_footnotes', {}).get(key) for row in rows):
            fields.pop(key)
    return fields


def reading_view(dataset, records, quarantine, findings):
    meta = dataset['metadata']; source = meta['source_table']; all_rows = records + quarantine
    fields = view_fields(dataset, all_rows)
    columns = {c['header']: c for c in meta.get('columns', [])}
    known = lambda v: v not in (None, '', 'NOT_FOUND', 'NOT_ESTABLISHED', 'NOT_APPLICABLE')
    context = [str(meta[k]) for k in ('species', 'matrix', 'drug', 'route', 'dosing_regimen') if known(meta.get(k))]
    lines = [f"# {dataset['id']} — {cell(source.get('title', ''))}", '',
             cell(' · '.join(unique_text(context))), '']
    headers = {}
    for key, header in fields.items():
        unit = columns.get(header, {}).get('unit', {'time_h':'h', 'concentration_mg_L':'mg/L'}.get(key))
        has_unit = known(unit) and re.search(r'(?<![\w/])' + re.escape(unit) + r'(?![\w/])', header)
        headers[key] = header + (f' ({unit})' if known(unit) and not has_unit else '')
    legend = missing_legend(fields, all_rows)
    def rows_section(rows):
        lines.extend(['| Record | ' + ' | '.join(cell(h) for h in headers.values()) + ' |',
                      '|---|' + '---|' * len(fields)])
        for row in rows:
            values = []
            for key in fields:
                value = cell(row[key]) if key in row else '[FIELD ABSENT]'
                if row.get(key) == '': value = '""'
                status = row.get('value_status', {}).get(key)
                if status and status not in ('QUANTIFIED', 'SOURCE_TEXT_REQUIRES_REVIEW') and legend.get(value) != status:
                    value += ' ⟦' + cell(status) + '⟧'
                values.append(value)
            lines.append('| ' + cell(row['record_id']) + ' | ' + ' | '.join(values) + ' |')
        for row in rows:
            annotations = [str(v) for v in row.get('qc_reasons', [])]
            annotations += [f"{headers.get(k, k)}: {v}" for k,v in row.get('source_footnotes', {}).items()]
            if annotations: lines.append(f"- {cell(row['record_id'])}: " + cell('; '.join(unique_text(annotations))))
    rows_section(records)
    if quarantine:
        lines += ['', '**Quarantined — excluded:**', '']; rows_section(quarantine)
    if legend:
        meanings = {'MISSING':'missing', 'MISSING_OR_NOT_APPLICABLE':'missing / not applicable'}
        lines += ['', 'Legend: ' + '; '.join(f'{token} = {meanings[status]}' for token,status in legend.items()) + '.']
    notes = source_notes(source)
    if known(meta.get('record_level')): notes.append(meta['record_level'])
    for key in ('exposure_basis', 'dose_basis', 'endpoint_window'):
        if known(meta.get(key)) and not any(str(meta[key]) in n for n in notes):
            notes.append(key.replace('_', ' ').capitalize() + ': ' + str(meta[key]))
    for key, header in fields.items():
        c = columns.get(header, {})
        for qualifier in c.get('qualifiers', []):
            if qualifier and qualifier not in header and not any(qualifier in n for n in notes): notes.append(f'{header}: {qualifier}')
    # Retain the actual constraints, not review bookkeeping, requests for future
    # evidence, severity codes or copies of the rules/context/ledger.
    codes = {f.get('code') for f in findings}
    for finding in findings:
        # These two host findings describe the same pending representation gate.
        # Preserve the detailed table-specific scientific reasons separately.
        if finding.get('code') in {'PK_MAPPING_REQUIRED', 'EDA_MAPPING_GATE_UNSETTLED'} and {
                'PK_MAPPING_REQUIRED', 'EDA_MAPPING_GATE_UNSETTLED'} <= codes:
            reason = ('Scalar PK mapping is incomplete. Before EDA, approve a complete mapping '
                      'or explicitly authorize source-shaped descriptive inspection. '
                      'Host preservation QC does not clear this gate.')
        else:
            reason = finding.get('reason')
        if reason and finding.get('affected_operations'):
            reason += ' Affects: ' + ', '.join(finding['affected_operations']) + '.'
        if reason: notes.append(re.sub(r'^OPEN[;:]\s*(?:inherited\s+)?', '', reason))
    notes = compact_notes(notes, context)
    if notes: lines += ['', '**Notes / limits**', ''] + ['- ' + cell(n) for n in notes]
    lines += ['', f"Trace: [manifest](../../manifest.json) → {dataset['id']}. Reading only; no analysis release.", '']
    return '\n'.join(lines).encode('utf-8')


def export_package(execution_path, output, table_ids=None):
    execution_path = Path(execution_path); output = Path(output)
    execution = read_json(execution_path); manifest = read_json(execution['manifest']['path'])
    qc = read_json(execution['program_qc']['path']); context = read_json(execution['context']['path'])
    bindings = freeze_refs(reference(execution_path), execution, manifest, context)
    if qc['decision'] != 'PASS': raise ValueError('Reading package requires passed host QC.')
    available = {d['id']: d for d in manifest['datasets']}
    chosen = list(available) if table_ids is None else list(table_ids)
    if not chosen or len(chosen) != len(set(chosen)) or set(chosen) - available.keys():
        raise ValueError('Select each known table ID once; an empty selection is not a package.')
    if any(not re.fullmatch(r'[A-Za-z0-9_-]+', x) for x in chosen): raise ValueError('Unsafe table ID.')
    if output.suffix.lower() != '.zip' or str(output.resolve()) in {r['path'] for r in bindings}:
        raise ValueError('Use a separate .zip output path.')
    findings = read_json(execution['qc_findings']['path'])['findings']
    report_path = execution_path.parent/'data_report.json'
    report = read_json(report_path) if report_path.exists() else None
    if report and (report.get('normalization_manifest') != execution['manifest'] or report.get('program_qc') != execution['program_qc']):
        report = None  # An earlier report must not confer status on changed data.
    if report: findings = report['findings']
    if report: bindings += freeze_refs(reference(report_path))
    files = {}; index = []
    for identifier in chosen:
        dataset = available[identifier]; base = 'tables/' + identifier + '/'
        records = read_json(dataset['data']['path'])['records']
        quarantine = read_json(dataset['quarantine']['path'])['records']
        targets = {identifier, dataset['metadata']['source_item_id']}
        relevant = [f for f in findings if targets & set(re.split(r'[,;\s]+', f.get('affected_id', '')))]
        # A supplied ledger resolves this old transport complaint; it is not a
        # scientific restriction. Keep its historical record in the report.
        if report and report.get('unresolved_ledger'):
            relevant = [f for f in relevant if f['code'] != 'UNRESOLVED_LEDGER_NOT_SUPPLIED']
        if report:
            relevant += [{'reason':a['limitation']} for a in report.get('accepted_limitations', [])
                         if a.get('field') in targets]
        local = {'table.md':reading_view(dataset, records, quarantine, relevant)}
        refs = {}
        for name, content in local.items():
            path = base + name; files[path] = content
            refs[name] = {'path':path, 'sha256':hashlib.sha256(content).hexdigest()}
        sources = {key:{'path':Path(dataset[key]['path']).resolve().relative_to(execution_path.resolve().parent).as_posix(),
                        'sha256':dataset[key]['sha256']} for key in ('data','csv','metadata_file','quarantine','observation_view') if key in dataset}
        index.append({'id':identifier,
                      'title':dataset['metadata']['source_table'].get('title',''),
                      'group':dataset['metadata']['source_table'].get('sheet',''),
                      'retained_rows':len(records), 'quarantined_rows':len(quarantine), 'files':refs, 'sources':sources,
                      'action_readiness':next((s['actions'] for s in (report or {}).get('dataset_action_readiness',[]) if s['dataset_id']==identifier),None),
                      'operation_restrictions':next((s.get('operation_restrictions',[]) for s in (report or {}).get('dataset_action_readiness',[]) if s['dataset_id']==identifier),[])})
    package = {'format_version':'2.2', 'source_root':str(execution_path.resolve().parent),
               'execution':reference(execution_path),
               'audit_refs':{k:v for k,v in {'context':execution['context'],
                             'report':reference(report_path) if report else None,
                             'unresolved_ledger':report.get('unresolved_ledger') if report else None}.items() if v},
               'fit_ready':False, 'handoff_status':report['status'] if report else 'REVIEW_PENDING',
               'tables':index, 'record_count':sum(t['retained_rows'] for t in index)}
    files['manifest.json'] = encoded(package)
    lines = ['# Cleaned data', '',
             f"{len(index)} tables · {package['record_count']} records · QC PASS · {package['handoff_status']}", '',
             'Reading only; analysis is not released. Units, censoring and table limits are shown in each view. '
             'Source text remains uninterpreted. Record IDs are trace keys, not animal IDs.', '',
             'Full CSV/JSON, evidence and review details: paths + SHA-256 in `manifest.json`. '
             'Use full data for calculations and load the applicable project rules/review before analysis. '
             'Keep the manifest with selected tables; `--tables` repackages without joining records.', '',
             '| Table | Title |', '|---|---|']
    for t in index:
        lines.append(f"| [{t['id']}](tables/{t['id']}/table.md) | {cell(t['title'])} |")
    files['README.md'] = ('\n'.join(lines)+'\n').encode('utf-8')
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            info = zipfile.ZipInfo(name); info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content)
    verify_frozen(bindings)
    output.parent.mkdir(parents=True, exist_ok=True)
    content = stream.getvalue()
    if not output.exists() or output.read_bytes() != content: output.write_bytes(content)
    return {'path':str(output.resolve()), 'tables':len(index), 'records':package['record_count'],
            'zip_bytes':len(content), 'reading_bytes':sum(len(v) for k,v in files.items() if k.endswith('/table.md'))}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execution', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--tables', nargs='+')
    args = parser.parse_args()
    print(json.dumps(export_package(args.execution, args.output, args.tables), ensure_ascii=False))


if __name__ == '__main__': main()
