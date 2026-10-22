"""Single-main transport contract; synthetic reviews do not establish scientific adequacy."""
import copy
import json
from pathlib import Path
import pytest
from research_pipeline import data_test_workflow as t, data_agents as d
from research_pipeline.common import read_json,write_json
from test_first_part_handoff import prepared,passing,f
from test_project_rule_agent import bundle


def publish(prepared):
    root,_=prepared
    f.review(root/'combined',generator=passing)
    return f.publish(root/'combined',root/'final')


def test_single_main_projects_full_embedded_rules_with_original_stage_semantics(prepared):
    result=publish(prepared);path=Path(result['main_ref']['path']);main=read_json(path);before=path.read_bytes()
    for stage in d.DATA_STAGES+['pk','pk_longitudinal','pkpd_index']:
        assert t.embedded_projection(main,[stage])==d.rules_for(main,[stage])
    class Captured(Exception):pass
    def capture(req,**kwargs):
        p=req['payload'];expected=t.embedded_projection(main,d.DATA_STAGES)
        assert p['project_rules']==expected
        assert p['test_scope']['rule_body_source']=='SOURCE_MAIN_RULES'
        assert p['test_scope']['first_part_review_ref']==result['review_ref']
        assert p['test_scope']['first_part_receipt_ref']==result['receipt_ref']
        original=d.source_map(main,expected);restored=copy.deepcopy(p['context_sources'])
        for r in expected:
            restored['rule:'+r['id']]=json.dumps(r,ensure_ascii=False)
        for pointer,value in d.leaves(main['rules']):restored['main:/rules'+pointer]=str(value)
        assert restored==original
        assert not any(k.startswith('main:/rules/') or k.startswith('rule:') for k in p['context_sources'])
        assert p['context_sources']['main:/objective']==main['objective']
        assert not any('alias' in k for k in p)
        raise Captured()
    with pytest.raises(Captured):t.run_stage(path,path.parent/'test','define',generator=capture,rules_mode='published')
    assert path.read_bytes()==before


@pytest.mark.parametrize('target',['main','receipt','review'])
def test_inline_main_tampering_is_refused_before_data_call(prepared,target):
    result=publish(prepared);path=Path(result['main_ref']['path'])
    altered=path if target=='main' else Path(result[target+'_ref']['path'])
    value=read_json(altered)
    if target=='receipt':value['main_ref']['sha256']='0'*64
    else:value['changed']=True
    write_json(altered,value)
    with pytest.raises(Exception):t.run_stage(path,path.parent/'test','define',generator=lambda *a,**k:pytest.fail('No model call allowed'))


def test_revise_first_part_cannot_enter_data(prepared):
    root,proof=prepared
    def revise(req,**kwargs):
        r=passing(req);r['decision']='REVISE';r['checks'][0]['verdict']='REVISE';return r
    f.review(root/'combined',generator=revise)
    with pytest.raises(Exception):t.run_stage(proof['main_ref']['path'],root/'test','define',generator=lambda *a,**k:pytest.fail('No model call allowed'))


def test_inline_dedup_keeps_unprojected_and_unequal_leaf_evidence():
    raw={'id':'R1','text':'One','scope':{'stages':['adequacy'],'task_ids':[],'source_ids':[]},'conditions':['When exact']}
    other={**copy.deepcopy(raw),'id':'R2','text':'Other','scope':{'stages':['clinical'],'task_ids':[],'source_ids':[]}}
    main={'rules':[raw,other],'project_rules_ref':{'path':'lineage','sha256':'x'},'objective':'Keep scientific context'}
    rules=t.embedded_projection(main,['adequacy']);source=d.source_map(main,rules)
    source['main:/rules/0/conditions/0']='Different source must stay'
    p={'context_sources':source,'project_rules':rules,'instructions':'Original'}
    out=t.deduplicate_rule_sources(p,main['rules'])
    assert out['context_sources']['main:/rules/0/conditions/0']=='Different source must stay'
    assert out['context_sources']['main:/rules/1/text']=='Other'
    assert out['context_sources']['main:/objective']=='Keep scientific context'
    assert 'main:/rules/0/text' not in out['context_sources']
    assert out['project_rules']==rules and p['context_sources']==source
    changed=copy.deepcopy(p);changed['project_rules'][0]['conditions']=['Different projection']
    out=t.deduplicate_rule_sources(changed,main['rules'])
    assert out['context_sources']['main:/rules/0/text']=='One'


@pytest.mark.parametrize('stages',[d.DATA_STAGES,['adequacy']])
def test_inline_access_path_enum_contains_exactly_transmitted_main_sources(prepared,stages):
    result=publish(prepared);path=Path(result['main_ref']['path']);main=read_json(path)
    scope=dict(status=t.SCOPE,project_rules_status=t.RULES_PROVIDED,source_main_ref=result['main_ref'],
        project_rules_ref=result['project_rules_ref'],first_part_receipt_ref=result['receipt_ref'],
        first_part_review_ref=result['review_ref'],rule_body_source='SOURCE_MAIN_RULES')
    module=t.private_agents(path,scope);rules=t.embedded_projection(main,stages)
    sources=d.source_map(main,rules)
    class Captured(Exception):pass
    def capture(req,**kwargs):
        p=req['payload'];paths=p['schema']['properties']['access']['items']['properties']['context_paths']['items']['enum']
        assert paths==[k.removeprefix('main:') for k in p['context_sources'] if k.startswith('main:')]
        assert '/objective' in paths
        assert p['project_rules']==rules
        assert all('main:'+x in sources for x in paths)
        for i,raw in enumerate(main['rules']):
            if raw['id'] not in {r['id'] for r in rules}:assert '/rules/'+str(i)+'/text' in paths
        raise Captured()
    with pytest.raises(Captured):module.invoke(path.parent/'access-test','DR-access',
        {'objective':main['objective'],'context_sources':sources,'project_rules':rules,'inventory':[],
         'tasks':[],'requirements':[],'instructions':'Test access projection'},d.ACCESS_DEFINITION,generator=capture)
