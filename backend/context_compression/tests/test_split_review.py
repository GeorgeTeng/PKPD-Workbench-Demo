"""Branch coverage, concurrency and publication gates; authored verdicts are not model accuracy."""
import copy
import threading
from pathlib import Path
import pytest
from ctxcomp.engine import init_run,prepare,accept,load_run,verify_context
from ctxcomp.io import read_json,write_json,digest
from ctxcomp.providers import run_model
from ctxcomp import split_review as split
from test_retention import reference_run, EXAMPLES


def context_run(run,reference_run,mode):
    """A run whose stages up to context are accepted from the reference responses, and the authored review."""
    init_run(run,EXAMPLES/'current_research/proposal.md',context_review_mode=mode)
    for stage in ['attachment_plan','attachment_evidence','requirements','requirements_review','context']:
        response=read_json(reference_run/'saved_responses'/f'{stage}.json')
        response['request_sha256']=prepare(run,stage)['request_sha256']; accept(run,stage,response)
    return run,read_json(reference_run/'saved_responses/context_review.json')['review']


@pytest.fixture
def completeness_parts(monkeypatch):
    """Rules with CC012 completeness_parts: 3, which no rules version sets yet. Request it before the run fixture."""
    from ctxcomp import engine
    from ctxcomp.rules import load_rules
    rules=copy.deepcopy(load_rules())
    next(r for r in rules['rules'] if r['id']=='CC012').setdefault('host_requirement',{})['completeness_parts']=3
    monkeypatch.setattr(engine,'load_rules',lambda: copy.deepcopy(rules))


@pytest.fixture
def split_run(tmp_path,reference_run):
    return context_run(tmp_path/'split',reference_run,'parallel_v1')


def authored_response(request, original):
    stage=request['payload']['stage']; review={k:copy.deepcopy(original[k]) for k in split.COMMON}
    if stage==split.FAITH:
        review.update({k:copy.deepcopy(original[k]) for k in ['claims','atomic_claims','decomposition']})
    elif stage==split.COMPLETE:
        review.update({k:copy.deepcopy(original[k]) for k in ['coverage','retention']})
        units=request['payload'].get('review_source_unit_ids',[u['id'] for u in request['payload']['source_units']])
        review['source_units']=[{'unit_id':u,'verdict':'PRESERVED','reason':'Authored test label only.'} for u in units]
    else:
        review['checks']=[{'id':key,'verdict':'PRESERVED','reason':'Authored test label only.','source_evidence':[],'targets':[]} for key in split.GLOBAL_CHECKS]
    if stage in (split.FAITH, split.COMPLETE) and 'scientific_context' in request['payload']:
        key = 'faithfulness' if stage == split.FAITH else 'completeness'
        review['scientific_checks'] = [{'id': c['id'], 'verdict': c[key], 'reason': c['reason']}
                                      for c in original['scientific_checks']]
    return {'request_sha256':request['request_sha256'],'review':review}


def test_parallel_branches_overlap_and_global_waits_for_both(split_run):
    run,original=split_run; barrier=threading.Barrier(2); finished=set(); lock=threading.Lock()
    def generator(request,model=None):
        stage=request['payload']['stage']
        if stage in [split.FAITH,split.COMPLETE]:
            barrier.wait(timeout=5)
            with lock: finished.add(stage)
        else:
            assert finished=={split.FAITH,split.COMPLETE}
            assert set(request['payload']['branch_reviews'])==finished
        return authored_response(request,original)
    assert run_model(run,generator=generator)['status']=='CONTEXT_READY'
    assert verify_context(run)['status']=='VALID'
    proof=read_json(run/'parallel_review_proof.json')
    assert set(proof['branches'])==set(split.BRANCHES)
    assert read_json(run/'handoff/main.json')['version']=='3.2'


def test_direct_legacy_review_cannot_bypass_parallel_gate(split_run):
    run,original=split_run; request=prepare(run,'context_review')
    with pytest.raises((OSError,ValueError)):
        accept(run,'context_review',{'request_sha256':request['request_sha256'],'review':original})
    assert not (run/'handoff/main.json').exists()


