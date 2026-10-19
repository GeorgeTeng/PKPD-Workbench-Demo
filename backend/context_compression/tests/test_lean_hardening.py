import copy
import pytest
from ctxcomp import lean_compression as lean
from ctxcomp.engine import prepare, load_run, accept, init_run
from ctxcomp.providers import run_model
from ctxcomp.io import read_json, digest
from test_lean_compression import setup, candidate, review, patch

def legacy_target_setup(tmp_path):
    """Collection typo normalization remains a historical-profile behavior."""
    from unittest.mock import patch as mock_patch
    original=lean.profile
    def frozen(identifier):
        value=original(identifier)
        if value:
            value.pop('review_target_contract',None);value['version']='1.11'
        return value
    with mock_patch.object(lean,'profile',side_effect=frozen):return setup(tmp_path)


def gap_candidate(req):
    result=candidate(req)
    for rid in ('MI003','MI004'):
        result['missing_information']['items'].append({'id':rid,'field':'Horse binding or dose basis',
            'status':'NOT_FOUND','needed_at':'index','impact':'Horse translation limitation',
            'why_it_matters':'Needed before horse translation','clarification':'Clarify from source','resolution_status':'OPEN'})
        result['evidence'].append({'id':rid,'status':'NOT_FOUND','citations':[],'reason':'Synthetic gap'})
        i=len(result['context']['uncertainties']);result['context']['uncertainties'].append('['+rid+']')
        result['evidence'].append({'id':'/uncertainties/'+str(i),'status':'REFERENCE','citations':[],'reason':'Gap link'})
    return result


def gap_review(req):
    result=review(req,'REVISE')
    result['review']['fixes']=[{'id':'FIX001','target':'/missing_information/items',
                              'reason':'Change needed_at for MI003 and MI004 only.','citations':[]}]
    for verdict in result['review']['records']:
        if verdict['id'] in ('MI003','MI004'):verdict['faithfulness']='ALTERED'
    return result


@pytest.mark.parametrize('saved_review',[False,True])
def test_collection_review_normalization_drives_one_precise_patch_and_recheck(tmp_path,saved_review):
    run=legacy_target_setup(tmp_path);calls=[]
    if saved_review:
        accept(run,'context',gap_candidate(prepare(run,'context')))
        assert accept(run,'context_review',gap_review(prepare(run,'context_review')))['status']=='REVISE'
    def model(req,**kwargs):
        p=req['payload'];calls.append(p.get('operation',p['stage']))
        if p['stage']=='context' and 'operation' not in p:return gap_candidate(req)
        if p.get('operation')=='TARGETED_PATCH':
            assert {f['target'] for f in p['review']['fixes']}=={'MI003','MI004'}
            response=patch(req);response.update(overview=[],evidence=[],replace_gaps=[])
            for record in p['candidate']['missing_information']['items']:
                replacement=copy.deepcopy(record);replacement['needed_at']='pk'
                response['replace_gaps'].append({'record':replacement,'fix_ids':['FIX001__'+record['id']]})
                response['evidence'].append(next(e for e in p['candidate']['evidence'] if e['id']==record['id']))
            return response
        return review(req) if 'TARGETED_PATCH' in calls else gap_review(req)
    assert run_model(run,generator=model)['status']=='CONTEXT_READY'
    assert calls==(['TARGETED_PATCH','context_review'] if saved_review else ['context','context_review','TARGETED_PATCH','context_review'])
    proof=read_json(run/'lean/patch_proof.json')
    assert proof['review']['review']['decision']=='REVISE'
    assert {f['target'] for f in proof['review']['review']['fixes']}=={'MI003','MI004'}
    audit=read_json(next((run/'audit/review_target_normalization').glob('*.json')))
    assert audit['raw_response']['review']['fixes'][0]['target']=='/missing_information/items'


