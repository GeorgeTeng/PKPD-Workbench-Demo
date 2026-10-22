import copy
import json
import pytest
from research_pipeline import data_source_first_review as r
from research_pipeline import data_agents as d
from research_pipeline.common import PipelineError, write_json, read_json
from research_pipeline.adequacy import file_ref, check_ref


def packet():
    need={'id':'N1','task_id':'T1','description':'Observed concentration','kind':'DATA',
          'required_by':'BEFORE_QC','fields':['concentration'],'rule_ids':[],
          'evidence':[{'source':'main:/objective','quote':'Describe concentrations'}],
          'origin':'PROJECT_EXPLICIT','method_profile_ids':[],'conditions':[]}
    label={'item_id':'I1','role':'PK_CONCENTRATION','requirement_ids':['N1'],
           'columns':[{'header':'Concentration','meaning':'CONCENTRATION','unit':'mg/L',
            'qualifiers':[],'evidence':[{'source':'I1:A1','quote':'Concentration mg/L'}]}],
           'evidence':[{'source':'I1:A2','quote':'2.5'}], 'stated_values':[]}
    catalog={'main:/objective':{'content':'Describe concentrations','kind':'MAIN','item_id':None},
             'I1:A1':{'content':'Concentration mg/L','kind':'SOURCE_HEADER','item_id':'I1'},
             'I1:A2':{'content':'2.5','kind':'SOURCE_CONTENT','item_id':'I1','origin':'REVIEW_SAMPLE'}}
    return {'objective':'Describe concentrations','project_rules':[],
            'context_sources':{'main:/objective':'Describe concentrations'},'evidence_catalog':catalog,
            'requirements':{'tasks':[{'id':'T1','objective':'Describe concentrations','destination':'pk','evidence':need['evidence']}],
                            'requirements':[need],'access':[{'item_id':'I1','disposition':'REVIEW_DATA',
                             'requirement_ids':['N1'],'rule_ids':[],'context_paths':[]}],'findings':[]},
            'data_labels':{'labels':[label],'stated_values':[],'coverage':[{'item_id':'I1','status':'BODY_REVIEWED'}],'findings':[]},
            'criterion_plans':[{'requirement_id':'N1','criteria':r.coverage.criterion_plan(need),
              'allowed_source_ids':list(catalog),'assigned_item_ids':['I1'],'unresolved_review_items':[],'search_scope':'all I1'}],
            'condition_checklist':[],'unresolved_ledger':[],'due_item_ids':[],
            'expected_check_ids':['N1','I1','OBJECTIVE_COVERAGE','PERMISSIONS','MATCHING','TIMING'],
            'label_vocabulary':{},'pk_terminology':{},'method_knowledge':None,
            'assessment_algorithm_version':'test','instructions':'Keep exact evidence.'}


def decode_table(value):
    return [dict(zip(value['fields'], row)) for row in value['rows']] if isinstance(value,dict) and value.get('encoding')=='ROWS_V1' else value


def test_transport_catalog_and_row_tables_roundtrip_without_losing_facts():
    original=packet(); before=copy.deepcopy(original)
    part=r.make_part(original,requirement_ids=['N1'],item_ids=['I1'])
    assert r.unpack_catalog(part['evidence_catalog'])==original['evidence_catalog']
    labels=decode_table(part['data_labels']['labels'])
    columns=decode_table(labels[0]['columns'])
    assert columns[0]['header']=='Concentration'
    assert columns[0]['evidence_source_ids']==['I1:A1']
    assert r.visible_sources(part)['I1:A2']=='2.5'
    assert original==before


def test_partition_preserves_every_requirement_item_and_global_check():
    original=packet(); before=copy.deepcopy(original)
    parts=r.plan_parts(original)
    assert len(parts)==3
    assert [p['part_kind'] for p in parts][-2:]==['GLOBAL_OBJECTIVE','GLOBAL_CROSS_SOURCE']
    r.assert_partition(original,parts)
    assert original==before
    with pytest.raises(PipelineError):
        r.assert_partition(original,parts[:-1])


