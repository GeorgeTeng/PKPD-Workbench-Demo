"""Published-rule test mode retains the original projector and never grants Data approval."""
import copy
import json
from pathlib import Path
import pytest
from research_pipeline import data_test_workflow as t,data_agents as d,project_rule_agent as rules
from research_pipeline.common import read_json,write_json,PipelineError
from test_project_rule_agent import bundle,run as publish_fixture


def scope_for(main):
    reference=t.verified_rules(main,read_json(main),'published')
    return dict(status=t.SCOPE,project_rules_status=t.RULES_PROVIDED,source_main_ref=d.file_ref(main),
        project_rules_ref=reference,input_approval='NOT_PROVIDED',production_release=False,
        stop_before='PREPARATION',model='gpt-6-sol')


def test_real_published_projection_reaches_definition_with_full_records(bundle):
    result=publish_fixture(bundle);main=Path(result['main_ref']['path']);before=main.read_bytes()
    expected=d.rules_for(read_json(main),d.DATA_STAGES);calls=[]
    def generate(req,**kwargs):
        p=req['payload'];calls.append(p)
        assert p['project_rules']==expected
        assert p['test_scope']['project_rules_ref']==result['project_rules_ref']
        ids=[r['id'] for r in expected]
        assert p['schema']['properties']['requirements']['items']['properties']['rule_ids']['items']['enum']==ids
        assert 'maxItems' not in p['schema']['properties']['requirements']['items']['properties']['rule_ids']
        assert 'Project Rules were deliberately not supplied' not in p['instructions']
        assert p['processing_rules'] and 'PROJECT_RULES_PROVIDED' in p['instructions']
        expanded={**p['context_sources'],**{'rule:'+r['id']:json.dumps(r,ensure_ascii=False) for r in p['project_rules']}}
        assert expanded==d.source_map(read_json(main),expected)
        assert all('rule:'+r['id'] not in p['context_sources'] for r in expected)
        cite=[{'source':'main:/objective','quote':p['objective']}]
        return {'request_sha256':req['request_sha256'],'tasks':[{'id':'T1','objective':p['objective'],
            'destination':'pk','evidence':cite}],'requirements':[{'id':'N1','task_id':'T1','description':'Source context',
            'kind':'DEFINITION','required_by':'BEFORE_QC','fields':[],'rule_ids':ids,'evidence':cite,
            'origin':'PROJECT_EXPLICIT','method_profile_ids':[],'conditions':[]}],'findings':[]}
    out=bundle[0]/'data_test';r=t.run_stage(main,out,'define',generator=generate,rules_mode='published')
    assert r['test_scope']['project_rules_status']==t.RULES_PROVIDED
    assert main.read_bytes()==before and len(calls)==1
    private=t.private_agents(main,scope_for(main))
    assert private.rules_for.__name__=='rules_for'  # The original module implementation, no rule override.
    assert private.rules_for(read_json(main),d.DATA_STAGES)==expected


@pytest.mark.parametrize('fault',['pack','candidate','main','wrong_main','missing_rules','explicit_none'])
def test_published_mode_rejects_unbound_or_tampered_rules(bundle,fault):
    result=publish_fixture(bundle);main=Path(result['main_ref']['path']);pack=rules.verify_published(result['project_rules_ref'])
    if fault=='pack':p=Path(result['project_rules_ref']['path']);p.write_bytes(p.read_bytes()+b' ')
    elif fault=='candidate':p=Path(pack['candidate_ref']['path']);p.write_bytes(p.read_bytes()+b' ')
    elif fault=='main':
        v=read_json(main);v['objective']='Changed';write_json(main,v)
    elif fault=='wrong_main':
        other=bundle[0]/'copied_main.json';other.write_bytes(main.read_bytes());main=other
    elif fault=='missing_rules':
        other=bundle[0]/'without_rules.json';v=read_json(main);v.pop('project_rules_ref');write_json(other,v);main=other
    with pytest.raises((PipelineError,ValueError)):
        t.run_stage(main,bundle[0]/'test','inventory',rules_mode='none' if fault=='explicit_none' else 'published')


def test_published_test_checkpoint_still_blocks_preparation(bundle):
    result=publish_fixture(bundle);main=Path(result['main_ref']['path']);scope=scope_for(main)
    folder=bundle[0]/'data_test';assessment=folder/'assessment'
    report=write_json(assessment/'adequacy.json',{'can_enter_qc':True,'llm_review':{'decision':'PASS'}})
    artifact=write_json(folder/'empty.json',{})
    write_json(assessment/'qc_context.json',{'can_enter_qc':True,'assessment':d.file_ref(report),
        'upstream_main':d.file_ref(main),'inventory':d.file_ref(artifact),'requirements':d.file_ref(artifact),
        'labels':d.file_ref(artifact),'files':[]})
    t.seal_assessment(folder,scope)
    sealed=read_json(assessment/'adequacy.json')
    assert sealed['technical_can_enter_qc'] and not sealed['can_enter_qc']
    assert sealed['test_scope']['project_rules_status']==t.RULES_PROVIDED
    with pytest.raises(PipelineError) as error:d.prepared_input(assessment/'qc_context.json')
    assert error.value.code=='DATA_REVIEW_REQUIRED'


def test_rule_transport_only_deletes_exact_present_projection_and_preserves_other_sources():
    import json
    rule={'id':'R1','text':'Full rule','conditions':['When scoped'],'authority':{'quote':'Original'}}
    text=json.dumps(rule,ensure_ascii=False)
    source={'rule:R1':text,'rule:NOT_PROJECTED':'Unassigned unchanged source','main:/objective':'Objective'}
    payload={'project_rules':[rule],'context_sources':source,'instructions':'Original'}
    result=t.deduplicate_rule_sources(payload)
    assert result['project_rules']==payload['project_rules']
    assert {**result['context_sources'],'rule:R1':json.dumps(result['project_rules'][0],ensure_ascii=False)}==source
    assert set(result)==set(payload)  # No extra alias/proof object is sent to the model.
    assert result['context_sources']['rule:NOT_PROJECTED']=='Unassigned unchanged source'
    assert payload['context_sources']==source  # Original host map is not modified.
    different=copy.deepcopy(payload);different['context_sources']['rule:R1']=text+' '
    assert t.deduplicate_rule_sources(different)==different
    d.evidence_check([{'source':'rule:R1','quote':'When scoped'}],source)
    with pytest.raises(PipelineError):d.evidence_check([{'source':'rule:R1','quote':'Invented condition'}],source)
