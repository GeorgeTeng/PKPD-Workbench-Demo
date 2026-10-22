"""DC-split (DC001): model-proposed table ranges are verified by host code; nothing is dropped silently."""
import pytest
from openpyxl import Workbook

from research_pipeline import data_agents as d
from research_pipeline.common import read_json, write_json


def workbook(path):
    """Supplementary-data layout: title and dose rows above the header, a side-by-side table and side notes."""
    wb = Workbook(); ws = wb.active; ws.title = 'Fig. 4b'
    ws['B1'] = 'Figure 4b Rat PK (Plasma)'; ws['C2'] = 'Compound 1 mg/kg IV'
    for col, value in zip('BCD', ['Time (h)', 'Rat 1', 'Rat 2']): ws[f'{col}3'] = value
    for row, values in enumerate([(0.17, 1.44, '*'), (0.5, 1.13, 1.94), (1, 0.81, '<LLOQ')], 4):
        for col, value in zip('BCD', values): ws[f'{col}{row}'] = value
    ws['F1'] = 'MIC (mg/L)'
    for row, values in enumerate([('Strain', 'MIC'), ('A', 1), ('B', 8)], 2):
        for col, value in zip('FG', values): ws[f'{col}{row}'] = value
    ws['I4'] = '* sample lost'; ws['B9'] = 'Data are from the authors.'
    wb.save(path); return path


@pytest.fixture
def sheet_case(tmp_path):
    source = workbook(tmp_path / 'source.xlsx')
    main = write_json(tmp_path / 'main.json', {'data': {'files': [{'id': 'F0001', 'kind': 'xlsx', 'role': 'DATA_CANDIDATE', **d.file_ref(source)}]}})
    return tmp_path, main


def proposal(tables=None, notes=None, findings=()):
    calls = []
    def generate(request, **kwargs):
        calls.append(request['payload'])
        return {'request_sha256': request['request_sha256'],
                'tables': tables if tables is not None else [
                    {'title': 'Figure 4b Rat PK (Plasma)', 'range': 'B1:D6', 'header_row': 3, 'reason': 'Title, dose row, header and time rows'},
                    {'title': 'MIC (mg/L)', 'range': 'F1:G4', 'header_row': 2, 'reason': 'Side-by-side table'}],
                'note_blocks': notes if notes is not None else [
                    {'range': 'I4', 'kind': 'FOOTNOTE', 'applies_to': [1], 'reason': 'Explains *'},
                    {'range': 'B9', 'kind': 'DESCRIPTION', 'applies_to': [], 'reason': 'Sheet-level note'}],
                'findings': list(findings)}
    return generate, calls


def test_proposed_split_is_verified_and_covers_every_cell(sheet_case):
    tmp, main = sheet_case
    generate, calls = proposal()
    inv = d.inventory(main, tmp / 'run/adequacy/inventory.json', run=tmp / 'run', generator=generate)
    assert [c['stage'] for c in calls] == ['DC-split'] and calls[0]['agent'] == 'DC'
    assert {r['id'][:2] for r in calls[0]['processing_rules']} == {'DC'}
    items = {i['id']: i for i in inv['items']}
    assert set(items) == {'F0001:S1:T1', 'F0001:S1:T2', 'F0001:S1:N1'}  # No unassigned remainder.
    pk = items['F0001:S1:T1']
    assert pk['region']['boundary_method'] == 'MODEL_PROPOSED' and pk['descriptor']['linked_notes'] == '* sample lost'
    assert 'Compound 1 mg/kg IV' in pk['descriptor']['source_notes'] and pk['body_rows'] == 3
    assert pk['descriptor']['source_notes'] == 'Figure 4b Rat PK (Plasma)\nCompound 1 mg/kg IV'  # Nothing from the MIC table beside it.
    assert items['F0001:S1:T2']['descriptor']['source_notes'] == 'MIC (mg/L)'
    assert 'F0001:S1:T1:I4' in dict(d.content_units(pk))  # The linked footnote is read with its table.
    assert items['F0001:S1:N1']['descriptor']['text'] == 'Data are from the authors.'
    assert inv['splits'][0]['status'] == 'ACCEPTED' and not inv['findings']


