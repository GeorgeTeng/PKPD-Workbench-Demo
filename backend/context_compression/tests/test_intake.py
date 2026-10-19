import io
import zipfile
from pathlib import Path
import pytest
from openpyxl import Workbook
from ctxcomp.intake import intake_files, verify_intake, inventory_sources
from ctxcomp.engine import init_run, load_run, prepare
from ctxcomp.io import read_json, write_json, leaves
from ctxcomp.validation import context_check
from attachment_fixture import accept_empty_search


def make_package(path):
    book = Workbook()
    sheet = book.active
    sheet.title = 'Original'
    sheet.append(['Time', 'Value'])
    sheet.append([0, '<LLOQ'])
    sheet.append([1, '=1+2'])
    sheet.append([2, None])
    buf = io.BytesIO(); book.save(buf)
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr('a/proposal.md', 'PMB project; observations require QC.\n')
        archive.writestr('b/data.xlsx', buf.getvalue())
        archive.writestr('c/catalog.csv', 'model_id,kind\nONE,PK\n')
        archive.writestr('d/benchmark_reference.json', '{"secret_reference_parameter":987654.321}')
        archive.writestr('e/proposal.md', 'Second document with the same basename.')


def test_all_file_contents_read_and_originals_untouched(tmp_path):
    package = tmp_path/'inputs.zip'; make_package(package)
    original = package.read_bytes()
    result = intake_files(tmp_path/'intake', package=package)
    assert len(result['manifest']['files']) == 5
    assert package.read_bytes() == original
    assert [f['id'] for f in result['manifest']['files']] == [f'F{i:04d}' for i in range(1,6)]
    assert len({f['working_name'] for f in result['manifest']['files']}) == 5
    assert all(f['read_status']=='READ_COMPLETE' and f['qc_status']=='NOT_RUN' for f in result['manifest']['files'])
    reference = next(f for f in result['manifest']['files'] if f['role']=='REFERENCE_ONLY')
    snapshot = read_json(tmp_path/'intake'/reference['snapshot_path'])
    assert snapshot['value']['secret_reference_parameter'] == 987654.321
    assert not any('987654.321' in s['text'] for s in result['sources'])
    assert verify_intake(tmp_path/'intake/manifest.json') == result['manifest']


def test_excel_formula_missing_and_location_are_preserved(tmp_path):
    package=tmp_path/'inputs.zip'; make_package(package)
    result=intake_files(tmp_path/'intake',package=package)
    file=next(f for f in result['manifest']['files'] if f['kind']=='xlsx')
    sheet=read_json(tmp_path/'intake'/file['snapshot_path'])['sheets'][0]
    cells={c['cell']:c for c in sheet['cells']}
    assert cells['B2']['value']=='<LLOQ'
    assert cells['B3']['value']=='=1+2' and cells['B3']['cached_value'] is None
    assert cells['B3']['formula_evaluated'] is False
    assert 'B4' not in cells and sheet['rows']==4
    assert not (tmp_path/'intake/tables').exists()


def test_hidden_rows_and_columns_are_recorded_per_sheet(tmp_path):
    book = Workbook(); sheet = book.active; sheet.title = 'Animals'
    for row in [['Animal', 'Dose', 'Scratch', 'Conc', 'Note'], ['A1', 10, 1, 5.2, ''], ['A2', 10, 2, 4.8, 'excluded'], ['A3', 10, 3, 5.0, '']]:
        sheet.append(row)
    sheet.row_dimensions[3].hidden = True
    sheet.column_dimensions.group('B', 'C', hidden=True)  # one stored span, as Excel saves hidden B:C
    sheet.column_dimensions['Z'].hidden = True  # outside the used range
    buf = io.BytesIO(); book.save(buf)
    package = tmp_path/'inputs.zip'
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr('proposal.md', 'PMB project.\n')
        archive.writestr('animals.xlsx', buf.getvalue())
    result = intake_files(tmp_path/'intake', package=package)
    file = next(f for f in result['manifest']['files'] if f['kind']=='xlsx')
    sheet = read_json(tmp_path/'intake'/file['snapshot_path'])['sheets'][0]
    assert sheet['hidden_rows'] == [3] and sheet['hidden_columns'] == [2, 3]
    make_package(tmp_path/'plain.zip')
    plain = intake_files(tmp_path/'plain', package=tmp_path/'plain.zip')
    plain_sheet = read_json(tmp_path/'plain'/next(f for f in plain['manifest']['files'] if f['kind']=='xlsx')['snapshot_path'])['sheets'][0]
    assert plain_sheet['hidden_rows'] == [] and plain_sheet['hidden_columns'] == []


def test_excel_tables_record_header_and_totals_rows(tmp_path):
    from openpyxl.worksheet.table import Table
    book = Workbook(); sheet = book.active; sheet.title = 'Doses'
    for row in [['Animal', 'Dose'], ['A1', 10], ['A2', 20], ['Mean', 15]]:
        sheet.append(row)
    sheet.add_table(Table(displayName='WithTotals', ref='A1:B4', totalsRowCount=1))
    sheet['D1'] = 'x'; sheet['D2'] = 1
    sheet.add_table(Table(displayName='NoHeader', ref='D1:D2', headerRowCount=0))
    buf = io.BytesIO(); book.save(buf)
    package = tmp_path/'inputs.zip'
    with zipfile.ZipFile(package, 'w') as archive:
        archive.writestr('proposal.md', 'PMB project.\n')
        archive.writestr('doses.xlsx', buf.getvalue())
    result = intake_files(tmp_path/'intake', package=package)
    file = next(f for f in result['manifest']['files'] if f['kind']=='xlsx')
    tables = {t['name']: t for t in read_json(tmp_path/'intake'/file['snapshot_path'])['sheets'][0]['tables']}
    assert tables['WithTotals'] == {'name': 'WithTotals', 'ref': 'A1:B4', 'header_row_count': 1, 'totals_row_count': 1}
    assert tables['NoHeader'] == {'name': 'NoHeader', 'ref': 'D1:D2', 'header_row_count': 0, 'totals_row_count': 0}