@pytest.mark.parametrize('branch',split.BRANCHES)
def test_no_branch_can_be_missing(split_run,branch):
    run,original=split_run
    run_model(run,generator=lambda request,model=None:authored_response(request,original))
    proof=read_json(run/'parallel_review_proof.json'); (run/proof['branches'][branch]['response']).unlink()
    with pytest.raises((OSError,ValueError)): verify_context(run)


@pytest.mark.parametrize('branch',[split.FAITH,split.COMPLETE])
def test_incomplete_branch_blocks_global_and_publication(split_run,branch):
    run,original=split_run; calls=[]
    def generator(request,model=None):
        stage=request['payload']['stage']; calls.append(stage); result=authored_response(request,original)
        if stage==branch:
            result['review']['claims' if stage==split.FAITH else 'coverage'].pop()
        return result
    with pytest.raises(ValueError,match='exactly once'): run_model(run,generator=generator)
    assert split.GLOBAL not in calls and not (run/'handoff/main.json').exists()


@pytest.mark.parametrize('fault', ['MIC_FREEZE_OMITTED','PARAMETER_PERMISSION_CONFLICT','FREE_TOTAL_CHANGED','UNITS_CHANGED','CONDITION_LOST','NEGATION_LOST'])
def test_known_defect_findings_cannot_be_overridden_by_global_pass(split_run,fault):
    run,original=split_run
    def generator(request,model=None):
        result=authored_response(request,original); branch=request['payload']['stage']; review=result['review']
        if fault=='MIC_FREEZE_OMITTED' and branch==split.COMPLETE:
            record=review['coverage'][0]; record['verdict']='MISSING'; record['components'][0]['verdict']='MISSING'
            record['components'][0]['targets']=[]; review['decision']='REVISE'; review['critical_errors']=[fault]
        elif fault=='PARAMETER_PERMISSION_CONFLICT' and branch==split.GLOBAL:
            review['checks'][0]['verdict']='UNRESOLVED'; review['decision']='NEEDS_REVIEW'; review['critical_errors']=[fault]
        elif fault not in {'MIC_FREEZE_OMITTED','PARAMETER_PERMISSION_CONFLICT'} and branch==split.FAITH:
            review['atomic_claims'][0]['verdict']='ALTERED'; review['decision']='REVISE'; review['critical_errors']=[fault]
        return result
    result=run_model(run,generator=generator)
    assert result['status'] in {'REVISE','NEEDS_REVIEW'} and not (run/'handoff/main.json').exists()
    assert fault in read_json(run/'feedback/context.json')['critical_errors']


def test_global_failure_never_publishes(split_run):
    run,original=split_run
    def generator(request,model=None):
        if request['payload']['stage']==split.GLOBAL: raise ValueError('Synthetic global model disconnect')
        return authored_response(request,original)
    with pytest.raises(ValueError,match='disconnect'): run_model(run,generator=generator)
    assert not (run/'handoff/main.json').exists()
    assert read_json(run/'stopped.json')['stage']==split.GLOBAL


def test_changed_proof_cannot_inherit_approval(split_run):
    run,original=split_run
    run_model(run,generator=lambda request,model=None:authored_response(request,original))
    proof=read_json(run/'parallel_review_proof.json'); proof['elapsed_seconds']+=1;write_json(run/'parallel_review_proof.json',proof)
    with pytest.raises(ValueError,match='changed after acceptance'): verify_context(run)


def test_parallel_preserves_existing_exact_envelope_pointer_compatibility(split_run):
    run,original=split_run
    def prefix(value):
        if isinstance(value,dict):
            for k,v in value.items():
                if k=='path': value[k]='/context'+v
                else: prefix(v)
        elif isinstance(value,list):
            for v in value: prefix(v)
    def generate(request,model=None):
        result=authored_response(request,original); prefix(result)
        return result
    assert run_model(run,generator=generate)['status']=='CONTEXT_READY'
    assert verify_context(run)['status']=='VALID'


