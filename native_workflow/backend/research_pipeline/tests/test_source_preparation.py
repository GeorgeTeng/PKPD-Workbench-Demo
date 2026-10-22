import io
import zipfile
import pytest
from openpyxl import Workbook
from fastapi.testclient import TestClient
from ctxcomp.intake import intake_files
from research_pipeline.source_preparation import prepare_sources
from research_pipeline.common import read_json, write_json
from research_pipeline.api import create_app


def package_bytes():
    book=Workbook(); sheet=book.active; sheet.title='Mixed'
    for row in [
        ['PK table'],['S21 | DOI 10.1234/example'],['PMB; concentration mg/L; time h.'],
        ['* indicates cannula blockage.'],['Time (h)','Rat 1','Rat 2'],
        [0,0.0,5.0],[1,'<LLOQ',None],[2,'*','No sampling'],[],[],
        ['Endpoint table'],['S22 | DOI 10.1234/second'],['Terminal observations.'],
        ['Group','Mouse 1','Mouse 2'],['Control',8,None],['PMB',4,5]]:
        sheet.append(row)
    xlsx=io.BytesIO(); book.save(xlsx)
    result=io.BytesIO()
    with zipfile.ZipFile(result,'w') as archive:
        archive.writestr('source.xlsx',xlsx.getvalue())
        archive.writestr('proposal.md','A study.')
    return result.getvalue()


def setup_intake(tmp_path):
    package=tmp_path/'package.zip'; package.write_bytes(package_bytes())
    intake_files(tmp_path/'intake',package=package)
    return tmp_path/'intake/manifest.json'


def test_split_wide_tables_without_losing_empty_or_censored_cells(tmp_path):
    manifest=setup_intake(tmp_path)
    result=prepare_sources(manifest,tmp_path/'b2')
    assert result['status']=='WAITING_FOR_REVIEW' and len(result['tables'])==2
    pk=read_json(tmp_path/'b2'/result['tables'][0]['records_path'])
    assert len(pk['records'])==6
    by_cell={r['source_cell']:r for r in pk['records']}
    assert by_cell['B6']['concentration_mg_L']==0.0
    assert by_cell['B7']['status']=='BLQ' and by_cell['B7']['concentration_mg_L'] is None
    assert by_cell['C7']['status']=='EMPTY_SLOT'
    assert by_cell['B8']['status']=='MISSING_CANNULA_BLOCKAGE'
    assert by_cell['C8']['status']=='NOT_SAMPLED'
    assert all(r['subject_id']=='NOT_FOUND' for r in pk['records'])
    assert pk['independent_animal_count']=='NOT_FOUND'
    pd=read_json(tmp_path/'b2'/result['tables'][1]['records_path'])
    assert pd['records'][0]['unit_id_candidate']!=pd['records'][2]['unit_id_candidate']
    assert result['released_datasets']==[] and result['model_execution']=='NOT_RUN'


def test_blank_rows_alone_do_not_define_source_tables(tmp_path):
    book=Workbook(); sheet=book.active
    for row in [['time','value'],[0,1],[],[1,2]]: sheet.append(row)
    path=tmp_path/'unknown.xlsx'; book.save(path)
    intake_files(tmp_path/'intake',paths=[path])
    result=prepare_sources(tmp_path/'intake/manifest.json',tmp_path/'b2')
    assert result['status']=='FAILED'
    assert result['errors'][0]['code']=='TABLE_BOUNDARIES_REQUIRED'
    assert result['released_datasets']==[]


@pytest.mark.parametrize('anchor', ['S01 | https://doi.org/10.1093/example',
                                   'S01 | http://dx.doi.org/10.1093/example'])