def test_cells_outside_the_proposal_stay_unassigned(sheet_case):
    tmp, main = sheet_case
    generate, _ = proposal(notes=[{'range': 'I4', 'kind': 'FOOTNOTE', 'applies_to': [1], 'reason': 'Explains *'}])
    inv = d.inventory(main, tmp / 'run/adequacy/inventory.json', run=tmp / 'run', generator=generate)
    left = next(i for i in inv['items'] if i['kind'] == 'UNASSIGNED')
    assert left['descriptor']['unassigned_cells'] == ['B9']


@pytest.mark.parametrize('tables,notes', [
    ([{'title': 'A', 'range': 'B1:D6', 'header_row': 3, 'reason': 'x'}, {'title': 'B', 'range': 'D1:G4', 'header_row': 2, 'reason': 'overlap'}], []),
    ([{'title': 'A', 'range': 'B1:D6', 'header_row': 7, 'reason': 'header outside'}], []),
    ([{'title': 'A', 'range': 'B1:D6', 'header_row': 1, 'reason': 'x'}, {'title': 'B', 'range': 'F1:G4', 'header_row': 5, 'reason': 'empty header'}], []),
    ([{'title': 'A', 'range': 'B1:D6', 'header_row': 3, 'reason': 'x'}], [{'range': 'C5', 'kind': 'FOOTNOTE', 'applies_to': [], 'reason': 'inside a table'}]),
    ([{'title': 'A', 'range': 'B1:D6', 'header_row': 3, 'reason': 'x'}], [{'range': 'I4', 'kind': 'FOOTNOTE', 'applies_to': [2], 'reason': 'unknown table'}]),
    ([{'title': 'A', 'range': 'not-a-range', 'header_row': 3, 'reason': 'x'}], []),
])
def test_invalid_proposal_leaves_the_sheet_unassigned_for_review(sheet_case, tables, notes):
    tmp, main = sheet_case
    generate, _ = proposal(tables, notes)
    inv = d.inventory(main, tmp / 'run/adequacy/inventory.json', run=tmp / 'run', generator=generate)
    assert [i['kind'] for i in inv['items']] == ['UNASSIGNED']
    assert [f['code'] for f in inv['findings']] == ['TABLE_SPLIT_INVALID'] and inv['findings'][0]['severity'] == 'HUMAN_REVIEW'
    assert inv['splits'][0]['status'] == 'REJECTED'


def test_without_a_run_or_within_budget_nothing_is_split_by_guessing(sheet_case, monkeypatch):
    tmp, main = sheet_case
    inv = d.inventory(main, tmp / 'plain/inventory.json')
    assert [f['code'] for f in inv['findings']] == ['TABLE_BOUNDARIES_REQUIRED']
    monkeypatch.setattr(d, 'REQUEST_BUDGET', 1000)
    generate, calls = proposal()
    inv = d.inventory(main, tmp / 'run/adequacy/inventory.json', run=tmp / 'run', generator=generate)
    assert not calls and [f['code'] for f in inv['findings']] == ['TABLE_SPLIT_TOO_LARGE']
    assert [i['kind'] for i in inv['items']] == ['UNASSIGNED']


def range_plan(tmp, main, tables, sheet='Fig. 4b', sha=None):
    f = read_json(main)['data']['files'][0]
    return write_json(tmp / 'range_plan.json', {'schema_version': '1.0', 'files': [{'file_id': 'F0001', 'sha256': sha or f['sha256'],
        'sheets': [{'sheet': sheet, 'tables': tables}]}]})


def test_explicit_range_plan_wins_over_dc_split(sheet_case):
    tmp, main = sheet_case
    generate, calls = proposal()
    plan = range_plan(tmp, main, [{'title': 'Rat PK', 'range': 'B3:D6', 'header_row': 3}])
    inv = d.inventory(main, tmp / 'run/adequacy/inventory.json', run=tmp / 'run', range_plan=plan, generator=generate)
    assert calls == [] and inv['range_plan'] == d.file_ref(plan)
    items = {i['id']: i for i in inv['items']}
    assert items['F0001:S1:T1']['region']['boundary_method'] == 'EXPLICIT_PLAN'
    assert set(items['F0001:S1:unassigned']['descriptor']['unassigned_cells']) == {'B1', 'C2', 'F1', 'F2', 'G2', 'F3', 'G3', 'F4', 'G4', 'I4', 'B9'}


