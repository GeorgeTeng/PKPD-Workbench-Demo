"""Scientific boundary tests; synthetic records are not real research results."""
import copy
import json
from pathlib import Path

import pytest
from openpyxl import Workbook

from research_pipeline.adequacy import file_ref
from research_pipeline.common import read_json, write_json, PipelineError
from research_pipeline.preparation_workflow import approved_inputs, import_inputs, split_sources, prepare, clean_table, partition
from research_pipeline.workflow_canvas import fingerprint
from research_pipeline.workflow_runtime import make_plan, execute_contract


@pytest.fixture
def approved(tmp_path):
    book = Workbook(); sheet = book.active; sheet.title = 'Rat'
    for row in [['Rat plasma observations'],['S01 | DOI 10.1000/synthetic'],
                ['Polymyxin B; concentration mg/L; time h; IV; * cannula blockage.'],
                ['Time (h)','Rat 1','Rat 2'],[0,0,'<LLOQ'],[1,2,'*'],[2,1,1]]:
        sheet.append(row)
    human = book.create_sheet('Human_PK')
    for row in [['Human validation'],['S02 | DOI 10.1000/heldout'],['Time (h)','Patient concentration'],[1,9837465.123]]: human.append(row)
    bench = book.create_sheet('Mouse')
    for row in [['Mouse index scatter'],['S03 | DOI 10.1000/benchmark'],['Exposure coordinates come from the published PK simulation.'],['Index coordinate','Response'],[9273645.321,2]]: bench.append(row)
    path = tmp_path/'arbitrary_name.xlsx'; book.save(path)
    file = {'id':'F1','name':path.name,'kind':'xlsx','role':'DATA_CANDIDATE',**file_ref(path)}
    main = write_json(tmp_path/'main.json', {'objective':'Synthetic technical QC test','data':{'files':[file]}})
    report = write_json(tmp_path/'adequacy.json', {'assessment_status':'NOT_CALCULABLE','can_enter_qc':False,
        'llm_review':{'validated':True,'decision':'PASS'},'evidence_refs':[file_ref(main)],
        'why_cannot_pass':[{'requirement_id':'N1','reason':'Partition unresolved','needed_material':'Partition manifest'}]})
    qc = write_json(tmp_path/'qc_context.json', {'assessment':file_ref(report),'upstream_main':file_ref(main),
        'files':[file],'task_requirements':[],'can_enter_qc':False})
    artifacts = [{'name':p.name,**file_ref(p)} for p in [report,qc]]; signature=fingerprint(artifacts)
    node = {'execution':'COMPLETED','artifacts':artifacts,'output_signature':signature,
        'review':{'decision':'APPROVE','output_signature':signature},'langgraph_review':{'status':'APPROVED'}}
    approval = write_json(tmp_path/'approval.json', {'adequacy':node})
    return file_ref(approval)


def run(approved, tmp_path):
    context = tmp_path/'result/inputs/qc_context.json'; import_inputs(approved, context)
    split_sources(context,tmp_path/'result/sources')
    return prepare(context,tmp_path/'result/sources/output.json',tmp_path/'result/prepared')


def test_partition_quarantine_and_scoped_handoffs(approved,tmp_path):
    report=run(approved,tmp_path)
    assert report['cleaning_complete'] and not report['fit_ready'] and not report['scientific_release']
    assert report['original_assessment_status']=='NOT_CALCULABLE' and report['execution_scope']=='DIAGNOSTIC_PREPARATION_ONLY'
    assert report['summary']['source_records']==6 and report['summary']['retained_records']==4
    assert report['summary']['quarantined_records']==2
    assert report['summary']['partitions']['WITHHELD_VALIDATION']==1
    assert report['summary']['partitions']['WITHHELD_BENCHMARK']==1
    content=''.join(p.read_text(encoding='utf-8-sig') for p in (tmp_path/'result').rglob('*') if p.is_file())
    assert '9837465.123' not in content and '9273645.321' not in content
    data=read_json(tmp_path/'result/prepared/normalized/T0001.json')['records']
    assert data[0]['concentration_mg_L']==0
    assert all(r['subject_id']=='NOT_FOUND' for r in data)
    q=read_json(tmp_path/'result/prepared/normalized/T0001.quarantine.json')['records']
    assert {r['status'] for r in q}=={'BLQ','MISSING_CANNULA_BLOCKAGE'}
    meta=read_json(tmp_path/'result/prepared/normalized/T0001.metadata.json')
    assert meta['review_status']=='PENDING' and meta['source_refs']
    index=read_json(tmp_path/'result/prepared/handoffs/index_context.json')
    assert index['candidate_indices']==['fAUC/MIC','fCmax/MIC','fT>MIC']
    assert not index['scientific_release']


def test_source_tamper_stops_before_processing(approved,tmp_path):
    (tmp_path/'arbitrary_name.xlsx').write_bytes(b'changed')
    with pytest.raises(PipelineError,match='changed'): approved_inputs(approved)


def test_invalid_or_rejected_review_cannot_start(approved,tmp_path):
    a=read_json(approved['path']); a['adequacy']['review']['decision']='REJECT'
    path=write_json(tmp_path/'reject.json',a)
    with pytest.raises(PipelineError): approved_inputs(file_ref(path))