@pytest.mark.parametrize('reason',['Change MI003 only','Change MI003, MI004 and MI999','Fix these gaps'])
def test_collection_fix_rejects_nonexact_target_scope(tmp_path,reason):
    run=legacy_target_setup(tmp_path);accept(run,'context',gap_candidate(prepare(run,'context')))
    raw=gap_review(prepare(run,'context_review'));raw['review']['fixes'][0]['reason']=reason
    with pytest.raises(ValueError,match='Ambiguous'):accept(run,'context_review',raw)
    assert not (run/'lean/last_review.json').exists()


@pytest.mark.parametrize('reason,accepted',[
    ('Fix SC003–SC006; keep MI001 in its gap.',True),
    ('Fix SC003-SC006.',True),
    ('Fix SC003–SC005.',False),
    ('Fix SC003–SC007.',False),
    ('Fix SC006–SC003.',False),
    ('Fix SC003–MI006.',False)])
def test_science_collection_range_requires_exact_failed_scope(tmp_path,reason,accepted):
    ids=['SC003','SC004','SC005','SC006']
    candidate={'scientific_context':{'items':[{'id':rid} for rid in ids]},'missing_information':{'items':[{'id':'MI001'}]}}
    raw={'review':{'decision':'REVISE','records':[{'id':rid,'faithfulness':'ALTERED','completeness':'PRESERVED'} for rid in ids],
                   'fixes':[{'id':'FIX001','target':'scientific_context.items','reason':reason,'citations':[]}]}}
    original=copy.deepcopy(raw)
    if not accepted:
        with pytest.raises(ValueError,match='Ambiguous'):lean.normalize_review_targets(tmp_path,raw,candidate)
    else:
        normalized=lean.normalize_review_targets(tmp_path,raw,candidate)
        assert {f['target'] for f in normalized['review']['fixes']}==set(ids)
        assert normalized['review']['decision']==raw['review']['decision']
        assert normalized['review']['records']==raw['review']['records']
        assert all(f['reason']==reason for f in normalized['review']['fixes'])
    assert raw==original


def test_raw_science_range_review_drives_precise_edge_patch_and_recheck(tmp_path):
    run=legacy_target_setup(tmp_path);calls=[];initial=[]
    def model(req,**kwargs):
        p=req['payload'];calls.append(p.get('operation',p['stage']))
        if p['stage']=='context' and 'operation' not in p:
            result=candidate(req);second=copy.deepcopy(result['scientific_context']['items'][0])
            u=p['source_units'][1];second.update(id='F002',statement=u['text'])
            result['scientific_context']['items'].append(second)
            for item,other in zip(result['scientific_context']['items'],('F002','F001')):
                item['science']['relations']=[{'type':'USES','target_id':other}]
            result['evidence'].append({'id':'F002','status':'EXPLICIT','reason':'Synthetic source fact',
                'citations':[{'source_id':u['source_id'],'unit_id':u['id'],'quote':u['text']}]})
            initial.extend(copy.deepcopy(result['scientific_context']['items']));return result
        if p.get('operation')=='TARGETED_PATCH':
            assert {f['target'] for f in p['review']['fixes']}=={'F001','F002'}
            response=patch(req);response.update(overview=[],replace_items=[],evidence=[])
            for item in p['candidate']['scientific_context']['items']:
                fixed=copy.deepcopy(item);fixed['science']['relations']=[]
                response['replace_items'].append({'record':fixed,'fix_ids':['FIX001__'+item['id']]})
                response['evidence'].append(next(e for e in p['candidate']['evidence'] if e['id']==item['id']))
            return response
        result=review(req)
        if 'TARGETED_PATCH' not in calls:
            result['review']['decision']='REVISE'
            for record in result['review']['records']:
                if record['id'] in ('F001','F002'):record['faithfulness']='ALTERED'
            result['review']['fixes']=[{'id':'FIX001','target':'scientific_context.items',
                                        'reason':'Remove wrong USES edges from F001–F002.','citations':[]}]
        return result
    assert run_model(run,generator=model)['status']=='CONTEXT_READY'
    assert calls==['context','context_review','TARGETED_PATCH','context_review']
    published=read_json(run/'handoff/main.json')['scientific_context']['items']
    assert [x['statement'] for x in published]==[x['statement'] for x in initial]
    assert all(x['science']['relations']==[] for x in published)
    proof=read_json(run/'lean/patch_proof.json')
    assert {f['target'] for f in proof['review']['review']['fixes']}=={'F001','F002'}