def test_source_quote_cannot_replace_candidate_quote_and_failure_is_actionable(split_run):
    run,original=split_run
    def generate(request,model=None):
        result=authored_response(request,original)
        if request['payload']['stage']==split.FAITH:
            result['review']['atomic_claims'][0]['quote']='This quotation is absent from the candidate.'
        return result
    with pytest.raises(split.ReviewOutputError,match='candidate context'):
        run_model(run,generator=generate)
    stopped=read_json(run/'stopped.json')
    assert stopped['error_code']=='MODEL_REVIEW_INVALID' and stopped['stage']==split.FAITH
    assert 'evidence[].quote' in stopped['reason']
    assert not (run/'handoff/main.json').exists()


@pytest.fixture
def split_run_v2(tmp_path,reference_run):
    return context_run(tmp_path/'split_v2',reference_run,'parallel_v2')


def part_response(request, original):
    """The authored whole-context review, cut down to one faithfulness or completeness part."""
    result=authored_response(request,original); part=request['payload'].get('review_part')
    if part:
        review=result['review']
        if request['payload']['stage']==split.COMPLETE:
            review['coverage']=[c for c in review['coverage'] if c['requirement_id'] in part['requirement_ids']]
            if not part['source_units']:
                for key in ['source_units','retention']: review.pop(key)
        else:
            own=lambda x: x['path'].removeprefix('/context') in part['paths']
            for key in ['claims','atomic_claims','decomposition']: review[key]=[x for x in review[key] if own(x)]
        if 'scientific_checks' in review:
            review['scientific_checks']=[c for c in review['scientific_checks'] if c['id'] in part['scientific_ids']]
    return result


def complete_branches(run):
    """Completeness branch names for this run's rules: parts from 1.28.0 (CC012 completeness_parts)."""
    base=prepare(run,'context_review'); count=split.completeness_part_count(base['payload'])
    return [part['id'] for part in split.completeness_parts(base,count)] if count else [split.COMPLETE]


def test_split_faithfulness_parts_cover_each_field_once(split_run_v2):
    from ctxcomp.io import leaves
    from ctxcomp import scientific
    run,_=split_run_v2; base=prepare(run,'context_review'); parts=split.faithfulness_parts(base)
    fields=[path for path,_ in leaves(base['payload']['context']) if path!='/version']
    assert len(parts)==split.FAITH_PARTS and all(part['paths'] for part in parts)
    assert [path for part in parts for path in part['paths']]==fields
    expected_ids=scientific.item_ids(base['payload']['requirements']) if 'scientific_context' in base['payload'] else []
    assert [i for part in parts for i in part['scientific_ids']]==expected_ids
    request=split.part_request(base,parts[1])['payload']
    assert request['review_part']['paths']==parts[1]['paths'] and 'you are part 2' in request['instructions']
    assert 'Cover every context scalar listed in review_part.paths' in request['instructions']


def test_split_faithfulness_runs_with_completeness_and_publishes(split_run_v2):
    run,original=split_run_v2; completes=complete_branches(run); first=split.FAITH_PARTS+len(completes)
    barrier=threading.Barrier(first); finished=[]; lock=threading.Lock()
    def generator(request,model=None):
        stage=request['payload']['stage']
        if stage in [split.FAITH,split.COMPLETE]:
            barrier.wait(timeout=5)  # Every part and the completeness review are in flight together.
            with lock: finished.append(stage)
        else:
            assert len(finished)==first
            assert request['payload']['branch_reviews'][split.FAITH]['review']['reviewer'].startswith('Faithfulness review in')
        return part_response(request,original)
    assert run_model(run,generator=generator)['status']=='CONTEXT_READY'
    assert verify_context(run)['status']=='VALID'
    proof=read_json(run/'parallel_review_proof.json')
    assert proof['mode']=='parallel_v2' and proof['faithfulness_parts']==split.FAITH_PARTS
    assert set(proof['branches'])=={f'{split.FAITH}--part_{n}' for n in range(1,split.FAITH_PARTS+1)}|set(completes)|{split.GLOBAL}
    review=read_json(run/state_file(run,'context_review'))['review']
    assert sorted(c['requirement_id'] for c in review['coverage'])==sorted(c['requirement_id'] for c in original['coverage'])
    assert sorted(c['path'] for c in review['claims'])==sorted(c['path'] for c in original['claims'])
    assert len(review['atomic_claims'])==len(original['atomic_claims'])
    assert read_json(run/'handoff/main.json')['version']=='3.2'


