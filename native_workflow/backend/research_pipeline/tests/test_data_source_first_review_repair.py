import copy,json
from pathlib import Path
import pytest
from research_pipeline import data_source_first_review_repair as r
from research_pipeline.common import read_json,write_json

BASE=Path(__file__).resolve().parents[3]/'outputs/Codex_Agent_Run_20261009/fixes/source-first-data/review_repair_contracts'


def local_answer(c):
    full,part,old=r._load(c)
    if c['kind']=='GLOBAL_SUPPLEMENT':
        source='main:/scientific_context/items/33/statement'
        return {'request_sha256':'LOCAL_ONLY','checks':old['checks'],'scope_finding':dict(old['findings'][0],
            code='REVIEW_SCOPE_CLARIFIED',reason='Local synthetic test: criterion review belongs to separate owning parts.',needed_material='Independent global claim review'),
            'additional_findings':[],'explicit_claim_review':{'source':source,'decision':'NEEDS_REVIEW','reason':'Local test only: original Rabbit source and current claim require independent reconciliation.',
                'evidence_selectors':[{'source':source,'field':'CONTENT'}],
                'finding':{'code':'DR_CLAIM_CORRECTION_REQUIRED','affected_id':source,'reason':'Local test only: check the different species in the source and claim.',
                    'needed_material':'Correct the DR association against the fixed source.','required_by':'BEFORE_QC','severity':'HUMAN_REVIEW'}}}
    def criterion(rid,cid):
        return {'requirement_id':rid,'criterion_id':cid,'status':'UNRESOLVED','reason':'Local synthetic contract test; independent evidence judgment remains required.',
                'needed_material':'Perform the independent original source review.','evidence_selectors':[]}
    answer={'request_sha256':'LOCAL_ONLY','criterion_corrections':[criterion(t['requirement_id'],t['criterion_id']) for t in c['targets']],
        'missing_matches':[],'deferred_evidence_corrections':[{'target':t['target'],'evidence_selectors':[{'source':'main:/rules/10/text','field':'CONTENT'}]} for t in c['deferred_targets']]}
    for rid in c['missing_requirements']:
        plan=next(p for p in full['criterion_plans'] if p['requirement_id']==rid)
        answer['missing_matches'].append({'requirement_id':rid,'reason':'Local synthetic missing-match completion test only.',
            'needed_material':'Independent requirement assessment','criteria':[criterion(rid,x['id']) for x in plan['criteria']]})
    return answer


@pytest.fixture(params=['REVIEW_001','REVIEW_002','REVIEW_004'])
def case(request):
    path=BASE/(request.param+'.json')
    if not path.exists():pytest.skip('Saved source-first review repair fixture absent')
    c=read_json(path);return c,local_answer(c)


def test_complete_host_checks_and_locking(case):
    c,a=case;new,audit=r.derive(a,c);full,part,old=r._load(c)
    r.review.validate_part(new,part,full)
    if c['kind']=='CRITERION_REPAIR':
        assert new['checks']==old['checks'] and new['findings']==old['findings']
        for match in old['matches']:
            after=next(m for m in new['matches'] if m['requirement_id']==match['requirement_id'])
            for cr in match['criteria']:
                if not any(t['requirement_id']==match['requirement_id'] and t['criterion_id']==cr['id'] for t in c['targets']):
                    assert cr==next(x for x in after['criteria'] if x['id']==cr['id'])
            assert after['reason'].startswith(match['reason'])
    else:
        assert len(new['ledger_outcomes'])==9
        for before,after in zip(old['ledger_outcomes'],new['ledger_outcomes']):
            assert after['outcome']==before['outcome']=='ESCALATED'
            assert before['limitation'] in after['reason'] and after['limitation']=='NONE'
            assert after['evidence']==before['evidence']


def test_frozen_governed_request_and_size(case):
    c,_=case;_,part,_=r._load(c)
    assert r.request_for(part)==read_json(c['original_request_ref']['path'])
    assert len(json.dumps(r.request_for(r.payload(c),r.schema(c)),ensure_ascii=False))<700000


def test_proof_replays_and_tamper_fails(case,tmp_path):
    c,a=case;q=r.request_for(r.payload(c),r.schema(c));a['request_sha256']=q['request_sha256'];new,audit=r.derive(a,c)
    refs={k:r.file_ref(write_json(tmp_path/(k+'.json'),v)) for k,v in [('contract_ref',c),('patch_request_ref',q),('raw_patch_ref',a),('derived_response_ref',new),('derivation_audit_ref',audit)]}
    path=write_json(tmp_path/'proof.json',{'version':r.VERSION,'attribution':'HOST_DERIVED_TARGETED_REVIEW',**refs})
    assert r.verify_proof(path)[0]==new
    new['decision']='PASS';write_json(refs['derived_response_ref']['path'],new)
    with pytest.raises(Exception):r.verify_proof(path)


@pytest.mark.parametrize('fault',['target_missing','extra_target','unknown_source','header_as_body','changed_valid_criterion','missing_sfq5','bad_deferred','changed_input'])
def test_criterion_negative_cases(fault):
    c=read_json(BASE/('REVIEW_002.json' if fault=='bad_deferred' else 'REVIEW_001.json'));a=local_answer(c)
    if fault=='target_missing':a['criterion_corrections'].pop()
    elif fault=='extra_target':a['criterion_corrections'].append(copy.deepcopy(a['criterion_corrections'][0]))
    elif fault=='unknown_source':a['criterion_corrections'][0]['evidence_selectors']=[{'source':'not-present','field':'CONTENT'}]
    elif fault=='header_as_body':
        row=a['criterion_corrections'][0];row.update(status='PARTIAL',evidence_selectors=[{'source':'main:/scientific_context/items/2/statement','field':'CONTENT'}])
    elif fault=='changed_valid_criterion':a['criterion_corrections'][0]['criterion_id']='FIELD_001'
    elif fault=='missing_sfq5':a['missing_matches']=[]
    elif fault=='bad_deferred':a['deferred_evidence_corrections'][0]['evidence_selectors']=[{'source':'F0001:document:line5','field':'CONTENT'}]
    else:c['input_refs'][0]['sha256']='0'*64
    with pytest.raises(Exception):r.derive(a,c)


@pytest.mark.parametrize('fault',['missing_claim','wrong_source','no_finding','upgrade'])
def test_global_requires_known_claim_and_preserves_adverse_decisions(fault):
    c=read_json(BASE/'REVIEW_004.json');a=local_answer(c)
    if fault=='missing_claim':del a['explicit_claim_review']
    elif fault=='wrong_source':a['explicit_claim_review']['evidence_selectors'][0]['source']='main:/scientific_context/items/32/statement'
    elif fault=='no_finding':a['explicit_claim_review']['finding']['affected_id']='unrelated'
    else:a['checks'][0]['decision']='PASS'
    with pytest.raises(Exception):r.derive(a,c)


def test_encoded_order_may_change_but_content_cannot():
    c=read_json(BASE/'REVIEW_001.json');_,part,_=r._load(c);q=read_json(c['original_request_ref']['path'])
    reordered=copy.deepcopy(part);reordered['evidence_catalog']['groups'].reverse()
    assert r.frozen_part(reordered,q)==part
    reordered['evidence_catalog']['groups'][0]['rows'][0][2]+='changed'
    with pytest.raises(Exception):r.frozen_part(reordered,q)
