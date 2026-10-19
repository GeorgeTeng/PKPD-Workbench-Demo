"""Scoped citation recovery; model relevance judgments remain independently reviewed."""
import copy
import pytest
from ctxcomp.io import digest, read_json
from ctxcomp import supporting
from ctxcomp import supporting_agents as agents
from test_supporting_agents import request
from rule_versions import rules_1_30


def case():
    req = request(); p = req['payload']
    p['questions'] = [p['questions'][0]]
    p['questions'][0]['file_ids'] = ['F1']
    p['passages'] = [x for x in p['passages'] if x['file_id']=='F1']
    p['searches'][0]['files'] = [p['searches'][0]['files'][0]]
    p['searches'][0]['passage_ids'] = ['F1_0']
    p['citation_repair_policy'] = {'max_attempts_per_response':1}
    req['request_sha256'] = digest(p)
    return req


def answer(req, cid='F1_1', quote='binding'):
    return {'request_sha256':req['request_sha256'],'answers':[{
        'question_id':'MI001','status':'SEARCH_INCOMPLETE','statement':'Exposure basis remains uncertain.',
        'reason':'Available source is incomplete.','citations':[{'passage_id':cid,'quote':quote}]}]}


def approve(req):
    return {'request_sha256':req['request_sha256'],'decisions':[
        {'issue_id':x['issue_id'],'decision':'APPROVE','quote':'binding',
         'reason':'The supplied passage addresses the assigned exposure-basis question without resolving its uncertainty.'}
        for x in req['payload']['issues']]}


def test_same_file_extra_citation_requires_fresh_scoped_review(tmp_path):
    req=case(); calls=[]
    def generate(r,label):
        calls.append(r)
        return approve(r) if r['payload']['stage']=='attachment_citation_repair' else answer(r)
    result=agents.execute(req,tmp_path,generate)
    assert [r['payload']['stage'] for r in calls]==['attachment_evidence','attachment_citation_repair']
    assert len(calls[1]['payload']['issues'])==1
    assert [s['id'] for s in calls[1]['payload']['passages']]==['F1_1']
    assert result['answers']==answer(req)['answers']
    from ctxcomp.citation_repair import verify_proof
    grants=verify_proof(tmp_path/'proof.json',req,result)
    supporting.validate(req,result,scope_grants=grants)
    with pytest.raises(supporting.EvidenceCitationError): supporting.validate(req,result)


@pytest.mark.parametrize('kind',['unknown','cross_file','protected','stale','rejected','fabricated_quote'])
def test_recovery_cannot_bypass_source_boundaries(tmp_path,kind):
    req=case(); calls=[]
    if kind=='protected': req['payload']['searches'][0]['files'][0]['status']='PROTECTED_NOT_READ'
    req['request_sha256']=digest(req['payload'])
    def generate(r,label):
        calls.append(r)
        if r['payload']['stage']=='attachment_citation_repair':
            value=approve(r)
            if kind=='rejected': value['decisions'][0]['decision']='UNRESOLVED'
            if kind=='fabricated_quote': value['decisions'][0]['quote']='invented text'
            return value
        value=answer(r,cid={'unknown':'invented','cross_file':'F2_0'}.get(kind,'F1_1'))
        if kind=='stale': value['request_sha256']='stale'
        return value
    with pytest.raises(ValueError): agents.execute(req,tmp_path,generate)
    assert len(calls)==(2 if kind in {'rejected','fabricated_quote'} else 1)
    assert not (tmp_path/'response.json').exists()


def test_misquoted_source_gets_one_repair_and_unchanged_claim(tmp_path):
    req=case()
    def generate(r,label):
        return approve(r) if r['payload']['stage']=='attachment_citation_repair' else answer(r,'F1_0','BINDING')
    result=agents.execute(req,tmp_path,generate)
    assert result['answers'][0]['citations']==[{'passage_id':'F1_0','quote':'binding'}]
    assert result['answers'][0]['statement']==answer(req)['answers'][0]['statement']
    supporting.validate(req,result)