def state_file(run, stage):
    _,state=load_run(run)
    return state['accepted'][stage]['file']


def test_part_cannot_review_another_parts_field(split_run_v2):
    run,original=split_run_v2; calls=[]
    def generator(request,model=None):
        calls.append(request['payload']['stage']); part=request['payload'].get('review_part')
        if part and part['part']==1:
            return authored_response(request,original)  # Whole-context claims, not just part 1.
        return part_response(request,original)
    with pytest.raises(ValueError,match='exactly once'): run_model(run,generator=generator)
    assert split.GLOBAL not in calls and not (run/'handoff/main.json').exists()


def test_part_finding_reaches_the_final_review(split_run_v2):
    run,original=split_run_v2
    def generator(request,model=None):
        result=part_response(request,original); part=request['payload'].get('review_part')
        if part and part['part']==2 and request['payload']['stage']==split.FAITH:
            review=result['review']; review['atomic_claims'][0]['verdict']='ALTERED'
            review['decision']='REVISE'; review['critical_errors']=['UNITS_CHANGED']
        return result
    assert run_model(run,generator=generator)['status']=='REVISE'
    assert 'UNITS_CHANGED' in read_json(run/'feedback/context.json')['critical_errors']
    assert not (run/'handoff/main.json').exists()


def test_changed_part_count_cannot_verify(completeness_parts,split_run_v2):
    from ctxcomp.engine import make_request
    run,original=split_run_v2
    run_model(run,generator=lambda request,model=None:part_response(request,original))
    base=make_request(run,'context_review'); result=read_json(run/state_file(run,'context_review'))
    proof=read_json(run/'parallel_review_proof.json'); split.verify_proof(run,base,result)
    for key in ['faithfulness_parts','completeness_parts']:
        for count in [2,None]:
            changed={k:v for k,v in proof.items() if k!=key}
            if count: changed[key]=count
            write_json(run/'parallel_review_proof.json',changed)
            with pytest.raises(ValueError): split.verify_proof(run,base,result)


def test_retry_regenerates_only_the_failed_part(split_run_v2):
    run,original=split_run_v2
    def disconnect_part_2(request,model=None):
        part=request['payload'].get('review_part')
        if part and part['part']==2 and request['payload']['stage']==split.FAITH: raise RuntimeError('Synthetic disconnect')
        return part_response(request,original)
    with pytest.raises(RuntimeError,match='disconnect'):
        run_model(run,generator=disconnect_part_2,review_executor_id='test-provider-v1')
    calls=[]
    def generate(request,model=None):
        part=request['payload'].get('review_part')
        calls.append(part['part'] if part else request['payload']['stage'])
        return part_response(request,original)
    assert run_model(run,generator=generate,review_executor_id='test-provider-v1')['status']=='CONTEXT_READY'
    assert calls==[2,split.GLOBAL]
    branches=read_json(run/'parallel_review_proof.json')['branches']
    assert branches[f'{split.FAITH}--part_2']['execution']=='GENERATED'
    assert {branches[key]['execution'] for key in [f'{split.FAITH}--part_1',f'{split.FAITH}--part_3',*complete_branches(run)]}=={'REUSED'}
    assert verify_context(run)['status']=='VALID'