def test_invalid_explicit_plan_is_reported_not_replaced_by_a_model_split(sheet_case):
    tmp, main = sheet_case
    generate, calls = proposal()
    plan = range_plan(tmp, main, [{'title': 'Rat PK', 'range': 'not-a-range', 'header_row': 3}])
    inv = d.inventory(main, tmp / 'run/adequacy/inventory.json', run=tmp / 'run', range_plan=plan, generator=generate)
    assert calls == [] and [f['code'] for f in inv['findings']] == ['TABLE_RANGE_PLAN_INVALID']
    assert [i['kind'] for i in inv['items']] == ['UNASSIGNED']


@pytest.mark.parametrize('sheet,sha,code', [('Fig. 4b', '0' * 64, 'TABLE_RANGE_PLAN_STALE'), ('Missing sheet', None, 'TABLE_RANGE_PLAN_INVALID')])
def test_stale_or_unknown_range_plan_stops_inventory(sheet_case, sheet, sha, code):
    from research_pipeline.common import PipelineError
    tmp, main = sheet_case
    plan = range_plan(tmp, main, [{'title': 'Rat PK', 'range': 'B3:D6', 'header_row': 3}], sheet=sheet, sha=sha)
    with pytest.raises(PipelineError) as error:
        d.inventory(main, tmp / 'run/adequacy/inventory.json', range_plan=plan)
    assert error.value.code == code


def test_hidden_sheet_is_read_but_flagged(sheet_case):
    from openpyxl import load_workbook
    tmp, main = sheet_case
    path = tmp / 'source.xlsx'; wb = load_workbook(path); wb.active.sheet_state = 'hidden'; extra = wb.create_sheet('Visible'); extra['A1'] = 'x'; wb.save(path)
    value = read_json(main); value['data']['files'][0].update(d.file_ref(path)); write_json(main, value)
    generate, _ = proposal()
    inv = d.inventory(main, tmp / 'run/adequacy/inventory.json', run=tmp / 'run', generator=generate)
    pk = next(i for i in inv['items'] if i['id'] == 'F0001:S1:T1')
    assert pk['descriptor']['sheet_visibility'] == 'hidden'
    assert [(f['code'], f['severity']) for f in inv['findings'] if f['code'] == 'HIDDEN_SHEET_CONTENT'] == [('HIDDEN_SHEET_CONTENT', 'FOLLOW_UP')]
    assert all('sheet_visibility' not in i['descriptor'] for i in inv['items'] if i['id'].startswith('F0001:S2'))


def test_pdf_and_docx_are_marked_text_only(tmp_path, monkeypatch):
    from ctxcomp import intake
    doc = tmp_path / 'paper.pdf'; doc.write_bytes(b'%PDF-fixture'); note = tmp_path / 'notes.md'; note.write_text('plain', encoding='utf-8')
    monkeypatch.setattr(intake, 'parse_file', lambda path: {'kind': 'document', 'text': 'Text only'})
    main = write_json(tmp_path / 'main.json', {'data': {'files': [{'id': 'F0001', 'kind': 'pdf', 'role': 'DATA_CANDIDATE', **d.file_ref(doc)},
                                                                    {'id': 'F0002', 'kind': 'md', 'role': 'DATA_CANDIDATE', **d.file_ref(note)}]}})
    inv = d.inventory(main, tmp_path / 'run/adequacy/inventory.json')
    items = {i['id']: i for i in inv['items']}
    assert items['F0001:document']['descriptor']['content_scope'] == 'EXTRACTED_TEXT_ONLY'
    assert 'content_scope' not in items['F0002:document']['descriptor']
    assert [f['affected_id'] for f in inv['findings']] == ['F0001:document']


