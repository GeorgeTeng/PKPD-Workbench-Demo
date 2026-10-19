"""Explicit original stage routing; original contracts and duties remain untouched."""
import copy
import pytest
from research_pipeline import data_assessment_workflow as workflow
from research_pipeline import data_coverage_direct as cov,data_necessity_decisions as nec
from research_pipeline import data_necessity_prompt as prompt,data_human_summary_v3 as summary
from research_pipeline.common import read_json,write_json,PipelineError
from test_data_coverage_direct import case
from test_data_decisions import answer


@pytest.fixture(autouse=True)
def no_provider(monkeypatch):
    def forbidden(*a,**kw):pytest.fail('Original-stage offline test cannot call a provider')
    monkeypatch.setattr(cov.rt.providers,'codex_generate',forbidden)


@pytest.fixture
def original(case):
    plan,source,main,out=case
    value=read_json(plan);value['version']='REQUIREMENT_PLAN_6.0';write_json(plan,value)
    methods=write_json(out.parent/'methods.json',{'profiles':[{'id':'MP004'}]})
    calls=[]
    def generate(request,**kw):
        calls.append(copy.deepcopy(request));return answer(request)
    workflow.run(plan,source,main,methods,out,generator=generate,contract='original')
    return out,(plan,source,main,methods),calls,generate


def test_explicit_original_option_uses_exact_original_stages_and_three_calls(original):
    out,args,calls,generate=original
    coverage=cov.verify_result(out/'coverage/coverage.json')
    necessity=nec.verify_result(out/'necessity/necessity.json')
    human=summary.verify_result(out/'human_summary/summary.json')
    assert coverage['version']=='DIRECT_DR_COVERAGE_1.0'
    assert necessity['version']=='DIRECT_NECESSITY_3.0'
    assert human['version']=='DATA_HUMAN_SUMMARY_3.0'
    assert [c['payload']['stage'] for c in calls]==[
        'DIRECT_DR_COVERAGE','NECESSITY_SCOPED_ASSESSMENT','HUMAN_REVIEW_SUMMARY_ONLY']
    assert len(calls)==3 and coverage['requirements']==read_json(args[0])['requirements']
    assert calls[0]['payload']['schema']==cov.response_schema(coverage['requirements'])
    assert cov.INSTRUCTIONS in calls[0]['payload']['instructions']
    assert prompt.INSTRUCTIONS in calls[1]['payload']['instructions']
    assert summary.INSTRUCTIONS in calls[2]['payload']['instructions']
    assert calls[1]['payload']['schema']==nec.schema_for(necessity['recorded_shortages'],['MP004'])
    assert set(calls[1]['payload']['schema']['properties']['action_decisions']['properties'])==set(nec.ACTIONS)
    assert 'scope_readiness' not in calls[1]['payload']['schema']['properties']['action_decisions']['properties']['PTA']['properties']
    assert calls[0]['payload']['rules']==[{k:r[k] for k in cov.RULE_KEYS if k in r} for r in read_json(args[2])['rules']]
    assert not human['scientific_approval'] and not human['downstream_executed']
    assert not (out/'human_gate.json').exists()
    assert read_json(out/'execution_contract.json')['contract']=='original'


def test_original_option_resume_is_explicit_and_does_not_add_calls(original):
    out,args,calls,generate=original
    workflow.run(*args,out,generator=generate,contract='original')
    assert len(calls)==3
    before=(out/'inputs.json').read_bytes()
    with pytest.raises(PipelineError,match='same explicit original contract'):
        workflow.run(*args,out,generator=generate)
    assert len(calls)==3 and (out/'inputs.json').read_bytes()==before


def test_default_versioned_run_cannot_be_silently_switched_to_original(case):
    plan,source,main,out=case
    methods=write_json(out.parent/'methods.json',{'profiles':[{'id':'MP004'}]})
    write_json(out/'inputs.json',{'existing':'versioned assessment'})
    before=(out/'inputs.json').read_bytes()
    with pytest.raises(PipelineError,match='no original contract binding'):
        workflow.run(plan,source,main,methods,out,generator=answer,contract='original')
    assert (out/'inputs.json').read_bytes()==before and not (out/'execution_contract.json').exists()


def test_unknown_contract_is_rejected_without_writing(case):
    plan,source,main,out=case
    with pytest.raises(PipelineError,match='Unknown explicit'):
        workflow.run(plan,source,main,main,out,contract='new-qualification')
    assert not out.exists()


@pytest.mark.parametrize('explicit',[False,True])
def test_production_frontdoors_forward_original_default_and_preserve_override(case,monkeypatch,explicit):
    from contextlib import nullcontext
    from research_pipeline import context_linear,data_direct_workflow
    calls=[]
    def execute(*args,**kwargs):calls.append(kwargs);return {'forwarded':True}
    monkeypatch.setattr(workflow,'run',execute)
    class Session:
        def __init__(self,*a,**kw):pass
        def activate(self):return nullcontext()
    monkeypatch.setattr(context_linear,'LinearSession',Session)
    plan,source,main,out=case
    options={'contract':None} if explicit else {}
    assert data_direct_workflow.run(plan,source,main,main,out,**options)=={'forwarded':True}
    assert context_linear.run_data(plan,source,main,main,out,out/'session',**options)=={'forwarded':True}
    assert len(calls)==2
    assert all(call['contract']==(None if explicit else 'original') for call in calls)