@pytest.fixture
def split_run_v3(tmp_path,reference_run):
    return context_run(tmp_path/'split_v3',reference_run,'parallel_v3')


def test_conflict_review_runs_alongside_both_branches_and_publishes(split_run_v3):
    run,original=split_run_v3; completes=complete_branches(run); barrier=threading.Barrier(split.FAITH_PARTS+len(completes)+1)
    def generator(request,model=None):
        barrier.wait(timeout=5)  # Every part, completeness and the conflict review are in flight together.
        p=request['payload']
        if p['stage']==split.GLOBAL:
            assert 'branch_reviews' not in p and 'you do not see\ntheir findings' in p['instructions']
            assert 'disagreements between the branch reviews' not in p['instructions']
        return part_response(request,original)
    assert run_model(run,generator=generator)['status']=='CONTEXT_READY'
    assert verify_context(run)['status']=='VALID'
    proof=read_json(run/'parallel_review_proof.json')
    assert proof['mode']=='parallel_v3' and proof['faithfulness_parts']==split.FAITH_PARTS
    assert set(proof['branches'])=={f'{split.FAITH}--part_{n}' for n in range(1,split.FAITH_PARTS+1)}|set(completes)|{split.GLOBAL}
    assert read_json(run/'handoff/main.json')['version']=='3.2'


@pytest.mark.parametrize('failing',[split.COMPLETE,f'{split.COMPLETE}--part_1',f'{split.COMPLETE}--part_3',f'{split.FAITH}--part_2'])
def test_concurrent_conflict_pass_cannot_override_a_branch_failure(request,failing):
    if '--part' in failing and failing.startswith(split.COMPLETE): request.getfixturevalue('completeness_parts')
    run,original=request.getfixturevalue('split_run_v3')
    def generator(request,model=None):
        result=part_response(request,original); p=request['payload']
        name=f"{p['stage']}--part_{p['review_part']['part']}" if 'review_part' in p else p['stage']
        if name==failing:
            review=result['review']
            if p['stage']==split.COMPLETE: review['coverage'][0]['verdict']='MISSING'
            else: review['atomic_claims'][0]['verdict']='ALTERED'
            review['decision']='REVISE'; review['critical_errors']=['AUTHORED_BRANCH_FAILURE']
        return result
    assert run_model(run,generator=generator)['status']=='REVISE'
    assert 'AUTHORED_BRANCH_FAILURE' in read_json(run/'feedback/context.json')['critical_errors']
    assert not (run/'handoff/main.json').exists()


def test_concurrent_conflict_proof_rejects_a_request_with_branch_findings(split_run_v3):
    from ctxcomp.engine import make_request
    run,original=split_run_v3
    run_model(run,generator=lambda request,model=None:part_response(request,original))
    base=make_request(run,'context_review'); result=read_json(run/state_file(run,'context_review'))
    split.verify_proof(run,base,result)
    proof=read_json(run/'parallel_review_proof.json'); record=proof['branches'][split.GLOBAL]
    request=read_json(run/record['request']); request['payload']['branch_reviews']={}
    write_json(run/record['request'],request); record['request_sha256']=digest(request)
    write_json(run/'parallel_review_proof.json',proof)
    with pytest.raises(ValueError,match='Parallel request inputs changed'): split.verify_proof(run,base,result)


def test_failed_branch_does_not_cancel_running_siblings(split_run):
    import time
    run,original=split_run; base=prepare(run,'context_review'); failed=threading.Event(); cancelled=[]
    def generate(request,branch,cancel):
        if branch==split.FAITH: failed.set(); raise RuntimeError('Synthetic disconnect')
        assert failed.wait(10); time.sleep(.2)  # Still running after its sibling failed.
        if cancel.is_set(): cancelled.append(branch)
        return authored_response(request,original)
    with pytest.raises(RuntimeError,match='disconnect'):
        split.execute(run,base,'first',generate,executor_id='test-provider-v1')
    assert not cancelled
    assert read_json(run/'review_branches/first'/(split.COMPLETE+'.receipt.json'))['status']=='VALIDATED'