def test_empty_sheets_are_recorded_without_a_call_or_an_item(tmp_path):
    source = workbook(tmp_path / 'source.xlsx')
    from openpyxl import load_workbook
    wb = load_workbook(source); wb.create_sheet('Sheet2'); wb.save(source)
    main = write_json(tmp_path / 'main.json', {'data': {'files': [{'id': 'F0001', 'kind': 'xlsx', 'role': 'DATA_CANDIDATE', **d.file_ref(source)}]}})
    generate, calls = proposal()
    inv = d.inventory(main, tmp_path / 'run/adequacy/inventory.json', run=tmp_path / 'run', generator=generate)
    assert len(calls) == 1 and inv['files'][0]['empty_sheets'] == ['Sheet2']
    assert not [i for i in inv['items'] if i['id'].startswith('F0001:S2')] and not inv['findings']
    assert [f['code'] for f in d.inventory(main, tmp_path / 'plain/inventory.json')['findings']] == ['TABLE_BOUNDARIES_REQUIRED']  # Only the real sheet.


def test_dc_split_sees_cell_comments(tmp_path):
    from openpyxl import load_workbook
    from openpyxl.comments import Comment
    source = workbook(tmp_path / 'source.xlsx')
    wb = load_workbook(source); ws = wb['Fig. 4b']; ws['C4'].comment = Comment('Rat 1 re-dosed', 'lab'); ws['I6'].comment = Comment('Assay batch 2', 'lab'); wb.save(source)
    main = write_json(tmp_path / 'main.json', {'data': {'files': [{'id': 'F0001', 'kind': 'xlsx', 'role': 'DATA_CANDIDATE', **d.file_ref(source)}]}})
    generate, calls = proposal(notes=[{'range': 'I4:I6', 'kind': 'FOOTNOTE', 'applies_to': [1], 'reason': 'Notes and a comment'},
                                      {'range': 'B9', 'kind': 'DESCRIPTION', 'applies_to': [], 'reason': 'Sheet-level note'}])
    inv = d.inventory(main, tmp_path / 'run/adequacy/inventory.json', run=tmp_path / 'run', generator=generate)
    cells = calls[0]['cells']  # Coordinate to cell text (CELL_FORMAT).
    assert '[comment: Rat 1 re-dosed' in cells['C4'] and cells['I6'].startswith('(empty) [comment: Assay batch 2')
    assert not [i for i in inv['items'] if i['kind'] == 'UNASSIGNED']


@pytest.mark.parametrize('title,accepted', [('Figure 4b Rat PK', True), ('NOT_FOUND', True), ('Rat plasma study 12', False)])
def test_proposed_titles_must_be_copied_from_the_sheet(sheet_case, title, accepted):
    tmp, main = sheet_case
    generate, _ = proposal([{'title': title, 'range': 'B1:D6', 'header_row': 3, 'reason': 'x'},
                            {'title': 'MIC (mg/L)', 'range': 'F1:G4', 'header_row': 2, 'reason': 'x'}],
                           findings=[{'code': 'MERGED_HEADER', 'affected_id': 'F0001:Fig. 4b', 'reason': 'Header unclear.',
                                      'needed_material': 'Confirm header.', 'required_by': 'BEFORE_QC', 'severity': 'FOLLOW_UP'}])
    inv = d.inventory(main, tmp / 'run/adequacy/inventory.json', run=tmp / 'run', generator=generate)
    if accepted:
        pk = next(i for i in inv['items'] if i['id'] == 'F0001:S1:T1')
        assert pk['descriptor']['title'] == ('Fig. 4b!B1:D6' if title == 'NOT_FOUND' else title)
    else:  # The proposal's own findings are kept with the rejection.
        assert [f['code'] for f in inv['findings']] == ['TABLE_SPLIT_INVALID', 'MERGED_HEADER']


