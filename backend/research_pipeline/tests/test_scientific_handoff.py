"""Typed compression context survives rule publication and task-scoped routing."""
import copy
import pytest
from ctxcomp.scientific import validate_handoff
from research_pipeline import adequacy, project_rule_agent as rules, clinical_dispatch
from research_pipeline.common import read_json, write_json, PipelineError
from test_adequacy import inputs, assessment, review
from test_project_rule_agent import bundle, run as publish_rules
from test_clinical_dispatch import snapshot, node
from retired_eda_support import approval


def science():
    return {'version':'1.0', 'items':[
        {'id':'E1','statement':'Human CL is predicted using allometry.',
         'science':{'role':'RESULT','evidence_status':'PREDICTED','method_refs':['M1'],
                    'bindings':[],'adoption_relations':[],'relations':[]},
         'source_refs':[{'component_id':'C1','source_id':'S1','unit_id':'S1_U0001','start_char':0,'end_char':10}]},
        {'id':'M1','statement':'Allometric scaling is the planned method.',
         'science':{'role':'METHOD','evidence_status':'NOT_APPLICABLE','method_refs':[],
                    'bindings':[],'adoption_relations':[],'relations':[]},
         'source_refs':[{'component_id':'C1','source_id':'S1','unit_id':'S1_U0001','start_char':11,'end_char':20}]}],
        'potential_questions':[{'id':'Q1','statement':'Is fu constant across the intended range?',
            'reason':'Authored inferred question.', 'origin':'MODEL_INFERENCE','status':'PENDING_CONFIRMATION',
            'needed_at':'human_pk','impact':'Free-exposure scenario may change.',
            'source_refs':[{'component_id':'QUESTION_BASIS','source_id':'S1','unit_id':'S1_U0001','start_char':21,'end_char':30}]}],
        'sources':[{'id':'S1','file_id':'F1','name':'proposal','role':'PROPOSAL','locator':'Synthetic fixture', 'original_sha256':'a'*64}]}


@pytest.mark.parametrize('compact',[False,True])
def test_adequacy_reviews_whole_scientific_records_and_keeps_pending_status(inputs,compact):
    _,_,_,main,inventory=inputs; main=copy.deepcopy(main)
    main.update(version='3.1',scientific_context=science()); validate_handoff(main['scientific_context'])
    if compact:
        from ctxcomp.scientific import compact_projection
        main.update(version='3.2',scientific_context=compact_projection(main['scientific_context']))
    req=adequacy.model_request('adequacy_assessment',main,inventory)
    expected={'/scientific_context/items/0','/scientific_context/items/1','/scientific_context/potential_questions/0'}
    assert {p for p in req['payload']['required_context_paths'] if p.startswith('/scientific_context/')}==expected
    assert req['payload']['main']['scientific_context']==main['scientific_context']
    draft=assessment(req); draft['tasks'][0]['context_evidence'].append({'path':'/scientific_context/items/0','quote':'PREDICTED'})
    adequacy.validate_assessment(draft,req,main,inventory)
    check_req=adequacy.model_request('adequacy_review',main,inventory,draft)
    result=review(check_req); adequacy.validate_review(result,check_req,draft,main,inventory)
    result['context_coverage']=[x for x in result['context_coverage'] if x['path']!='/scientific_context/items/0']
    with pytest.raises(ValueError): adequacy.validate_review(result,check_req,draft,main,inventory)


@pytest.mark.parametrize('compact',[False,True])
def test_rules_reread_sources_but_preserve_typed_context_and_bind_its_version(bundle,compact):
    root,ref,value=bundle
    main=read_json(value['base_main_ref']['path']); main.update(version='3.1',scientific_context=science())
    if compact:
        from ctxcomp.scientific import compact_projection
        main.update(version='3.2',scientific_context=compact_projection(main['scientific_context']))
    main_ref=rules.file_ref(write_json(root/'main-3.1.json',main))
    value=rules._input_value(main_ref,value['sources'],value['source_refs'])
    ref=rules.file_ref(write_json(root/'input-3.1.json',value))
    req=rules.request(value,'project_rules_extract')
    assert req['payload']['inherited_scientific_context']==main['scientific_context']
    assert req['payload']['source_units']==value['source_units']
    result=publish_rules((root,ref,value)); published=read_json(result['main_ref']['path'])
    assert published['scientific_context']==main['scientific_context']
    rules.context_with_rules(published,'adequacy')
    changed=copy.deepcopy(published); changed['scientific_context']['items'][0]['science']['evidence_status']='OBSERVED'
    with pytest.raises(PipelineError) as exc:
        rules.context_with_rules(changed,'adequacy')
    assert exc.value.code == 'PROJECT_RULES_CONTEXT_MISMATCH'


@pytest.mark.parametrize('compact',[False,True])
def test_dispatch_sends_only_cited_records_plus_method_dependencies(snapshot,tmp_path,compact):
    s=read_json(snapshot['path']); artifacts=s['nodes']['adequacy']['artifacts']
    main_path=next(x['path'] for x in artifacts if x['name']=='effective_main.json')
    assessment_path=next(x['path'] for x in artifacts if x['name']=='assessment.json')
    main=read_json(main_path); main['scientific_context']=science()
    if compact:
        from ctxcomp.scientific import compact_projection
        main['scientific_context']=compact_projection(main['scientific_context'])
    write_json(main_path,main)
    data=read_json(assessment_path)
    data['tasks'][0]['context_evidence']=[{'path':'/scientific_context/items/0','quote':'Human CL'}]
    data['tasks'][1]['context_evidence']=[{'path':'/scientific_context/potential_questions/0','quote':'fu constant'}]
    write_json(assessment_path,data)
    artifacts=[{**a,**adequacy.file_ref(a['path'])} for a in artifacts]
    s['nodes']['adequacy']=node(artifacts); s['nodes']['context']=node(artifacts[:1])
    new_ref=adequacy.file_ref(write_json(tmp_path/'updated-snapshot.json',s))
    out=tmp_path/'dispatch'; clinical_dispatch.build(new_ref,out)
    pk=read_json(out/'pk_context.json'); index=read_json(out/'index_context.json')
    assert {x['id'] for x in pk['scientific_context']['items']}=={'E1','M1'}
    assert not pk['scientific_context']['potential_questions']
    assert not index['scientific_context']['items']
    assert index['scientific_context']['potential_questions'][0]['status']=='PENDING_CONFIRMATION'
    assert pk['scientific_context_source']['sha256']==adequacy.file_ref(main_path)['sha256']
