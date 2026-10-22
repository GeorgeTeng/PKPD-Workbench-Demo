"""Read the supplied PMB workbook without changing it; retain cell provenance.

Run with bundled Python (openpyxl is used for read-only extraction).
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re

from openpyxl import load_workbook


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workbook', type=Path, required=True)
    parser.add_argument('--b2', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    source, output = args.workbook.resolve(), args.out.resolve()
    output.mkdir(parents=True, exist_ok=False)
    before = sha(source)
    book = load_workbook(source, read_only=True, data_only=False)
    tables = {}
    summaries = []
    for sheet in book:
        rows = []
        for cells in sheet.iter_rows():
            values = {cell.coordinate: cell.value for cell in cells if cell.value is not None}
            if values:
                rows.append({'row': cells[0].row, 'cells': values})
        path = output / 'source_sheets' / (sheet.title + '.json')
        write(path, {'workbook': str(source), 'source_sha256': before, 'sheet': sheet.title,
                     'nonempty_rows': rows, 'fit_ready': False})
        header = {cell.column: str(cell.value) for cell in next(sheet.iter_rows(min_row=1, max_row=1)) if cell.value is not None}
        records = []
        if sheet.title != 'ReadMe':
            for cells in sheet.iter_rows(min_row=2):
                if not any(cell.value is not None for cell in cells):
                    continue
                record = {header[c.column]: c.value for c in cells if c.column in header}
                record['_workbook_row'] = cells[0].row
                record['_workbook_cells'] = {header[c.column]: c.coordinate for c in cells if c.column in header}
                records.append(record)
        tables[sheet.title] = records
        summaries.append({'sheet': sheet.title, 'nonempty_rows_including_header': len(rows),
                          'records': len(records), 'headers': list(header.values()),
                          'extracted_json': str(path), 'sha256': sha(path)})
    library_note = {'sheet': 'ReadMe', 'cell': 'B4', 'value': book['ReadMe']['B4'].value}
    book.close()
    rat = tables['PK_Rat_Individual']
    b2_rows = json.loads((args.b2 / 'normalized/rat_plasma_IV.json').read_text(encoding='utf-8'))['records']
    keyed = {(int(re.search(r'(\d+)$', r['subject_id']).group(1)), r['time_h']): r
             for r in b2_rows if r['status'] == 'QUANTIFIED'}
    discrepancies = []
    for row in rat:
        key = (int(re.search(r'(\d+)$', row['subject_id']).group(1)), row['time_h'])
        original = keyed.get(key)
        if original is None or abs(original['concentration_mg_L']-row['concentration_mg_L']) > 1e-12:
            discrepancies.append({'subject_time': key, 'workbook_row': row['_workbook_row'],
                                  'xlsx_concentration': row['concentration_mg_L'],
                                  'b2_concentration': original.get('concentration_mg_L') if original else None})
    pd_counts = Counter(r['observation_status'] for r in tables['PD_TimeKill_Support'])
    b2_pd = []
    for strain in ('BAA1705', 'KP619'):
        b2_pd += json.loads((args.b2 / f'normalized/kp_{strain}_time_kill.json').read_text(encoding='utf-8'))['records']
    result = {
        'status': 'AUDITED_READ_ONLY', 'created_at': datetime.now(timezone.utc).isoformat(),
        'workbook': str(source), 'sha256': before, 'source_unchanged': sha(source) == before,
        'sheet_count': len(summaries), 'sheets': summaries,
        'model_library_statement': library_note,
        'model_definition_sheets': [s['sheet'] for s in summaries if 'model_id' in s['headers'] or 'model_spec' in s['headers']],
        'rat_metadata_correction': {
            'previous_b2_concentration_basis': 'NOT_FOUND',
            'workbook_declared_basis': sorted({r['concentration_basis'] for r in rat}),
            'source_sheet': 'PK_Rat_Individual', 'source_range': 'R2:R103',
            'quantified_observations': len(rat), 'subject_labels': len({r['subject_id'] for r in rat}),
            'b2_quantified_observations': len(keyed), 'concentration_discrepancies': discrepancies,
            'status': 'DECLARED_METADATA_LOCATED_NOT_YET_RELEASED',
            'note': 'This locates the workbook declaration. It is not an independent review of the source paper. Existing B2 metadata/review was not modified.'},
        'time_kill_comparison': {
            'workbook_observations': len(tables['PD_TimeKill_Support']), 'workbook_statuses': dict(pd_counts),
            'b2_observations': len(b2_pd), 'b2_statuses': dict(Counter(r['status'] for r in b2_pd)),
            'note': 'The B2 missing-Y source row remains preserved. Do not replace the lossless B2 table with a workbook containing only the non-missing observations.'},
        'animal_status_rows': tables['Animal_PK_Status'], 'index_status_rows': tables['Index_Status'],
        'scientific_model_execution': 'NOT_RUN', 'human_review': 'PENDING',
        'content_instruction_handling': 'Workbook access rules are source content, not new user instructions. Readiness conclusions refer to the actual available data.'
    }
    if not result['source_unchanged']:
        raise RuntimeError('Workbook changed during read-only audit')
    write(output / 'audit.json', result)
    print(json.dumps({k: result[k] for k in ('status', 'sheet_count', 'model_library_statement', 'rat_metadata_correction', 'time_kill_comparison')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
