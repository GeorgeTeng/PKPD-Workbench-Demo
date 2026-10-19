import copy,shutil
from pathlib import Path
import pytest
from research_pipeline import data_source_first_review_repair as r

BASE=Path(__file__).resolve().parents[3]/'outputs/Codex_Agent_Run_20261009'
FOLDER=BASE/'fixes/source-first-data/review_repair_contracts'


def case():
    c=r.read_json(FOLDER/'REVIEW_001_continuation.json')
    a=r.read_json(FOLDER/'REVIEW_001_continuation_local_answer.json')
    return c,a


def test_exact_main_scalar_alias_is_logged_and_no_other_meaning_changes():
    c,_=case();parent,full,_,_,_=r._continuation_load(c);p=r.payload(parent);main=r.read_json(parent['main_ref']['path']);audit=[]
    source='main:/rules/37/text'
    result=r._span({'source':source,'field':'text'},p,full,main=main,audit=audit)
    assert result==r._span({'source':source,'field':'CONTENT'},p,full,main=main)
    assert audit[0]['canonical_selector']=={'source':source,'field':'CONTENT'}


@pytest.mark.parametrize('source,field',[('main:/rules/37','text'),('main:/no-such-source','text'),('F0004:S1:T11:A132','text'),('main:/rules/37/text','usage')])
def test_other_selector_aliases_rejected(source,field):
    c,_=case();parent,full,_,_,_=r._continuation_load(c)
    with pytest.raises(Exception):r._span({'source':source,'field':field},r.payload(parent),full,main=r.read_json(parent['main_ref']['path']))


def test_saved_raw_still_rejected_without_index_or_provider(tmp_path,monkeypatch):
    c,_=case();run=BASE/'data_test_05_source_first/run';shutil.copyfile(run/'manifest.json',tmp_path/'manifest.json')
    monkeypatch.setattr(r.sf,'invoke',lambda *a,**k:pytest.fail('No provider may run'))
    with pytest.raises(Exception,match='original body evidence'):
        r.replay_saved_patch(tmp_path,c['parent_contract_ref']['path'],c['original_patch_request_ref']['path'],c['fixed_patch_ref']['path'])
    assert not(tmp_path/r.INDEX).exists() and not(tmp_path/'.stage.lock').exists()
    r.check_ref(c['fixed_patch_ref'])


@pytest.mark.parametrize('fault',['extra_row','missing_row','unknown_source','header_support','outside_allowed'])
def test_two_row_scope_and_original_evidence_gates(fault):
    c,a=case()
    if fault=='extra_row':a['row_replacements'][0]['criterion_id']='FIELD_001'
    elif fault=='missing_row':a['row_replacements'].pop()
    elif fault=='unknown_source':a['row_replacements'][0]['evidence_selectors']=[{'source':'unknown','field':'CONTENT'}]
    elif fault=='header_support':a['row_replacements'][0].update(status='PARTIAL',evidence_selectors=[{'source':'F0004:S1:T11:A132','field':'CONTENT'}])
    else:a['row_replacements'][1]['evidence_selectors']=[{'source':'F0004:S1:T15:A210','field':'CONTENT'}]
    with pytest.raises(Exception):r.derive_continuation(a,c)


def test_complete_saved_continuation_execute_index_and_proof_replay(tmp_path):
    c,a=case();run=BASE/'data_test_05_source_first/run';shutil.copyfile(run/'manifest.json',tmp_path/'manifest.json')
    raw_before=r.file_ref(c['fixed_patch_ref']['path'])
    def fake(request,**options):
        answer=copy.deepcopy(a);answer['request_sha256']=request['request_sha256'];return answer
    fake.executor_id='LOCAL_CONTINUATION_TEST_NO_MODEL'
    result=r.execute_continuation(tmp_path,FOLDER/'REVIEW_001_continuation.json',generator=fake)
    new,parent=r.verify_proof(result['proof_ref']['path']);full,part,old=r._load(parent)
    assert r.load_checked_response(tmp_path,part,full)==new
    proof=r.read_json(result['proof_ref']['path']);corrected=r.read_json(proof['corrected_patch_ref']['path']);fixed=r.read_json(c['fixed_patch_ref']['path'])
    wanted=copy.deepcopy(fixed);match=next(x for x in wanted['missing_matches'] if x['requirement_id']=='SFQ5')
    for row in a['row_replacements']:
        i=next(i for i,x in enumerate(match['criteria']) if x['criterion_id']==row['criterion_id']);match['criteria'][i]={'requirement_id':'SFQ5',**row}
    assert corrected==wanted and r.file_ref(c['fixed_patch_ref']['path'])==raw_before
    new['matches'][0]['criteria'][0]['reason']='tampered';r.write_json(proof['derived_response_ref']['path'],new)
    with pytest.raises(Exception):r.verify_proof(result['proof_ref']['path'])