def test_explicit_plan_is_checked_like_a_proposal_and_may_name_note_blocks(sheet_case):
    tmp, main = sheet_case
    f = read_json(main)['data']['files'][0]
    def plan(tables, notes):
        return write_json(tmp / 'range_plan.json', {'schema_version': '1.0', 'files': [{'file_id': 'F0001', 'sha256': f['sha256'],
            'sheets': [{'sheet': 'Fig. 4b', 'tables': tables, 'note_blocks': notes}]}]})
    generate, calls = proposal()
    tables = [{'title': 'Rat PK', 'range': 'B1:D6', 'header_row': 3}, {'title': 'MIC', 'range': 'F1:G4', 'header_row': 2}]
    inv = d.inventory(main, tmp / 'run/adequacy/inventory.json', run=tmp / 'run', generator=generate,
                      range_plan=plan(tables, [{'range': 'I4', 'kind': 'FOOTNOTE', 'applies_to': [1]}, {'range': 'B9', 'kind': 'DESCRIPTION'}]))
    items = {i['id']: i for i in inv['items']}
    assert calls == [] and set(items) == {'F0001:S1:T1', 'F0001:S1:T2', 'F0001:S1:N1'}
    assert items['F0001:S1:T1']['descriptor']['linked_notes'] == '* sample lost'
    inv = d.inventory(main, tmp / 'run/adequacy/inventory.json', run=tmp / 'run', generator=generate,
                      range_plan=plan([{'title': 'Rat PK', 'range': 'B1:D9', 'header_row': 7}], []))  # Row 7 is empty.
    assert calls == [] and [x['code'] for x in inv['findings']] == ['TABLE_RANGE_PLAN_INVALID']


def test_excel_totals_rows_are_statistics_and_headerless_tables_need_review():
    from research_pipeline.common import PipelineError
    cells = [{'cell': c + str(r), 'row': r, 'column': i + 1, 'value': v} for r, row in enumerate([['Time', 'Conc'], [1, 2], ['Mean', 2]], 1)
             for i, (c, v) in enumerate(zip('AB', row))]
    region = lambda: [{'start_row': 1, 'end_row': 3, 'left': 1, 'right': 2, 'header_row': 1, 'title': 'T1', 'boundary_method': 'EXCEL_TABLE'}]
    sheet = {'name': 'S', 'cells': cells, 'tables': [{'name': 'T1', 'ref': 'A1:B3', 'header_row_count': 1, 'totals_row_count': 1}]}
    r = d.check_split(sheet, region())[0]
    assert r['end_row'] == 2 and r['note_regions'] == [{'start_row': 3, 'end_row': 3, 'left': 1, 'right': 2, 'kind': 'STATISTICS'}]
    assert d.check_split({**sheet, 'tables': [{'name': 'T1', 'ref': 'A1:B3'}]}, region())[0]['end_row'] == 3  # Older intake: unchanged.
    with pytest.raises(PipelineError) as error:
        d.check_split({**sheet, 'tables': [{'name': 'T1', 'ref': 'A1:B3', 'header_row_count': 0}]}, region())
    assert error.value.code == 'TABLE_HEADER_REQUIRED'


def test_hidden_rows_and_columns_in_a_table_are_flagged(tmp_path):
    from ctxcomp.intake import parse_file
    source = workbook(tmp_path / 'source.xlsx')
    snapshot = parse_file(source); sheet = snapshot['sheets'][0]
    sheet.update(hidden_rows=[5, 9], hidden_columns=[7])
    snap = write_json(tmp_path / 'snapshot.json', snapshot)
    def main_with(path):
        ref = d.file_ref(path)
        return write_json(tmp_path / 'main.json', {'data': {'files': [{'id': 'F0001', 'kind': 'xlsx', 'role': 'DATA_CANDIDATE', **d.file_ref(source),
                                                                        'snapshot_path': ref['path'], 'snapshot_sha256': ref['sha256']}]}})
    generate, calls = proposal()
    inv = d.inventory(main_with(snap), tmp_path / 'run/adequacy/inventory.json', run=tmp_path / 'run', generator=generate)
    assert calls[0]['sheet']['hidden_rows'] == [5, 9]
    items = {i['id']: i for i in inv['items']}
    assert (items['F0001:S1:T1']['descriptor']['hidden_rows'], items['F0001:S1:T1']['descriptor']['hidden_columns']) == ([5], [])
    assert (items['F0001:S1:T2']['descriptor']['hidden_rows'], items['F0001:S1:T2']['descriptor']['hidden_columns']) == ([], [7])
    assert [(f['code'], f['affected_id'], f['severity']) for f in inv['findings']] == [
        ('HIDDEN_ROWS_OR_COLUMNS', 'F0001:S1:T1', 'FOLLOW_UP'), ('HIDDEN_ROWS_OR_COLUMNS', 'F0001:S1:T2', 'FOLLOW_UP')]
    del sheet['hidden_rows'], sheet['hidden_columns']  # Older intake: unknown, not "nothing hidden".
    inv = d.inventory(main_with(write_json(tmp_path / 'snapshot.json', snapshot)), tmp_path / 'run/adequacy/inventory.json', run=tmp_path / 'run', generator=generate)
    assert inv['items'][0]['descriptor']['hidden_rows_and_columns'] == 'NOT_RECORDED' and not inv['findings']