def test_tampered_repair_audit_is_rejected(tmp_path):
    req=case()
    result=agents.execute(req,tmp_path,lambda r,label:approve(r) if r['payload']['stage']=='attachment_citation_repair' else answer(r))
    from ctxcomp.citation_repair import verify_proof
    proof=read_json(tmp_path/'proof.json')
    path=tmp_path/proof['repairs'][0]['review_response']['path']
    path.write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError): verify_proof(tmp_path/'proof.json',req,result)


def test_no_literal_hit_is_not_an_access_denial():
    from ctxcomp.citation_repair import make_request, apply_response
    req=case(); req['payload']['searches'][0]['passage_ids']=[]
    req['payload']['searches'][0]['files'][0]['status']='NO_LITERAL_MATCH'
    req['request_sha256']=digest(req['payload'])
    candidate=answer(req)
    review=make_request(req,candidate)
    fixed,grants=apply_response(req,candidate,review,approve(review))
    supporting.validate(req,fixed,scope_grants=grants)
    with pytest.raises(supporting.EvidenceCitationError): supporting.validate(req,fixed)


def test_scope_grant_survives_multi_file_synthesis_with_audited_proof(tmp_path):
    req=request(); p=req['payload']
    p['searches'][0]['passage_ids'].remove('F1_1')
    p['citation_repair_policy']={'max_attempts_per_response':1}
    req['request_sha256']=digest(p)
    def generate(r,label):
        if r['payload']['stage']=='attachment_citation_repair': return approve(r)
        task=r['payload']['evidence_task']
        return answer(r,'F2_0' if task.get('file_id')=='F2' else 'F1_1')
    result=agents.execute(req,tmp_path,generate)
    from ctxcomp.citation_repair import verify_proof
    grants=verify_proof(tmp_path/'proof.json',req,result)
    assert grants==[{'question_id':'MI001','citation_id':'F1_1','quote':'binding'}]
    supporting.validate(req,result,scope_grants=grants)


def test_unresolved_review_reports_every_failed_citation(tmp_path):
    req=case()
    def generate(r,label):
        if r['payload']['stage']=='attachment_citation_repair':
            value=approve(r)
            for d in value['decisions']: d.update(decision='UNRESOLVED',reason='Study identity cannot be verified.')
            return value
        value=answer(r)
        value['answers'][0]['citations'].append({'passage_id':'F1_2','quote':'binding'})
        return value
    with pytest.raises(ValueError) as error: agents.execute(req,tmp_path,generate)
    details=error.value.validation_details
    assert details['attempts']==1 and details['issue_count']==2
    assert {x['citation_id'] for x in details['issues']}=={'F1_1','F1_2'}
    assert not (tmp_path/'response.json').exists()


@pytest.mark.usefixtures('rules_1_30')
def test_real_runner_binds_successful_correction_and_rechecks_its_audit(tmp_path):
    from test_runtime_rules import evidence_run
    from ctxcomp.providers import run_model
    from ctxcomp.engine import load_run
    run,_,_=evidence_run(tmp_path)
    calls=[]
    def generate(req,model=None):
        stage=req['payload']['stage']; calls.append(stage)
        if stage=='attachment_evidence':
            source=req['payload']['passages'][0]
            return answer(req,source['id'],'Incorrect paraphrased quotation.')
        if stage=='attachment_citation_repair':
            return {'request_sha256':req['request_sha256'],'decisions':[{
                'issue_id':x['issue_id'],'decision':'APPROVE','source_id':x['citation']['passage_id'],
                'quote':req['payload']['passages'][0]['text'],
                'reason':'Synthetic contract test, not an accuracy claim.'} for x in req['payload']['issues']]}
        raise RuntimeError('Stop before scientific extraction')
    with pytest.raises(RuntimeError,match='Stop before scientific'): run_model(run,generator=generate)
    assert calls==['attachment_evidence','attachment_citation_repair','requirements']
    bundle,state=load_run(run)
    assert state['accepted']['attachment_evidence']['citation_proof_sha256']
    supporting.view(run,bundle,state)
    (run/'audit/attachment_evidence_proof.json').unlink()
    with pytest.raises(ValueError,match='proof changed or is missing'): supporting.view(run,bundle,state)
    assert not (run/'handoff/main.json').exists()


