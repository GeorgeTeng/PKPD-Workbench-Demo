"""Compression rules 1.27.0 (CC002 table_context): a spreadsheet row travels with its table's title and
column-header rows. The layout mirrors the 2026-10-09 Voriconazole sheet, where a citation review saw
'Mean ± SD | 24 ± 17' without the header that names the column as the free-drug AUC/MIC ratio."""
import copy
import io
import json
import zipfile

from ctxcomp import engine, supporting
from ctxcomp import supporting_agents as agents
from ctxcomp.engine import init_run, prepare, accept
from ctxcomp.rules import load_rules
from test_runtime_rules import question

HEADER = ['C. albicans strain', 'MIC (mg/liter) Voriconazole', 'ED50 (mg/kg/24 h)',
          '24-h AUC/MIC ratio Total drug', '24-h AUC/MIC ratio Free drug']


def workbook(extra_rows=0):
    from openpyxl import Workbook
    book = Workbook(); sheet = book.active; sheet.title = 'Mouse'
    sheet['A39'] = 'Serum PK parameters given in the Fig. 1 legend'
    sheet['A40'] = 'S02 | DOI 10.1128/AAC.47.10.3165-3169.2003'
    for col, value in enumerate(['Dose (mg/kg)', 'Elimination half-life (h)', 'AUC (mg·h/liter)'], 1):
        sheet.cell(41, col, value)
    for col, value in enumerate(['40', '2.90 ± 0.12', '27.2 ± 12.2'], 1):
        sheet.cell(42, col, value)
    sheet['A50'] = 'Voriconazole efficacy against 10 C. albicans isolates'
    sheet['A51'] = 'S02 | DOI 10.1128/AAC.47.10.3165-3169.2003'
    sheet['A52'] = 'Neutropenic mice as in the PK block'
    for col, value in enumerate(HEADER, 1):
        sheet.cell(53, col, value)
    for n in range(54, 65 + extra_rows):
        for col, value in enumerate([f'K{n}', '0.03', '19.7', '60.8', f'{n}.3'], 1):
            sheet.cell(n, col, value + (' filler text for size' * 20 if extra_rows and col == 1 else ''))
    last = 65 + extra_rows
    sheet.cell(last, 1, 'Mean ± SD'); sheet.cell(last, 5, '24 ± 17')
    data = io.BytesIO(); book.save(data)
    return data.getvalue(), last


def table_run(tmp_path, terms=('24 ± 17',), extra_rows=0):
    content, last = workbook(extra_rows)
    archive = tmp_path / 'input.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('proposal.md', 'Study mouse PK/PD of voriconazole; whether the AUC/MIC target is free or total drug is not stated.')
        z.writestr('tables.xlsx', content)
    run = tmp_path / 'run'
    init_run(run, package=archive, proposal_entry='proposal.md')
    plan = prepare(run, 'attachment_plan')
    fid = plan['payload']['files'][0]['id']
    accept(run, 'attachment_plan', {'request_sha256': plan['request_sha256'],
                                    'questions': [question(fid, terms=list(terms))]})
    return run, fid, last, prepare(run, 'attachment_evidence')


def row(fid, n):
    return f'{fid}_S01R{n:06d}'


def test_table_heads_follow_title_and_header_rows():
    cells = lambda n, values: (f'sheet Mouse row {n}', json.dumps({'sheet': 'Mouse', 'cells': [
        {'row': n, 'column': c, 'value': v} for c, v in enumerate(values, 1)]}), f'S01R{n:06d}')
    rows = ([cells(n, ['title']) for n in (39, 40)] + [cells(41, ['Dose (mg/kg)', 'AUC'])] + [cells(42, ['40', '27.2 ± 12.2'])]
            + [cells(n, ['title']) for n in (50, 51, 52)] + [cells(53, HEADER)]
            + [cells(n, ['K1', '0.03', '60.8']) for n in range(54, 65)] + [cells(65, ['Mean ± SD', '24 ± 17'])])
    heads = supporting.table_heads(rows)
    numbers = lambda i: [int(rows[h][2][-6:]) for h in heads.get(i, [])]
    index = {int(r[2][-6:]): i for i, r in enumerate(rows)}
    assert numbers(index[65]) == [50, 51, 52, 53]
    assert numbers(index[42]) == [39, 40, 41]
    assert numbers(index[53]) == [50, 51, 52]   # A header row gets its table's first rows.
    assert numbers(index[50]) == []             # The first row of a table has nothing above it.
    long = [cells(n, ['title']) for n in range(1, 13)] + [cells(13, HEADER), cells(14, ['K1', '0.03'])]
    assert [int(long[h][2][-6:]) for h in supporting.table_heads(long)[13]] == [1, 2, 8, 9, 10, 11, 12, 13]


