import copy
import pytest
from research_pipeline import data_direct_workflow as workflow
from research_pipeline import data_necessity_decisions as nec, data_human_summary_v3 as summary
from research_pipeline.common import read_json,write_json,PipelineError
from test_data_coverage_direct import case, answer as coverage_answer
from test_data_necessity_direct import answer as advice_answer


def answer(request,**kwargs):
    p=request['payload']
    if p['stage']=='DIRECT_DR_COVERAGE':return coverage_answer(request)
    if p['stage']=='NECESSITY_SCOPED_ASSESSMENT':
        r=advice_answer(request)
        r['analyses'][0]['importance']='ANALYSIS_SPECIFIC'
        r['assessment']={'decision':'CONDITIONAL_PASS','scope':'Next analysis inputs','opinion':'Aggregate PK may proceed; matched index comparison lacks response links.'}
        r['action_decisions']={k:{'readiness':'NOT_ESTABLISHED','source_scope':'A group study',
            'finding':'Individual IDs are not established for this source.',
            'next_step':'Use aggregate records; clarify existing individual identities.',
            'gap_ids':list(p['recorded_shortages'])} for k in nec.ACTIONS}
        r['action_decisions']['MODEL_BASED_ANIMAL_PK']['readiness']='CONDITIONAL'
        r['action_decisions']['PTA']['readiness']='LATER'
        return r
    return {'request_sha256':request['request_sha256'],'decision':p['assessment']['decision'],
        'headline':'Use aggregate PK inputs; verify links before index comparison.',
        'rows':{k:{'readiness':p['action_decisions'][k]['readiness'],
            'finding':p['action_decisions'][k]['finding'],'next_step':p['action_decisions'][k]['next_step']} for k in summary.PRIMARY},
        'later_and_optional':'NCA is optional; PTA awaits its upstream model and target.'}


@pytest.fixture
def run(case,tmp_path,monkeypatch):
    # Explicit historical v3 regression; the active v4 path has separate tests.
    from research_pipeline import data_assessment_workflow as runner, data_coverage_direct as coverage
    monkeypatch.setattr(runner,'coverage',coverage)
    monkeypatch.setattr(runner,'necessity',nec)
    monkeypatch.setattr(runner,'human_summary',summary)
    plan,source,main,_=case
    mp=write_json(tmp_path/'mp.json',{'profiles':[{'id':'MP004'}]})
    out=tmp_path/'decisions';calls=[]
    def generate(request,**kwargs):
        calls.append(request['payload']['stage']);return answer(request)
    workflow.run(plan,source,main,mp,out,generator=generate)
    return out,(plan,source,main,mp),calls,generate


def test_five_distinct_opinions_three_visible_rows_no_approval(run,tmp_path):
    out,args,calls,generate=run
    n=nec.verify_result(out/'necessity/necessity.json');s=summary.verify_result(out/'human_summary/summary.json')
    assert len(n['action_decisions'])==5 and len(s['summary']['rows'])==3
    assert len(calls)==3 and not s['scientific_approval']
    assert s['summary']['rows']['MODEL_BASED_ANIMAL_PK']['readiness']=='CONDITIONAL'
    assert s['summary']['rows']['PD_INDEX_COMPARISON']['readiness']=='NOT_ESTABLISHED'
    assert 'recorded_shortages' in n and n['analyses'][0]['gap_ids']
    second=tmp_path/'second'
    workflow.run(*args,second,reuse_coverage=out/'coverage/coverage.json',reuse_necessity=out/'necessity/necessity.json',generator=generate)
    assert calls[3:]==['HUMAN_REVIEW_SUMMARY_ONLY']


@pytest.mark.parametrize('damage',['false_pass','missing_action','invented_gap','verbose_finding'])
def test_data_recommendations_cannot_hide_missing_scope_or_evidence(run,damage):
    out,_,_,_=run;p=read_json(out/'necessity/prepared.json');r=answer(p['request'])
    if damage=='false_pass':r['assessment']['decision']='PASS'
    elif damage=='missing_action':del r['action_decisions']['PD_TARGET_ESTIMATION']
    elif damage=='invented_gap':r['action_decisions']['MODEL_BASED_ANIMAL_PK']['gap_ids']=['FAKE']
    else:r['action_decisions']['MODEL_BASED_ANIMAL_PK']['finding']='word '*46
    with pytest.raises(PipelineError):nec.validate_response(r,p)


@pytest.mark.parametrize('damage',['upgraded_action','omitted_action','long_row','long_summary'])
def test_short_summary_preserves_every_primary_decision(run,damage):
    out,_,_,_=run;p=read_json(out/'human_summary/prepared.json');r=answer(p['request'])
    if damage=='upgraded_action':r['rows']['PD_INDEX_COMPARISON']['readiness']='READY'
    elif damage=='omitted_action':del r['rows']['PD_INDEX_COMPARISON']
    elif damage=='long_row':r['rows']['PD_INDEX_COMPARISON']['finding']='word '*46
    else:r['later_and_optional']='word '*251
    with pytest.raises(PipelineError):summary.validate(r,p)
