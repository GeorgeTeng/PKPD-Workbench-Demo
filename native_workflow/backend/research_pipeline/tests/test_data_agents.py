"""Synthetic contract tests. These do not measure real-model scientific accuracy."""
import copy
import json
from pathlib import Path

import pytest
from research_pipeline import data_agents as d
from research_pipeline.common import read_json,write_json,PipelineError


@pytest.fixture
def case(tmp_path,monkeypatch):
    source=tmp_path/'data.csv';source.write_text('Time (h),Concentration (mg/L)\n0,4\n1,2\n',encoding='utf-8')
    protected=tmp_path/'reserved.csv';protected.write_text('HUMAN_HOLDOUT_SECRET_98342',encoding='utf-8')
    main=write_json(tmp_path/'main.json',{'version':'3.0','objective':'Describe this new compound exposure.',
        'study':{'drug':'Compound Z'},'rules':[],'checks':[],'uncertainties':[],
        'project_rules_ref':d.file_ref(write_json(tmp_path/'project_rules.json',{'rules':[]})),
        'data':{'files':[{'id':'F0001','kind':'csv','role':'DATA_CANDIDATE',**d.file_ref(source)},
            {'id':'F0002','kind':'csv','role':'REFERENCE_ONLY',**d.file_ref(protected)}]}})
    monkeypatch.setattr(d,'rules_for',lambda main,stages: [])
    run=tmp_path/'run';inv=run/'adequacy/inventory.json';d.inventory(main,inv)
    calls=[]
    def model(req,**kwargs):
        p=req['payload'];calls.append(copy.deepcopy(p));out={'request_sha256':req['request_sha256']}
        if p.get('operation')=='DEFINE_REQUIREMENTS':
            ev=[{'source':'main:/objective','quote':p['objective']}]
            out.update(tasks=[{'id':'T001','objective':p['objective'],'destination':'pk','evidence':ev}],
                requirements=[{'id':'N001','task_id':'T001','description':'Concentration and time','kind':'DATA','required_by':'BEFORE_QC',
                    'fields':['time','concentration'],'rule_ids':[],'evidence':ev,
                    'origin':'PROJECT_EXPLICIT','method_profile_ids':[],'conditions':[]}],findings=[])
        elif p.get('operation')=='ASSIGN_ACCESS':
            out.update(access=[{'item_id':i['id'],'disposition':'REFERENCE_ONLY' if i['kind']=='PROTECTED' else 'REVIEW_DATA',
                    'reason':'Synthetic permission fixture','rule_ids':[],
                    'requirement_ids':[] if i['kind']=='PROTECTED' else ['N001'],
                    'context_paths':['/study/drug']} for i in p['inventory']],findings=[])
        elif p.get('operation')=='LABEL_FILE_DATA':
            key=next(iter(p['source_units']))
            out.update(labels=[{'item_id':p['item_id'],'role':'PK_OBSERVATIONS','requirement_ids':['N001'],
                **{k:'NOT_FOUND' for k in d.LABEL_FIELDS},'additional_roles':[],
                'columns':[{'header':h,'meaning':m,'unit':h[h.index('(')+1:-1],'qualifiers':[],'evidence':[{'source':k,'quote':p['source_units'][k]}]}
                    for m,cell in [('TIME',':A1'),('CONCENTRATION',':B1')]
                    for k in p['source_units'] if k.endswith(cell) for h in [p['source_units'][k]]],
                'stated_values':[],'reason':'Synthetic label fixture','evidence':[{'source':key,'quote':value} for key,value in p['source_units'].items()]}],findings=[])
        elif p['stage']=='DP':
            key=next(iter(p['source_units']))
            out.update(tables=[{'item_id':p['table']['id'],'action':'PREPARE','reason':'Explicit header units',
                'columns':[{'target':'time_h','source_header':'Time (h)'},{'target':'concentration_mg_L','source_header':'Concentration (mg/L)'}],
                'evidence':[{'source':key,'quote':p['source_units'][key]}]}],findings=[])
        else:
            out.update(checks=[{'id':key,'decision':'PASS','reason':'Synthetic fixture review'} for key in p['expected_check_ids']],findings=[])
            if 'decision' in p['schema']['properties']: out['decision']='PASS'
            if p['stage'] in {'DC-review','DH-handoff'}:
                out['ledger_outcomes']=[{'item_id':i,'outcome':'LIMITATION_ACCEPTED','reason':'Synthetic ledger fixture',
                    'evidence':[],'limitation':'Synthetic limitation','carried_to':'NOT_APPLICABLE'} for i in p.get('due_item_ids',[])]
            if p['stage']=='DC-review':
                out['condition_checks']=[{'id':r['id'],'decision':'UNRESOLVED','reason':'Synthetic condition fixture',
                    'needed_material':'Synthetic condition source','evidence':[]} for r in p['condition_checklist']]
                out['matches']=[]
                for plan in p['criterion_plans']:
                    key=next(k for k in plan['allowed_source_ids'] if p['evidence_catalog'][k]['kind']=='SOURCE_CONTENT')
                    evidence=[{'source':key,'quote':p['evidence_catalog'][key]['content']}]
                    out['matches'].append({'requirement_id':plan['requirement_id'],'status':'AVAILABLE_CANDIDATE',
                        'source_ids':[key], 'reason':'Fixture source match','needed_material':'NONE','deferred_outputs':[],
                        'criteria':[{'id':c['id'],'status':'SUPPORTED','evidence':evidence,
                                     'reason':'Synthetic criterion','needed_material':'NONE'} for c in plan['criteria']]})
        return out
    return tmp_path,run,main,inv,model,calls


def requirements(run,main,inv,req,generator):
    """DR, then DR-access: the requirement definition is written beside requirements.json."""
    definition=Path(req).with_name('requirement_definition.json')
    d.define(run,main,definition,generator=generator);d.assign_access(run,main,inv,definition,req,generator=generator)


def assess(case,model=None):
    _,run,main,inv,generator,_=case;generator=model or generator
    req=run/'adequacy/requirements.json';labels=run/'adequacy/data_labels.json'
    requirements(run,main,inv,req,generator)
    d.label(run,main,inv,req,labels,generator=generator)
    d.assess(run,main,inv,req,labels,run/'adequacy',generator=generator)
    return run/'adequacy/qc_context.json'


def prepared(case):
    _,run,_,_,model,_=case;context=approve_dp(assess(case));plan=run/'data_agents/preparation_plan.json'
    d.plan_preparation(run,context,plan,generator=model)
    d.execute_preparation(context,plan,run/'data_preparation')
    return run/'data_preparation/preparation_execution.json'


def approve_dp(context):
    """Synthetic human decision fixture; production approval comes from Canvas."""
    from research_pipeline.workflow_canvas import fingerprint
    from research_pipeline.preparation_workflow import import_inputs
    context=Path(context)
    artifacts=[{'name':p.name,**d.file_ref(p)} for p in sorted(context.parent.iterdir()) if p.is_file()]
    signature=fingerprint(artifacts)
    node={'execution':'COMPLETED','artifacts':artifacts,'output_signature':signature,
          'requires_human_review':True,
          'review':{'decision':'APPROVE','confirmed':True,'reviewer':'Synthetic human fixture',
                    'at':'2026-10-13T12:00:00Z','output_signature':signature},
          'langgraph_review':{'status':'APPROVED'}}
    approval=write_json(context.parent.parent/'dp_inputs/approval.json',{'adequacy':node})
    imported=context.parent.parent/'dp_inputs/qc_context.json'
    import_inputs(d.file_ref(approval),imported)
    return imported


@pytest.mark.parametrize('entry',['plan','execute'])
def test_dp_human_gate_blocks_direct_entry_even_after_clean_dc_pass(case,entry):
    _,run,_,_,model,calls=case
    context=assess(case);plan=run/'unapproved_plan.json'
    assert read_json(run/'adequacy/adequacy.json')['can_enter_qc'] is True
    count=len(calls)
    with pytest.raises(PipelineError) as error:
        if entry=='plan': d.plan_preparation(run,context,plan,generator=model)
        else: d.execute_preparation(context,plan,run/'data_preparation')
    assert error.value.code=='DP_HUMAN_APPROVAL_REQUIRED'
    assert len(calls)==count and not plan.exists()
    assert not (run/'data_preparation').exists()
    checkpoint=read_json(run/'adequacy/checkpoint.json')
    assert checkpoint['dp_entry_gate']['status']=='HUMAN_APPROVAL_REQUIRED'


@pytest.mark.parametrize('fault',['reject','request_changes','automatic','unconfirmed','no_reviewer','no_timestamp','wrong_signature'])
def test_dp_requires_a_confirmed_human_approval_of_this_version(case,fault):
    _,run,_,_,model,calls=case
    context=approve_dp(assess(case));value=read_json(context)
    path=Path(value['approval']['path']);approval=read_json(path);node=approval['adequacy']
    if fault=='reject': node['review']['decision']='REJECT'
    if fault=='request_changes': node['review']['decision']='REQUEST_CHANGES'
    if fault=='automatic':
        node.update(requires_human_review=False,review=None,
                    automatic_validation={'output_signature':node['output_signature']})
    if fault=='unconfirmed': node['review']['confirmed']=False
    if fault=='no_reviewer': node['review']['reviewer']=' '
    if fault=='no_timestamp': node['review'].pop('at')
    if fault=='wrong_signature': node['review']['output_signature']='other-version'
    write_json(path,approval);value['approval']=d.file_ref(path);write_json(context,value)
    count=len(calls)
    with pytest.raises(PipelineError):
        d.plan_preparation(run,context,run/'plan.json',generator=model)
    assert len(calls)==count and not (run/'plan.json').exists()


def test_dp_cannot_swap_in_freshly_hashed_inputs_after_human_approval(case):
    _,run,_,_,model,calls=case
    context=approve_dp(assess(case));value=read_json(context)
    labels=read_json(value['labels']['path']);labels['labels'][0]['species']='changed after review'
    changed=write_json(run/'changed_labels.json',labels)
    value['labels']=d.file_ref(changed);write_json(context,value)
    count=len(calls)
    with pytest.raises(PipelineError) as error:
        d.plan_preparation(run,context,run/'plan.json',generator=model)
    assert error.value.code=='DP_HUMAN_APPROVAL_STALE'
    assert len(calls)==count


def test_dp_rechecks_human_reviewed_checkpoint_after_model_response(case):
    _,run,_,_,model,_=case
    context=approve_dp(assess(case));plan=run/'plan.json'
    checkpoint=run/'adequacy/checkpoint.json'
    def mutate(request,**kwargs):
        response=model(request,**kwargs)
        with checkpoint.open('a',encoding='utf-8') as handle: handle.write('\n')
        return response
    with pytest.raises(PipelineError,match='changed or is missing'):
        d.plan_preparation(run,context,plan,generator=mutate)
    assert not plan.exists()


