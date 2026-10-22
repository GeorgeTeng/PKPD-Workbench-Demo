import copy
import pytest
from research_pipeline.task_rules import project_rules, scoped_context
from research_pipeline.animal_pk_agents import invoke_agent
from research_pipeline.common import PipelineError


def source(drug='Polymyxin B (PMB)'):
    return {'study':{'drug':drug}, 'rules':[
        'R001: Follow the Example et al. translational objective using the existing model library without importing the apramycin model or its parameters.',
        'R020: Admit only converged PK fits with identifiable parameters. Rank eligible models on identical data and likelihood by AIC; differences <2 AIC units are inconclusive.',
        'R023: Fit all three PD indices with both Emax and Hill models on the same response rows and likelihood. Keep matrices and endpoints separate.',
        'R025: Human PK validation uses a priori predictions. Adopt median error <=20%.',
        'R017: PMB activity converts at 10,000 IU per mg; sulfate-to-base conversion requires documented potency.',
        'R018: Reconcile S15 component-versus-sum assay-limit labeling before applying a BLQ likelihood. Preserve BLQ records without zero or half-limit substitution.',
        'R006: Published fitted PK/PD parameters, model structures and benchmark results cannot determine primary starting values, bounds, priors or rankings.',
        'R009: A successful fit is not predictive validation; human PK agreement does not validate antibacterial efficacy or safety. Obtain human review before fitting.',
        'R019: Without supported human binding or population variability, report conditional scenarios, not qualified population PTA; measurement error is not interindividual PK variability.'
    ]}


def texts(projection):
    return '\n'.join(r['text'] for r in projection['rules'])


def test_animal_pk_receives_no_pd_or_pta_or_validation_rules():
    main=source(); before=copy.deepcopy(main)
    p=project_rules(main,'animal_pk',[{'source_id':'S02'}]); t=texts(p)
    assert 'R020' in t and 'R023' not in t and 'R025' not in t
    assert 'S15' not in t and 'Preserve BLQ' in t and '10,000 IU' in t
    assert 'population PTA' not in t and 'Measurement error' in t
    assert 'successful fit is not predictive validation' in t
    assert 'human review before fitting' in t
    assert 'apramycin' not in t and 'Polymyxin B' in t
    assert 'cannot determine primary starting values' in t
    assert len(p['audit'])==len(main['rules']) and not p['unresolved']
    assert main==before


@pytest.mark.parametrize('drug',['apramycin','meropenem'])
def test_drug_is_bound_to_input_and_conversion_is_not_portable(drug):
    p=project_rules(source(drug),'animal_pk',[]);t=texts(p)
    assert 'library for '+drug in t and 'PMB activity' not in t
    assert p['audit'][0]['normalization']['permissions_relaxed'] is False


def test_rule_ids_order_and_filenames_never_determine_scope():
    a=source();b=copy.deepcopy(a)
    # A different source artifact may number rules differently; IDs remain unique.
    b['rules']=[f'R{900+i:03}: '+r.split(': ',1)[1] for i,r in enumerate(reversed(b['rules']))]
    one=project_rules(a,'animal_pk',[{'source_id':'S02','file':'human.csv'}])
    two=project_rules(b,'animal_pk',[{'source_id':'S02','file':'renamed.csv'}])
    assert sorted(r['text'].split(': ',1)[1] for r in one['rules'])==sorted(r['text'].split(': ',1)[1] for r in two['rules'])


def test_scope_can_be_explicit_unknown_cannot_invoke_agent(tmp_path):
    main={'rules':[{'id':'CUSTOM','text':'A custom acceptance condition.','stages':['index']},
                   'A new project condition without a defined task.']}
    p=project_rules(main,'animal_pk')
    assert not p['rules'] and len(p['unresolved'])==1
    with pytest.raises(PipelineError,match='unclassified'):
        invoke_agent({'rule_scope':{'unresolved':p['unresolved']}},{},tmp_path)


def test_reprojection_and_human_task_removal():
    main=source();main.update(module='pk',tasks=[{'id':'animal','question':'Fit animal PK'},
        {'id':'human','question':'Translate animal PK to human exposures'}],
        task_requirements=[{'task_id':'animal'},{'task_id':'human'}])
    branch=copy.deepcopy(main);branch['rules']=project_rules(main,'pk')['rules']
    view,p=scoped_context(branch,'animal_pk')
    assert [t['id'] for t in view['tasks']]==['animal']
    assert view['task_requirements']==[{'task_id':'animal'}]
    assert not p['unresolved'] and 'R023' not in texts(p)


def test_unresolved_scope_survives_projection_and_source_names_are_metadata():
    main=source();main['rules'].append('An unfamiliar scientific restriction.')
    view,p=scoped_context(main,'animal_pk')
    again=project_rules(view,'animal_pk')
    assert again['unresolved']==p['unresolved']
    assert 'Reconcile S15' not in texts(project_rules(source(),'animal_pk',[{'path':'S15.csv'}]))
    assert 'Reconcile S15' in texts(project_rules(source(),'animal_pk',[{'source_id':'S15','path':'arbitrary.csv'}]))
    main['tasks']=[{'id':'PK','question':'Fit animal PK without using human outcomes'}]
    assert scoped_context(main,'animal_pk')[0]['tasks']==main['tasks']
