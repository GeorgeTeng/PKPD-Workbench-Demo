"""Fault-injection tests for one bounded repair; not an LLM accuracy benchmark."""
import copy
import pytest
from ctxcomp import binding_repair as repair
from ctxcomp.bindings import binding_diagnostics, BindingValidationError
from ctxcomp.scientific import validate_inventory
from ctxcomp.rules import load_rules
from ctxcomp.schemas import SCHEMAS
from ctxcomp.io import digest,read_json
from ctxcomp.engine import init_run,verify_context
from ctxcomp.providers import run_model
from attachment_fixture import accept_empty_search
from test_scientific_extraction import scientific_fixture
from test_retention import reference_run,EXAMPLES
from test_split_review import authored_response
from ctxcomp import split_review as split
from rule_versions import before_1_29, freeze


def case():
    _,units,inv=scientific_fixture()
    inv['items'][2]['science']['bindings'][2]['value']='4.0 L/hour'
    p={'stage':'requirements','schema':SCHEMAS['requirements'],'source_units':units}
    parent={'request_sha256':digest(p),'payload':p}
    candidate={'request_sha256':parent['request_sha256'],'requirements':inv}
    details=binding_diagnostics(inv,units)
    req=repair.make_request(parent,candidate,details,load_rules())
    response={'request_sha256':req['request_sha256'],'repairs':[{'item_id':'R003','binding_index':2,
        'status':'CORRECTED','replacements':[{'field':'value','value':'4','component_ids':['C1']}],
        'reason':'Copy the numeric source excerpt; units remain in the unchanged units binding.'}],'method_ref_repairs':[]}
    return parent,candidate,details,req,response


def test_repair_only_changes_flagged_binding_and_keeps_all_other_meaning():
    parent,candidate,details,req,response=case(); before=copy.deepcopy(candidate)
    fixed=repair.apply_response(parent,candidate,req,response)
    expected=copy.deepcopy(candidate); expected['requirements']['items'][2]['science']['bindings'][2]['value']='4'
    assert candidate==before and fixed==expected
    assert req['payload']['agent_contract']['task']==load_rules()['agent_contracts']['agents']['binding_repair']['task']
    assert req['request_sha256']==digest(req['payload'])


@pytest.mark.parametrize('fault',['drop','extra','duplicate','field','component','fabricate','stale','changed_candidate','unresolved'])
def test_invalid_repair_cannot_drop_widen_or_invent(fault):
    parent,candidate,_,req,response=case(); r=response['repairs'][0]
    if fault=='drop': r['replacements']=[]
    elif fault=='extra': response['repairs'].append({**copy.deepcopy(r),'item_id':'R999'})
    elif fault=='duplicate': response['repairs'].append(copy.deepcopy(r))
    elif fault=='field': r['replacements'][0]['field']='dose'
    elif fault=='component': r['replacements'][0]['component_ids']=['C999']
    elif fault=='fabricate': r['replacements'][0]['value']='400'
    elif fault=='stale': response['request_sha256']='old'
    elif fault=='changed_candidate': candidate['requirements']['items'][2]['statement']='Changed candidate'
    else: r.update(status='UNRESOLVED',replacements=[],reason='Cannot preserve the intended association.')
    with pytest.raises(ValueError): repair.apply_response(parent,candidate,req,response)


def test_failed_repair_preserves_all_records_and_does_not_call_twice(tmp_path):
    parent,candidate,details,req,response=case(); calls=[]
    response['repairs'][0]['replacements'][0]['value']='400'
    def generate(request):
        calls.append(request); response['request_sha256']=request['request_sha256']; return response
    with pytest.raises(ValueError): repair.execute(parent,candidate,details,load_rules(),tmp_path,generate)
    assert len(calls)==1
    assert read_json(tmp_path/'result.json')['status']=='FAILED'
    assert read_json(tmp_path/'original_response.json')==candidate
    assert read_json(tmp_path/'response.json')==response
    assert not (tmp_path/'corrected_response.json').exists()


def runner(reference_run,calls,repair_ok,review_ok):
    original=read_json(reference_run/'saved_responses/context_review.json')['review']
    def generator(request,model=None):
        stage=request['payload']['stage']; calls.append(stage)
        if stage=='binding_repair':
            task=request['payload']['tasks'][0]
            return {'request_sha256':request['request_sha256'],'repairs':[
                {'item_id':task['item_id'],'binding_index':task['binding_index'],'status':'CORRECTED',
                 'replacements':[{'field':task['field'],'component_ids':task['component_ids'],
                     'value':task['evidence'][0]['quote'] if repair_ok else 'still rewritten'}],
                 'reason':'Authored source excerpt for a contract test.'}],'method_ref_repairs':[]}
        if stage in split.BRANCHES:
            result=authored_response(request,original)
            if not review_ok and stage==split.FAITH:
                result['review']['decision']='REVISE'
                result['review']['critical_errors']=['Authored semantic failure after exact binding repair.']
            return result
        result=read_json(reference_run/'saved_responses'/f'{stage}.json')
        result['request_sha256']=request['request_sha256']
        if stage=='requirements':
            result['requirements']['items'][0]['science']['bindings']=[
                {'field':'condition','value':'rewritten summary','component_ids':['C1']}]
        return result
    return generator