def test_parallel_repairs_keep_plan_order_in_the_proof(tmp_path):
    import time
    from pathlib import Path
    req=request(); p=req['payload']
    for pid in ['F1_1','F2_1']: p['searches'][0]['passage_ids'].remove(pid)
    p['citation_repair_policy']={'max_attempts_per_response':1}
    req['request_sha256']=digest(p)
    def generate(r,label):
        if r['payload']['stage']=='attachment_citation_repair': return approve(r)
        fid=r['payload']['evidence_task'].get('file_id')
        if fid=='F1': time.sleep(.3)  # The second file's repair finishes first.
        return answer(r,'F2_1' if fid=='F2' else 'F1_1')
    one=agents.execute(req,tmp_path/'one',generate)
    assert agents.execute(req,tmp_path/'many',generate,workers=4)==one
    proof=read_json(tmp_path/'many/proof.json')
    assert proof==read_json(tmp_path/'one/proof.json')
    assert [Path(r['original_request']['path']).parent.name for r in proof['repairs']]==['file_0001','file_0002']


def moved_case():
    req=case(); p=req['payload']
    p['searches'][0]['passage_ids']=[x['id'] for x in p['passages']]
    p['citation_repair_policy']={'max_attempts_per_response':1,'alternative_sources':True}
    req['request_sha256']=digest(p)
    return req


def test_exact_quote_under_the_wrong_passage_moves_to_the_reviewed_source(tmp_path):
    req=moved_case(); reviews=[]
    def generate(r,label):
        if r['payload']['stage']!='attachment_citation_repair': return answer(r,'F1_1','binding 3 binding 3')
        reviews.append(r)
        return {'request_sha256':r['request_sha256'],'decisions':[{'issue_id':'CIT001','decision':'APPROVE',
            'source_id':'F1_3','quote':'binding 3 binding 3','reason':'Same table as the linked claim.'}]}
    result=agents.execute(req,tmp_path,generate)
    issue=reviews[0]['payload']['issues'][0]
    assert issue['alternative_source_ids']==['F1_3'] and {s['id'] for s in reviews[0]['payload']['passages']}=={'F1_1','F1_3'}
    assert result['answers'][0]['citations']==[{'passage_id':'F1_3','quote':'binding 3 binding 3'}]
    supporting.validate(req,result)  # In scope at its new source; no grant needed.
    from ctxcomp.citation_repair import verify_proof
    assert verify_proof(tmp_path/'proof.json',req,result)==[]


@pytest.mark.parametrize('decision',[{'source_id':'F1_4'},{'source_id':'F1_3','quote':'binding 3'}])
def test_a_move_needs_a_listed_source_and_the_original_quote(decision):
    from ctxcomp.citation_repair import make_request, apply_response
    req=moved_case(); candidate=answer(req,'F1_1','binding 3 binding 3')
    review=make_request(req,candidate)
    reply={'request_sha256':review['request_sha256'],'decisions':[{'issue_id':'CIT001','decision':'APPROVE',
        'source_id':'F1_1','quote':'binding 3 binding 3','reason':'Synthetic.'} | decision]}
    with pytest.raises(ValueError):
        apply_response(req,candidate,review,reply)


def test_runs_frozen_before_alternative_sources_keep_their_review_request():
    from ctxcomp.citation_repair import make_request, SCHEMA
    req=case(); review=make_request(req,answer(req,'F1_1','binding 3 binding 3'))
    assert review['payload']['schema']==SCHEMA and 'alternative_source_ids' not in review['payload']['issues'][0]
    assert 'alternative_source_ids' not in review['payload']['instructions']