@pytest.mark.parametrize('field',['raw_path','snapshot_path'])
def test_changed_attachment_blocks_context_continuation(tmp_path,field):
    package=tmp_path/'inputs.zip'; make_package(package)
    run=tmp_path/'run'; init_run(run,package=package,proposal_entry='a/proposal.md')
    manifest=read_json(run/'intake/manifest.json')
    target=run/'intake'/manifest['files'][0][field]
    target.write_bytes(target.read_bytes()+b' ')
    with pytest.raises(ValueError,match='Changed'):
        load_run(run)


@pytest.mark.parametrize('entry',['../outside.txt','C:/outside.txt','a/../../outside.txt','bad.exe'])
def test_unsafe_or_unsupported_zip_fails(tmp_path,entry):
    package=tmp_path/'unsafe.zip'
    with zipfile.ZipFile(package,'w') as archive: archive.writestr(entry,'untrusted')
    with pytest.raises(ValueError): intake_files(tmp_path/'intake',package=package)
    assert not (tmp_path/'outside.txt').exists()


def test_inventory_declaration_is_planning_evidence_not_proposal_evidence(tmp_path):
    proposal=tmp_path/'proposal.md'; proposal.write_text('Study details NOT_FOUND.',encoding='utf-8')
    inventory=tmp_path/'inventory.json'
    quote='Supplied mixed workbook; not QC verified.'
    write_json(inventory,[{'id':'MIXED_SOURCE_TABLES','description':quote,'path':'Z:/must_not_read.xlsx'}])
    run=tmp_path/'run'; init_run(run,proposal,inventory_path=inventory)
    accept_empty_search(run)
    bundle,_=load_run(run)
    source=next(s for s in bundle['planning_sources'] if s['id']=='MIXED_SOURCE_TABLES')
    assert source['role']=='INVENTORY_DECLARATION' and source['text']==quote
    context={'version':'3.0','objective':quote,'study':{k:'NOT_FOUND' for k in ['drug','regimen','population','system','measurements','methods']},
             'data':{'available':[],'required':[]},'rules':[],'checks':[],'uncertainties':[]}
    evidence=[{'path':p,'status':'EXPLICIT' if p=='/objective' else 'NOT_FOUND',
               'source_id':'MIXED_SOURCE_TABLES' if p=='/objective' else '',
               'quote':quote if p=='/objective' else '', 'reason':'Registry declaration only.'}
              for p,v in leaves(context) if p!='/version']
    with pytest.raises(ValueError):
        context_check(context,evidence,bundle['sources'],bundle['budget'])
    assert prepare(run,'requirements')['payload']['sources']==bundle['sources']
    assert prepare(run,'requirements')['payload']['inventory']==[]


def test_ambiguous_proposal_stops_instead_of_compressing_all_documents(tmp_path):
    package=tmp_path/'inputs.zip'; make_package(package)
    with pytest.raises(ValueError, match='exactly one proposal'):
        init_run(tmp_path/'run', package=package)
    assert not (tmp_path/'run/handoff/main.json').exists()


def test_proposal_only_compression_and_complete_file_routing(tmp_path):
    package=tmp_path/'inputs.zip'; make_package(package)
    run=tmp_path/'run'
    init_run(run, package=package, proposal_entry='a/proposal.md')
    accept_empty_search(run)
    bundle,_=load_run(run)
    request=prepare(run,'requirements')['payload']
    assert [s['name'] for s in request['sources']]==['a/proposal.md']
    assert ''.join(u['text'] for u in request['source_units'])=='PMB project; observations require QC.\n'
    assert all(s['role'] in {'PRIMARY_SOURCE','FILE_REGISTRY'} for s in bundle['planning_sources'])
    assert not any('987654.321' in s['text'] or '<LLOQ' in s['text'] for s in bundle['planning_sources'])
    handoff=read_json(run/'audit/file_registry.json')
    assert not (run/'handoff/main.json').exists()
    assert len(handoff['files'])==5 and handoff['status']=='FILES_CHECKED_CONTEXT_PENDING'
    assert sum(f['compression_input'] for f in handoff['files'])==1
    assert all(not f['fit_ready'] for f in handoff['files'])
    assert {f['purpose'] for f in handoff['files']}=={'PROPOSAL','DATA_CANDIDATE','MODEL_CATALOG','REFERENCE_ONLY','SUPPORTING_DOCUMENT'}
    assert next(f for f in handoff['files'] if f['purpose']=='REFERENCE_ONLY')['receivers']==['validation']
    assert verify_intake(run/'intake/manifest.json')['compression_scope']['mode']=='PROPOSAL_ONLY'
    handoff['files'][1]['receivers']=['pk_longitudinal']
    write_json(run/'audit/file_registry.json',handoff)
    with pytest.raises(ValueError,match='File handoff changed'):
        load_run(run)


def test_inventory_cannot_redefine_an_existing_source():
    with pytest.raises(ValueError,match='collision'):
        inventory_sources([{'id':'S1','text':'original'}],[{'id':'S1','description':'different'}])


def test_manifest_ids_stay_same_for_identical_input(tmp_path):
    package=tmp_path/'inputs.zip'; make_package(package)
    a=intake_files(tmp_path/'one',package=package)
    b=intake_files(tmp_path/'two',package=package)
    assert a['manifest']==b['manifest']