def test_human_approval_is_bound_into_the_dp_plan(case):
    _,run,_,_,model,_=case
    context=approve_dp(assess(case));plan=run/'plan.json'
    d.plan_preparation(run,context,plan,generator=model)
    output=read_json(plan)
    assert output['human_approval']==read_json(context)['approval']
    assert d.file_ref(run/'adequacy/checkpoint.json') in output['input_bindings']


def test_four_data_agents_preserve_values_and_emit_bound_eda_handoff(case):
    _,run,_,_,model,calls=case;execution=prepared(case)
    metadata=run/'data_agents/metadata_review.json';d.metadata_review(run,execution,metadata,generator=model)
    d.publish_data(run,execution,metadata,run/'data_preparation',generator=model)
    assert [p['stage'] for p in calls]==['DR','DR-access','DC-label','DC-review','DP','DH-handoff']
    # Each of the four agents sends only its own rule file; G001-G008 come with every call.
    for p in calls:
        assert {r['id'][:2] for r in p['processing_rules']}=={p['agent']}
        assert [r['id'] for r in p['governance']['rules']]==[f'G{i:03d}' for i in range(1,9)]
    # G005: each DC call receives only the rules that name it.
    assert [r['id'] for r in calls[0]['processing_rules']]==['DR001']
    assert [r['id'] for r in calls[1]['processing_rules']]==['DR002']
    assert [r['id'] for r in calls[2]['processing_rules']]==['DC002','DC003','DC004','DC005']
    assert [r['id'] for r in calls[3]['processing_rules']]==['DC002','DC003','DC005','DC006','DC007','DC008']
    assert calls[2]['label_vocabulary']==calls[3]['label_vocabulary'] and 'POOLED' in calls[2]['label_vocabulary']['record_category']
    assert 'main' not in calls[3]['requirements'] and 'requirements' not in calls[3]['data_labels']  # File bindings stay host-side.
    assert [r['id'] for r in calls[-1]['processing_rules']]==['DH001','DH002','DH003','DH004','DH005']
    assert 'DP010' in [r['id'] for r in calls[-2]['processing_rules']]
    assert 'source_units' not in calls[3] and 'source_units' not in calls[5]
    assert not any('HUMAN_HOLDOUT_SECRET_98342' in str(p) for p in calls)
    labels=read_json(run/'adequacy/data_labels.json')
    assert {c['status'] for c in labels['coverage']}=={'BODY_REVIEWED','REFERENCE_ONLY'}
    report=read_json(run/'data_preparation/main.json')
    assert report['cleaning_complete'] and not report['requires_human_review']
    assert report['fit_ready'] is False and report['scientific_release'] is False
    handoff=read_json(run/'data_preparation/handoffs/eda_context.json');assert len(handoff['files'])==1
    item=handoff['files'][0];sidecar=read_json(item['metadata_file']['path'])
    assert sidecar['data_file']==item['data']
    rows=read_json(item['data']['path'])['records']
    assert [r['concentration_mg_L'] for r in rows]==[4,2]
    assert rows[0]['source_raw_values']['c002_concentration_mg_l']=='4'
    assert sidecar['metadata']['species']=='NOT_FOUND'


def test_preparation_metadata_retains_source_labels_and_column_meanings(case):
    _,run,_,_,model,calls=case
    execution=prepared(case)
    label=read_json(run/'adequacy/data_labels.json')['labels'][0]
    manifest=read_json(run/'data_preparation/normalization_manifest.json')
    sidecar=read_json(manifest['datasets'][0]['metadata_file']['path'])
    for key in ['role',*d.LABEL_FIELDS,'additional_roles','columns']:
        assert sidecar['metadata'][key]==label[key]
    assert sidecar['metadata']['source_evidence']==label['evidence']
    d.metadata_review(run,execution,run/'data_agents/metadata_review.json',generator=model)
    assert not any(p['stage']=='DH-metadata' for p in calls)
    validation=read_json(run/'data_agents/metadata_review.json')
    assert validation['executor']=='HOST_PROGRAM'
    assert validation['reviews'][0]['review']['decision']=='PASS'


@pytest.mark.parametrize('header', ['AUC (mg/L*h)', 'Elimination slope (ng/mL/h)'])
def test_preparation_rejects_compound_units_mapped_as_concentration(case, header):
    root,run,main,inv,model,_=case
    (root/'data.csv').write_text('Time (h),'+header+'\n0,4\n1,2\n',encoding='utf-8')
    source_main=read_json(main)
    source_main['data']['files'][0].update(d.file_ref(root/'data.csv'))
    write_json(main,source_main);d.inventory(main,inv)
    def generate(request,**kwargs):
        response=model(request,**kwargs)
        if request['payload']['stage']=='DP':
            response['tables'][0]['columns'][1]['source_header']=header
        return response
    context=approve_dp(assess(case,generate));plan=run/'data_agents/preparation_plan.json'
    with pytest.raises(PipelineError) as error:
        d.plan_preparation(run,context,plan,generator=generate)
    assert error.value.code=='DATA_UNIT_UNSUPPORTED'
    assert not plan.exists()
    assert not list((run/'data_preparation/normalized').glob('**/*.json'))


@pytest.mark.parametrize('legacy_compacted_headers', [False, True])
def test_preparation_rejects_blank_header_without_shifting_source_columns(case, legacy_compacted_headers):
    from openpyxl import Workbook
    from openpyxl.worksheet.table import Table
    root,run,main,inv,model,_=case
    wb=Workbook();ws=wb.active
    for row in [['Time (h)',None,'Concentration (mg/L)'],[0,999,4],[1,888,2]]: ws.append(row)
    ws.add_table(Table(displayName='PKT',ref='A1:C3'));wb.save(root/'data.xlsx')
    source_main=read_json(main)
    source_main['data']['files'][0].update(kind='xlsx',**d.file_ref(root/'data.xlsx'))
    write_json(main,source_main);d.inventory(main,inv)
    inventory=read_json(inv)
    table=next(i for i in inventory['items'] if i['kind']=='TABLE')
    assert table['descriptor']['headers']==['Time (h)',None,'Concentration (mg/L)']
    if legacy_compacted_headers:
        table['descriptor']['headers']=[h for h in table['descriptor']['headers'] if h is not None]
        write_json(inv,inventory)
    def generate(request,**kwargs):
        response=model(request,**kwargs);payload=request['payload']
        if payload.get('operation')=='LABEL_FILE_DATA':
            key=next(k for k in payload['source_units'] if k.endswith(':C1'))
            response['labels'][0]['columns'].append({'header':'Concentration (mg/L)',
                'meaning':'CONCENTRATION','unit':'mg/L','qualifiers':[],
                'evidence':[{'source':key,'quote':payload['source_units'][key]}]})
        return response
    context=approve_dp(assess(case,generate));plan=run/'data_agents/preparation_plan.json'
    d.plan_preparation(run,context,plan,generator=generate)
    with pytest.raises(PipelineError) as error:
        d.execute_preparation(context,plan,run/'data_preparation')
    assert error.value.code=='DATA_HEADER_INVALID'
    assert not list((run/'data_preparation/normalized').glob('**/*.json'))


def test_registered_protected_body_is_not_parsed(case,monkeypatch):
    root,run,main,_,_,_=case
    import ctxcomp.intake as intake
    original=intake.parse_file
    def inspect(path):
        assert path.name!='reserved.csv'
        return original(path)
    monkeypatch.setattr(intake,'parse_file',inspect)
    inv=d.inventory(main,run/'check/inventory.json')
    assert len(inv['files'])==2 and len(inv['items'])==2


@pytest.mark.parametrize('error',['unknown_requirement','bad_citation','promote_protected','omit_file','stale_response'])
def test_reject_invalid_requirements_or_labels(case,error):
    _,run,main,inv,model,_=case
    def invalid(req,**kwargs):
        r=model(req,**kwargs)
        if req['payload'].get('operation')=='ASSIGN_ACCESS':
            if error=='promote_protected': r['access'][-1]['disposition']='REVIEW_DATA'
            elif error=='omit_file': r['access'].pop()
            elif error=='stale_response': r['request_sha256']='old'
        elif req['payload'].get('operation')=='LABEL_FILE_DATA':
            if error=='bad_citation': r['labels'][0]['evidence'][0]['quote']='invented quotation'
            elif error=='unknown_requirement': r['labels'][0]['requirement_ids']=['NO_SUCH_REQUIREMENT']
        return r
    with pytest.raises(PipelineError): assess(case,invalid)
    assert not (run/'adequacy/qc_context.json').exists()


def test_failed_independent_review_prevents_preparation(case):
    _,run,_,_,model,_=case
    def reject(req,**kw):
        r=model(req,**kw)
        if req['payload']['stage']=='DC-review':
            r['decision']='REVISE';r['checks'][0]['decision']='REVISE'
        return r
    context=assess(case,reject)
    report=read_json(run/'adequacy/adequacy.json')
    assert any(f['code']=='DATA_ASSESSMENT_REVIEW_NOT_PASSED' for f in report['why_cannot_pass'])
    with pytest.raises(PipelineError,match='independent review'):
        d.plan_preparation(run,context,run/'plan.json',generator=model)


def test_changed_data_after_preparation_cannot_be_reviewed(case):
    _,run,_,_,model,_=case;execution=prepared(case)
    manifest=read_json(run/'data_preparation/normalization_manifest.json')
    Path(manifest['datasets'][0]['data']['path']).write_text('{}',encoding='utf-8')
    with pytest.raises(PipelineError): d.metadata_review(run,execution,run/'metadata.json',generator=model)


def test_unknown_unit_never_gets_model_invented_conversion(case):
    root,run,main,inv,model,_=case
    source=root/'data.csv';source.write_text('Time (h),Concentration (unknown)\n0,4\n',encoding='utf-8')
    value=read_json(main);value['data']['files'][0].update(d.file_ref(source));write_json(main,value);d.inventory(main,inv)
    context=approve_dp(assess(case))
    def unit_plan(req,**kw):
        r=model(req,**kw)
        if req['payload']['stage']=='DP':r['tables'][0]['columns'][1]['source_header']='Concentration (unknown)'
        return r
    plan=run/'plan.json'
    with pytest.raises(PipelineError,match='compatible header units'):
        d.plan_preparation(run,context,plan,generator=unit_plan)
    assert not plan.exists()