def test_doi_url_section_does_not_become_extra_terminal_animals(tmp_path, anchor):
    book = Workbook(); sheet = book.active
    for row in [['Endpoint table'], ['S21 | DOI 10.1234/old'],
                ['Group', 'Mouse 1', 'Mouse 2'], ['PMB', 4, 5], [],
                ['Strain MICs'], [anchor], ['Species', 'Strain', 'MIC'],
                ['K. pneumoniae', 'KP032', 0.5]]:
        sheet.append(row)
    path = tmp_path / 'mixed.xlsx'; book.save(path)
    intake_files(tmp_path / 'intake', paths=[path])
    result = prepare_sources(tmp_path / 'intake/manifest.json', tmp_path / 'b2')
    assert result['status'] == 'WAITING_FOR_REVIEW'
    assert len(result['tables']) == 2
    first = read_json(tmp_path / 'b2' / result['tables'][0]['records_path'])
    second = read_json(tmp_path / 'b2' / result['tables'][1]['records_path'])
    assert len(first['records']) == 2
    assert all(r['group_label'] == 'PMB' for r in first['records'])
    assert second['records'][0]['c003_mic'] == 0.5
    assert second['records'][0]['source_cells']['c003_mic'] == 'C9'


def test_explicit_plan_enables_rectangular_source(tmp_path):
    book=Workbook(); book.active.append(['time','value']); book.active.append([0,1])
    path=tmp_path/'source.xlsx'; book.save(path)
    intake_files(tmp_path/'intake',paths=[path])
    result=prepare_sources(tmp_path/'intake/manifest.json',tmp_path/'b2',
                           {'F0001:Sheet':[{'range':'A1:B2','header_row':1,'title':'Explicit source'}]})
    assert result['status']=='WAITING_FOR_REVIEW'
    assert result['tables'][0]['record_count_including_empty_slots']==1


def test_duplicate_csv_headers_are_not_overwritten(tmp_path):
    path=tmp_path/'duplicate.csv'; path.write_text('id,value,value\n1,2,3\n',encoding='utf-8')
    intake_files(tmp_path/'intake',paths=[path])
    result=prepare_sources(tmp_path/'intake/manifest.json',tmp_path/'b2')
    assert result['status']=='FAILED' and result['errors'][0]['code']=='AMBIGUOUS_HEADER'


def test_modified_snapshot_stops_before_any_table(tmp_path):
    manifest=setup_intake(tmp_path)
    file=read_json(manifest)['files'][0]
    path=manifest.parent/file['snapshot_path']; path.write_bytes(path.read_bytes()+b' ')
    result=prepare_sources(manifest,tmp_path/'b2')
    assert result['status']=='FAILED' and not result['tables']


def test_unreviewed_file_handoff_blocks_b2(tmp_path):
    from ctxcomp.engine import init_run
    package=tmp_path/'package.zip'; package.write_bytes(package_bytes())
    init_run(tmp_path/'b1',package=package)
    result=prepare_sources(tmp_path/'b1/audit/file_registry.json',tmp_path/'b2')
    assert result['status']=='FAILED' and result['errors'][0]['code']=='CONTEXT_NOT_READY'
    assert not result['tables']


def test_catalog_is_routed_to_search_not_converted_to_observations(tmp_path):
    from ctxcomp.engine import init_run
    proposal=tmp_path/'proposal.md'; proposal.write_text('A study.',encoding='utf-8')
    catalog=tmp_path/'catalog.csv'; catalog.write_text('model_id,kind\nONE,PK\n',encoding='utf-8')
    init_run(tmp_path/'b1',proposal=proposal,attachments=[catalog])
    result=prepare_sources(tmp_path/'b1/intake/manifest.json',tmp_path/'b2')
    assert result['status']=='WAITING_FOR_REVIEW' and not result['tables']
    assert any(f['action']=='ROUTED_TO_LITERATURE_SEARCH' for f in result['files'])


