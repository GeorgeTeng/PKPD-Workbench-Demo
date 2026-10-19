"""Deferred Data ownership contracts; authored reviews do not establish semantic accuracy."""
import copy

import pytest

from ctxcomp.engine import init_run, prepare, accept, load_run, verify_context
from ctxcomp.handoff import verify_main
from ctxcomp.io import read_json, write_json, leaves, digest
from ctxcomp import output_profile, split_review
from ctxcomp.schemas import validate_schema
from attachment_fixture import accept_empty_search
from test_retention import demo


FACT = 'Give Compound Z 2 mg/kg IV to rats; reserve human PK until predictions are frozen.'


def ready(tmp_path, legacy=False):
    proposal = tmp_path/'proposal.txt'; proposal.write_text(FACT, encoding='utf-8')
    run = tmp_path/'run'
    options = {'context_output_profile':None} if legacy else {}
    init_run(run, proposal, context_review_mode='legacy', **options)
    accept_empty_search(run)
    request = prepare(run,'requirements')
    requirements = demo.fixture_requirements({'/study/regimen':FACT},request['payload']['source_units'])
    accept(run,'requirements',{'request_sha256':request['request_sha256'],'requirements':requirements})
    request = prepare(run,'requirements_review')
    accept(run,'requirements_review',{'request_sha256':request['request_sha256'],
        'review':demo.fixture_requirements_review(requirements,request['payload']['source_units'])})
    context = {'version':'3.0','objective':FACT,
        'study':{k:FACT if k=='regimen' else 'NOT_FOUND' for k in
                 ['drug','regimen','population','system','measurements','methods']},
        'data':{'available':[],'required':[]},'rules':[],'checks':[],'uncertainties':[]}
    return run, context, requirements


def submit_context(run, context):
    request=prepare(run,'context')
    evidence=[{'path':p,'status':'NOT_FOUND' if value=='NOT_FOUND' else 'EXPLICIT',
               'source_id':'' if value=='NOT_FOUND' else 'S1','quote':'' if value=='NOT_FOUND' else FACT,
               'reason':'Authored fixture only.'} for p,value in leaves(context) if p!='/version']
    response={'request_sha256':request['request_sha256'],'context':context,'evidence':evidence}
    accept(run,'context',response)
    return response


def review_for(run, response, requirements):
    request=prepare(run,'context_review');context=response['context'];evidence=response['evidence']
    atoms,decomposition=demo.fixture_atoms(context,evidence,request['payload']['source_units'])
    review={'decision':'PASS','reviewer':'Authored fixture','review_type':'ASSISTANT_INTERNAL_REVIEW',
        'claims':[{'path':p,'verdict':'PRESERVED','reason':'Fixture.'} for p,_ in leaves(context) if p!='/version'],
        'retention':[{'source_id':'S1','quote':FACT,'verdict':'PRESERVED','critical':True,'reason':'Fixture.'}],
        'coverage':demo.fixture_coverage(requirements,['/study/regimen'],context),
        'atomic_claims':atoms,'decomposition':decomposition,
        'scientific_checks':[{'id':r['id'],'faithfulness':'PRESERVED','completeness':'PRESERVED','reason':'Fixture.'}
                             for r in requirements['items']],
        'critical_errors':[],'limitations':['Authored contract fixture, not semantic validation.']}
    return {'request_sha256':request['request_sha256'],'review':review}