def test_blq_is_retained_in_quarantine_without_imputation(case):
    root,run,main,inv,model,_=case
    source=root/'data.csv';source.write_text('Time (h),Concentration (mg/L)\n0,BLQ\n1,2\n',encoding='utf-8')
    value=read_json(main);value['data']['files'][0].update(d.file_ref(source));write_json(main,value);d.inventory(main,inv)
    execution=prepared(case)
    manifest=read_json(run/'data_preparation/normalization_manifest.json')
    rows=read_json(manifest['datasets'][0]['quarantine']['path'])['records']
    assert rows[0]['source_raw_values']['c002_concentration_mg_l']=='BLQ'
    assert 'BLQ' in rows[0]['qc_reasons']
    metadata=run/'metadata.json';d.metadata_review(run,execution,metadata,generator=model)
    d.publish_data(run,execution,metadata,run/'data_preparation',generator=model)
    assert read_json(run/'data_preparation/main.json')['requires_human_review']
    assert read_json(run/'data_preparation/handoffs/eda_context.json')['files']==[]


def test_workbench_new_plan_uses_only_rebuilt_data_agents(case,tmp_path):
    from research_pipeline.workflow_runtime import make_plan
    _,_,main,_,_,_=case
    approval=write_json(tmp_path/'approval.json',{'context':{'artifacts':[{'name':'main.json',**d.file_ref(main)}]}})
    spec={'mode':'reviewed_context','data_agents_version':'2.0','approved_context':d.file_ref(approval),
        'job_dir':str(tmp_path/'job'),'out':str(tmp_path/'new_run')}
    plan=make_plan(spec)
    assert list(plan['steps'])==['reviewed_context','data_inventory','data_requirements_agent','data_access_agent','data_label_agents','data_adequacy_agent']
    assert plan['targets']=={'adequacy':'data_adequacy_agent'}
    assert plan['scheduler']=='Prefect' and plan['file_executor']=='Snakemake'
    assert any(Path(r['path']).name=='dc_coverage.json' for r in plan['code_refs'])
    assert plan['steps']['data_requirements_agent']['depends']==['reviewed_context']  # DR runs alongside the inventory.
    assert plan['steps']['data_access_agent']['depends']==['data_inventory','data_requirements_agent']
    assert plan['steps']['data_label_agents']['depends']==['data_access_agent']


def test_raw_headers_or_documents_cannot_establish_data_availability(case):
    _,run,_,_,model,_=case
    def ungrounded(req,**kw):
        response=model(req,**kw)
        if req['payload']['stage']=='DC-review':
            response['matches'][0]['source_ids']=['main:/objective']
        return response
    with pytest.raises(PipelineError,match='Match source IDs'): assess(case,ungrounded)
    assert not (run/'adequacy/qc_context.json').exists()


def test_failed_host_metadata_check_cannot_release_handoff(case):
    _,run,_,_,model,_=case;execution=prepared(case);metadata=run/'metadata.json'
    d.metadata_review(run,execution,metadata,generator=model)
    validation=read_json(metadata)
    validation['reviews'][0]['review']['decision']='REVISE'
    validation['reviews'][0]['review']['checks'][0]['decision']='REVISE'
    write_json(metadata,validation)
    d.publish_data(run,execution,metadata,run/'data_preparation',generator=model)
    assert read_json(run/'data_preparation/main.json')['requires_human_review']
    assert read_json(run/'data_preparation/handoffs/eda_context.json')['files']==[]


def test_metadata_is_host_only_and_handoff_receives_actual_execution_evidence(case):
    _,run,_,_,model,calls=case;execution=prepared(case);metadata=run/'metadata.json'
    def forbidden(*args,**kwargs):
        raise AssertionError('Metadata must not call a model')
    d.metadata_review(run,execution,metadata,generator=forbidden)
    d.publish_data(run,execution,metadata,run/'data_preparation',generator=model)
    request=calls[-1]
    assert request['stage']=='DH-handoff'
    assert [r['concentration_mg_L'] for r in request['actual_data'][0]['records']]==[4,2]
    assert request['qc_results']['decision']=='PASS'
    assert request['transformation_logs']['changes']
    assert request['metadata_reviews'][0]['review']['executor']=='HOST_PROGRAM'
    assert request['supplied_record_scope']==[{'dataset_id':'T0001','retained_records':2,'quarantined_records':0}]
    report=read_json(run/'data_preparation/main.json')
    assert set(report['agent_reviews'])=={'handoff'}
    assert report['metadata_validation']==d.file_ref(metadata)
    assert report['human_prediction_validated'] is False


def test_independent_handoff_failure_blocks_even_when_host_checks_pass(case):
    _,run,_,_,model,_=case;execution=prepared(case);metadata=run/'metadata.json'
    d.metadata_review(run,execution,metadata)
    def reject(request,**kwargs):
        response=model(request,**kwargs)
        response['decision']='REVISE';response['checks'][0]['decision']='REVISE'
        return response
    d.publish_data(run,execution,metadata,run/'data_preparation',generator=reject)
    assert read_json(metadata)['reviews'][0]['review']['decision']=='PASS'
    assert read_json(run/'data_preparation/main.json')['requires_human_review']
    assert read_json(run/'data_preparation/handoffs/eda_context.json')['files']==[]


@pytest.mark.parametrize('changed',['data','metadata','log','program_qc','plan','source','project_rules'])
def test_input_changed_during_handoff_never_publishes_a_new_binding(case,changed):
    root,run,main,_,model,_=case;execution=prepared(case);metadata=run/'metadata.json'
    d.metadata_review(run,execution,metadata)
    executed=read_json(execution);dataset=read_json(executed['manifest']['path'])['datasets'][0]
    path={'data':dataset['data']['path'],'metadata':dataset['metadata_file']['path'],
          'log':executed['cleaning_log']['path'],'program_qc':executed['program_qc']['path'],
          'plan':executed['plan']['path'],'source':str(root/'data.csv'),
          'project_rules':read_json(main)['project_rules_ref']['path']}[changed]
    def mutate(request,**kwargs):
        response=model(request,**kwargs)
        with Path(path).open('a',encoding='utf-8') as handle: handle.write('\n')
        return response
    with pytest.raises(PipelineError,match='changed or is missing'):
        d.publish_data(run,execution,metadata,run/'data_preparation',generator=mutate)
    assert not (run/'data_preparation/main.json').exists()
    assert not (run/'data_preparation/handoffs').exists()


def test_changed_input_during_dp_does_not_publish_a_stale_plan(case):
    _,run,_,_,model,_=case;context=approve_dp(assess(case));plan=run/'plan.json'
    def mutate(request,**kwargs):
        response=model(request,**kwargs)
        with context.open('a',encoding='utf-8') as handle: handle.write('\n')
        return response
    with pytest.raises(PipelineError,match='changed or is missing'):
        d.plan_preparation(run,context,plan,generator=mutate)
    assert not plan.exists()


def test_preparation_workflow_schedules_metadata_as_a_host_step(case,monkeypatch):
    from research_pipeline import preparation_workflow
    from research_pipeline.workflow_runtime import make_plan
    root,run,_,_,_,_=case
    context=assess(case)
    approval=write_json(root/'approval.json',{'adequacy':{'artifacts':[]}})
    monkeypatch.setattr(preparation_workflow,'approved_inputs',
        lambda ref: (read_json(approval),read_json(context),{}))
    plan=make_plan({'mode':'reviewed_data','data_agents_version':'2.0',
        'approved_data':d.file_ref(approval),'job_dir':str(root/'job'),
        'out':str(root/'new_run'),'model':'test-model'})
    assert 'data_metadata_agent' not in plan['steps']
    step=plan['steps']['data_metadata_validation']
    contract=read_json(step['contract'])
    assert contract['kind']=='data_v2_metadata' and 'model' not in contract['options']
    assert plan['steps']['data_handoff_agent']['depends']==['data_metadata_validation']
    assert any(Path(ref['path']).name=='preparation_checks.py' for ref in plan['code_refs'])


def test_oversized_actual_handoff_stops_without_sending_partial_data(case,monkeypatch):
    _,run,_,_,model,calls=case;execution=prepared(case);metadata=run/'metadata.json'
    d.metadata_review(run,execution,metadata)
    count=len(calls)
    monkeypatch.setattr(d,'REQUEST_BUDGET',100)
    with pytest.raises(PipelineError,match='no content was truncated'):
        d.publish_data(run,execution,metadata,run/'data_preparation',generator=model)
    assert len(calls)==count
    assert not (run/'data_preparation/main.json').exists()


@pytest.mark.parametrize('fault',['converted_value','raw_value','missing_row','extra_log','missing_log','log_provenance','csv_value'])
def test_program_qc_detects_actual_output_or_log_corruption(case,fault):
    _,run,_,_,_,_=case;execution=prepared(case)
    executed=read_json(execution);manifest=read_json(executed['manifest']['path'])
    dataset=manifest['datasets'][0];records=read_json(dataset['data']['path'])
    changes=read_json(executed['cleaning_log']['path'])['changes']
    if fault=='converted_value': records['records'][0]['concentration_mg_L']=999
    if fault=='raw_value': records['records'][0]['source_raw_values']['c002_concentration_mg_l']='999'
    if fault=='missing_row': records['records'].pop()
    if fault=='extra_log': changes.append(copy.deepcopy(changes[0]))
    if fault=='missing_log': changes.pop()
    if fault=='log_provenance': changes[0]['source_cell']='Z999'
    if fault=='csv_value':
        path=Path(dataset['csv']['path']);path.write_text('record_id\ninvented\n',encoding='utf-8')
    write_json(dataset['data']['path'],records)
    result=d.preparation_checks.verify_preparation(manifest,read_json(executed['plan']['path']),
        read_json(read_json(executed['context']['path'])['inventory']['path']),changes,
        read_json(executed['data_dictionary']['path']))
    assert result['decision']=='REVISE'


def test_scoped_packet_budget_stops_without_truncating(case,monkeypatch):
    _,run,main,inv,model,calls=case
    monkeypatch.setattr(d,'REQUEST_BUDGET',100)
    with pytest.raises(PipelineError,match='no content was truncated'):
        d.define(run,main,run/'requirements.json',generator=model)
    assert not calls