def test_budget_rejects_complete_oversized_unit_without_truncation(monkeypatch):
    original=packet(); before=copy.deepcopy(original)
    monkeypatch.setattr(r,'SOFT_BUDGET',100)
    with pytest.raises(PipelineError,match='complete requirement'):
        r.plan_parts(original)
    assert original==before


def test_scope_rejects_quote_known_globally_but_not_shown_to_part():
    full=packet(); full['evidence_catalog']['I2:A9']={'content':'secret unrelated value','kind':'SOURCE_CONTENT','item_id':'I2'}
    part=r.make_part(full,requirement_ids=['N1'],item_ids=['I1'])
    response={'evidence':[{'source':'I2:A9','quote':'secret unrelated value'}]}
    with pytest.raises(PipelineError,match='Citation does not match'):
        r.validate_part(response,part,full)


def test_scope_rejects_hidden_rule_audit_field():
    full=packet(); full['project_rules']=[{'id':'R1','text':'R1: Keep source units',
        'conditions':[],'exceptions':[],'scope':{},'requirement':{},'usage':{},'context_path':'/rules/0',
        'classification_reason':'This hidden annotation is not delivered.'}]
    part=r.make_part(full,kind='GLOBAL_OBJECTIVE')
    assert r.visible_sources(part)['main:/rules/0/text']=='Keep source units'
    with pytest.raises(PipelineError,match='Citation does not match'):
        r.validate_part({'evidence':[{'source':'rule:R1','quote':'This hidden annotation is not delivered.'}]},part,full)


def test_global_objective_gets_unlinked_original_objective_and_gap_text():
    full=packet(); source='main:/scientific_context/items/9/statement'
    full['context_sources'][source]='A project objective not covered by the present requirement.'
    full['post_source_objective_coverage']=[{'source':source,'requirement_ids':[],
        'reason':'No present requirement covers it.','evidence':[{'source':source,'quote':full['context_sources'][source]}]}]
    part=r.make_part(full,kind='GLOBAL_OBJECTIVE')
    assert r.visible_sources(part)[source]==full['context_sources'][source]
    assert part['post_source_dr_claims_to_review']['objective_coverage']==full['post_source_objective_coverage']


def source_fixture():
    source='I1'; req=packet()['requirements']
    req['access'][0]['requirement_ids']=[]
    inv={'items':[{'id':source,'kind':'TABLE','region':{'start_row':1,'header_row':1,'end_row':3,'left':1,'right':1}}]}
    cells={source+':A1':{'row':1,'column':1,'value':'Concentration mg/L','data_type':'s'},
           source+':A2':{'row':2,'column':1,'value':2.5,'data_type':'n'},
           source+':A3':{'row':3,'column':1,'value':'BLQ','data_type':'s'}}
    label=packet()['data_labels']['labels'][0]; label['requirement_ids']=[];label['columns'][0]['column']='A'
    labeled={'labels':[label],'coverage':[{'item_id':source,'status':'BODY_REVIEWED'}]}
    sources={'main:/objective':'Describe concentrations',source:'source table descriptor'}
    return req,inv,labeled,sources,lambda item:[(k,str(v['value'])) for k,v in cells.items()],lambda item:list(cells.items())


def test_unassociated_permitted_item_retains_body_counterevidence_and_summary():
    args=source_fixture(); plans,catalog=r._new_source_catalog(*args)
    assert catalog['I1:A2']['kind']=='SOURCE_CONTENT'
    assert catalog['I1:A3']['content']=='BLQ'
    assert catalog['I1:A3']['origin']=='REVIEW_SAMPLE'
    assert catalog['I1:column:A']['kind']=='COMPUTED'
    assert 'I1:A2' not in plans[0]['allowed_source_ids']


