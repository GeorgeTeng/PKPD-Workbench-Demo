import copy
import json
import pytest
from research_pipeline import data_source_first_organize as o,method_profiles as mp,data_agents as d


@pytest.fixture
def inputs(monkeypatch):
    main={'objective':'Assess mouse PK','data':{'files':[]},'rules':[{'id':'R1','kind':'REQUIREMENT','text':'Keep source units',
        'conditions':['same experiment'],'exceptions':[],'scope':{'stages':['adequacy']},'requirement':{'fields':['units']},
        'usage':'planning','field_evidence':{'text':'upstream evidence'}}],
        'scientific_context':{'items':[{'statement':'Mouse PK is the objective'}]},
        'missing_information':{'items':[{'field':'dose basis','status':'AMBIGUOUS'}]}}
    monkeypatch.setattr(o,'embedded_projection',lambda m,stages:[{**m['rules'][0],'stages':['adequacy'],'context_path':'/rules/0'}])
    descriptor={'title':'Source table','source_notes':'Dose 2 mg\nidentity unknown','linked_notes':'Not supplied elsewhere'}
    view={'profiles':[{'item_id':'I','columns':[{'header':'Time','unit':'h','qualifiers':['after dose']}],
          'species':'mouse','stated_values':[{'value':'2','unit':'mg','subject':'group A'}],'evidence_source_ids':['I:1']}],
          'source_units':{'I':json.dumps(descriptor,ensure_ascii=False),'I:1':'Dose 2 mg','I:2':'identity unknown'},
          'legacy_findings':[{'code':'UNKNOWN_IDENTITY','reason':'identity unknown','affected_id':'OLD_Q'}]}
    return main,view,mp.planning_context()


def test_projection_retains_all_notes_rules_conditions_and_findings(inputs):
    main,view,knowledge=inputs;original=copy.deepcopy(view)
    payload,schema,sources=o.build_payload(main,view,knowledge)
    assert view==original
    assert set(payload['source_units'])==set(view['source_units'])
    assert payload['source_units']['I:1']==view['source_units']['I:1']
    descriptor=json.loads(payload['source_units']['I'])
    assert 'source_notes' not in descriptor
    assert descriptor['linked_notes']=='Not supplied elsewhere'
    assert descriptor['title']=='Source table'
    assert payload['legacy_findings']==view['legacy_findings']
    assert 'stated_values' not in payload['data_profiles'][0]
    assert payload['data_profiles'][0]['checked_stated_value_count']==1
    assert payload['data_profiles'][0]['columns']==view['profiles'][0]['columns']
    rule=payload['project_rules'][0]
    assert rule['conditions']==['same experiment'] and rule['exceptions']==[] and rule['usage']=='planning'
    assert 'field_evidence' not in rule
    assert sources['main:/rules/0/conditions/0']=='same experiment'
    assert 'main:/rules/0/field_evidence/text' not in sources
    assert sources['I']==view['source_units']['I']


def response(payload):
    return {'request_sha256':'fixture','tasks':[{'id':'SFT001','objective':'Assess mouse PK','destination':'pk',
        'evidence':[{'source':'main:/objective','quote':'Assess mouse PK'}]}],
        'requirements':[{'id':'SFQ001','task_id':'SFT001','description':'Source concentrations','kind':'DATA',
        'required_by':'BEFORE_MODELING','fields':['concentration'],'rule_ids':['R1'],
        'evidence':[{'source':'main:/objective','quote':'Assess mouse PK'}],
        'origin':'PROJECT_EXPLICIT','method_profile_ids':[],'conditions':[]}],
        'findings':[], 'data_links':[{'item_id':'I','requirement_ids':['SFQ001'],'reason':'Potential source, unresolved identity',
        'evidence':[{'source':'I:2','quote':'identity unknown'}]}],
        'objective_coverage':[{'source':s,'requirement_ids':['SFQ001'],'reason':'Preserve project objective or gap',
        'evidence':[{'source':s,'quote':payload['context_sources'][s]}]} for s in payload['objective_source_ids']]}


def test_original_evidence_and_new_associations_pass(inputs):
    p,s,sources=o.build_payload(*inputs);r=response(p)
    d.validate_schema(r,s)
    assert o.validate_response(r,p,sources,inputs[2])


@pytest.mark.parametrize('fault',['missing_item','unknown_need','bad_quote','lost_objective','wrong_item_evidence','wrong_objective_evidence','method_without_project'])
def test_missing_coverage_and_unsupported_evidence_rejected(inputs,fault):
    p,s,sources=o.build_payload(*inputs);r=response(p)
    if fault=='missing_item':r['data_links']=[]
    elif fault=='unknown_need':r['data_links'][0]['requirement_ids']=['OLD_Q']
    elif fault=='bad_quote':r['data_links'][0]['evidence'][0]['quote']='Invented identity'
    elif fault=='lost_objective':r['objective_coverage'].pop()
    elif fault=='wrong_item_evidence':r['data_links'][0]['evidence']=r['tasks'][0]['evidence']
    elif fault=='wrong_objective_evidence':r['objective_coverage'][-1]['evidence']=r['tasks'][0]['evidence']
    else:
        n=r['requirements'][0];n.update(origin='METHOD_CANDIDATE',method_profile_ids=['MP002'],conditions=['if requested'],
            evidence=[{'source':'method:MP002','quote':'MP002'}])
    with pytest.raises(Exception):o.validate_response(r,p,sources,inputs[2])


def test_descriptor_projection_cannot_support_new_nonoriginal_json_quote(inputs):
    p,s,sources=o.build_payload(*inputs);r=response(p)
    r['data_links'][0]['evidence']=[{'source':'I','quote':p['source_units']['I']}]
    with pytest.raises(Exception):o.validate_response(r,p,sources,inputs[2])


@pytest.mark.parametrize('leaf,index,valid',[('clarification',0,True),('impact',0,True),('why_it_matters',0,True),
    ('clarification',1,False),('status',0,False),('needed_at',0,False)])
def test_mi_coverage_keeps_exact_canonical_record_boundary(inputs,leaf,index,valid):
    main,view,knowledge=inputs
    main['missing_information']['items'][0].update(clarification='Clarify dose basis',impact='Basis uncertain',why_it_matters='Units depend on basis',needed_at='prepare')
    main['missing_information']['items'].append({'field':'Other missingness','clarification':'Other clarification'})
    p,s,sources=o.build_payload(main,view,knowledge);r=response(p)
    row=next(x for x in r['objective_coverage'] if x['source']=='main:/missing_information/items/0/field')
    source=f'main:/missing_information/items/{index}/{leaf}'
    row['evidence']=[{'source':source,'quote':sources[source]}]
    if valid:assert o.validate_response(r,p,sources,knowledge)
    else:
        with pytest.raises(Exception):o.validate_response(r,p,sources,knowledge)