def test_review_worker_setting_limits_concurrent_calls(split_run_v2,monkeypatch):
    run,original=split_run_v2; base=prepare(run,'context_review'); active=[0]; peak=[0]; lock=threading.Lock()
    def generate(request,branch,cancel):
        import time
        with lock: active[0]+=1; peak[0]=max(peak[0],active[0])
        time.sleep(.05)
        with lock: active[0]-=1
        return part_response(request,original)
    monkeypatch.setenv('CTXCOMP_REVIEW_WORKERS','1')
    split.execute(run,base,'serial',generate)
    assert peak[0]==1


@pytest.mark.parametrize('value,expected',[(None,5),('2',2),(' 9 ',5),('0',None),('two',None)])
def test_review_worker_setting(monkeypatch,value,expected):
    if value is None: monkeypatch.delenv('CTXCOMP_REVIEW_WORKERS',raising=False)
    else: monkeypatch.setenv('CTXCOMP_REVIEW_WORKERS',value)
    if expected is None:
        with pytest.raises(ValueError,match='whole number'): split.review_workers(5)
    else:
        assert split.review_workers(5)==expected


def test_completeness_parts_share_the_requirements_and_part_1_reviews_the_source_units(completeness_parts,split_run_v2):
    run,_=split_run_v2; base=prepare(run,'context_review'); p=base['payload']
    parts=split.completeness_parts(base,split.completeness_part_count(p))
    assert [i for part in parts for i in part['requirement_ids']]==[r['id'] for r in p['requirements']['items']]
    assert [part['source_units'] for part in parts]==[True,False,False]
    if 'scientific_context' in p:
        from ctxcomp import scientific
        assert sorted(i for part in parts for i in part['scientific_ids'])==sorted(scientific.item_ids(p['requirements']))
    requests=[split.completeness_request(base,part)['payload'] for part in parts]
    reviewed=lambda r: r['schema']['properties']['review']['properties']
    assert 'source_units' in reviewed(requests[0]) and 'retention' in reviewed(requests[0])
    assert all('source_units' not in reviewed(r) and 'retention' not in reviewed(r) for r in requests[1:])
    whole=split.request_for(base,split.COMPLETE)['payload']
    assert all(r['context']==whole['context'] and r['source_units']==whole['source_units'] for r in requests)
    assert 'you are part 2' in requests[1]['instructions'] and 'review_part.requirement_ids' in requests[1]['instructions']


def test_completeness_parts_run_together_and_publish_one_review(completeness_parts,split_run_v3):
    run,original=split_run_v3; completes=complete_branches(run)
    assert completes==[f'{split.COMPLETE}--part_{n}' for n in (1,2,3)]
    barrier=threading.Barrier(split.FAITH_PARTS+len(completes)+1)
    def generator(request,model=None):
        barrier.wait(timeout=5)  # Every faithfulness and completeness part and the conflict review run together.
        return part_response(request,original)
    assert run_model(run,generator=generator)['status']=='CONTEXT_READY'
    proof=read_json(run/'parallel_review_proof.json')
    assert proof['completeness_parts']==3 and set(completes)<=set(proof['branches'])
    review=read_json(run/state_file(run,'context_review'))['review']
    assert sorted(c['requirement_id'] for c in review['coverage'])==sorted(c['requirement_id'] for c in original['coverage'])
    assert verify_context(run)['status']=='VALID'


def test_rules_without_completeness_parts_keep_one_completeness_review(split_run_v2):
    run,original=split_run_v2
    assert complete_branches(run)==[split.COMPLETE]
    assert run_model(run,generator=lambda request,model=None:part_response(request,original))['status']=='CONTEXT_READY'
    proof=read_json(run/'parallel_review_proof.json')
    assert 'completeness_parts' not in proof and split.COMPLETE in proof['branches']
    assert verify_context(run)['status']=='VALID'