def test_prefix_normalization_preserves_raw_and_exact_candidate(tmp_path):
    run=setup(tmp_path);req=prepare(run,'context');raw=candidate(req)
    original=copy.deepcopy(raw);raw['evidence'][0]['id']='/context'+raw['evidence'][0]['id']
    retained=copy.deepcopy(raw)
    assert accept(run,'context',raw)['status']=='ACCEPTED'
    assert raw==retained
    _,state=load_run(run)
    assert read_json(run/state['accepted']['context']['file'])==original
    audit=read_json(next((run/'audit/evidence_pointer_normalization').glob('*.json')))
    assert audit['raw_response']==retained and audit['normalized_response_sha256']==digest(original)
    assert read_json(next((run/'submissions').glob('*.json')))==retained
    assert prepare(run,'context_review')['payload']['candidate']==lean.content(original)


@pytest.mark.parametrize('fault',['unknown','collision'])
def test_prefix_normalization_rejects_ambiguous_or_unknown_pointers(tmp_path,fault):
    run=setup(tmp_path);raw=candidate(prepare(run,'context'))
    extra=copy.deepcopy(raw['evidence'][0])
    extra['id']='/context/objective' if fault=='collision' else '/context/unknown'
    raw['evidence'].append(extra)
    with pytest.raises(ValueError,match='collision|Unknown'):accept(run,'context',raw)
    assert not load_run(run)[1]['accepted']


def test_revision_feedback_reaches_generator_but_not_independent_reviewer(tmp_path):
    proposal=tmp_path/'source.txt';proposal.write_text('Source body',encoding='utf-8')
    revision={'guidance':'Keep the source conditions','prior_review':{
        'terminal_review':{'decision':'REVISE','critical_errors':['Unsupported search history']},
        'previous_horse_phase_review':{'decision':'REVISE','critical_errors':['Horse needed before index']}}}
    run=tmp_path/'run';init_run(run,proposal,compression_profile=lean.ID,revision=revision)
    req=prepare(run,'context')
    assert req['payload']['revision_feedback']==revision
    assert 'NON-EVIDENCE' in req['payload']['revision_policy']
    # A request-only unit test can compare stage contracts without fabricating source facts.
    from unittest.mock import patch as mock_patch
    response=candidate(req)
    with mock_patch('ctxcomp.engine.accepted_response',return_value=response),mock_patch.object(lean,'validate_candidate'):
        bundle,state=load_run(run);review_req=lean.request(run,bundle,state,'context_review')
    assert 'revision_feedback' not in review_req['payload'] and 'revision_policy' not in review_req['payload']
    old=copy.deepcopy(bundle);old['compression_profile'].pop('revision_policy');old['compression_profile']['version']='1.0'
    assert 'revision_feedback' not in lean.request(run,old,state,'context')['payload']


def test_gap_classification_contract_reaches_both_calls_and_is_frozen(tmp_path):
    run=setup(tmp_path);bundle,state=load_run(run)
    assert bundle['compression_profile']['version']=='1.14'
    for key in ('generation_instructions','review_instructions'):
        instructions=bundle['compression_profile'][key]
        assert 'SEARCH_INCOMPLETE requires the source to report an actual incomplete search' in instructions
        assert 'Use DEFERRED for a required later assessment' in instructions
        assert 'human_pk is reserved for human translation, never horse' in instructions
        assert 'preserve unique counts, sample sizes and file roles' in instructions
        assert 'gap condition has one full-text owner' in instructions
        assert 'shared topic alone is not duplication' in instructions
        assert 'USES means consumer or method -> adopted input or evidence' in instructions
        assert 'TESTS means test, evidence or design -> the tested claim or model' in instructions
        assert 'including unchanged edges after a patch' in instructions
        assert 'preserving all source-bound prose, conditions and evidence' in instructions
    # Runtime constants cannot silently change either instruction in an existing frozen bundle.
    from unittest.mock import patch as mock_patch
    with mock_patch.object(lean,'GAP_CLASSIFICATION','UNFROZEN REPLACEMENT'):
        assert lean.request(run,bundle,state,'context')['payload']['instructions'].endswith(bundle['compression_profile']['generation_instructions'])