def test_reviewed_proposal_handoff_reaches_b2_without_bypassing_qc(tmp_path):
    """Authored response replay verifies the interface; it is not a model call."""
    import importlib.util
    from pathlib import Path
    from ctxcomp.engine import init_run, prepare, accept, STAGES
    examples=Path(__file__).parents[2]/'context_compression/examples'
    spec=importlib.util.spec_from_file_location('handoff_replay',examples/'replay_demo.py')
    replay=importlib.util.module_from_spec(spec); spec.loader.exec_module(replay)
    replay.replay(tmp_path/'authored_reference')
    package=tmp_path/'package.zip'
    with zipfile.ZipFile(io.BytesIO(package_bytes())) as source, zipfile.ZipFile(package,'w') as target:
        target.writestr('source.xlsx',source.read('source.xlsx'))
        target.writestr('proposal.md',(examples/'current_research/proposal.md').read_bytes())
        target.writestr('catalog.csv','model_id,kind\nONE,PK\n')
        target.writestr('benchmark_reference.json','{"reference":123}')
    # The authored replay uses the supported legacy review schema; keep its
    # policy and review mode consistent without changing production defaults.
    run=tmp_path/'b1'
    init_run(run,package=package,policy=read_json(examples/'current_research/policy.json'),
             context_review_mode='legacy')
    with pytest.raises(ValueError,match='Complete attachment_plan and attachment_evidence'):
        prepare(run,'requirements')
    source_id=prepare(run,'attachment_plan')['payload']['proposal_sources'][0]['id']
    def remap(value):
        if isinstance(value,dict): return {k:remap(v) for k,v in value.items()}
        if isinstance(value,list): return [remap(v) for v in value]
        if isinstance(value,str) and (value=='S1' or value.startswith('S1_U')):
            return source_id+value[2:]
        return value
    # Include all prerequisites and stop at the stage that publishes main.json.
    for stage in STAGES[:STAGES.index('context_review')+1]:
        assert not (run/'handoff/main.json').exists()
        response=remap(read_json(tmp_path/'authored_reference/saved_responses'/(stage+'.json')))
        response['request_sha256']=prepare(run,stage)['request_sha256']
        assert accept(run,stage,response)['status']=='ACCEPTED'
    # Only the main JSON is handed over; B2 has no dependency on B1 sidecars.
    delivery=tmp_path/'delivery'; delivery.mkdir()
    main=delivery/'main.json'
    main.write_bytes((run/'handoff/main.json').read_bytes())
    result=prepare_sources(main,tmp_path/'b2')
    assert result['status']=='WAITING_FOR_REVIEW' and len(result['tables'])==2
    assert result['context']['study']['drug']
    assert result['context']['rules']==[]
    assert result['context']['rule_publication']=='PROJECT_RULES_AGENT'
    assert result['context']['scientific_context']==read_json(main)['scientific_context']
    assert 'files' not in result['context']['data']
    assert {f['action'] for f in result['files']} >= {'RETAINED_REFERENCE_ONLY','ROUTED_TO_LITERATURE_SEARCH'}
    assert result['released_datasets']==[] and result['model_execution']=='NOT_RUN'


@pytest.fixture
def portable_main(tmp_path):
    from pathlib import Path
    manifest_path=setup_intake(tmp_path)
    file=next(f for f in read_json(manifest_path)['files'] if f['kind']=='xlsx')
    value={'version':'3.2','objective':'Prepare synthetic source tables for review.',
        'study':{key:'NOT_FOUND' for key in ('drug','regimen','population','system','measurements','methods')},
        'data':{'available':[],'required':[],'files':[{
            'id':file['id'],'name':file['original_name'],
            'path':str((Path(manifest_path).parent/file['raw_path']).resolve()),
            'sha256':file['sha256'],'kind':'xlsx','role':'DATA_CANDIDATE',
            'receivers':['data_preparation'],'read_status':'READ_COMPLETE',
            'qc_status':'NOT_RUN','fit_ready':False}]},
        'rules':[],'checks':[],'uncertainties':[],
        'scientific_context':{'version':'2.0','items':[],'potential_questions':[]}}
    return tmp_path/'main.json',value