def test_open_context_warnings_reach_d01_d02_and_stay_visible(case):
    tmp,run,main_path,_,model,calls=case
    assess(case)
    assert all('missing_information' not in c['instructions'] for c in calls)  # Historical handoffs: unchanged requests.
    assert all('CONTEXT_WARNINGS' not in c.get('expected_check_ids',[]) for c in calls)
    main=read_json(main_path);main['missing_information']={'schema_version':'1.0','items':[
        {'id':'MI001','field':'animal identifiers','status':'NOT_FOUND','needed_at':'pk',
         'impact':'Individual random effects cannot be identified.','why_it_matters':'Repeated measures need unit identity.',
         'clarification':'Confirm whether animal IDs exist.','resolution_status':'OPEN'},
        {'id':'MI002','field':'dose basis','status':'AMBIGUOUS','needed_at':'prepare','impact':'Normalisation unclear.',
         'why_it_matters':'Salt form changes dose.','clarification':'State the dose basis.','resolution_status':'RESOLVED'}]}
    run=tmp/'warned';main_path=write_json(tmp/'warned_main.json',main);inv=run/'adequacy/inventory.json';d.inventory(main_path,inv)
    reporting=model;calls.clear();requirements(run,main_path,inv,run/'adequacy/requirements.json',reporting)
    d.label(run,main_path,inv,run/'adequacy/requirements.json',run/'adequacy/data_labels.json',generator=reporting)
    d.assess(run,main_path,inv,run/'adequacy/requirements.json',run/'adequacy/data_labels.json',run/'adequacy',generator=reporting)
    d01=next(c for c in calls if c.get('operation')=='DEFINE_REQUIREMENTS');d02=next(c for c in calls if c['stage']=='DC-review')
    for c in (d01,d02):
        assert 'main:/missing_information/items' in c['instructions'] and 'not proof' in c['instructions']
        assert c['context_sources']['main:/missing_information/items/0/status']=='NOT_FOUND'
    assert 'CONTEXT_WARNINGS' in d02['expected_check_ids']
    report=read_json(run/'adequacy/adequacy.json')
    warned=[f for f in report['findings'] if f['code']=='CONTEXT_WARNING_OPEN']
    assert warned==[{'code':'CONTEXT_WARNING_OPEN','affected_id':'MI001',
        'reason':'NOT_FOUND (animal identifiers): Individual random effects cannot be identified.',
        'needed_material':'Confirm whether animal IDs exist.','required_by':'BEFORE_MODELING','severity':'FOLLOW_UP'}]
    assert report['can_enter_qc'] is True  # A later-stage warning stays visible without blocking QC.
    assert 'MI001' in (run/'adequacy/evidence_gaps.csv').read_text(encoding='utf-8-sig')
    assert d.warning_findings(main,[{'affected_id':'MI001'}])==[]  # A DC-review finding on the warning is not duplicated.


def test_inventory_reuses_intake_snapshot_and_rejects_changed_snapshot(tmp_path):
    from ctxcomp.intake import parse_file
    source=tmp_path/'data.csv';source.write_text('Time (h),Concentration (mg/L)\n0,4\n1,2\n',encoding='utf-8')
    snapshot=write_json(tmp_path/'intake/parsed/F0001.json',parse_file(source))
    entry={'id':'F0001','kind':'csv','role':'DATA_CANDIDATE',**d.file_ref(source),
        'snapshot_path':str(snapshot),'snapshot_sha256':d.file_ref(snapshot)['sha256']}
    main=write_json(tmp_path/'main.json',{'data':{'files':[entry]}})
    inv=d.inventory(main,tmp_path/'run/adequacy/inventory.json')
    assert inv['files'][0]['snapshot_origin']=='INTAKE'
    assert not (tmp_path/'run/adequacy/snapshots').exists()
    assert {i['snapshot']['path'] for i in inv['items']}=={str(snapshot)}
    assert [i['kind'] for i in inv['items']]==['TABLE']
    write_json(snapshot,{'kind':'csv','rows':[]})
    with pytest.raises(PipelineError):
        d.inventory(main,tmp_path/'run2/adequacy/inventory.json')


MI = [{'id':'MI001','field':'animal identifiers','status':'NOT_FOUND','needed_at':'pk','impact':'Individual random effects cannot be identified.',
       'why_it_matters':'Repeated measures need unit identity.','clarification':'Confirm whether animal IDs exist.','resolution_status':'OPEN'},
      {'id':'MI002','field':'dose basis','status':'AMBIGUOUS','needed_at':'prepare','impact':'Normalisation unclear.',
       'why_it_matters':'Salt form changes dose.','clarification':'State the dose basis.','resolution_status':'OPEN'}]


def ledger_run(case, outcomes=None, extra_findings=(), label_findings=()):
    """Full DR->DH run on a main.json carrying CC019 warnings; outcomes(stage, payload) overrides the fixture."""
    tmp,_,main_path,_,model,calls=case
    main=read_json(main_path);main['missing_information']={'schema_version':'1.0','items':copy.deepcopy(MI)}
    run=tmp/'ledger';main_path=write_json(tmp/'ledger_main.json',main);inv=run/'adequacy/inventory.json';d.inventory(main_path,inv)
    def generate(request,**kwargs):
        result=model(request,**kwargs);p=request['payload']
        if p.get('stage')=='DC-review': result['findings']+=list(extra_findings)
        if p.get('operation')=='LABEL_FILE_DATA': result['findings']+=list(label_findings)
        decided=outcomes(p['stage'],p) if outcomes and 'ledger_outcomes' in result else None
        if decided is not None: result['ledger_outcomes']=decided
        return result
    req=run/'adequacy/requirements.json';labels=run/'adequacy/data_labels.json'
    requirements(run,main_path,inv,req,generate);d.label(run,main_path,inv,req,labels,generator=generate)
    d.assess(run,main_path,inv,req,labels,run/'adequacy',generator=generate)
    if not read_json(run/'adequacy/adequacy.json')['can_enter_qc']: return run
    context=approve_dp(run/'adequacy/qc_context.json');plan=run/'data_agents/preparation_plan.json'
    d.plan_preparation(run,context,plan,generator=generate);d.execute_preparation(context,plan,run/'data_preparation')
    execution=run/'data_preparation/preparation_execution.json';metadata=run/'data_agents/metadata_review.json'
    d.metadata_review(run,execution,metadata,generator=generate);d.publish_data(run,execution,metadata,run/'data_preparation',generator=generate)
    return run


def outcome(item,kind,**extra):
    return {'item_id':item,'outcome':kind,'reason':'Synthetic decision','evidence':[],'limitation':'NONE','carried_to':'NOT_APPLICABLE',**extra}


def test_item_due_before_qc_gets_an_outcome_and_escalation_keeps_qc_closed(case):
    calls=case[-1]
    run=ledger_run(case,lambda stage,p:[outcome('MI002','ESCALATED')])
    review=next(c for c in calls if c['stage']=='DC-review')
    assert review['due_item_ids']==['MI002'] and [i['id'] for i in review['unresolved_ledger']]==['MI001','MI002']
    report=read_json(run/'adequacy/adequacy.json')
    assert report['can_enter_qc'] is False
    assert [f['code'] for f in report['why_cannot_pass'] if f['affected_id']=='MI002']==['UNRESOLVED_ITEM_ESCALATED']
    items={i['id']:i for i in read_json(run/'adequacy/unresolved_ledger.json')['items']}
    assert items['MI002']['resolution_status']=='ESCALATED' and items['MI002']['history'][0]['bound_to']==report['input_refs']
    assert items['MI001']['resolution_status']=='OPEN' and items['MI001']['record']==MI[0]  # Not due yet: unchanged.


@pytest.mark.parametrize('fault',['missing','resolved_without_evidence','carried_backwards','limitation_without_text','outcome_for_later_item'])
def test_invalid_ledger_outcomes_are_rejected(case,fault):
    bad={'missing':[],
         'resolved_without_evidence':[outcome('MI002','RESOLVED')],
         'carried_backwards':[outcome('MI002','CARRIED',carried_to='BEFORE_QC')],
         'limitation_without_text':[outcome('MI002','LIMITATION_ACCEPTED')],
         'outcome_for_later_item':[outcome('MI002','ESCALATED'),outcome('MI001','RESOLVED')]}[fault]
    with pytest.raises(PipelineError) as error:
        ledger_run(case,lambda stage,p:bad if stage=='DC-review' else None)
    assert error.value.code=='UNRESOLVED_LEDGER_INVALID'


def test_resolved_item_is_closed_with_its_evidence_and_not_reported_open(case):
    def decide(stage,p):
        if stage=='DC-review':
            return [outcome('MI002','RESOLVED',evidence=[{'source':'main:/objective','quote':'Describe this new compound'}])]
    run=ledger_run(case,decide)
    report=read_json(run/'adequacy/adequacy.json')
    assert not [f for f in report['findings'] if f['affected_id']=='MI002']
    handoff=read_json(run/'data_preparation/handoffs/pk_context.json')
    assert 'MI002' not in [i['id'] for i in handoff['unresolved_items']]


def test_open_items_reach_every_handoff_unchanged_and_dh_decides_items_due_before_eda(case):
    calls=case[-1]
    def decide(stage,p):
        if stage=='DC-review': return [outcome('MI002','CARRIED',carried_to='BEFORE_EDA')]
        if stage=='DH-handoff': return [outcome('MI002','LIMITATION_ACCEPTED',limitation='Dose basis unconfirmed; doses kept as reported.')]
    later={'code':'MODEL_INPUT_GAP','affected_id':'N001','reason':'Dosing history for modelling is incomplete.',
           'needed_material':'Infusion durations.','required_by':'BEFORE_MODELING','severity':'FOLLOW_UP'}
    run=ledger_run(case,decide,[later])
    dc=read_json(run/'adequacy/unresolved_ledger.json')
    assert {i['id']:i['status'] for i in dc['items']}=={'MI001':'NOT_FOUND','MI002':'AMBIGUOUS','DC-U001':'OPEN_FINDING'}
    assert next(c for c in calls if c['stage']=='DH-handoff')['due_item_ids']==['MI002']
    for destination in ['eda','pk','index']:
        handoff=read_json(run/f'data_preparation/handoffs/{destination}_context.json')
        forwarded={i['id']:i for i in handoff['unresolved_items']}
        assert set(forwarded)=={'MI001','DC-U001'} and forwarded['MI001']['record']==MI[0]
        assert forwarded['DC-U001']['phase']=='BEFORE_MODELING' and forwarded['DC-U001']['origin']['step']=='DC'
        assert handoff['accepted_limitations']==[{'id':'MI002','field':'dose basis','limitation':'Dose basis unconfirmed; doses kept as reported.'}]
    history=[h['outcome'] for h in {i['id']:i for i in read_json(run/'data_preparation/unresolved_ledger.json')['items']}['MI002']['history']]
    assert history==['CARRIED','LIMITATION_ACCEPTED']


