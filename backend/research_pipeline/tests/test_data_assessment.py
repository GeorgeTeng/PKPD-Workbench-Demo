"""Scoped recommendation, faithful summary and immutable human handoff."""
import copy
import pytest
from research_pipeline import data_direct_workflow as workflow
from research_pipeline import data_necessity_assessment as nec, data_human_summary_v2 as summary
from research_pipeline import data_coverage_direct as cov
from research_pipeline.common import read_json, write_json, PipelineError
from research_pipeline.data_direct_review import DirectDataReview
from test_data_coverage_direct import case, answer as coverage_answer
from test_data_necessity_direct import answer as advice_answer


def answer(request, **kwargs):
    stage=request['payload']['stage']
    if stage=='DIRECT_DR_COVERAGE':
        return coverage_answer(request)
    if stage=='NECESSITY_SCOPED_ASSESSMENT':
        raw=advice_answer(request)
        raw['analyses'][0]['importance']='ANALYSIS_SPECIFIC'
        raw['assessment']={'decision':'CONDITIONAL_PASS','scope':'Aggregate input preparation',
            'opinion':'Prepare aggregate inputs; individual modeling is not established.',
            'reasons_to_proceed':['Aggregate observations are available.'],
            'reasons_not_to_proceed':['Individual identities are unconfirmed.'],
            'conditions':['Do not estimate individual variability from group means.'],
            'next_steps':['Prepare aggregate records.']}
        return raw
    return {'request_sha256':request['request_sha256'],'decision':'CONDITIONAL_PASS',
        'headline':'Prepare aggregate records within explicit limits',
        'overview':'Individual-level modeling is not established.',
        'can_proceed_now':['Aggregate input preparation'], 'must_wait':['Individual modeling'],
        'optional_improvements':[], 'issues':[{'title':'Identity uncertainty',
            'problem':'Individual records are not established.',
            'effect_on_progress':'Limits individual modeling only.', 'advice':'Clarify existing records.',
            'analysis_ids':[a['id'] for a in request['payload']['analyses']]}],
        'recommended_next_steps':['Prepare aggregate records.']}


@pytest.fixture
def assessed(case,tmp_path,monkeypatch):
    from research_pipeline import data_assessment_workflow as runner
    monkeypatch.setattr(runner,"coverage",cov)
    monkeypatch.setattr(runner,"necessity",nec)
    monkeypatch.setattr(runner,"human_summary",summary)
    plan,source,main,_=case
    mp=write_json(tmp_path/'mp.json',{'profiles':[{'id':'MP004'}]})
    out=tmp_path/'assessed'
    calls=[]
    def generate(request,**kwargs):
        calls.append(request['payload']['stage'])
        return answer(request)
    workflow.run(plan,source,main,mp,out,generator=generate,contract=None)
    return out,(plan,source,main,mp),calls,generate


def test_reuse_coverage_only_two_new_calls_and_no_approval(assessed,tmp_path):
    out,args,calls,generate=assessed
    assert len(calls)==3
    second=tmp_path/'second'
    workflow.run(*args,second,reuse_coverage=out/'coverage/coverage.json',generator=generate,contract=None)
    assert calls[3:]==['NECESSITY_SCOPED_ASSESSMENT','HUMAN_REVIEW_SUMMARY_ONLY']
    n=nec.verify_result(second/'necessity/necessity.json')
    s=summary.verify_result(second/'human_summary/summary.json')
    assert s['assessment']==n['assessment']
    assert s['summary']['decision']==n['assessment']['decision']
    assert not n['scientific_approval'] and not s['downstream_executed']
    workflow.run(*args,second,reuse_coverage=out/'coverage/coverage.json',generator=generate,contract=None)
    assert len(calls)==5


@pytest.mark.parametrize('damage',['unconditional','unsupported_positive','optional_blocker','future','missing_gap'])
def test_opinion_cannot_hide_conditions_or_lose_gaps(assessed,damage):
    out,_,_,_=assessed
    p=read_json(out/'necessity/prepared.json');r=answer(p['request'])
    if damage=='unconditional':r['assessment']['decision']='PASS'
    elif damage=='unsupported_positive':r['assessment']['reasons_to_proceed']=[]
    elif damage=='optional_blocker':r['analyses'][0]['importance']='OPTIONAL_IMPROVEMENT'
    elif damage=='future':r['analyses'][0]['importance']='FUTURE_DEPENDENCY'
    else:r['analyses']=[]
    with pytest.raises(PipelineError):nec.validate_response(r,p)


@pytest.mark.parametrize('damage',['decision','missing_analysis','invented_optional'])
def test_summary_cannot_change_opinion_or_omit_issues(assessed,damage):
    out,_,_,_=assessed
    p=read_json(out/'human_summary/prepared.json');r=answer(p['request'])
    if damage=='decision':r['decision']='PASS'
    elif damage=='missing_analysis':r['issues']=[]
    else:r['optional_improvements']=['Invented suggestion']
    with pytest.raises(PipelineError):summary.validate(r,p)


def test_summary_gate_binds_new_summary_and_reused_coverage(assessed,tmp_path,monkeypatch):
    out,_,_,_=assessed
    store=DirectDataReview(tmp_path/'state',tmp_path)
    with pytest.raises(ValueError,match='Synthetic'):store.publish(out)
    for mod,path in [(cov,out/'coverage/coverage.json'),(nec,out/'necessity/necessity.json'),(summary,out/'human_summary/summary.json')]:
        value=copy.deepcopy(mod.verify_result(path));value['execution']['test_generator']=False
        monkeypatch.setattr(mod,'verify_result',lambda path,value=value:value)
    gate=store.publish(out)
    assert gate['status']=='INTERRUPTED' and gate['review'] is None
    assert 'summary.json' in [a['name'] for a in gate['artifacts']]
    write_json(out/'human_summary/summary.json',{'changed':True})
    stale=store.view(gate['id'])
    assert stale['status']=='STALE' and not stale['can_review']


def test_altered_assessment_cannot_be_replayed(assessed):
    out,_,_,_=assessed
    path=out/'necessity/necessity.json'
    value=read_json(path);value['assessment']['decision']='PASS';write_json(path,value)
    with pytest.raises(PipelineError,match='differs'):nec.verify_result(path)


def test_only_summary_is_regenerated_from_verified_advice(assessed,tmp_path):
    out,args,calls,generate=assessed
    destination=tmp_path/'summary_only'
    workflow.run(*args,destination,reuse_coverage=out/'coverage/coverage.json',contract=None,
        reuse_necessity=out/'necessity/necessity.json',generator=generate)
    assert calls[3:]==['HUMAN_REVIEW_SUMMARY_ONLY']
    assert summary.verify_result(destination/'human_summary/summary.json')['bindings']['necessity']==nec.rt.file_ref(out/'necessity/necessity.json')


def test_summary_word_limit(assessed):
    out,_,_,_=assessed
    p=read_json(out/'human_summary/prepared.json');r=answer(p['request'])
    r['overview']='word ' * 651
    with pytest.raises(PipelineError,match='650-word'):summary.validate(r,p)