def test_a_hit_on_a_value_row_brings_its_title_and_header_rows(tmp_path):
    run, fid, last, request = table_run(tmp_path)
    p = request['payload']
    passages = {x['id']: x for x in p['passages']}
    assert passages[row(fid, last)]['table_header_ids'] == [row(fid, n) for n in (50, 51, 52, 53)]
    assert set(passages) == {row(fid, n) for n in (50, 51, 52, 53, last - 1, last)}
    assert set(p['searches'][0]['passage_ids']) == set(passages)
    assert 'table_header_ids' in p['instructions']


def test_every_evidence_batch_carries_the_header_rows_of_its_tables(tmp_path):
    run, fid, last, request = table_run(tmp_path, terms=('K', 'Mean'), extra_rows=40)
    size = lambda passages: len(agents.canonical(agents.file_request(request['payload'], fid, passages)))
    passages = request['payload']['passages']
    fixed = size(passages[:1])
    calls = agents.plan_calls(request, max_chars=fixed + (size(passages) - fixed) // 4)
    assert len(calls) >= 3
    for call in calls:
        ids = {x['id'] for x in call['request']['payload']['passages']}
        for x in call['request']['payload']['passages']:
            assert set(x.get('table_header_ids', [])) <= ids
    for call in calls:
        ids = {x['id'] for x in call['request']['payload']['passages']}
        if any(int(i[-6:]) >= 54 for i in ids):
            assert {row(fid, n) for n in (50, 51, 52, 53)} <= ids


def test_a_citation_review_of_a_row_receives_its_header_rows(tmp_path):
    from ctxcomp.citation_repair import make_request
    run, fid, last, request = table_run(tmp_path)
    parent = agents.plan_calls(request)[0]['request']
    candidate = {'request_sha256': parent['request_sha256'], 'answers': [{
        'question_id': 'MI001', 'status': 'FOUND', 'statement': 'The free-drug 24-h AUC/MIC ratio is 24 ± 17.',
        'reason': 'Authored test.', 'citations': [{'passage_id': row(fid, last), 'quote': '24 (SD 17)'}]}]}
    review = make_request(parent, candidate)['payload']
    assert {x['id'] for x in review['passages']} == {row(fid, n) for n in (50, 51, 52, 53, last)}
    assert 'table_header_ids' in review['instructions']


def test_a_cited_row_brings_its_header_rows_into_later_stages(tmp_path):
    run, fid, last, request = table_run(tmp_path)
    accept(run, 'attachment_evidence', {'request_sha256': request['request_sha256'], 'answers': [{
        'question_id': 'MI001', 'status': 'FOUND', 'statement': 'The free-drug 24-h AUC/MIC ratio is 24 ± 17.',
        'reason': 'Authored test.', 'citations': [{'passage_id': row(fid, last), 'quote': '24 ± 17'}]}]})
    payload = prepare(run, 'requirements')['payload']
    supporting_sources = {s['id']: s for s in payload['sources'] if s['role'] == 'SUPPORTING_EVIDENCE'}
    assert set(supporting_sources) == {row(fid, n) for n in (50, 51, 52, 53, last)}
    assert supporting_sources[row(fid, last)]['table_header_ids'] == [row(fid, n) for n in (50, 51, 52, 53)]
    assert 'Free drug' in supporting_sources[row(fid, 53)]['text']
    assert 'table_header_ids' in payload['instructions']
    from ctxcomp.requirements_parts import supporting_groups
    groups = supporting_groups(payload, 3)
    assert len(groups) == 1 and set(groups[0]['passage_ids']) == set(supporting_sources)


def test_runs_frozen_before_1_27_keep_row_only_passages(tmp_path, monkeypatch):
    earlier = copy.deepcopy(load_rules())
    next(r for r in earlier['rules'] if r['id'] == 'CC002')['host_requirement'].pop('table_context')
    monkeypatch.setattr(engine, 'load_rules', lambda: copy.deepcopy(earlier))
    run, fid, last, request = table_run(tmp_path)
    p = request['payload']
    assert {x['id'] for x in p['passages']} == {row(fid, last - 1), row(fid, last)}
    assert not any('table_header_ids' in x for x in p['passages'])
    assert 'table_header_ids' not in p['instructions']