def test_qc_follow_ups_reach_the_handoff_review_and_items_keep_their_origin(case):
    calls=case[-1]
    hidden={'code':'HIDDEN_SHEET_CONTENT','affected_id':'F0001:S1:T1','reason':'Hidden sheet read but not confirmed.',
            'needed_material':'Confirm the hidden sheet.','required_by':'BEFORE_QC','severity':'FOLLOW_UP'}
    later={'code':'LABEL_SCOPE_GAP','affected_id':'F0001:S1:T1','reason':'Strain not stated.',
           'needed_material':'Strain.','required_by':'BEFORE_MODELING','severity':'FOLLOW_UP'}
    def decide(stage,p):
        if stage=='DC-review': return [outcome('MI002','LIMITATION_ACCEPTED',limitation='Dose basis as reported.')]
        if stage=='DH-handoff':
            return [outcome(i,'LIMITATION_ACCEPTED',limitation='Hidden sheet unconfirmed.') for i in p['due_item_ids']]
    run=ledger_run(case,decide,[hidden],[later])
    assert read_json(run/'adequacy/adequacy.json')['can_enter_qc'] is True  # A follow-up still does not block QC.
    items={i['id']:i for i in read_json(run/'adequacy/unresolved_ledger.json')['items']}
    assert (items['DC-U001']['origin']['step'],items['DC-U001']['phase'])==('DC-label','BEFORE_MODELING')
    assert items['DC-U001']['origin']['artifact'].endswith('data_labels.json')
    assert (items['DC-U002']['origin']['step'],items['DC-U002']['phase'])==('DC','BEFORE_EDA')
    assert items['DC-U002']['record']==hidden
    assert next(c for c in calls if c['stage']=='DH-handoff')['due_item_ids']==['DC-U002']
    handoff=read_json(run/'data_preparation/handoffs/pk_context.json')
    assert {'id':'DC-U002','field':'F0001:S1:T1','limitation':'Hidden sheet unconfirmed.'} in handoff['accepted_limitations']
    assert 'DC-U001' in [i['id'] for i in handoff['unresolved_items']]


def test_a_computed_summary_cannot_resolve_an_item(case):
    def decide(stage,p):
        if stage=='DC-review':
            key=next(k for k,v in p['evidence_catalog'].items() if v['kind']=='COMPUTED')
            return [outcome('MI002','RESOLVED',evidence=[{'source':key,'quote':p['evidence_catalog'][key]['content'][:20]}])]
    with pytest.raises(PipelineError) as error:
        ledger_run(case,decide)
    assert error.value.code=='UNRESOLVED_LEDGER_INVALID'


ONE_ROW_PAGE=112  # The fixture header takes 56 characters (half a page) and each body row 30, so each page holds one row.

def test_page_conflicts_stay_undecided_and_roles_and_columns_are_merged(case,monkeypatch):
    monkeypatch.setattr(d,'PAGE_BUDGET',ONE_ROW_PAGE)
    _,run,_,_,model,calls=case
    def generate(request,**kwargs):
        result=model(request,**kwargs);p=request['payload']
        if p.get('operation')=='LABEL_FILE_DATA':
            label=result['labels'][0]
            if p['page']==1:
                label.update(role='PK_OBSERVATIONS',route_category='IV_BOLUS')
            else:
                label.update(role='DOSING',additional_roles=['PK_OBSERVATIONS'],route_category='EXTRAVASCULAR')
                key=next(k for k in p['source_units'] if k.endswith(':A1'))
                label['columns']=[{'header':'Time (h)','meaning':'OTHER','unit':'h','qualifiers':[],'evidence':[{'source':key,'quote':p['source_units'][key]}]}]
        return result
    assess(case,generate)
    labeled=read_json(run/'adequacy/data_labels.json');label=labeled['labels'][0]
    assert next(c for c in calls if c.get('operation')=='LABEL_FILE_DATA')['pages']>1
    assert label['role']=='MIXED' and label['additional_roles']==['DOSING','PK_OBSERVATIONS']
    assert label['route_category']=='MIXED'
    time=next(c for c in label['columns'] if c['header']=='Time (h)')
    assert (time['meaning'],time['unit'],time['conflict'])==('OTHER','NOT_FOUND',True)
    conflicts={f['reason'].split(':')[0] for f in labeled['findings'] if f['code']=='LABEL_CONFLICT'}
    assert conflicts=={'Pages disagree on role','Pages disagree on route_category','Pages disagree on column A Time (h)'}


def test_page_wording_and_partial_columns_merge_without_false_conflicts(case,monkeypatch):
    monkeypatch.setattr(d,'PAGE_BUDGET',ONE_ROW_PAGE)
    _,run,_,_,model,calls=case
    def generate(request,**kwargs):
        result=model(request,**kwargs);p=request['payload']
        if p.get('operation')=='LABEL_FILE_DATA':
            label=result['labels'][0];label['species']='Rat' if p['page']==1 else ' rat'
            time=next(c for c in label['columns'] if c['meaning']=='TIME')
            if p['page']>1: time['unit']='NOT_FOUND'  # Not restated on this page: not a disagreement.
            else: time['qualifiers']=['h']
        return result
    assess(case,generate)
    labeled=read_json(run/'adequacy/data_labels.json');label=labeled['labels'][0]
    assert next(c for c in calls if c.get('operation')=='LABEL_FILE_DATA')['pages']>1
    assert not [f for f in labeled['findings'] if f['code']=='LABEL_CONFLICT']
    assert label['species']=='Rat' and {c['column'] for c in label['columns']}=={'A','B'}
    time=next(c for c in label['columns'] if c['column']=='A')
    assert (time['unit'],time['qualifiers'])==('h',['h'])


def test_columns_are_keyed_by_position_not_header_text(case):
    _,run,_,_,model,_=case
    def generate(request,**kwargs):
        result=model(request,**kwargs)
        if request['payload'].get('operation')=='LABEL_FILE_DATA':
            for c in result['labels'][0]['columns']: c['header']='Mean'  # Repeated header text, as under grouped headers.
        return result
    assess(case,generate)
    label=read_json(run/'adequacy/data_labels.json')['labels'][0]
    assert [(c['column'],c['meaning']) for c in label['columns']]==[('A','TIME'),('B','CONCENTRATION')]


@pytest.mark.parametrize('fault',['body_citation','missing_column'])
def test_columns_cite_their_header_cell_and_undescribed_columns_are_reported(case,fault):
    _,run,_,_,model,_=case
    def generate(request,**kwargs):
        result=model(request,**kwargs);p=request['payload']
        if p.get('operation')=='LABEL_FILE_DATA':
            columns=result['labels'][0]['columns']
            if fault=='body_citation':
                key=next(k for k in p['source_units'] if k.endswith(':A2'))
                columns[0]['evidence']=[{'source':key,'quote':p['source_units'][key]}];columns[0]['unit']='NOT_FOUND'
            else: del columns[1]
        return result
    if fault=='body_citation':
        with pytest.raises(PipelineError) as error: assess(case,generate)
        assert error.value.code=='DATA_EVIDENCE_INVALID'
    else:
        assess(case,generate)
        labeled=read_json(run/'adequacy/data_labels.json')
        assert labeled['labels'][0]['undescribed_columns']==['B']
        assert [(f['code'],f['severity']) for f in labeled['findings']]==[('LABEL_COLUMN_MISSING','FOLLOW_UP')]


def test_column_citations_must_quote_the_page(case):
    _,_,_,_,model,_=case
    def generate(request,**kwargs):
        result=model(request,**kwargs)
        if request['payload'].get('operation')=='LABEL_FILE_DATA':
            result['labels'][0]['columns'][0]['evidence']=[{'source':'F0001:S1:T1:A1','quote':'Time (min)'}]
        return result
    with pytest.raises(PipelineError) as error:
        assess(case,generate)
    assert error.value.code=='DATA_EVIDENCE_INVALID'


def test_any_role_of_an_item_can_carry_a_method_condition():
    from research_pipeline import method_profiles as m
    trigger={'labels':{'role':['DOSING']},'review':'NONE'}
    assert m.applicability(trigger,{'role':'PK_OBSERVATIONS','additional_roles':['DOSING']})[0]=='APPLIES'
    assert m.applicability(trigger,{'role':'MIXED','additional_roles':['PK_OBSERVATIONS']})[0]=='UNDETERMINED'
    assert m.applicability(trigger,{'role':'PK_OBSERVATIONS','additional_roles':[]})[0]=='NOT_APPLICABLE'


def test_oversized_review_is_split_by_task_and_merged_strictly(case,monkeypatch):
    calls=case[-1];original=d.invoke
    def invoke(run,stage,payload,schema,**kw):
        if stage=='DC-review' and 'split review' not in payload['instructions']:
            raise PipelineError('DATA_REQUEST_TOO_LARGE','Synthetic transport limit.')
        return original(run,stage,payload,schema,**kw)
    monkeypatch.setattr(d,'invoke',invoke)
    def decide(stage,p):
        if stage=='DC-review' and p['due_item_ids']: return [outcome('MI002','ESCALATED')]
    run=ledger_run(case,decide)
    reviews=[c for c in calls if c['stage']=='DC-review'];assert len(reviews)==2
    task,rest=sorted(reviews,key=lambda c:'scope: TASK T001' not in c['instructions'])  # Parts run concurrently, so calls arrive in any order.
    assert [n['id'] for n in task['requirements']['requirements']]==['N001'] and task['due_item_ids']==[]
    assert 'F0001:S1:T1' in task['expected_check_ids'] and 'F0002:registry' not in task['expected_check_ids']
    assert rest['requirements']['requirements']==[] and rest['due_item_ids']==['MI002']
    assert 'F0002:registry' in rest['expected_check_ids'] and not rest['criterion_plans']
    review=read_json(run/'adequacy/review.json')
    assert [p['scope'] for p in review['parts']]==['TASK T001','ITEMS_WITHOUT_TASK_AND_DUE_LEDGER_ITEMS']
    assert [m['requirement_id'] for m in review['matches']]==['N001']
    assert [c['id'] for c in review['checks']].count('PERMISSIONS')==1
    items={i['id']:i for i in read_json(run/'adequacy/unresolved_ledger.json')['items']}
    assert items['MI002']['resolution_status']=='ESCALATED'