def test_new_context_and_all_review_branches_freeze_empty_data_contract(tmp_path):
    run,context,requirements=ready(tmp_path)
    request=prepare(run,'context');profile=load_run(run)[0]['context_output_profile']
    assert profile['id']=='DATA_DEFERRED_1.0'
    assert request['payload']['context_output_profile']==profile
    for name in ['available','required']:
        assert request['payload']['schema']['properties']['context']['properties']['data']['properties'][name]['maxItems']==0
    response=submit_context(run,context)
    base=prepare(run,'context_review')
    assert base['payload']['context_output_profile']==profile
    for branch in split_review.BRANCHES:
        part=split_review.request_for(base,branch)
        assert part['payload']['context_output_profile']==profile
        assert profile['instructions'] in part['payload']['instructions']
    assert 'every required component' in base['payload']['instructions']
    accept(run,'context_review',review_for(run,response,requirements))
    main=read_json(run/'handoff/main.json')
    assert main['data']['available']==main['data']['required']==[]
    assert main['data']['files'][0]['path']==str((tmp_path/'proposal.txt').resolve())
    assert main['data']['files'][0]['sha256']==load_run(run)[0]['document_files'][0]['sha256']
    assert main['study']['regimen']==FACT
    assert main['scientific_context']['items'][0]['statement']==FACT
    assert verify_main(main)==main and verify_context(run)['status']=='VALID'


@pytest.mark.parametrize('name',['available','required'])
def test_data_summary_is_rejected_at_generation_not_removed_afterward(tmp_path,name):
    run,context,_=ready(tmp_path);context['data'][name]=[FACT]
    with pytest.raises(ValueError):
        submit_context(run,context)
    assert 'context' not in load_run(run)[1]['accepted']
    assert not (run/'handoff/main.json').exists()


@pytest.mark.parametrize('defect',['missing_coverage','missing_component','invented_data_target'])
def test_empty_data_never_waives_critical_component_retention(tmp_path,defect):
    run,context,requirements=ready(tmp_path);response=submit_context(run,context)
    reviewed=review_for(run,response,requirements);review=reviewed['review']
    if defect=='missing_coverage': review['coverage']=[]
    elif defect=='missing_component':
        component=review['coverage'][0]['components'][0]
        component.update(verdict='MISSING',targets=[])
    else: review['coverage'][0]['components'][0]['targets'][0]['path']='/data/available/0'
    with pytest.raises(ValueError): accept(run,'context_review',reviewed)
    assert not (run/'handoff/main.json').exists()


def test_existing_profileless_run_keeps_nonempty_data_and_request_hash(tmp_path,monkeypatch):
    run,context,requirements=ready(tmp_path,legacy=True)
    before=prepare(run,'context')
    monkeypatch.setattr(output_profile,'load_profile',lambda *args: {'id':'FUTURE_PROFILE'})
    assert prepare(run,'context')==before
    assert 'context_output_profile' not in before['payload']
    assert 'maxItems' not in before['payload']['schema']['properties']['context']['properties']['data']['properties']['available']
    context['data']['available']=[FACT]
    response=submit_context(run,context)
    accept(run,'context_review',review_for(run,response,requirements))
    assert read_json(run/'handoff/main.json')['data']['available']==[FACT]
    assert verify_context(run)['status']=='VALID'


def test_profile_is_frozen_and_tampering_invalidates_run(tmp_path,monkeypatch):
    run,_,_=ready(tmp_path);before=prepare(run,'context')
    monkeypatch.setattr(output_profile,'load_profile',lambda *args: {'id':'FUTURE_PROFILE'})
    assert prepare(run,'context')==before
    bundle=read_json(run/'inputs.json');bundle['context_output_profile']['instructions']='Changed'
    write_json(run/'inputs.json',bundle)
    with pytest.raises(ValueError,match='inputs changed'): load_run(run)


def test_missing_information_warning_stays_in_uncertainties_with_empty_data():
    from ctxcomp.supporting import check_warning_retention
    warning={'id':'MI001','field':'binding','status':'NOT_FOUND','needed_at':'pk',
             'why_it_matters':'Free exposure','downstream_impact':'Cannot infer free exposure',
             'requested_information':'Binding evidence'}
    context={'data':{'available':[],'required':[]},'uncertainties':['[MI001] Binding evidence not located.']}
    check_warning_retention(context,[warning])
    context['uncertainties']=[]
    with pytest.raises(ValueError): check_warning_retention(context,[warning])