def test_spreadsheet_and_csv_passages_are_named_by_row(tmp_path):
    """Compression rules 1.23.0: a model citing 'row 9' of a sheet writes the passage that holds row 9."""
    import io, zipfile
    from openpyxl import Workbook
    from ctxcomp.engine import init_run, prepare, accept
    from test_runtime_rules import question
    book=Workbook(); first=book.active; first.title='Notes'; first['A1']='cover'
    sheet=book.create_sheet('Mouse'); sheet['A3']='Animal sample header'; sheet['A9']='n=4 animal per time'
    data=io.BytesIO(); book.save(data)
    archive=tmp_path/'input.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('proposal.md','Study animal PK; the sample size is not stated.')
        z.writestr('tables.xlsx',data.getvalue())
        z.writestr('samples.csv','animal,time\nA1,2\n')
    run=tmp_path/'run'
    init_run(run,package=archive,proposal_entry='proposal.md')
    plan=prepare(run,'attachment_plan')
    ids={f['name']:f['id'] for f in plan['payload']['files']}
    q=question(None); q['file_ids']=[ids['tables.xlsx'],ids['samples.csv']]
    accept(run,'attachment_plan',{'request_sha256':plan['request_sha256'],'questions':[q]})
    p=prepare(run,'attachment_evidence')['payload']
    by_id={x['id']:x['locator'] for x in p['passages']}
    x,c=ids['tables.xlsx'],ids['samples.csv']
    assert by_id[f'{x}_S02R000009']=='sheet Mouse row 9' and by_id[f'{x}_S02R000003']=='sheet Mouse row 3'
    assert by_id[f'{c}_R000002']=='row 2'
    assert not any('_E' in pid for pid in by_id)


def test_runs_frozen_before_row_ids_keep_record_index_ids():
    from ctxcomp.supporting import records, row_passage_ids
    assert not row_passage_ids({'processing_rules':{'version':'1.22.0'}})
    assert row_passage_ids({'processing_rules':{'attachment_passage_ids':{'format':'SHEET_ROW'}}})
    snapshot={'kind':'xlsx','sheets':[{'name':'Mouse','cells':[{'cell':'A9','row':9,'column':1,'value':'n=4'}]}]}
    assert [r[2] for r in records(snapshot)]==['S01R000009']


@pytest.mark.parametrize('excerpts',[True,False])
def test_a_synthesis_may_cite_an_excerpt_of_an_approved_quote(tmp_path,excerpts):
    """Compression rules 1.28.0 (approved_excerpts): the 2026-10-09 PMB synthesis shortened an approved quote."""
    req=request(); p=req['payload']
    p['searches'][0]['passage_ids'].remove('F1_1')
    p['citation_repair_policy']={'max_attempts_per_response':1,**({'approved_excerpts':True} if excerpts else {})}
    req['request_sha256']=digest(p)
    full='binding 1 binding 1'; part='binding 1'
    def generate(r,label):
        if r['payload']['stage']=='attachment_citation_repair':
            return {'request_sha256':r['request_sha256'],'decisions':[{'issue_id':x['issue_id'],'decision':'APPROVE',
                'quote':full,'reason':'The passage addresses the exposure-basis question.'} for x in r['payload']['issues']]}
        task=r['payload']['evidence_task']
        if task.get('file_id')=='F2': return answer(r,'F2_0','binding 0')
        return answer(r,'F1_1',full if task.get('file_id')=='F1' else part)  # The synthesis keeps an excerpt.
    if not excerpts:
        with pytest.raises(supporting.EvidenceCitationError): agents.execute(req,tmp_path,generate)
        return
    result=agents.execute(req,tmp_path,generate)
    from ctxcomp.citation_repair import verify_proof
    grants=verify_proof(tmp_path/'proof.json',req,result)
    assert grants==[{'question_id':'MI001','citation_id':'F1_1','quote':full}]
    supporting.validate(req,result,scope_grants=grants)
    # The approval covers text inside the approved quote only, for that question and source.
    other=copy.deepcopy(result); other['answers'][0]['citations']=[{'passage_id':'F1_1','quote':'binding 1 binding 1 binding'}]
    with pytest.raises(supporting.EvidenceCitationError): supporting.validate(req,other,scope_grants=grants)
