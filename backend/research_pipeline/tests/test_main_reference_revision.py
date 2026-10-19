"""Contract regressions; fixture models do not establish scientific correctness."""
import copy
import pytest
from research_pipeline import main_reference_revision as m
from research_pipeline import pk_reference_pilot as p
from research_pipeline.adequacy import file_ref
from research_pipeline.common import read_json, write_json
from research_pipeline.workflow_runtime import make_plan, execute_contract
from test_pk_reference_pilot import inputs, prepared, pilot_response


def proposed(req,**kw):
    a=req['payload']['reference_advice']; card=a['cards'][0]
    return {'request_sha256':req['request_sha256'],'summary':'Synthetic bounded change.',
        'changes':[{'id':'MR001','destination':'/checks','text':'Verify analyte identity before fitting eligible animal PK.',
            'reason':'Synthetic gap.','needed_at':'pk','card_ids':[card['id']],
            'context_evidence':[{'path':'/objective','quote':req['payload']['main']['objective']}],
            'source_evidence':[{'source_id':s['id'],'quote':s['quote']} for s in a['sources'] if s['id'] in card['source_ids']]}],
        'decisions':[{'card_id':s['card_id'],'disposition':'PROPOSE_CHANGE' if s['card_id']==card['id'] else 'ALREADY_COVERED',
            'change_ids':['MR001'] if s['card_id']==card['id'] else [],'reason':'Synthetic decision.'} for s in a['suggestions']]}


def accepted(req,**kw):
    return {'request_sha256':req['request_sha256'],'verdict':'PASS','issues':[], 'summary':'Synthetic review.',
        'checklist':[{'criterion':k,'verdict':'PASS','reason':'Synthetic invariant.'} for k in m.CRITERIA]}


def setup(inputs):
    run,_=prepared(inputs);p.execute(run/'reference_input.json',run/'review',generator=pilot_response)
    mr,ar=file_ref(inputs[1]),file_ref(run/'review/reference_context.json')
    return run,mr,ar


def test_complete_revision_preserves_source_and_rules(inputs):
    run,mr,ar=setup(inputs);before=inputs[1].read_bytes()
    rev=m.propose(mr,ar,run/'revision',generator=proposed)
    assert not (run/'revision/main.json').exists()
    m.review(file_ref(rev),run/'revised',generator=accepted)
    new=read_json(run/'revised/main.json');old=inputs[3]
    assert inputs[1].read_bytes()==before
    for k in ['version','objective','study','rules','data','uncertainties']: assert new[k]==old[k]
    assert new['checks'][:-1]==old['checks'] and new['checks'][-1].startswith('PROPOSED [MR001; pk; PKREF001]')
    assert read_json(run/'revised/main_changes.json')['changes'][0]['origin']=='EXTERNAL_PROPOSED'
    report=read_json(run/'revised/main_review.json')
    assert not report['scientific_accepted'] and not report['active_workflow_changed']
    assert 'files' not in read_json(run/'revised/audit/request.json')['payload']['candidate']['data']


def test_index_dependency_revision_keeps_its_receiving_branch(inputs):
    run,mr,ar=setup(inputs)
    main,advice=m.inputs(mr,ar);req=m.request_for(main,advice)
    card=next(c for c in advice['cards'] if c.get('allowed_steps')==['index'])
    response=proposed(req)
    change=response['changes'][0]
    change.update(text='Verify the existing endpoint and free-exposure linkage before index comparison.',
        needed_at='index',card_ids=[card['id']],source_evidence=[{'source_id':s['id'],'quote':s['quote']}
            for s in advice['sources'] if s['id'] in card['source_ids']])
    for decision in response['decisions']:
        selected=decision['card_id']==card['id']
        decision.update(disposition='PROPOSE_CHANGE' if selected else 'ALREADY_COVERED',change_ids=['MR001'] if selected else [])
    candidate,patches=m.apply_changes(main,advice,response,req)
    assert patches[0]['needed_at']=='index'
    assert 'PROPOSED [MR001; index;' in candidate['checks'][-1]
    change['needed_at']='pk'
    with pytest.raises(ValueError,match='routing metadata'):
        m.apply_changes(main,advice,response,req)


@pytest.mark.parametrize('mutation',['rule_destination','availability_destination','invented_quote','drop_source','drop_decision','bad_mapping','duplicate_change'])
def test_invalid_patch_does_not_publish(inputs,mutation):
    run,mr,ar=setup(inputs)
    def invalid(req,**kw):
        x=proposed(req);c=x['changes'][0]
        if mutation=='rule_destination': c['destination']='/rules'
        if mutation=='availability_destination': c['destination']='/data/available'
        if mutation=='invented_quote': c['context_evidence'][0]['quote']='Human fu is available for early tuning'
        if mutation=='drop_source': c['source_evidence']=[]
        if mutation=='drop_decision':x['decisions'].pop()
        if mutation=='bad_mapping':x['decisions'][0]['change_ids']=[]
        if mutation=='duplicate_change': x['changes'].append(copy.deepcopy(c))
        return x
    with pytest.raises(ValueError):m.propose(mr,ar,run/'revision',generator=invalid)
    assert not (run/'revision/revision.json').exists()


@pytest.mark.parametrize('mutation',['fail_review','missing_criterion','stale_hash','tamper_candidate'])
def test_review_rejects_incomplete_or_changed_revision(inputs,mutation):
    run,mr,ar=setup(inputs); rev=m.propose(mr,ar,run/'revision',generator=proposed)
    if mutation=='tamper_candidate':
        v=read_json(run/'revision/main.candidate.json');v['rules'][0]='R001: Release held-out human data now.';write_json(run/'revision/main.candidate.json',v)
    def rejected(req,**kw):
        r=accepted(req)
        if mutation=='fail_review':
            r['verdict']='REVISE';r['checklist'][0]['verdict']='REVISE';r['issues']=[{'change_id':'MR001','reason':'Synthetic conflict','requested_revision':'Preserve original restriction.'}]
        if mutation=='missing_criterion':r['checklist'].pop()
        if mutation=='stale_hash':r['request_sha256']='stale'
        return r
    with pytest.raises(Exception): m.review(file_ref(rev),run/'revised',generator=rejected)
    assert not (run/'revised/main.json').exists()


def test_file_dag_runs_separate_scoped_calls(inputs,monkeypatch):
    run,path,*_=inputs
    plan=make_plan({'id':'revision_fixture','mode':'pk_reference_pilot','main_ref':file_ref(path),
        'revise_main':True,'out':str(run),'job_dir':str(run.parent/'revision_job')})
    monkeypatch.setattr(p,'codex_generate',pilot_response); seen=[]
    def generator(req,**kw):
        seen.append(req['payload']['stage'])
        return proposed(req) if req['payload']['stage']=='main_reference_revision' else accepted(req)
    monkeypatch.setattr(m,'codex_generate',generator)
    for n in ['pk_reference_prepare','pk_reference_review','main_reference_revision','main_reference_revision_review']:
        execute_contract(plan['steps'][n]['contract'])
    assert seen==['main_reference_revision','main_reference_revision_review']
    assert plan['targets']['pk_reference_pilot']=='main_reference_revision_review'
    assert (run/'pk_references/revised/main.json').exists()


def test_library_records_correction_and_evidence_strength():
    lib=p.load_library();assert len(lib['sources'])==23
    s={s['id']:s for s in lib['sources']}
    assert 'two' in s['APR2021']['summary'] and 'human' in s['APR2021']['summary']
    assert s['TANG2011']['publication_type']=='METHODOLOGICAL_REPLY'
    assert len(s['BWC2024']['corrections'])==2