def test_split_review_keeps_the_strictest_shared_decision(case,monkeypatch):
    _,run,_,_,model,_=case;original=d.invoke
    def invoke(run,stage,payload,schema,**kw):
        if stage=='DC-review' and 'split review' not in payload['instructions']:
            raise PipelineError('DATA_REQUEST_TOO_LARGE','Synthetic transport limit.')
        return original(run,stage,payload,schema,**kw)
    monkeypatch.setattr(d,'invoke',invoke)
    def generate(request,**kwargs):
        result=model(request,**kwargs);p=request['payload']
        if p.get('stage')=='DC-review' and not p['requirements']['requirements']:
            result['decision']='NEEDS_REVIEW'
            next(c for c in result['checks'] if c['id']=='PERMISSIONS').update(decision='NEEDS_REVIEW',reason='Reference file scope unclear')
        return result
    assess(case,generate)
    review=read_json(run/'adequacy/review.json')
    permissions=next(c for c in review['checks'] if c['id']=='PERMISSIONS')
    assert review['decision']=='NEEDS_REVIEW' and permissions['decision']=='NEEDS_REVIEW'
    assert 'TASK T001: ' in permissions['reason'] and 'Reference file scope unclear' in permissions['reason']
    assert [p['decision'] for p in review['parts']]==['PASS','NEEDS_REVIEW']
    assert read_json(run/'adequacy/adequacy.json')['can_enter_qc'] is False


def test_every_label_page_repeats_the_table_header(case,monkeypatch):
    monkeypatch.setattr(d,'PAGE_BUDGET',ONE_ROW_PAGE)
    calls=case[-1];assess(case)
    pages=[c for c in calls if c.get('operation')=='LABEL_FILE_DATA']
    assert len(pages)>1
    for p in pages:
        assert {'F0001:S1:T1:A1','F0001:S1:T1:B1'}<=set(p['source_units'])
    body=[k for p in pages for k in p['source_units'] if k[-1].isdigit() and not k.endswith('1')]
    assert sorted(body)==sorted(set(body))  # Each body cell is read on exactly one page.
    for p in pages:  # DC002: a row is never split across pages.
        rows={k.rsplit(':',1)[1][1:] for k in p['source_units'] if k.count(':')==3}-{'1'}
        assert all({'F0001:S1:T1:A'+r,'F0001:S1:T1:B'+r}<=set(p['source_units']) for r in rows)



def test_label_pages_run_concurrently_and_merge_in_page_order(case,monkeypatch):
    import threading,time
    monkeypatch.setattr(d,'PAGE_BUDGET',ONE_ROW_PAGE)
    _,run,_,_,model,_=case;active=[0,0];lock=threading.Lock()
    def generate(request,**kwargs):
        p=request['payload']
        if p.get('operation')=='LABEL_FILE_DATA':
            with lock: active[0]+=1;active[1]=max(active)
            time.sleep(0.3 if p['page']==1 else 0.05)  # The first page finishes last.
            with lock: active[0]-=1
        return model(request,**kwargs)
    assess(case,generate)
    label=read_json(run/'adequacy/data_labels.json')['labels'][0]
    assert active[1]==2
    body=[e['source'] for e in label['evidence'] if e['source'][-1] in '23']
    assert body==['F0001:S1:T1:A2','F0001:S1:T1:B2','F0001:S1:T1:A3','F0001:S1:T1:B3']


def test_after_a_failed_call_no_new_call_starts_and_the_first_failure_in_plan_order_is_raised(monkeypatch):
    import time
    monkeypatch.setenv('DATA_AGENT_WORKERS','2');started=[]
    def job(n):
        started.append(n)
        if n==0: time.sleep(0.2);raise PipelineError('FIRST','first in plan order')
        if n==1: raise PipelineError('SECOND','fails first')
        return n
    with pytest.raises(PipelineError,match='first in plan order'):
        d.run_calls([lambda n=n: job(n) for n in range(6)])
    assert sorted(started)==[0,1]
    monkeypatch.setenv('DATA_AGENT_WORKERS','1');assert d.run_calls([lambda n=n: n for n in range(3)])==[0,1,2]
    monkeypatch.setenv('DATA_AGENT_WORKERS','0')
    with pytest.raises(PipelineError,match='at least 1'): d.run_calls([lambda: 1,lambda: 2])


def test_kept_responses_are_separated_by_resolved_provider_and_model(monkeypatch):
    monkeypatch.setenv('CTXCOMP_MODEL_PROVIDER', 'codex')
    monkeypatch.setenv('CTXCOMP_CODEX_MODEL', 'gpt-6-sol')
    sol = d.executor_id(None, None)
    assert sol != 'codex:CLI_DEFAULT'
    assert sol == d.executor_id('gpt-6-sol', None)
    monkeypatch.setenv('CTXCOMP_CODEX_MODEL', 'test-other-model')
    assert d.executor_id(None, None) != sol
    assert d.executor_id('gpt-6-sol', None) == sol
    monkeypatch.setenv('CTXCOMP_MODEL_PROVIDER', 'claude')
    assert d.executor_id('gpt-6-sol', None) != sol