def test_text_beside_an_excel_table_is_its_note_and_numbers_stay_unassigned(tmp_path):
    from openpyxl.worksheet.table import Table
    wb = Workbook(); ws = wb.active; ws.title = 'PK'
    for row in [['Time (h)', 'Conc (ng/mL)'], [0.5, 'BLQ'], [1, 3.2]]: ws.append(row)
    ws['A5'] = 'BLQ: below 1 ng/mL; values are mean of n=3'; ws['B6'] = 99
    ws.add_table(Table(displayName='PKT', ref='A1:B3')); wb.save(tmp_path / 'a.xlsx')
    main = write_json(tmp_path / 'main.json', {'data': {'files': [{'id': 'F0001', 'kind': 'xlsx', 'role': 'DATA_CANDIDATE', **d.file_ref(tmp_path / 'a.xlsx')}]}})
    table, rest = d.inventory(main, tmp_path / 'inventory.json')['items']
    assert table['region']['note_regions'] == [{'start_row': 5, 'end_row': 5, 'left': 1, 'right': 1, 'kind': 'SHEET_TEXT'}]
    assert table['descriptor']['linked_notes'] == 'BLQ: below 1 ng/mL; values are mean of n=3'
    assert rest['kind'] == 'UNASSIGNED' and rest['descriptor']['unassigned_cells'] == ['B6']


def test_footnote_markers_link_cells_to_their_notes_without_changing_values(tmp_path):
    from openpyxl.worksheet.table import Table
    wb = Workbook(); ws = wb.active; ws.title = 'PK'
    for row in [['Time (h)', 'Conc (ng/mL)', 'Dose (mg/m²)'], [0.5, '*', 1], [1, '3.2†', 1], [2, '1.1‡', 1]]: ws.append(row)
    ws['A6'] = '* sample lost'; ws['A7'] = '† hemolysed sample'
    ws.add_table(Table(displayName='PKT', ref='A1:C4')); wb.save(tmp_path / 'a.xlsx')
    main = write_json(tmp_path / 'main.json', {'data': {'files': [{'id': 'F0001', 'kind': 'xlsx', 'role': 'DATA_CANDIDATE', **d.file_ref(tmp_path / 'a.xlsx')}]}})
    inv = d.inventory(main, tmp_path / 'inventory.json')
    table = inv['items'][0]
    assert table['descriptor']['footnote_links'] == [
        {'cell': 'B2', 'marker': '*', 'note_cell': 'A6', 'note': '* sample lost'},
        {'cell': 'B3', 'marker': '†', 'note_cell': 'A7', 'note': '† hemolysed sample'}]
    assert [(f['code'], f['severity']) for f in inv['findings']] == [('FOOTNOTE_MARKER_UNRESOLVED', 'FOLLOW_UP')]
    assert 'B4' in inv['findings'][0]['reason'] and 'C1' not in inv['findings'][0]['reason']


def test_a_marker_finds_its_note_elsewhere_on_the_sheet(sheet_case):
    tmp, main = sheet_case
    f = read_json(main)['data']['files'][0]
    plan = write_json(tmp / 'range_plan.json', {'schema_version': '1.0', 'files': [{'file_id': 'F0001', 'sha256': f['sha256'],
        'sheets': [{'sheet': 'Fig. 4b', 'tables': [{'title': 'Rat PK', 'range': 'B1:D6', 'header_row': 3}],
                    'note_blocks': [{'range': 'I4', 'kind': 'FOOTNOTE', 'applies_to': []}]}]}]})
    items = {i['id']: i for i in d.inventory(main, tmp / 'inventory.json', range_plan=plan)['items']}
    assert items['F0001:S1:N1']['kind'] == 'NOTE'  # The note stays its own item; only the marker is linked.
    assert items['F0001:S1:T1']['descriptor']['footnote_links'] == [{'cell': 'D4', 'marker': '*', 'note_cell': 'I4', 'note': '* sample lost'}]


