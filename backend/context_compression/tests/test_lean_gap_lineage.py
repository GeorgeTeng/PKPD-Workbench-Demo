"""Same-group missing-information split; synthetic protocol evidence, no model calls."""
import copy
import pytest
from ctxcomp import lean_compression as lean
from ctxcomp.engine import load_run, prepare, verify_context
from ctxcomp.io import read_json, write_json
from ctxcomp.providers import run_model
from test_lean_compression import setup, candidate, review, patch


def gap_candidate(req):
    value=candidate(req)
    value['missing_information']['items']=[dict(id='MI001',field='Two pending source assessments',
        status='DEFERRED',needed_at='pk',impact='Assess independently',why_it_matters='Synthetic fixture',
        clarification='Separate dose and release assessments',resolution_status='OPEN')]
    value['context']['uncertainties']=['[MI001]']
    ev=copy.deepcopy(value['evidence'][-1]);ev['id']='MI001';value['evidence'].append(ev)
    value['evidence'].append(dict(id='/uncertainties/0',status='REFERENCE',citations=[],reason='MI001'))
    return value


def gap_review(req):
    value=review(req,'REVISE')
    quote=next(e for e in req['payload']['candidate']['evidence'] if e['id']=='MI001')['citations']
    value['review']['fixes']=[dict(id='SPLIT1',target='MI001',reason='Split independent assessments.',citations=copy.deepcopy(quote))]
    return value


def gap_patch(req):
    base=req['payload']['candidate'];value=patch(req);parent=copy.deepcopy(base['missing_information']['items'][0])
    parent['field']='Dose assessment';child=copy.deepcopy(parent)
    child.update(id='MI002',field='Release assessment',needed_at='validation')
    evidence=copy.deepcopy(next(e for e in base['evidence'] if e['id']=='MI001'))
    child_ev=copy.deepcopy(evidence);child_ev['id']='MI002'
    value.update(overview=[],replace_gaps=[dict(record=parent,fix_ids=['SPLIT1'])],
                 add_gaps=[dict(record=child,fix_ids=['SPLIT1'])],uncertainty_refs=['[MI001]','[MI002]'],
                 evidence=[evidence,child_ev]+[dict(id='/uncertainties/'+str(i),status='REFERENCE',citations=[],reason=rid)
                    for i,rid in enumerate(['MI001','MI002'])])
    return value


def fixture(tmp_path):
    run=setup(tmp_path);bundle,_=load_run(run);base=lean.content(gap_candidate(prepare(run,'context')))
    quote=next(e for e in base['evidence'] if e['id']=='MI001')['citations']
    findings={'fixes':[dict(id='SPLIT1',target='MI001',reason='Split',citations=copy.deepcopy(quote))]}
    req=lean.patch_request(bundle,base,findings,run)
    return run,bundle,base,findings,req,gap_patch(req)


def test_gap_split_full_review_and_replayable_proof(tmp_path):
    run=setup(tmp_path);calls=[]
    def model(req,**kwargs):
        p=req['payload'];calls.append(p.get('operation',p['stage']))
        if p.get('operation')=='TARGETED_PATCH':return gap_patch(req)
        if p['stage']=='context':return gap_candidate(req)
        return review(req) if 'TARGETED_PATCH' in calls else gap_review(req)
    assert run_model(run,generator=model)['status']=='CONTEXT_READY'
    assert calls==['context','context_review','TARGETED_PATCH','context_review']
    proof=read_json(run/'lean/patch_proof.json');lineage=proof['split_lineage']['MI002']
    assert lineage['record_group']=='gaps' and lineage['parent_id']=='MI001'
    assert verify_context(run)['status']=='VALID'
    proof['split_lineage']['MI002']['record_group']='items';write_json(run/'lean/patch_proof.json',proof)
    with pytest.raises(ValueError,match='lineage changed'):verify_context(run)


@pytest.mark.parametrize('fault',['orphan','unchanged_parent','different_fix','cross_group','outside_parent','outside_fix','no_evidence'])
def test_gap_split_requires_same_group_mutation_and_both_source_bounds(tmp_path,fault):
    run,bundle,base,findings,req,response=fixture(tmp_path)
    if fault=='orphan':response['replace_gaps']=[]
    elif fault=='unchanged_parent':response['replace_gaps'][0]['record']=copy.deepcopy(base['missing_information']['items'][0])
    elif fault=='different_fix':response['replace_gaps'][0]['fix_ids']=['OTHER']
    elif fault=='cross_group':findings['fixes'][0]['target']='F001'
    elif fault=='outside_parent':response['evidence'][1]['citations'][0]['quote']='Unrelated source text'
    elif fault=='outside_fix':findings['fixes'][0]['citations'][0]['quote']='Unrelated review text'
    elif fault=='no_evidence':response['evidence'][1]['citations']=[]
    with pytest.raises(ValueError,match='split'):lean.apply_patch_response(bundle,base,findings,req,response)


def test_frozen_17_still_rejects_gap_split_and_no_question_exception(tmp_path):
    run,bundle,base,findings,req,response=fixture(tmp_path)
    bundle['compression_profile'].pop('record_split_patch');bundle['compression_profile']['version']='1.7'
    assert lean.split_groups(bundle)==('items',)
    with pytest.raises(ValueError,match='unrelated'):lean.apply_patch_response(bundle,base,findings,req,response)
    assert 'not gaps or questions' in lean.patch_request(bundle,base,findings,run)['payload']['instructions']


def test_new_contract_owns_source_explicit_gaps_and_clinical_pta(tmp_path):
    run=setup(tmp_path);bundle,_=load_run(run)
    assert bundle['compression_profile']['version']=='1.14'
    assert lean.split_groups(bundle)==('items','gaps')
    for key in ('generation_instructions','review_instructions'):
        text=bundle['compression_profile'][key]
        assert 'clinical is the stage for PTA population and scenario choices' in text
        assert 'express its complete meaning only in MI' in text
        assert 'not a second full gap statement' in text
