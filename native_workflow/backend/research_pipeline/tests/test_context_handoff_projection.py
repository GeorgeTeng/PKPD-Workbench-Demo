"""Scoped upstream handoffs preserve conclusions and complete assigned evidence."""
import copy
import json

import pytest

from research_pipeline import context_minimal_policy
from research_pipeline.minimal_context_reducer import reduce_payload, expand_payload, canonical


def policy():
    return context_minimal_policy.load_policy()[0]


def reduce(payload, route):
    result,audit=reduce_payload(payload,route,policy())
    return result,expand_payload(result),audit


def test_local_necessity_bibliography_host_profile_conditions_complete():
    profile={'id':'MP004','name':'Model inputs','source_ids':['S01'],
        'applies_when':'Only when permitted dosing context exists.',
        'required_inputs':['Actual concentration and dose units'],
        'conditional_inputs':['Keep BLQ censored; no invented animal IDs'],
        'acceptable_alternatives':['Group means at their actual level'],
        'data_checks':['Do not infer a serial profile from terminal sampling'],
        'missing_effect':'Only the dependent action is limited',
        'not_established':['No model qualification'],
        'condition_triggers':{'review':'DATA'},'needed_at':'BEFORE_MODELING',
        'outputs':['Conditional simulation definition'], 'future_substantive_field':'Retain unknown fields'}
    payload={'stage':'NECESSITY_SCOPED_ASSESSMENT','local_method_knowledge':{
        'status':'DRAFT','use':'CANDIDATE_ONLY','interpretation':'Not adopted project Rules',
        'profiles':[profile], 'sources':[{'id':'S01','title':'A bibliography','url':'https://example.test'}],
        'library_sha256':'hash','lineage':{'path':'host library','version':'old'}},
        'recorded_shortages':{'RQ1:F1':{'status':'CONFLICT','scope_ids':['mouse/plasma'],
            'conditions':['Known dose basis remains unknown'],
            'evidence':[{'source':'S_A','item_id':'A','quote':'Reported one basis'}],
            'counterevidence':[{'source':'S_B','item_id':'B','quote':'Reported conflicting basis'}]}},
        'schema':{'type':'object','properties':{'local_method_profile_ids':{'enum':['MP004']}}}}
    out,semantic,audit=reduce(payload,'data.necessity')
    expected=copy.deepcopy(profile);expected.pop('source_ids')
    assert semantic['local_method_knowledge']['profiles']==[expected]
    assert semantic['local_method_knowledge']['status']=='DRAFT'
    assert 'sources' not in semantic['local_method_knowledge']
    assert semantic['recorded_shortages']==payload['recorded_shortages']
    assert out['schema']==payload['schema']
    assert all(entry['reason'] for entry in audit['mechanical_field_ledger'])


def test_method_library_as_review_evidence_not_pruned():
    payload={'local_method_knowledge':{'sources':[{'id':'S01','text':'complete candidate evidence'}],
        'profiles':[{'id':'MP004','source_ids':['S01'],'exceptions':['explicit exception']}],
        'lineage':{'path':'scientific-source-locator'}}}
    for route in ('data.coverage','compression.review','eda.plan','eda.findings','eda.review'):
        _,semantic,_=reduce(payload,route)
        assert semantic==payload


def published_rule():
    return {'id':'R020','kind':'PROJECT_REQUIREMENT','text':'Keep the exact operative rule.',
        'conditions':['Only in the named source scope'],'exceptions':['Except explicitly held-out data'],
        'scope':{'species':['mouse'],'matrix':'plasma'},'requirement':{'action':'Preserve records'},
        'usage':{'required_phase':'BEFORE_QC'},'stages':['prepare'],'context_path':'/rules/7',
        'evidence':[{'quote':'Published derivation'}],'authority_evidence':[{'quote':'Adoption evidence'}],
        'field_evidence':[{'path':'/text','spans':[{'quote':'Audit span'}]}],
        'classification_reason':'Rule admission audit','routing_reason':'Already routed by host',
        'candidate_ids':['C021'],'project_rules_ref':{'path':'published rule pack','sha256':'hash'},
        'projection_version':'PUBLISHED_RULE_PROJECTION_1.0',
        'new_scientific_limit':'Unknown substantive field remains'}


