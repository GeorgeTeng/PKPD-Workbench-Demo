"""Offline execution/QC checks against source cells, never a live model."""
import pytest
from openpyxl import Workbook
from ctxcomp.intake import parse_file
from research_pipeline import data_agents as d, preparation_checks as checks
from research_pipeline.common import PROJECT, read_json, write_json


def no_model(*args,**kwargs):
    raise AssertionError('Offline self-check must not call a model.')


@pytest.fixture
def tiny_execution(tmp_path,monkeypatch):
    # Source semantics are literal worksheet facts. Gate tests live separately;
    # here the prepared-input adapter is injected to isolate execution and QC.
    source=tmp_path/'source.xlsx';book=Workbook();sheet=book.active;sheet.title='PD'
    sheet.append(['SC 2 mg/kg'])
    sheet.append(['CENS=1 flags censored Y.'])
    sheet.append(['Y','CENS'])
    sheet.append([0,1]);sheet.append([3.2,0]);book.save(source)
    snapshot=write_json(tmp_path/'snapshot.json',parse_file(source))
    item_id='F1:S1:T1'
    item={'id':item_id,'kind':'TABLE','file_id':'F1','source':d.file_ref(source),
          'snapshot':d.file_ref(snapshot),'sheet_index':0,
          'region':{'start_row':1,'end_row':5,'left':1,'right':2,'header_row':3},
          'descriptor':{'headers':['Y','CENS'],'title':'PD response','source_notes':'SC 2 mg/kg\nCENS=1 flags censored Y.'}}
    inventory={'items':[item],'files':[{'id':'F1',**d.file_ref(source)}]}
    label={**{k:'NOT_FOUND' for k in d.LABEL_FIELDS},'item_id':item_id,'role':'PD_OBSERVATIONS',
           'route':'SC','drug':'Compound Z','species':'mouse','additional_roles':[],
           'requirement_ids':[],'columns':[],'evidence':[{'source':item_id+':A1','quote':'SC 2 mg/kg'}]}
    stated={'item_id':item_id,'quantity':'dose','value':'2','unit':'mg/kg','subject':'Compound Z',
            'qualifiers':[],'evidence':[{'source':item_id+':A1','quote':'SC 2 mg/kg'}]}
    labels={'labels':[label],'stated_values':[stated]}
    requirements=write_json(tmp_path/'requirements.json',{'access':[{'item_id':item_id,'disposition':'REVIEW_DATA'}]})
    labels_path=write_json(tmp_path/'labels.json',labels)
    context={'requirements':d.file_ref(requirements),'labels':d.file_ref(labels_path)}
    context_path=write_json(tmp_path/'context.json',context)
    plan={'context':d.file_ref(context_path),'input_bindings':[],
          'tables':[{'item_id':item_id,'action':'PREPARE','columns':[],'reason':'Preserve source'}],'findings':[]}
    plan_path=write_json(tmp_path/'plan.json',plan)
    monkeypatch.setattr(d,'prepared_input',lambda path:(context,{},inventory,labels))
    monkeypatch.setattr(d,'codex_generate',no_model)
    output=tmp_path/'output'
    d.execute_preparation(context_path,plan_path,output)
    return output,plan,inventory,labels


def check_again(output,plan,inventory,labels,manifest=None):
    return checks.verify_preparation(manifest or read_json(output/'normalization_manifest.json'),
        plan,inventory,read_json(output/'cleaning_log.json')['changes'],
        read_json(output/'data_dictionary.json'),labels=labels)


def test_integrated_tiny_source_preserves_censor_number_and_explicit_dose(tiny_execution):
    output,plan,inventory,labels=tiny_execution
    manifest=read_json(output/'normalization_manifest.json');dataset=manifest['datasets'][0]
    records=read_json(dataset['data']['path'])['records']
    first=records[0];y=next(k for k,h in dataset['metadata']['source_table']['column_map'].items() if h=='Y')
    assert first[y]==0 and first['source_raw_values'][y]==0
    assert first['value_status'][y]=='CENSORED'
    assert records[1]['value_status'][y]=='QUANTIFIED'
    assert dataset['metadata']['dose']['value']=='2' and dataset['metadata']['dose']['unit']=='mg/kg'
    assert 'censor_limit' not in first and 'lloq' not in first
    assert check_again(output,plan,inventory,labels)['decision']=='PASS'


@pytest.mark.parametrize('fault',['status','dose'])
def test_qc_reconstructs_source_semantics_and_rejects_bad_output(tiny_execution,fault):
    output,plan,inventory,labels=tiny_execution
    manifest=read_json(output/'normalization_manifest.json');dataset=manifest['datasets'][0]
    if fault=='status':
        value=read_json(dataset['data']['path'])
        y=next(k for k,h in dataset['metadata']['source_table']['column_map'].items() if h=='Y')
        value['records'][0]['value_status'][y]='QUANTIFIED'
        write_json(dataset['data']['path'],value)
    else:
        dataset['metadata']['dose']='NOT_FOUND'
    result=check_again(output,plan,inventory,labels,manifest)
    assert result['decision']=='REVISE'
    errors=result['datasets'][0]['errors']
    assert any(('status differs at A4' if fault=='status' else 'Dose metadata differs') in e for e in errors)


def test_real_approved_source_execution_and_selfcheck(tmp_path,monkeypatch):
    from research_pipeline.direct_preparation import host_plan
    run=PROJECT/'outputs/Codex_Agent_Run_20261009/data_test_20_cleaning_sol61/live02'
    context_path=run/'inputs/context.json'
    if not context_path.exists():
        pytest.skip('Reviewed real-source fixture is unavailable.')
    monkeypatch.setattr(d,'codex_generate',no_model)
    # The immutable historical model plan binds an earlier policy version.
    # Derive a current host plan from the still-approved source; never rebind it.
    plan_path=tmp_path/'current_host_plan.json'
    host_plan(context_path,plan_path)
    output=tmp_path/'actual_source_reexecution'
    d.execute_preparation(context_path,plan_path,output)
    manifest=read_json(output/'normalization_manifest.json')
    by_source={x['metadata']['source_item_id']:x for x in manifest['datasets']}
    assert len(by_source)==58
    dataset=by_source['F0004:S4:T1'];records=read_json(dataset['data']['path'])['records']
    y=next(k for k,h in dataset['metadata']['source_table']['column_map'].items() if h=='Y')
    for row in (26,33,34):
        record=next(r for r in records if r['source_row']==row)
        assert record[y]==0 and record['source_raw_values'][y]==0
        assert record['value_status'][y]=='CENSORED'
    for table,value in [(28,'2'),(29,'4'),(30,'8'),(31,'16')]:
        dose=by_source[f'F0004:S1:T{table}']['metadata']['dose']
        assert dose['value']==value and dose['unit']=='mg/kg'
        assert dose['dose_basis']=='as-reported PMB sulphate' and dose['per_record_assignment'] is False
    assert read_json(output/'program_qc.json')['decision']=='PASS'
    assert not (output/'data_report.json').exists()
