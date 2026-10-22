"""Bounded scientific splitting; semantic preservation still requires a fresh full review."""
import copy
import pytest
from ctxcomp import lean_compression as lean
from ctxcomp.engine import load_run,prepare,verify_context
from ctxcomp.providers import run_model
from ctxcomp.io import read_json,write_json
from test_lean_compression import setup,candidate,review,patch


def split_review(req):
    value=review(req,'REVISE');parent=req['payload']['candidate']
    citation=copy.deepcopy(next(e for e in parent['evidence'] if e['id']=='F001')['citations'][0])
    citation['quote']='reserve human PK until predictions are frozen.'
    value['review']['fixes']=[{'id':'SPLIT1','target':'F001','reason':'Separate dose and validation restriction.', 'citations':[citation]}]
    return value


def split_patch(req):
    base=req['payload']['candidate'];value=patch(req);parent=copy.deepcopy(base['scientific_context']['items'][0])
    parent['statement']='Give Compound Z 2 mg/kg IV to rats.'
    child=copy.deepcopy(parent);child.update(id='F002',statement='Reserve human PK until predictions are frozen.')
    child['science'].update(role='REQUIREMENT',evidence_status='NOT_APPLICABLE')
    old_e=copy.deepcopy(next(e for e in base['evidence'] if e['id']=='F001'));child_e=copy.deepcopy(old_e)
    child_e['id']='F002';child_e['citations'][0]['quote']='reserve human PK until predictions are frozen.'
    value.update(overview=[],replace_items=[{'record':parent,'fix_ids':['SPLIT1']}],
                 add_items=[{'record':child,'fix_ids':['SPLIT1']}],evidence=[old_e,child_e])
    return value


def split_fixture(tmp_path):
    run=setup(tmp_path);bundle,state=load_run(run);base=lean.content(candidate(prepare(run,'context')))
    citation=copy.deepcopy(next(e for e in base['evidence'] if e['id']=='F001')['citations'][0])
    citation['quote']='reserve human PK until predictions are frozen.'
    findings={'fixes':[{'id':'SPLIT1','target':'F001','reason':'Split the source restriction','citations':[citation]}]}
    req=lean.patch_request(bundle,base,findings,run)
    return run,bundle,base,findings,req,split_patch(req)


def test_scientific_split_keeps_one_parent_and_replayable_full_source_recheck(tmp_path):
    run=setup(tmp_path);calls=[]
    def model(req,**kwargs):
        p=req['payload'];calls.append(p.get('operation',p['stage']))
        if p.get('operation')=='TARGETED_PATCH':return split_patch(req)
        if p['stage']=='context':return candidate(req)
        return review(req) if 'TARGETED_PATCH' in calls else split_review(req)
    assert run_model(run,generator=model)['status']=='CONTEXT_READY'
    assert calls==['context','context_review','TARGETED_PATCH','context_review']
    proof=read_json(run/'lean/patch_proof.json');lineage=proof['split_lineage']['F002']
    assert lineage['parent_id']=='F001' and lineage['fix_ids']==['SPLIT1']
    assert lineage['parent_before_sha256']!=lineage['parent_after_sha256']
    assert lineage['child_citations'][0]['quote'] in lineage['parent_citations'][0]['quote']
    assert verify_context(run)['status']=='VALID'
    proof['split_lineage']['F002']['parent_id']='OTHER';write_json(run/'lean/patch_proof.json',proof)
    with pytest.raises(ValueError,match='lineage changed'):verify_context(run)


@pytest.mark.parametrize('fault',['orphan','unchanged_parent','different_fix','outside_parent','outside_fix','no_evidence','multiple_parents'])
def test_split_rejects_unrelated_or_untraceable_child(tmp_path,fault):
    run,bundle,base,findings,req,response=split_fixture(tmp_path)
    if fault=='orphan':response['replace_items']=[]
    elif fault=='unchanged_parent':response['replace_items'][0]['record']=copy.deepcopy(base['scientific_context']['items'][0])
    elif fault=='different_fix':response['replace_items'][0]['fix_ids']=['OTHER']
    elif fault=='outside_parent':
        u=bundle['source_units'][1];response['evidence'][1]['citations']=[{'source_id':u['source_id'],'unit_id':u['id'],'quote':u['text']}]
    elif fault=='outside_fix':response['evidence'][1]['citations'][0]['quote']='Give Compound Z 2 mg/kg IV to rats'
    elif fault=='no_evidence':response['evidence'][1]['citations']=[]
    else:
        findings['fixes'].append({'id':'SPLIT2','target':'OTHER','reason':'Other parent','citations':[]})
        response['add_items'][0]['fix_ids'].append('SPLIT2')
    with pytest.raises(ValueError,match='split|Split'):lean.apply_patch_response(bundle,base,findings,req,response)


def test_old_profile_does_not_gain_new_split_capability(tmp_path):
    run,bundle,base,findings,req,response=split_fixture(tmp_path)
    bundle['compression_profile'].pop('record_split_patch');bundle['compression_profile'].pop('science_split_patch');bundle['compression_profile']['version']='1.6'
    with pytest.raises(ValueError,match='unrelated'):lean.apply_patch_response(bundle,base,findings,req,response)


def test_mi_contract_splits_states_and_stages_without_inventing_requirements(tmp_path):
    run=setup(tmp_path);bundle,_=load_run(run)
    for key in ('generation_instructions','review_instructions'):
        instructions=bundle['compression_profile'][key]
        assert 'one independently closable issue' in instructions
        assert 'never make different states artificially uniform' in instructions
        assert 'Do not add new experiments, thresholds or assumptions' in instructions
    assert bundle['compression_profile']['science_split_patch']=='SOURCE_SPAN_LINEAGE_1.0'