def test_resume_budget_keeps_prior_execution_and_stops_at_cumulative_limit(tmp_path):
    run=setup(tmp_path);lean.record_prior_elapsed(run,1500,'Measured first invocation')
    with pytest.raises(ValueError,match='already recorded'):lean.record_prior_elapsed(run,0,'reset')
    calls=[]
    with pytest.raises(ValueError,match='budget exhausted'):
        run_model(run,generator=lambda req,**kwargs:calls.append(req))
    assert calls==[] and read_json(run/'lean/execution_budget.json')['elapsed_seconds']>=1500


def test_successful_patch_archives_resolved_stop_without_losing_review(tmp_path):
    run=setup(tmp_path);reviews=[]
    def model(req,**kwargs):
        p=req['payload']
        if p.get('operation')=='TARGETED_PATCH': return patch(req)
        if p['stage']=='context': return candidate(req)
        reviews.append(req)
        return review(req,'REVISE' if len(reviews)==1 else 'PASS')
    assert run_model(run,generator=model)['status']=='CONTEXT_READY'
    assert not (run/'stopped.json').exists()
    archived=list((run/'audit/resolved_stops').glob('*.json'))
    assert len(archived)==1 and read_json(archived[0])['status']=='REVISE'
    assert read_json(run/'lean/last_review.json')['review']['decision']=='PASS'


def test_unrelated_overview_change_cannot_cite_another_targets_fix(tmp_path):
    run=setup(tmp_path);bundle,_=load_run(run);base=lean.content(candidate(prepare(run,'context')))
    findings={'fixes':[{'id':'FIX1','target':'/objective','reason':'Overview change','citations':[]}]}
    req=lean.patch_request(bundle,base,findings,run);response=patch(req)
    response['overview'][0].update(path='/study/drug',value='Compound Z')
    response['evidence'][0]['id']='/study/drug'
    with pytest.raises(ValueError,match='unrelated'):lean.apply_patch_response(bundle,base,findings,req,response)


@pytest.mark.parametrize('unrelated_statement',[False,True])
def test_only_reference_updates_can_follow_another_record_removal(tmp_path,unrelated_statement):
    run=setup(tmp_path);bundle,_=load_run(run);base=lean.content(candidate(prepare(run,'context')))
    method=copy.deepcopy(base['scientific_context']['items'][0]);method['id']='M001'
    method['statement']='Only intravenous administration.';method['science']['role']='METHOD'
    base['scientific_context']['items'].append(method)
    base['scientific_context']['items'][0]['science']['method_refs']=['M001']
    ev=copy.deepcopy(base['evidence'][-1]);ev['id']='M001';base['evidence'].append(ev)
    findings={'fixes':[{'id':'FIX1','target':'M001','reason':'Remove incorrect method','citations':[]}]}
    req=lean.patch_request(bundle,base,findings,run);response=patch(req)
    replacement=copy.deepcopy(base['scientific_context']['items'][0]);replacement['science']['method_refs']=[]
    if unrelated_statement: replacement['statement']='Unrelated statement change'
    response.update(overview=[],remove_items=[{'id':'M001','fix_ids':['FIX1']}],
        replace_items=[{'record':replacement,'fix_ids':['FIX1']}],evidence=[base['evidence'][-2]])
    if unrelated_statement:
        with pytest.raises(ValueError,match='unrelated'):lean.apply_patch_response(bundle,base,findings,req,response)
    else:
        fixed=lean.apply_patch_response(bundle,base,findings,req,response)
        assert [x['id'] for x in fixed['scientific_context']['items']]==['F001']
        assert fixed['scientific_context']['items'][0]['science']['method_refs']==[]
        assert fixed['scientific_context']['items'][0]['statement']==base['scientific_context']['items'][0]['statement']