@pytest.mark.parametrize('version',['3.0','3.1','3.2'])
def test_portable_main_versions_reach_source_review(portable_main,tmp_path,version):
    path,value=portable_main
    value['version']=version
    if version=='3.0':
        value.pop('scientific_context')
    elif version=='3.1':
        value['scientific_context'].update(version='1.0',sources=[])
    write_json(path,value)
    result=prepare_sources(path,tmp_path/'prepared')
    assert result['status']=='WAITING_FOR_REVIEW',result['errors']
    assert result['context']['version']==version and len(result['tables'])==2
    assert all(not table['fit_ready'] for table in result['tables'])
    assert result['released_datasets']==[] and result['model_execution']=='NOT_RUN'


@pytest.mark.parametrize('defect',['unknown_version','missing_science','changed_attachment'])
def test_portable_main_validation_still_blocks_invalid_input(portable_main,tmp_path,defect):
    from pathlib import Path
    path,value=portable_main
    if defect=='unknown_version':
        value['version']='99.0'
    elif defect=='missing_science':
        value.pop('scientific_context')
    else:
        Path(value['data']['files'][0]['path']).write_bytes(b'changed attachment')
    write_json(path,value)
    result=prepare_sources(path,tmp_path/'prepared')
    assert result['status']=='FAILED' and result['tables']==[]
    assert result['released_datasets']==[] and result['model_execution']=='NOT_RUN'
    message=result['errors'][0]['message']
    assert ('missing or changed' if defect=='changed_attachment' else
            'scientific_context' if defect=='missing_science' else 'version') in message


def test_http_upload_intake_split_and_retrieve(tmp_path):
    client=TestClient(create_app(tmp_path/'state'))
    upload=client.post('/v1/attachments',files={'file':('package.zip',package_bytes(),'application/zip')})
    assert upload.status_code==200
    intake=client.post('/v1/intakes',json={'package_upload_id':upload.json()['upload_id']})
    assert intake.status_code==200 and intake.json()['status']=='READ_COMPLETE'
    prepared=client.post('/v1/data-preparation/source-tables',json={'intake_id':intake.json()['intake_id']})
    assert prepared.status_code==200 and prepared.json()['status']=='WAITING_FOR_REVIEW'
    body=prepared.json()
    artifact=client.get('/v1/source-preparations/'+body['source_preparation_id']+'/files/'+body['tables'][0]['records_path'])
    assert artifact.status_code==200 and artifact.json()['fit_ready'] is False


def test_overlapping_ranges_stop(tmp_path):
    manifest=setup_intake(tmp_path)
    file=next(f for f in read_json(manifest)['files'] if f['kind']=='xlsx')
    result=prepare_sources(manifest,tmp_path/'b2',{file['id']+':Mixed':[
        {'range':'A1:C8','header_row':5,'title':'One'},
        {'range':'A5:C8','header_row':5,'title':'Overlap'}]})
    assert result['status']=='FAILED' and result['errors'][0]['code']=='OVERLAPPING_SOURCE_TABLES'


def test_candidate_table_cannot_bypass_scientific_qc_and_review(tmp_path):
    from research_pipeline.engine import execute_step
    from ctxcomp.intake import file_hash
    manifest=setup_intake(tmp_path)
    prepared=prepare_sources(manifest,tmp_path/'b2')
    data=tmp_path/'b2'/prepared['tables'][0]['records_path']
    step={'id':'pk','module':'pk_longitudinal','input':{'data_attachment':'data'},'options':{}}
    output=execute_step(step,{'request_id':'bypass_test'},
                        {'data':{'id':'data','path':str(data),'sha256':file_hash(data)}},tmp_path/'run',{})
    assert output['status']=='FAILED' and output['errors'][0]['code']=='SOURCE_REVIEW_REQUIRED'
    assert not (tmp_path/'run/steps/pk/input.json').exists()
