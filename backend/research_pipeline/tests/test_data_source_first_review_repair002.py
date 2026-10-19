import copy,shutil,json
from pathlib import Path
import pytest
from research_pipeline import data_source_first_review_repair as r,data_source_first_review_repair002 as t

BASE=Path(__file__).resolve().parents[3]/'outputs/Codex_Agent_Run_20261009'
CP=BASE/'fixes/source-first-data/review_repair_contracts/REVIEW_002_continuation.json'


def case():
    return r.read_json(CP),r.read_json(CP.with_name('REVIEW_002_continuation_local_answer.json'))


def test_complete_derive_locks_eight_successful_repairs_and_all_other_fields():
    c,a=case();new,corrected,audit=t.derive(a,c);fixed=r.read_json(c['fixed_patch_ref']['path']);targetset=set(t.TARGETS)
    for before,after in zip(fixed['criterion_corrections'],corrected['criterion_corrections']):
        if (before['requirement_id'],before['criterion_id']) not in targetset:assert before==after
    assert fixed['missing_matches']==corrected['missing_matches']
    assert new['decision']=='NEEDS_REVIEW' and len(new['matches'])==12
    parent,full,part,old,_=t.load(c);r.review.validate_part(new,part,full)
    for before,after in zip(old['matches'],new['matches']):
        for cr in before['criteria']:
            if not any(x['requirement_id']==before['requirement_id'] and x['criterion_id']==cr['id'] for x in parent['targets']):
                assert cr==next(x for x in after['criteria'] if x['id']==cr['id'])


@pytest.mark.parametrize('fault',['cross_need','missing_body','header_body','wrong_deferred','extra_target','duplicate_choice'])
def test_per_target_schema_and_source_body_gate_reject(fault):
    c,a=case();p=t.payload(c)
    if fault=='cross_need':a['row_replacements']['SFQ15__SCOPE_ALIGNMENT']['evidence_choices']=['F0004:S1:T5:B67']
    elif fault=='missing_body':a['row_replacements']['SFQ6__FULL_REQUIREMENT']['status']='PARTIAL'
    elif fault=='header_body':a['row_replacements']['SFQ6__FULL_REQUIREMENT'].update(status='PARTIAL',body_evidence_choice='F0004:S1:T5:A61')
    elif fault=='wrong_deferred':a['deferred_evidence_choice']='F0001:document:line5'
    elif fault=='extra_target':a['row_replacements']['SFQ7__FULL_REQUIREMENT']={}
    else:
        source=p['targets']['SFQ15__SCOPE_ALIGNMENT']['allowed_source_choices'][0]['choice']
        a['row_replacements']['SFQ15__SCOPE_ALIGNMENT']['evidence_choices']=[source,source]
    with pytest.raises(Exception):t.derive(a,c)


def test_full_execute_proof_index_replay_and_raw_immutability(tmp_path):
    c,a=case();run=BASE/'data_test_05_source_first/run';shutil.copyfile(run/'manifest.json',tmp_path/'manifest.json')
    original=r.file_ref(c['fixed_patch_ref']['path'])
    def fake(request,**options):
        answer=copy.deepcopy(a);answer['request_sha256']=request['request_sha256'];return answer
    fake.executor_id='SYNTHETIC_002_CONTINUATION_NO_PROVIDER'
    result=r.execute_continuation(tmp_path,CP,generator=fake);new,parent=r.verify_proof(result['proof_ref']['path']);full,part,_=r._load(parent)
    assert result['part_id']=='REVIEW_002' and r.load_checked_response(tmp_path,part,full)==new
    assert r.file_ref(c['fixed_patch_ref']['path'])==original
    assert len(json.dumps(r.request_for(t.payload(c),t.schema(c)),ensure_ascii=False))<700000
    proof=r.read_json(result['proof_ref']['path']);raw=r.read_json(proof['raw_patch_ref']['path']);raw['deferred_evidence_choice']='invalid';r.write_json(proof['raw_patch_ref']['path'],raw)
    with pytest.raises(Exception):r.verify_proof(result['proof_ref']['path'])