def test_dr_can_cite_original_descriptor_without_promoting_it_to_body():
    args=source_fixture();args[0]['requirements'][0]['evidence']=[{'source':'I1','quote':'source table descriptor'}]
    plans,catalog=r._new_source_catalog(*args)
    assert catalog['I1']['kind']=='DESCRIPTOR'
    assert 'I1' in plans[0]['allowed_source_ids']


def test_feasibility_claim_original_note_is_retained_for_independent_global_review():
    args=source_fixture()
    args[0]['method_feasibility']=[{'task_id':'T1','evidence':[{'source':'I1:A3','quote':'BLQ'},
        {'source':'main:/scientific_context/items/9/statement','quote':'Do not infer identity'}]}]
    args[3]['main:/scientific_context/items/9/statement']='Do not infer identity'
    _,catalog=r._new_source_catalog(*args)
    assert catalog['I1:A3']['content']=='BLQ'
    assert catalog['main:/scientific_context/items/9/statement']['content']=='Do not infer identity'


def test_test_export_closes_every_prepare_gate_and_updates_hashes(tmp_path):
    folder=tmp_path/'adequacy'; write_json(folder/'adequacy.json',{'can_enter_qc':True,'requires_human_review':True})
    for name in ['qc_context.json','checkpoint.json']:
        write_json(folder/name,{'can_enter_qc':True,'assessment':file_ref(folder/'adequacy.json')})
    r.seal_test_outputs(tmp_path)
    report=read_json(folder/'adequacy.json')
    assert report['can_enter_qc'] is False and report['technical_can_enter_qc'] is True
    for name in ['qc_context.json','checkpoint.json']:
        value=read_json(folder/name)
        assert value['can_enter_qc'] is False and value['production_release'] is False
        check_ref(value['assessment']);check_ref(value['test_original_ref'])
    assert read_json(tmp_path/'audit/unapproved_technical_review/adequacy.json')['can_enter_qc'] is True


def test_unadopted_candidate_profile_delivered_only_as_review_evidence(tmp_path):
    args=source_fixture(); req=args[0]
    knowledge=d.method_profiles.planning_context()
    profile=d.method_profiles.check_context(knowledge)['profiles'][0]
    source='method:'+profile['id']
    req['method_knowledge_ref']=file_ref(write_json(tmp_path/'knowledge.json',knowledge))
    req['method_feasibility']=[{'task_id':'T1','evidence':[{'source':source,'quote':profile['id']}]}]
    before=copy.deepcopy(req)
    plans,catalog=r._new_source_catalog(*args)
    assert catalog[source]['kind']=='METHOD'
    assert catalog[source]['content']==json.dumps(profile,ensure_ascii=False)
    assert source not in plans[0]['allowed_source_ids']
    assert req==before and req['requirements'][0]['method_profile_ids']==[]


def test_resume_restores_only_lossless_catalog_order_without_any_provider(tmp_path,monkeypatch):
    def forbidden(*args,**kwargs):
        raise AssertionError('Provider must never be reached')
    monkeypatch.setattr(d,'codex_generate',forbidden)
    original=r.make_part(packet(),requirement_ids=['N1'],item_ids=['I1'],part_id='REVIEW_001')
    request=r.governed_part_request(original)
    write_json(tmp_path/'data_agents/audit/DC-review/prior/request.json',request)
    changed=copy.deepcopy(original)
    for group in changed['evidence_catalog']['groups']:
        group['rows'].reverse()
    changed['evidence_catalog']['groups'].reverse()
    assert changed!=original
    restored=r.restore_frozen_part(tmp_path,changed)
    assert restored==original
    assert r.governed_part_request(restored)==request
    altered=copy.deepcopy(changed); altered['objective']='A different objective'
    with pytest.raises(PipelineError,match='unchanged frozen'):
        r.restore_frozen_part(tmp_path,altered)
    altered=copy.deepcopy(changed)
    altered['evidence_catalog']['groups'][0]['rows'][0][2]='altered original body'
    with pytest.raises(PipelineError,match='unchanged frozen'):
        r.restore_frozen_part(tmp_path,altered)
