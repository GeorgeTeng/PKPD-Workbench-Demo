"""A module rename must not lose rules or reinterpret human validation as translation."""
import copy
import pytest
from research_pipeline import project_rule_agent as a
from research_pipeline import project_rule_compact as c
from research_pipeline.common import read_json
from test_project_rule_agent import bundle
from test_project_rule_compact import compact_bundle, extract, publish


@pytest.mark.parametrize('stored_tag',['human_pk','pk_translation'])
@pytest.mark.parametrize('requested',['human_pk','pk_translation','pk'])
def test_translation_aliases_preserve_source_records(stored_tag,requested):
    rules=[{'id':'R1','text':'Translate accepted models.','used_in':[stored_tag],'evidence':[]},
           {'id':'R2','text':'Validate frozen predictions.','used_in':['human_validation'],'evidence':[]}]
    original=copy.deepcopy(rules)
    selected=c.projection(rules,requested,None)['rules']
    assert [r['id'] for r in selected]==['R1']
    assert selected[0]['used_in']==[stored_tag]
    assert rules==original


def test_new_catalog_and_module_reference_agree(compact_bundle):
    _,_,value=compact_bundle
    req=a.request(value,'project_rules_extract')
    assert 'pk_translation' in req['payload']['step_catalog']
    assert 'human_pk' not in req['payload']['step_catalog']
    modules=value['workflow_reference']['modules']
    assert [m['id'] for m in modules]==['intake','context_bundle','data_bundle','eda','dispatch','pk','translation','index','targets','pta','results','clinical']
    assert modules[6]['name']=='PK translation'
    assert modules[6]['routing_hint']['tags']==['pk_translation','human_validation']
    candidate=extract(req)
    a.validate_candidate(candidate,req,value)
    candidate['items'][0]['used_in']=['human_pk']
    with pytest.raises(ValueError):a.validate_candidate(candidate,req,value)


def test_published_translation_reaches_data_and_embedded_consumers(compact_bundle):
    from research_pipeline.data_agents import rules_for, DATA_STAGES
    from research_pipeline.data_test_workflow import embedded_projection
    result=publish(compact_bundle);main=read_json(result['main_ref']['path'])
    pack=a.verify_published(result['project_rules_ref'])
    for tag in ('pk_translation','human_pk'):
        rows=rules_for(main,[tag])
        assert [r['id'] for r in rows]==['R001']
        assert rows[0]['used_in']==['pk_translation','human_validation']
        assert embedded_projection({**main,'rules':pack['rules']},[tag])==rows
    assert 'R001' in {r['id'] for r in rules_for(main,DATA_STAGES)}


def test_current_policy_cannot_drop_its_pinned_module_reference(compact_bundle):
    _,_,value=compact_bundle
    value=copy.deepcopy(value)
    value.pop('workflow_reference');value.pop('workflow_reference_sha256')
    with pytest.raises(ValueError):a.request(value,'project_rules_extract')
