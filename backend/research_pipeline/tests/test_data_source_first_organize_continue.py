import copy
from pathlib import Path
import pytest
from research_pipeline import data_source_first_organize_continue as c,data_agents as d
from research_pipeline.common import read_json,write_json


@pytest.fixture
def actual_case():
    root=Path(__file__).resolve().parents[3]
    path=root/'outputs/Codex_Agent_Run_20261009/fixes/source-first-data/organize_continuation_contract.json'
    if not path.exists():pytest.skip('Saved rejected DR continuation evidence is not present')
    contract=read_json(path)
    answer={'request_sha256':'LOCAL_TEST_ONLY','evidence_selections':[{'path':t['path'],'source':t['choices'][0]['source']} for t in contract['evidence_targets']],
        'objective_replacements':[{'source':t['source'],'requirement_ids':[],
            'reason':'Local synthetic validation only: unresolved coverage requires independent review and a follow-up proposal.'} for t in contract['objective_targets']]}
    return contract,answer


def test_actual_complete_derived_candidate_and_locked_fields(actual_case):
    contract,answer=actual_case;result,patch=c.derive(answer,contract);original=read_json(contract['fixed_patch_ref']['path'])
    expected=copy.deepcopy(original);expected['request_sha256']=answer['request_sha256']
    for t in contract['evidence_targets']:c.prior.put_at(expected,t['path'],t['choices'][0])
    for row in patch['objective_replacements']:
        i=next(i for i,r in enumerate(expected['objective_replacements']) if r['source']==row['source']);expected['objective_replacements'][i]=row
    assert patch==expected
    assert len(result['tasks'])==5 and len(result['requirements'])==17 and len(result['data_links'])==60
    assert result['method_feasibility']==patch['method_feasibility']


@pytest.mark.parametrize('fault',['duplicate','unknown_source','changed_quote','wrong_leaf','off_scope','changed_statement','unknown_need','extra_output'])
def test_reject_changed_or_off_scope_continuation(actual_case,fault):
    contract,answer=actual_case
    if fault=='duplicate':answer['evidence_selections']*=2
    elif fault=='unknown_source':answer['evidence_selections'][0]['source']='main:/missing_information/items/14/clarification'
    elif fault=='changed_quote':contract['evidence_targets'][1]['choices'][0]['quote']='fabricated'
    elif fault=='wrong_leaf':contract['evidence_targets'][0]['choices'][0]['source']='main:/missing_information/items/15/field'
    elif fault=='off_scope':contract['evidence_targets'][0]['path']='/method_feasibility/0/reason'
    elif fault=='changed_statement':contract['objective_targets'][0]['authoritative_text']='Changed scientific condition'
    elif fault=='unknown_need':answer['objective_replacements'][0]['requirement_ids']=['UNKNOWN']
    else:answer['tasks']=[]
    with pytest.raises(Exception):c.derive(answer,contract)


def test_replay_and_tamper_rejection(actual_case,tmp_path):
    contract,answer=actual_case;q=d.governed_request(c.payload(contract));answer['request_sha256']=q['request_sha256']
    result,patch=c.derive(answer,contract)
    refs={k:d.file_ref(write_json(tmp_path/(k+'.json'),v)) for k,v in [('contract_ref',contract),('request_ref',q),('raw_response_ref',answer),('corrected_patch_ref',patch),('derived_response_ref',result)]}
    proof=write_json(tmp_path/'proof.json',{'version':c.VERSION,'attribution':'HOST_MATERIALIZED_MODEL_SOURCE_SELECTIONS',**refs})
    assert c.verify_proof(proof)['status']=='VALID_CONTINUATION_PROOF'
    patch['method_feasibility'][0]['reason']='changed';write_json(refs['corrected_patch_ref']['path'],patch)
    with pytest.raises(Exception):c.verify_proof(proof)