@pytest.mark.parametrize('repair_ok,review_ok',[(True,True),(False,True),(True,False)])
def test_runner_repairs_once_then_still_requires_all_reviews(tmp_path,reference_run,monkeypatch,repair_ok,review_ok):
    if not repair_ok: freeze(monkeypatch,before_1_29())  # From 1.29.0 the binding is dropped instead (below).
    run=tmp_path/'run'; init_run(run,EXAMPLES/'current_research/proposal.md',context_review_mode='parallel_v1')
    accept_empty_search(run); calls=[]
    generator=runner(reference_run,calls,repair_ok,review_ok)
    if repair_ok:
        result=run_model(run,generator=generator)
        assert result['status']==('CONTEXT_READY' if review_ok else 'REVISE')
        assert set(split.BRANCHES)<=set(calls)
        assert calls.index('binding_repair')<calls.index('requirements_review')
        if review_ok: assert verify_context(run)['status']=='VALID'
    else:
        with pytest.raises(ValueError): run_model(run,generator=generator)
        assert 'requirements_review' not in calls
    assert calls.count('requirements')==calls.count('binding_repair')==1
    assert (run/'handoff/main.json').exists()==(repair_ok and review_ok)
    audit=next((run/'audit/binding_repairs').iterdir())
    assert read_json(audit/'original_response.json')['requirements']['items'][0]['science']['bindings'][0]['value']=='rewritten summary'


def ref_case(target='R001'):
    """R003 names a non-METHOD item in method_refs; the only flagged issue is that reference."""
    _,units,inv=scientific_fixture()
    inv['items'][2]['science']['method_refs']=['R002',target]
    p={'stage':'requirements','schema':SCHEMAS['requirements'],'source_units':units}
    parent={'request_sha256':digest(p),'payload':p}
    candidate={'request_sha256':parent['request_sha256'],'requirements':inv}
    with pytest.raises(BindingValidationError) as caught: validate_inventory(inv,units)
    details=caught.value.validation_details
    req=repair.make_request(parent,candidate,details,load_rules())
    return parent,candidate,details,req


@pytest.mark.parametrize('target',['R001','R999'])
def test_a_method_ref_to_a_non_method_item_is_a_repairable_issue(target):
    _,_,details,req=ref_case(target)
    assert [(i['item_id'],i['reason'],i['proposed_value'],i['ref_index']) for i in details['issues']]==[
        ('R003','METHOD_REF_NOT_METHOD',target,1)]
    assert details['issues'][0]['target_role']==('OBJECTIVE' if target=='R001' else 'MISSING')
    assert req['payload']['tasks']==[] and [t['ref_index'] for t in req['payload']['method_ref_tasks']]==[1]
    assert [m['id'] for m in req['payload']['method_items']]==['R002']


@pytest.mark.parametrize('status,replacement,expected',[('REMOVED','',['R002']),('REPLACED','R002',['R002'])])
def test_method_ref_repair_only_replaces_with_a_method_or_removes(status,replacement,expected):
    parent,candidate,_,req=ref_case()
    response={'request_sha256':req['request_sha256'],'repairs':[],'method_ref_repairs':[{'item_id':'R003','ref_index':1,
        'status':status,'replacement':replacement,'reason':'The objective is not a method.'}]}
    fixed=repair.apply_response(parent,candidate,req,response)
    want=copy.deepcopy(candidate); want['requirements']['items'][2]['science']['method_refs']=expected
    assert fixed==want


@pytest.mark.parametrize('fault',['not_method','removal_with_value','missing','unresolved'])
def test_method_ref_repair_cannot_point_elsewhere_or_skip(fault):
    parent,candidate,_,req=ref_case()
    entry={'item_id':'R003','ref_index':1,'status':'REPLACED','replacement':'R004','reason':'x'}
    if fault=='removal_with_value': entry.update(status='REMOVED',replacement='R002')
    elif fault=='unresolved': entry.update(status='UNRESOLVED',replacement='')
    response={'request_sha256':req['request_sha256'],'repairs':[],
        'method_ref_repairs':[] if fault=='missing' else [entry]}
    with pytest.raises(ValueError): repair.apply_response(parent,candidate,req,response)


def test_a_later_failure_after_a_successful_correction_reports_that_failure(tmp_path):
    parent,candidate,details,req,response=case()
    candidate['requirements']['items'][3]['science']['evidence_status']='OBSERVED'
    req=repair.make_request(parent,candidate,details,load_rules())
    def generate(request):
        response['request_sha256']=request['request_sha256']; return response
    with pytest.raises(ValueError) as caught: repair.execute(parent,candidate,details,load_rules(),tmp_path,generate)
    remaining=caught.value.validation_details
    assert remaining['issues']==[] and remaining['corrected_issues']==details['issues']
    assert 'project assumption' in remaining['post_repair_error']
    assert read_json(tmp_path/'result.json')['validation_details']==remaining


def test_method_ref_repair_is_only_for_runs_whose_rules_list_it():
    rules=load_rules()
    assert repair.eligible(rules)=={'VALUE_NOT_IN_CITED_SOURCE','VALUE_NOT_IN_SINGLE_QUOTE','EMPTY_VALUE','METHOD_REF_NOT_METHOD'}
    earlier=copy.deepcopy(rules); earlier['retry_policy']['binding_repair']['eligible_reasons'].remove('METHOD_REF_NOT_METHOD')
    assert repair.eligible(earlier)==repair.LEGACY_REASONS