def test_a_notes_sheet_is_shown_with_every_table_and_resolves_markers(tmp_path):
    from openpyxl.worksheet.table import Table
    wb = Workbook(); ws = wb.active; ws.title = 'PK'
    for row in [['Time (h)', 'Conc (ng/mL)'], [0.5, '*'], [1, '3.2§']]: ws.append(row)
    ws.add_table(Table(displayName='PKT', ref='A1:B3'))
    notes = wb.create_sheet('Notes'); notes['A1'] = 'Abbreviations: BLQ, below the limit of quantification'; notes['A2'] = '* sample lost'
    wb.save(tmp_path / 'a.xlsx')
    main = write_json(tmp_path / 'main.json', {'data': {'files': [{'id': 'F0001', 'kind': 'xlsx', 'role': 'DATA_CANDIDATE', **d.file_ref(tmp_path / 'a.xlsx')}]}})
    inv = d.inventory(main, tmp_path / 'inventory.json')
    table = next(i for i in inv['items'] if i['kind'] == 'TABLE')
    assert table['descriptor']['footnote_links'] == [{'cell': 'B2', 'marker': '*', 'note_cell': 'A2', 'note': '* sample lost', 'note_sheet': 'Notes'}]
    assert table['descriptor']['workbook_notes'] == [{'sheet': 'Notes', 'text': 'Abbreviations: BLQ, below the limit of quantification\n* sample lost'}]
    assert [(f['code'], 'B3' in f['reason']) for f in inv['findings']] == [('FOOTNOTE_MARKER_UNRESOLVED', True)]


def test_cells_are_sent_as_their_content_and_stay_distinguishable():
    date={'type':'datetime','iso':'2024-01-02T08:00:00'}
    cases=[({'value':12},'12'),({'value':0.5},'0.5'),({'value':'Time (h)'},'Time (h)'),({'value':'BLQ'},'BLQ'),
           ({'value':'12'},'text "12"'),({'value':'TRUE'},'text "TRUE"'),({'value':' padded'},'text " padded"'),
           ({'value':'formula =A1 (not evaluated)'},'text "formula =A1 (not evaluated)"'),({'value':'time after dose'},'time after dose'),
           ({'value':True},'TRUE'),({'value':date},'datetime 2024-01-02T08:00:00'),({'value':'#DIV/0!','data_type':'e'},'error #DIV/0!'),
           ({'value':'=B2*2','data_type':'f','cached_value':8},'formula =B2*2 (not evaluated; cached value 8)'),
           ({'value':'=B3','data_type':'f'},'formula =B3 (not evaluated)'),
           ({'value':None,'comment':'Rat 1 re-dosed'},'(empty) [comment: Rat 1 re-dosed]'),({'value':4,'comment':'Batch 2'},'4 [comment: Batch 2]')]
    assert [d.render_cell(cell) for cell,_ in cases]==[text for _,text in cases]
    assert d.render_cell({'value':'12'},csv_text=True)=='12'  # Every CSV value is text, so numbers are not marked.


def test_a_rejected_split_is_not_reused_and_an_accepted_one_is(sheet_case):
    tmp, main = sheet_case
    bad, bad_calls = proposal([{'title': 'Rat plasma study 12', 'range': 'B1:D6', 'header_row': 3, 'reason': 'x'}])
    good, good_calls = proposal()
    bad.executor_id = good.executor_id = 'fixture'
    run = lambda generate: d.inventory(main, tmp / 'run/adequacy/inventory.json', run=tmp / 'run', generator=generate)
    assert [f['code'] for f in run(bad)['findings']] == ['TABLE_SPLIT_INVALID']
    assert not list((tmp / 'run/data_agents/kept').glob('*'))
    run(good); run(good)  # The second inventory reuses the accepted proposal.
    assert len(good_calls) == 1 and len(list((tmp / 'run/data_agents/kept').iterdir())) == 1