def test_real_contract_execution_writes_receipts_without_fitting(approved,tmp_path):
    spec={'mode':'reviewed_data','approved_data':approved,'out':str(tmp_path/'run'),'job_dir':str(tmp_path/'job')}
    plan=make_plan(spec)
    assert plan['targets']=={'data_preparation':'clean_and_assess'}
    for step in plan['steps'].values(): execute_contract(step['contract'])
    assert read_json(tmp_path/'job/receipts/clean_and_assess.json')['status']=='SUCCEEDED'
    assert read_json(tmp_path/'run/data_preparation/main.json')['released_datasets']==[]


def test_filename_is_not_a_routing_input():
    descriptor={'sheet':'Rat','title':'Rat observed concentrations','headers':['Time (h)','Concentration (mg/L)'],'source_notes':'Animal measurements'}
    assert partition(descriptor)[0]=='DEVELOPMENT_CANDIDATE'
    descriptor['title']='Human observed concentrations'
    assert partition(descriptor)[0]=='WITHHELD_VALIDATION'


def test_explicit_units_and_formula_quarantine():
    table={'table_id':'T1','title':'Rat plasma concentration','source_notes':'Group mean observations',
        'kind':'source_records','source_sheet':'Rat','region':{},'column_map':{'c1':'Time (min)','c2':'Mean concentration (ng/mL)'},
        'missingness':[],'records':[{'record_id':'r1','c1':60,'c2':1000,'source_cells':{'c1':'A2','c2':'B2'}},
            {'record_id':'r2','c1':120,'c2':'=2*1000','source_cells':{'c1':'A3','c2':'B3'}}]}
    raw={'cells':[{'cell':'B3','data_type':'f'}]}
    group,changes,issues=clean_table(table,raw)
    assert group['records'][0]['time_h']==1 and group['records'][0]['concentration_mg_L']==1
    assert len(group['quarantine'])==1
    assert 'FORMULA_REQUIRES_REVIEW' in group['quarantine'][0]['qc_reasons']
    assert any(c.get('factor')==.001 for c in changes)
    wrong=copy.deepcopy(table); wrong['column_map']['c2']='Whole lung (ug/g)'
    group,_,_=clean_table(wrong,raw)
    assert 'concentration_mg_L' not in group['records'][0]
    with pytest.raises(PipelineError,match='unit'):
        clean_table(wrong,raw,{'columns':{'concentration_mg_L':'Whole lung (ug/g)'}})


def test_stale_mapping_cannot_cross_assessments(approved,tmp_path):
    a=read_json(approved['path'])
    plan=write_json(tmp_path/'plan.json',{'adequacy_signature':'unrelated','tables':{}})
    a['preparation_plan']=file_ref(plan); path=write_json(tmp_path/'stale.json',a)
    with pytest.raises(PipelineError,match='different approved'): approved_inputs(file_ref(path))


def test_failed_mapping_has_clear_diagnostics(approved,tmp_path):
    from research_pipeline.execution_feedback import execution_feedback
    value=read_json(approved['path']); signature=value['adequacy']['output_signature']
    p=write_json(tmp_path/'wrong_plan.json',{'adequacy_signature':signature,'tables':{'T0001':{'columns':{'time_h':'Wrong header'}}}})
    value['preparation_plan']=file_ref(p); approval=write_json(tmp_path/'mapped_approval.json',value)
    spec={'mode':'reviewed_data','approved_data':file_ref(approval),'out':str(tmp_path/'run'),'job_dir':str(tmp_path/'job')}
    plan=make_plan(spec)
    execute_contract(plan['steps']['reviewed_data']['contract']); execute_contract(plan['steps']['partition_sources']['contract'])
    with pytest.raises(PipelineError,match='Wrong header'): execute_contract(plan['steps']['clean_and_assess']['contract'])
    failure=execution_feedback(tmp_path/'run','Snakemake stopped',stage='data_preparation')
    assert failure['code']=='QC_MAPPING_COLUMN_UNKNOWN' and 'Wrong header' in failure['summary']
    assert failure['retry_supported'] and not failure['scientific_release']
    assert not (tmp_path/'job/receipts/clean_and_assess.json').exists()
@pytest.mark.parametrize('header,target,factor', [
    ('Time (h)','time_h',1), ('Time (min)','time_h',1/60), ('Time [s]','time_h',1/3600),
    ('Concentration (mg/L)','concentration_mg_L',1), ('Concentration (μg/mL)','concentration_mg_L',1),
    ('Concentration [µg/mL]','concentration_mg_L',1), ('Mean concentration (ng/mL)','concentration_mg_L',.001),
    ('ug/L','concentration_mg_L',.001), ('AUC (mg/L*h)','concentration_mg_L',None),
    ('Slope (ng/mL/h)','concentration_mg_L',None), ('Concentration (mg/L)/h','concentration_mg_L',None),
    ('AUC (mg/L)*h','concentration_mg_L',None), ('Time (h)/kg','time_h',None),
    ('Concentration','concentration_mg_L',None)])
def test_unit_mapping_requires_complete_compatible_expression(header, target, factor):
    from research_pipeline.preparation_workflow import unit_mapping
    assert unit_mapping(header, target) == factor