def test_a_retry_reuses_checked_pages_and_calls_the_model_for_the_rest(case,monkeypatch):
    monkeypatch.setattr(d,'PAGE_BUDGET',ONE_ROW_PAGE)
    _,run,main,inv,model,calls=case
    req=run/'adequacy/requirements.json';labels=run/'adequacy/data_labels.json';kept=run/'data_agents/kept'
    requirements(run,main,inv,req,model)
    d.label(run,main,inv,req,labels,generator=model)
    assert not kept.exists()  # A generator that does not name itself is never reused.
    def named(edit=None):
        def generate(request,**kwargs):
            result=model(request,**kwargs)
            if edit and request['payload'].get('operation')=='LABEL_FILE_DATA': edit(result,request['payload'])
            return result
        generate.executor_id='fixture';return generate
    def label_calls(run_label):
        before=len(calls);run_label()
        return sorted(c['page'] for c in calls[before:] if c.get('operation')=='LABEL_FILE_DATA')
    def wrong_quote(result,p):
        if p['page']==2: result['labels'][0]['evidence'][0]['quote']='not in the source'
    with pytest.raises(PipelineError):
        d.label(run,main,inv,req,labels,generator=named(wrong_quote))
    assert len(list(kept.iterdir()))==1  # Only the page that passed its checks is kept.
    assert label_calls(lambda: d.label(run,main,inv,req,labels,generator=named()))==[2]
    reuse=[json.loads(line) for line in (run/'data_agents/cache_reuse.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len([entry for entry in reuse if entry['stage']=='DC-label'])==1
    assert label_calls(lambda: d.label(run,main,inv,req,labels,generator=named()))==[]
    assert label_calls(lambda: d.label(run,main,inv,req,labels,generator=named(),model='other'))==[1,2]  # Another model answers afresh.
    assert len(list(kept.iterdir()))==4
    for path in kept.iterdir():  # A kept response that today's checks reject is replaced by a fresh call.
        value=read_json(path);value['labels'][0]['evidence'][0]['quote']='not in the source';write_json(path,value)
    assert label_calls(lambda: d.label(run,main,inv,req,labels,generator=named()))==[1,2]
    assert label_calls(lambda: d.label(run,main,inv,req,labels,generator=named()))==[]

def test_review_warnings_close_only_through_the_ledger(case):
    calls=case[-1];ledger_run(case,lambda stage,p:[outcome('MI002','ESCALATED')] if stage=='DC-review' else None)
    review=next(c for c in calls if c['stage']=='DC-review')
    assert 'closed only through ledger_outcomes' in review['instructions']
    assert 'report that as a finding citing both' not in review['instructions']
    dr=next(c for c in calls if c['stage']=='DR')
    assert 'report that as a finding citing both' in dr['instructions']


def test_split_call_gets_only_split_rules_and_no_coverage_scope(tmp_path):
    from test_dc_split import workbook, proposal
    source=workbook(tmp_path/'s.xlsx')
    main=write_json(tmp_path/'main.json',{'data':{'files':[{'id':'F0001','kind':'xlsx','role':'DATA_CANDIDATE',**d.file_ref(source)}]}})
    generate,calls=proposal();d.inventory(main,tmp_path/'run/adequacy/inventory.json',run=tmp_path/'run',generator=generate)
    assert [r['id'] for r in calls[0]['processing_rules']]==['DC001','DC002']
    assert 'AVAILABLE_CANDIDATE' not in calls[0]['instructions'] and 'regardless of its relevance' in calls[0]['instructions']


def test_label_vocabulary_must_define_every_value(monkeypatch,tmp_path):
    policy=read_json(d.AGENT_FILES['DC']);del policy['label_vocabulary']['record_category']['POOLED']
    monkeypatch.setitem(d.AGENT_FILES,'DC',write_json(tmp_path/'dc.json',policy))
    with pytest.raises(PipelineError) as error: d.label_vocabulary()
    assert error.value.code=='DATA_AGENT_POLICY_INVALID'


@pytest.mark.parametrize('field,value',[('unit','min'),('qualifiers',['after start of infusion'])])
def test_units_and_qualifiers_must_be_written_in_the_column_evidence(case,field,value):
    _,_,_,_,model,_=case
    def generate(request,**kwargs):
        result=model(request,**kwargs)
        if request['payload'].get('operation')=='LABEL_FILE_DATA':
            result['labels'][0]['columns'][0][field]=value
        return result
    with pytest.raises(PipelineError) as error:
        assess(case,generate)
    assert error.value.code=='DATA_EVIDENCE_INVALID' and 'not written in its cited evidence' in str(error.value)


def test_label_and_review_get_only_the_declared_pk_terminology(case):
    calls=case[-1];assess(case)
    for stage in ['DC-label','DC-review']:
        terms=next(c for c in calls if c['stage']==stage)['pk_terminology']
        assert [g['id'] for g in terms['groups']]==['CPK01','CPK02','CPK03','CPK04','CPK08']
        assert 'destructive sampling' in ' '.join(terms['data_qualifiers']) and terms['authority']=='TERMINOLOGY_AND_BINDING_GUIDANCE_ONLY'
    assert 'pk_terminology' not in next(c for c in calls if c['stage']=='DR')


def test_review_gets_computed_column_summaries_that_cannot_prove_data(case):
    calls=case[-1];assess(case)
    review=next(c for c in calls if c['stage']=='DC-review')
    summary=review['evidence_catalog']['F0001:S1:T1:column:A']
    assert summary['kind']=='COMPUTED' and summary['item_id']=='F0001:S1:T1'
    value=json.loads(summary['content'])
    assert (value['header'],value['non_empty'],value['numeric_min'],value['numeric_max'])==('Time (h)',2,0,1)
    from research_pipeline import data_requirement_check as drc
    need=read_json(case[1]/'adequacy/requirements.json')['requirements'][0]
    plan=next(p for p in review['criterion_plans'] if p['requirement_id']==need['id'])
    assert 'F0001:S1:T1:column:A' in plan['allowed_source_ids']
    span={'source':'F0001:S1:T1:column:A','quote':'"non_empty": 2'}
    match={'requirement_id':need['id'],'status':'AVAILABLE_CANDIDATE','source_ids':[span['source']],'reason':'x','needed_material':'NONE','deferred_outputs':[],
           'criteria':[{'id':c['id'],'status':'SUPPORTED','evidence':[span],'reason':'x','needed_material':'NONE'} for c in plan['criteria']]}
    with pytest.raises(PipelineError,match='original body evidence'):
        drc.validate_match(need,match,plan,review['evidence_catalog'])


@pytest.mark.parametrize('extra,label_model,review_model',[({'model':'m1'},'m1','m1'),({'model':'m1','review_model':'m2'},'m1','m2')])
def test_review_can_use_its_own_model(case,tmp_path,extra,label_model,review_model):
    from research_pipeline.workflow_runtime import make_plan
    _,_,main,_,_,_=case
    approval=write_json(tmp_path/'approval.json',{'context':{'artifacts':[{'name':'main.json',**d.file_ref(main)}]}})
    plan=make_plan({'mode':'reviewed_context','data_agents_version':'2.0','approved_context':d.file_ref(approval),
        'job_dir':str(tmp_path/'job'),'out':str(tmp_path/'new_run'),**extra})
    option=lambda step: read_json(plan['steps'][step]['contract'])['options']['model']
    assert (option('data_label_agents'),option('data_adequacy_agent'))==(label_model,review_model)


def test_condition_can_be_met_by_a_dataset_linked_to_the_same_requirement():
    row=lambda: [{'id':'F1:S1:T1:MP001:CI01','item_id':'F1:S1:T1','requirement_ids':['N001'],'applicability':'APPLIES'}]
    catalog={'F1:S1:T2:A2':{'content':'IV bolus 1 mg/kg','kind':'SOURCE_CONTENT','item_id':'F1:S1:T2'},
             'F2:S1:T1:A2':{'content':'IV bolus 1 mg/kg','kind':'SOURCE_CONTENT','item_id':'F2:S1:T1'}}
    check=lambda source: [{'id':'F1:S1:T1:MP001:CI01','decision':'MET','reason':'IV reference','needed_material':'NONE',
                           'evidence':[{'source':source,'quote':'IV bolus'}]}]
    linked={'N001':{'F1:S1:T1','F1:S1:T2'}}
    assert d.check_conditions(row(),check('F1:S1:T2:A2'),catalog,linked)[0]['decision']=='MET'
    with pytest.raises(PipelineError) as error:  # A dataset outside the requirement cannot satisfy the condition.
        d.check_conditions(row(),check('F2:S1:T1:A2'),catalog,linked)
    assert error.value.code=='DATA_CONDITION_INVALID'


def test_a_computed_summary_alone_cannot_meet_a_condition():
    row=lambda: [{'id':'F1:S1:T1:MP001:DC01','item_id':'F1:S1:T1','requirement_ids':['N001'],'applicability':'APPLIES'}]
    catalog={'F1:S1:T1:column:B':{'content':'{"numeric": 12}','kind':'COMPUTED','item_id':'F1:S1:T1'},
             'F1:S1:T1:B3':{'content':'0.5','kind':'SOURCE_CONTENT','item_id':'F1:S1:T1'}}
    check=lambda *sources: [{'id':'F1:S1:T1:MP001:DC01','decision':'MET','reason':'Enough samples','needed_material':'NONE',
                             'evidence':[{'source':s,'quote':catalog[s]['content'][:5]} for s in sources]}]
    with pytest.raises(PipelineError) as error:
        d.check_conditions(row(),check('F1:S1:T1:column:B'),catalog)
    assert error.value.code=='DATA_CONDITION_INVALID'
    assert d.check_conditions(row(),check('F1:S1:T1:column:B','F1:S1:T1:B3'),catalog)[0]['decision']=='MET'


def test_an_item_left_for_review_is_reported_when_labels_are_made(case):
    _,run,main,inv,model,_=case
    def generate(request,**kwargs):
        result=model(request,**kwargs)
        if request['payload'].get('operation')=='ASSIGN_ACCESS':
            for a in result['access']:
                if a['item_id']=='F0001:S1:T1': a.update(disposition='NEEDS_REVIEW',reason='Permission unclear.',requirement_ids=[])
        return result
    req=run/'adequacy/requirements.json';labels=run/'adequacy/data_labels.json'
    requirements(run,main,inv,req,generate);d.label(run,main,inv,req,labels,generator=generate)
    found=[(f['code'],f['affected_id'],f['severity']) for f in read_json(labels)['findings']]
    assert found==[('ITEM_NOT_REVIEWED','F0001:S1:T1','FOLLOW_UP')]


def test_data_found_only_in_document_text_cannot_open_qc(case):
    tmp,run,main_path,inv,model,_=case
    note=tmp/'note.txt';note.write_text('At 0 h the concentration was 4 mg/L.\n',encoding='utf-8')
    main=read_json(main_path);main['data']['files'].append({'id':'F0003','kind':'txt','role':'DATA_CANDIDATE',**d.file_ref(note)})
    write_json(main_path,main);d.inventory(main_path,inv)
    def generate(request,**kwargs):
        result=model(request,**kwargs);p=request['payload']
        if p.get('stage')=='DC-review':
            key=next(k for k,v in p['evidence_catalog'].items() if v['item_id']=='F0003:document' and v['kind']=='SOURCE_CONTENT')
            for m in result['matches']:
                m['source_ids']=[key]
                for c in m['criteria']: c['evidence']=[{'source':key,'quote':p['evidence_catalog'][key]['content']}]
        return result
    assess(case,generate)
    report=read_json(run/'adequacy/adequacy.json')
    assert report['can_enter_qc'] is False
    assert [(f['code'],f['severity']) for f in report['why_cannot_pass']]==[('DATA_NOT_IN_TABLE','HUMAN_REVIEW')]


def test_possible_copies_of_one_dataset_are_reported(tmp_path):
    rows='Time (h),Conc (mg/L)\n'+''.join(f'{t},{c}\n' for t,c in [(0.25,4.1),(0.5,3.6),(1,2.9),(2,1.7),(4,0.8),(8,0.2)])
    a=tmp_path/'a.csv';a.write_text(rows,encoding='utf-8')
    b=tmp_path/'b.csv';b.write_text(rows.replace('Conc (mg/L)','Concentration'),encoding='utf-8')
    pdf=tmp_path/'paper.txt';pdf.write_text('Table 2\n'+''.join(f'{t} h {c} mg/L\n' for t,c in [(0.25,4.1),(0.5,3.6),(1,2.9),(2,1.7),(4,0.8)]),encoding='utf-8')
    other=tmp_path/'c.csv';other.write_text('Time (h),Conc (mg/L)\n0.25,9\n0.5,8\n1,7\n',encoding='utf-8')
    files=[{'id':f'F000{i}','kind':p.suffix[1:],'role':'DATA_CANDIDATE',**d.file_ref(p)} for i,p in enumerate([a,b,pdf,other],1)]
    main=write_json(tmp_path/'main.json',{'data':{'files':files}})
    inv=d.inventory(main,tmp_path/'inventory.json')
    pairs=sorted((f['affected_id'],f['reason'].split(' ')[2]) for f in inv['findings'] if f['code']=='POSSIBLE_DUPLICATE_DATA')
    assert pairs==[('F0001:S1:T1','F0002:S1:T1'),('F0001:S1:T1','F0003:document'),('F0002:S1:T1','F0003:document')]
    assert all(f['severity']=='FOLLOW_UP' for f in inv['findings'])


def stated_case(case):
    """A Cmax table and a text file that restates, contradicts and adds to it."""
    tmp,run,main_path,inv,model,_=case
    table=tmp/'cmax.csv';table.write_text('Group,Cmax (mg/L)\n10 mg/kg,13.1\n30 mg/kg,40\n',encoding='utf-8')
    text=tmp/'paper.txt';text.write_text('Cmax was 12.3 mg/L in the 10 mg/kg group.\nCmax was 40 mg/L in the 30 mg/kg group.\n'
        'The 10 mg/kg group had a Cmax of 12.3 mg/L.\nHalf-life was 2 h.\n',encoding='utf-8')
    main=read_json(main_path)
    main['data']['files']+=[{'id':'F0003','kind':'csv','role':'DATA_CANDIDATE',**d.file_ref(table)},{'id':'F0004','kind':'txt','role':'DATA_CANDIDATE',**d.file_ref(text)}]
    write_json(main_path,main);d.inventory(main_path,inv)
    stated=[('Cmax','12.3','mg/L','10 mg/kg',1),('Cmax','40','mg/L','30 mg/kg',2),('Cmax','12.3','mg/L','10 mg/kg',3),('Half-life','2','h','NOT_FOUND',4)]
    def generate(request,**kwargs):
        p=request['payload']
        if p.get('operation')=='LABEL_FILE_DATA' and p['item_id'] in {'F0003:S1:T1','F0004:document'}:
            units=p['source_units'];cite=lambda k: [{'source':k,'quote':units[k]}]
            label={'item_id':p['item_id'],'role':'REPORTED_PARAMETERS','requirement_ids':['N001'],**{k:'NOT_FOUND' for k in d.LABEL_FIELDS},
                'additional_roles':[],'columns':[],'stated_values':[],'reason':'Synthetic stated-value fixture','evidence':cite(next(k for k in units if k!=p['item_id']))}
            if p['item_id']=='F0003:S1:T1':
                label['columns']=[{'header':'Group','meaning':'GROUP_OR_TREATMENT','unit':'NOT_FOUND','qualifiers':[],'evidence':cite('F0003:S1:T1:A1')},
                    {'header':'Cmax (mg/L)','meaning':'PARAMETER_VALUE','unit':'mg/L','qualifiers':[],'evidence':cite('F0003:S1:T1:B1')}]
            else:
                label['stated_values']=[{'quantity':q,'value':v,'unit':u,'subject':s,'qualifiers':[],'evidence':cite(f'F0004:document:line{n}')} for q,v,u,s,n in stated]
            return {'request_sha256':request['request_sha256'],'labels':[label],'findings':[]}
        if p.get('stage')=='DP' and p['table']['id']=='F0003:S1:T1':
            key=next(iter(p['source_units']))
            return {'request_sha256':request['request_sha256'],'findings':[],'tables':[{'item_id':'F0003:S1:T1','action':'PREPARE',
                'reason':'Generic source table','columns':[],'evidence':[{'source':key,'quote':p['source_units'][key]}]}]}
        return model(request,**kwargs)
    return generate


def test_values_written_in_text_are_listed_and_checked_against_tables(case):
    _,run,main,inv,_,calls=case;generate=stated_case(case)
    req=run/'adequacy/requirements.json';labels=run/'adequacy/data_labels.json'
    requirements(run,main,inv,req,generate);d.label(run,main,inv,req,labels,generator=generate)
    labeled=read_json(labels)
    assert [(v['id'],v['status'],[(m['kind'],m['ref']) for m in v['matches']]) for v in labeled['stated_values']]==[
        ('SV0001','CONFLICT',[('DIFFERENT_VALUE','F0003:S1:T1:B2')]),
        ('SV0002','DUPLICATE',[('SAME_VALUE','F0003:S1:T1:B3')]),
        ('SV0003','CONFLICT',[('SAME_VALUE','SV0001'),('DIFFERENT_VALUE','F0003:S1:T1:B2')]),
        ('SV0004','TEXT_ONLY',[])]
    assert labeled['stated_values'][0]['item_id']=='F0004:document' and labeled['stated_values'][0]['evidence'][0]['quote'].startswith('Cmax was 12.3')
    conflicts=[f for f in labeled['findings'] if f['code']=='STATED_VALUE_CONFLICT']
    assert [(f['affected_id'],f['severity'],f['required_by']) for f in conflicts]==[('SV0001','HUMAN_REVIEW','BEFORE_EDA'),('SV0003','HUMAN_REVIEW','BEFORE_EDA')]
    assert '13.1' in conflicts[0]['reason'] and '12.3' in conflicts[0]['reason']
    assert 'stated_values' in next(c for c in calls if c.get('operation')=='LABEL_FILE_DATA')['instructions']


def test_stated_values_reach_review_and_preparation_without_entering_tables(case):
    _,run,main,inv,model,calls=case;generate=stated_case(case)
    context=approve_dp(assess(case,generate))
    review=next(c for c in calls if c.get('stage')=='DC-review')
    assert [v['id'] for v in review['data_labels']['stated_values']]==['SV0001','SV0002','SV0003','SV0004']
    assert read_json(run/'adequacy/adequacy.json')['can_enter_qc'] is True  # Conflicts are due before EDA.
    plan=run/'data_agents/preparation_plan.json';d.plan_preparation(run,context,plan,generator=generate)
    d.execute_preparation(context,plan,run/'data_preparation')
    manifest=read_json(run/'data_preparation/normalized/../normalization_manifest.json')
    values=read_json(manifest['stated_values']['path'])['values']
    assert [v['id'] for v in values]==['SV0001','SV0002','SV0003','SV0004'] and values[0]['value']=='12.3'
    assert all('stated_values' not in ds['metadata'] for ds in manifest['datasets'])


def test_a_stated_value_must_be_copied_from_its_line(case):
    _,run,main,inv,_,_=case;generate=stated_case(case)
    def bad(request,**kwargs):
        result=generate(request,**kwargs)
        if request['payload'].get('item_id')=='F0004:document': result['labels'][0]['stated_values'][0]['value']='12.30'
        return result
    req=run/'adequacy/requirements.json';requirements(run,main,inv,req,bad)
    with pytest.raises(PipelineError) as error:
        d.label(run,main,inv,req,run/'adequacy/data_labels.json',generator=bad)
    assert error.value.code=='DATA_EVIDENCE_INVALID'


def test_text_only_data_with_listed_values_is_a_follow_up(case):
    _,run,_,_,_,_=case;generate=stated_case(case)
    def review(request,**kwargs):
        result=generate(request,**kwargs);p=request['payload']
        if p.get('stage')=='DC-review':
            key=next(k for k,v in p['evidence_catalog'].items() if v['item_id']=='F0004:document' and v['kind']=='SOURCE_CONTENT')
            for m in result['matches']:
                m['source_ids']=[key]
                for c in m['criteria']: c['evidence']=[{'source':key,'quote':p['evidence_catalog'][key]['content']}]
        return result
    assess(case,review)
    report=read_json(run/'adequacy/adequacy.json')
    found=next(f for f in report['findings'] if f['code']=='DATA_NOT_IN_TABLE')
    assert found['severity']=='FOLLOW_UP' and 'SV0002, SV0004' in found['reason'] and report['can_enter_qc'] is True


def test_review_can_cite_the_lines_of_stated_values(case):
    _,run,_,_,_,calls=case;generate=stated_case(case)
    def label_without_line(request,**kwargs):
        result=generate(request,**kwargs)
        if request['payload'].get('item_id')=='F0004:document':  # The label's own evidence cites only the first line.
            result['labels'][0]['evidence']=[{'source':'F0004:document:line1','quote':request['payload']['source_units']['F0004:document:line1']}]
        return result
    assess(case,label_without_line)
    catalog=next(c for c in calls if c.get('stage')=='DC-review')['evidence_catalog']
    assert catalog['F0004:document:line4']['kind']=='SOURCE_CONTENT'


def test_document_pages_that_differ_are_a_follow_up_and_tables_still_block(case,monkeypatch):
    tmp,run,main_path,inv,model,_=case
    text=tmp/'paper.txt';text.write_text('Rats received 10 mg/kg intravenously in study one of this report.\n'*5+'Mice received 5 mg/kg orally in study two of this report.\n'*5,encoding='utf-8')
    main=read_json(main_path);main['data']['files'].append({'id':'F0003','kind':'txt','role':'DATA_CANDIDATE',**d.file_ref(text)})
    write_json(main_path,main);d.inventory(main_path,inv)
    monkeypatch.setattr(d,'PAGE_BUDGET',500)
    def generate(request,**kwargs):
        p=request['payload']
        if p.get('operation')=='LABEL_FILE_DATA' and p['item_id']=='F0003:document':
            key=next(k for k in p['source_units'] if k!=p['item_id'])
            return {'request_sha256':request['request_sha256'],'findings':[],'labels':[{'item_id':p['item_id'],'role':'SUPPORTING_EVIDENCE','requirement_ids':[],
                **{k:'NOT_FOUND' for k in d.LABEL_FIELDS},'species':'rat' if 'Rats' in p['source_units'][key] else 'mouse',
                'additional_roles':[],'columns':[],'stated_values':[],'reason':'Synthetic document page','evidence':[{'source':key,'quote':p['source_units'][key]}]}]}
        return model(request,**kwargs)
    req=run/'adequacy/requirements.json';labels=run/'adequacy/data_labels.json'
    requirements(run,main_path,inv,req,generate);d.label(run,main_path,inv,req,labels,generator=generate)
    labeled=read_json(labels)
    found=[(f['affected_id'],f['severity']) for f in labeled['findings'] if f['code']=='LABEL_CONFLICT']
    assert found==[('F0003:document','FOLLOW_UP')]
    assert next(l for l in labeled['labels'] if l['item_id']=='F0003:document')['species']=='NOT_FOUND'


def test_review_sees_uncited_rows_chosen_by_fixed_rules(case):
    tmp,run,main_path,inv,model,calls=case
    rows=''.join(f'{t},{c}\n' for t,c in [(0,4),(1,3),(2,2.5),(3,'BLQ'),(4,1.9),(5,1.5),(6,1.2),(7,1),(8,0.8),(9,0.6)])
    (tmp/'data.csv').write_text('Time (h),Concentration (mg/L)\n'+rows,encoding='utf-8')
    main=read_json(main_path);source=next(f for f in main['data']['files'] if f['id']=='F0001')
    source.update(d.file_ref(tmp/'data.csv'));write_json(main_path,main);d.inventory(main_path,inv)
    def generate(request,**kwargs):
        result=model(request,**kwargs)
        if request['payload'].get('operation')=='LABEL_FILE_DATA':  # The label cites the header only.
            result['labels'][0]['evidence']=[e for c in result['labels'][0]['columns'] for e in c['evidence']]
        return result
    assess(case,generate)
    catalog=next(c for c in calls if c.get('stage')=='DC-review')['evidence_catalog']
    cells=[k.split(':')[-1] for k,v in catalog.items() if v.get('origin')=='REVIEW_SAMPLE']
    sampled=sorted(int(c[1:]) for c in cells if c[0]=='B')
    assert sampled==[2,3,4,5,9,10,11]  # Rows 2-4 and 9-11 (first and last three) and row 5, which holds BLQ.
    assert 'REVIEW_SAMPLE' in next(c for c in calls if c.get('stage')=='DC-review')['instructions']


def test_clean_review_still_requires_human_checkpoint_confirmation(case):
    _,run,_,_,_,_=case
    assess(case)
    report=read_json(run/'adequacy/adequacy.json')
    assert report['can_enter_qc'] is True and report['llm_review']['decision']=='PASS'
    assert report['requires_human_review'] is True
    assert read_json(run/'adequacy/checkpoint.json')['confirmation_required'] is True


def test_review_checkpoint_lists_what_the_person_decides(case):
    _,run,_,_,_,_=case;generate=stated_case(case)
    assess(case,generate)
    checkpoint=read_json(run/'adequacy/checkpoint.json')
    assert checkpoint['confirmation_required'] is True and checkpoint['same_model_for_label_and_review'] is True
    assert [f['affected_id'] for f in checkpoint['decisions']['Conflicts']]==['SV0001','SV0003']
    assert set(checkpoint['decisions'])=={'Blocking QC','Conflicts','Items not read','Requirements not met'}
    assert '## Conflicts (2)' in (run/'adequacy/checkpoint.md').read_text(encoding='utf-8')
    assert read_json(run/'adequacy/adequacy.json')['models']=={'label':'DEFAULT','review':'DEFAULT','same':True}


def test_prepared_records_carry_the_footnote_of_their_cell(case):
    from openpyxl import Workbook
    from openpyxl.worksheet.table import Table
    tmp,run,main_path,inv,model,_=case
    wb=Workbook();ws=wb.active;ws.title='PK'
    for row in [['Time (h)','Concentration (mg/L)'],[0,4],[1,'*'],[2,1.5]]: ws.append(row)
    ws['A6']='* sample lost';ws.add_table(Table(displayName='PKT',ref='A1:B4'));wb.save(tmp/'data.xlsx')
    main=read_json(main_path);source=next(f for f in main['data']['files'] if f['id']=='F0001')
    source.update(kind='xlsx',**d.file_ref(tmp/'data.xlsx'));write_json(main_path,main);d.inventory(main_path,inv)
    prepared(case)
    manifest=read_json(run/'data_preparation/normalization_manifest.json')
    lost=[r for r in read_json(manifest['datasets'][0]['quarantine']['path'])['records'] if r['source_row']==3]
    assert lost and lost[0]['source_footnotes']=={next(k for k,v in lost[0]['source_cells'].items() if v=='B3'):'* sample lost'}
    assert lost[0]['source_raw_values'][next(iter(lost[0]['source_footnotes']))]=='*'