@pytest.mark.parametrize('route',['data.adapter_DP','data.adapter_DH-handoff','data.necessity','data.coverage'])
def test_published_rule_derivation_host_all_operative_fields_exact(route):
    rule=published_rule()
    source={'source_id':'S02','text':'Independent counterevidence must stay complete'}
    payload={'project_rules':[rule], 'source_units':[source]}
    _,semantic,audit=reduce(payload,route)
    removed={'evidence','authority_evidence','field_evidence','classification_reason','routing_reason',
             'candidate_ids','project_rules_ref','projection_version'}
    assert semantic['project_rules']==[{key:value for key,value in rule.items() if key not in removed}]
    assert semantic['source_units']==[source]
    assert audit['operative_rule_comparison']==[{'id':'R020','operative_sha256':audit['operative_rule_comparison'][0]['operative_sha256'],'exact':True}]


@pytest.mark.parametrize('change',['missing_ref','missing_version','source_review'])
def test_rule_audit_is_not_discarded_from_unpublished_or_independent_sources(change):
    rule=published_rule();route='data.adapter_DP'
    if change=='missing_ref':rule.pop('project_rules_ref')
    if change=='missing_version':rule.pop('projection_version')
    if change=='source_review':route='compression.review'
    _,semantic,_=reduce({'project_rules':[rule]},route)
    assert semantic['project_rules']==[rule]


def test_summary_keeps_scope_holds_numbers_readiness_and_every_analysis():
    payload={'assessment':{'decision':'CONDITIONAL','scope':'Rat plasma only','conditions':['Dose units unresolved'],
        'must_wait':['Held-out horse validation'],'opinion':'Only defined preparation may continue'},
        'action_decisions':{'MODEL_BASED_ANIMAL_PK':{'readiness':'CONDITIONAL','source_scope':'S21 rat IV',
            'finding':'First observed time is 0.17 h; free-base basis unresolved',
            'next_step':'Clarify source-supported dose basis','gap_ids':['RQ1:F1']}},
        'analyses':[{'id':'NA1','impact':'UNCERTAIN','conditions_to_verify':['No inferred cohort join'],
                    'evidence':[{'source':'E1','quote':'Counterevidence remains'}]}]}
    _,semantic,_=reduce(payload,'data.human_summary')
    assert semantic==payload


def test_all_registered_profiles_keep_assigned_upstream_conclusions_and_source_basis():
    value=policy()
    registered=json.loads(context_minimal_policy.ROUTES.read_text(encoding='utf-8'))['routes']
    assert set(value['routes'])==set(registered) and registered
    basis={'scope':'Mouse plasma; another matrix is not equivalent','status':'CONFLICT',
        'conditions':['At a defined endpoint'],'limitations':['No individual trajectory from means'],
        'source_units':[{'id':'E1','source_id':'S1','text':'Exact observation 0.17 h'},
                        {'id':'E2','source_id':'S2','text':'Contrary independently scoped record'}],
        'record_scope':{'supplied':2,'unchecked':7},'human_approval':False}
    for route in value['routes']:
        payload={'upstream_result':copy.deepcopy(basis),'calculation_bundle':{'complete_rows':[[1,None],[2,'BLQ']]},
            'figure_bundle':{'unreviewed_images':['fig1'],'plot_rows':[[1,2],[2,3]]},
            'requirements':[{'id':'RQ1','conditions':['Original conditional requirement']}],
            'schema':{'type':'object','enum':['E1','E2']}}
        out,semantic,_=reduce(payload,route)
        assert semantic==payload
        assert out['schema']==payload['schema']


def test_shared_exact_text_preserves_each_scope_and_avoids_duplicate_label_prefix():
    quote='Same exact source quotation with conditions and a limitation. '*12
    rows=[{'source':'S'+str(i),'item_id':'independent'+str(i),'quote':quote,'scope':'separate'+str(i)} for i in range(5)]
    payload={'source_units':rows,'source_rows':[quote,quote,quote]}
    out,semantic,_=reduce(payload,'data.coverage')
    assert semantic==payload
    assert len(canonical(out))<len(canonical(payload))
    assert all(not name.startswith('source_rows.source_rows.') for name in out['input_contract']['shared_text'])


def test_eda_profiles_and_route_definitions_unchanged_from_source_capture():
    value=policy()
    assert [value['routes'][route]['profile'] for route in ('eda.plan','eda.findings','eda.review')]==['eda_plan','eda_findings','eda_review']
    assert value['handoff_projection']['version']=='UPSTREAM_SEMANTIC_HANDOFF_1.0'
    assert 'counterevidence' in value['handoff_projection']['protected_evidence']
