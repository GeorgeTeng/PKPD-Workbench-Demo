"""Request transport and evidence gates; not measurements of LLM accuracy."""
from pathlib import Path
import copy
import json
import subprocess
import zipfile
import pytest

from ctxcomp.engine import init_run, prepare, accept, load_run, verify_context
from ctxcomp.io import read_json, write_json, digest, leaves
from ctxcomp.rules import load_rules
from ctxcomp import supporting, split_review
from test_retention import reference_run, replay_until, demo


def test_rule_pack_is_frozen_with_run_inputs(tmp_path):
    from ctxcomp.io import read_json
    proposal = tmp_path / 'proposal.txt'
    proposal.write_text('Study animal PK and predict human exposure.', encoding='utf-8')
    run = tmp_path / 'run'
    init_run(run, proposal)
    bundle = read_json(run / 'inputs.json')
    assert 'processing_rules' in bundle
    rules = bundle['processing_rules']['rules']
    assert {r['id'] for r in rules} == {f'CC{i:03}' for i in range(1, 20) if i not in {10, 13, 14, 18}}
    assert [r['id'] for r in rules] == [rid for group in bundle['processing_rules']['logical_order']['groups'] for rid in group['rules']]
    assert bundle['processing_rules']['governance']['rules'][0]['id']=='G001'
    cc005 = next(r for r in rules if r['id'] == 'CC005')
    assert len(cc005['details']['preserve']) == 13


def question(fid, *, stage='pk', identifier='MI001', terms=None):
    return {'id': identifier, 'field': 'sampling identity', 'question': 'Are repeated samples from one animal?',
            'importance': 'MATERIAL', 'importance_reason': 'Defines the statistical experimental unit.',
            'needed_at': stage, 'downstream_impact': 'Cannot choose individual random effects without subject identity.',
            'requested_information': 'Confirm the animal identity across sample times.',
            'file_ids': [fid] if fid else [], 'search_terms': terms or ['animal', 'sample']}


def evidence_run(tmp_path, *, protected=False):
    archive = tmp_path / 'input.zip'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('proposal.md', 'Study animal PK. Use plasma concentration data; animal identity is not stated.')
        z.writestr('sampling.txt', 'Repeated samples use the same animal ID. Concentration is total plasma drug.')
    run = tmp_path / 'run'
    init_run(run, package=archive, proposal_entry='proposal.md',
             reference_only=['sampling.txt'] if protected else [])
    plan = prepare(run, 'attachment_plan')
    fid = next(f['id'] for f in plan['payload']['files'] if f['name']=='sampling.txt')
    q = question(fid)
    accept(run, 'attachment_plan', {'request_sha256': plan['request_sha256'], 'questions':[q]})
    return run, q, prepare(run, 'attachment_evidence')


def test_every_invocation_receives_full_scoped_rules_and_explicit_contract(tmp_path, reference_run):
    run = tmp_path / 'run'
    replay_until(run, reference_run, 'context')
    requests = [prepare(run, s) for s in ('attachment_plan','attachment_evidence','requirements','requirements_review','context','context_review')]
    base = requests[-1]
    requests += [split_review.request_for(base, b, prior={}) for b in split_review.BRANCHES]
    master = load_rules()
    for request in requests:
        p=request['payload']; stage=p['stage']
        expected=[r for r in master['rules'] if 'all' in r['agents'] or stage in r['agents']]
        assert p['processing_rules']['rules'] == expected
        for profile_name in ('scientific_extraction', 'pk_binding_knowledge'):
            profile = master[profile_name]
            if stage in profile['scope']:
                assert p['processing_rules'][profile_name] == profile
            else:
                assert profile_name not in p['processing_rules']
        assert p['governance'] == master['governance']
        assert [r['id'] for r in p['governance']['rules']] == [f'G{i:03}' for i in range(1, 9)]
        assert p['instructions'].startswith('Apply governance rule G001 first')
        assert len(next(r for r in p['processing_rules']['rules'] if r['id']=='CC005')['details']['preserve'])==13
        assert p['agent_contract']['task'] == master['agent_contracts']['agents'][stage]['task']
        assert p['agent_contract']['response_contract'] and p['agent_contract']['self_check']
        assert p['processing_rules_sha256'] == digest(p['processing_rules'])
        assert request['request_sha256'] == digest(p)


@pytest.mark.parametrize('stage', ['requirements', 'context', *split_review.BRANCHES])
def test_cli_transport_contains_actual_inline_rules(tmp_path, reference_run, monkeypatch, stage):
    from ctxcomp import providers
    run=tmp_path/'run'; replay_until(run,reference_run,'context')
    request=(split_review.request_for(prepare(run,'context_review'),stage)
             if stage in split_review.BRANCHES else prepare(run,stage))
    def fake_run(command, prompt, cwd, diagnostics_dir=None, **kwargs):
        assert json.loads(prompt[prompt.index('{'):]) == providers.model_view.view(request)
        assert 'logic_scope_and_exceptions' in prompt
        assert [r['id'] for r in request['payload']['governance']['rules']] == [f'G{i:03}' for i in range(1, 9)]
        assert 'G008' in request['payload']['instructions']
        profile=request['payload']['processing_rules']['pk_binding_knowledge']
        assert profile == load_rules()['pk_binding_knowledge']
        assert profile['version'] == '2.0.0'
        assert len(profile['supporting_metadata'].split()) <= 25
        output=Path(command[command.index('--output-last-message')+1])
        write_json(output, {'request_sha256':request['request_sha256']})
        return subprocess.CompletedProcess(command,0,'','')
    monkeypatch.setattr(providers.shutil,'which',lambda _: 'mock-codex')
    monkeypatch.setattr(providers,'monitored_run',fake_run)
    assert providers.codex_generate(request)['request_sha256']==request['request_sha256']


def test_glossary_update_applies_to_new_runs_without_rewriting_existing_reviews(tmp_path, reference_run, monkeypatch):
    from ctxcomp import engine
    from attachment_fixture import accept_empty_search
    existing = tmp_path/'existing'
    replay_until(existing, reference_run, 'context')
    frozen = prepare(existing, 'context_review')
    revised = copy.deepcopy(load_rules())
    revised['pk_binding_knowledge']['version'] = 'test-future-version'
    revised['pk_binding_knowledge']['use'] += ' Test future guidance.'
    monkeypatch.setattr(engine, 'load_rules', lambda: copy.deepcopy(revised))

    assert prepare(existing, 'context_review') == frozen
    for branch in split_review.BRANCHES:
        request = split_review.request_for(frozen, branch)
        assert request['payload']['processing_rules']['pk_binding_knowledge']['version'] == '2.0.0'

    proposal = tmp_path/'proposal.txt'
    proposal.write_text('Predict human PK from animal exposure.', encoding='utf-8')
    fresh = tmp_path/'fresh'
    init_run(fresh, proposal)
    accept_empty_search(fresh)
    request = prepare(fresh, 'requirements')
    assert request['payload']['processing_rules']['pk_binding_knowledge'] == revised['pk_binding_knowledge']
    assert read_json(fresh/'audit/processing_rules.json')['pk_binding_knowledge'] == revised['pk_binding_knowledge']


def test_attachment_search_adds_only_cited_evidence_with_provenance(tmp_path):
    run,q,req=evidence_run(tmp_path)
    passage=req['payload']['passages'][0]
    response={'request_sha256':req['request_sha256'],'answers':[{'question_id':q['id'],'status':'FOUND',
        'statement':'The supporting file describes repeated samples from the same animal.', 'reason':'Exact source statement.',
        'citations':[{'passage_id':passage['id'],'quote':'Repeated samples use the same animal ID.'}]}]}
    accept(run,'attachment_evidence',response)
    payload=prepare(run,'requirements')['payload']
    support=[s for s in payload['sources'] if s['role']=='SUPPORTING_EVIDENCE']
    assert len(support)==1 and support[0]['file_id']==q['file_ids'][0]
    assert support[0]['locator'] and support[0]['original_sha256']
    assert not payload['missing_information_warnings']
    assert 'same animal ID' not in json.dumps(prepare(run,'attachment_plan')['payload']['files'])


@pytest.mark.parametrize('mutation',['fabricated_quote','wrong_passage','omitted_answer','found_without_citation'])
def test_bad_attachment_response_is_rejected(tmp_path,mutation):
    run,q,req=evidence_run(tmp_path)
    answer={'question_id':q['id'],'status':'FOUND','statement':'Authored test','reason':'Fixture',
            'citations':[{'passage_id':req['payload']['passages'][0]['id'],'quote':'Repeated samples'}]}
    if mutation=='fabricated_quote': answer['citations'][0]['quote']='Nine animals were sampled.'
    if mutation=='wrong_passage': answer['citations'][0]['passage_id']='UNKNOWN'
    if mutation=='found_without_citation': answer['citations']=[]
    with pytest.raises(ValueError):
        accept(run,'attachment_evidence',{'request_sha256':req['request_sha256'],
            'answers':[] if mutation=='omitted_answer' else [answer]})
    assert not (run/'handoff/main.json').exists()


def test_protected_attachment_is_not_sent_and_material_warning_reaches_review_inputs(tmp_path):
    run,q,req=evidence_run(tmp_path,protected=True)
    assert req['payload']['passages']==[]
    assert req['payload']['searches'][0]['files'][0]['status']=='PROTECTED_NOT_READ'
    accept(run,'attachment_evidence',{'request_sha256':req['request_sha256'],'answers':[
        {'question_id':q['id'],'status':'DEFERRED','statement':'Protected evidence not read.',
         'reason':'Evidence is not authorized for this stage.','citations':[]}]})
    payload=prepare(run,'requirements')['payload']
    warning=payload['missing_information_warnings'][0]
    assert warning['id']=='MI001' and warning['requested_information']
    assert warning['search']['files'][0]['status']=='PROTECTED_NOT_READ'
    assert 'same animal ID' not in json.dumps(payload)
    report=read_json(run/'audit/missing_information_review.json')
    # Models get a search summary; the audit keeps the full search log.
    assert [{k:v for k,v in w.items() if k!='search'} for w in report['warnings']]==[{k:v for k,v in warning.items() if k!='search'}]
    assert report['warnings'][0]['search']['files']==[{**f,'locations':[]} for f in
        [{k:v for k,v in f.items() if k!='matched_locations'} for f in warning['search']['files']]]


def test_missing_warning_blocks_context_acceptance_but_retained_warning_can_be_reviewed(tmp_path):
    run,q,req=evidence_run(tmp_path,protected=True)
    accept(run,'attachment_evidence',{'request_sha256':req['request_sha256'],'answers':[
        {'question_id':'MI001','status':'DEFERRED','statement':'Not read.','reason':'Protected.','citations':[]}]})
    payload=prepare(run,'requirements')['payload']; units=payload['source_units']
    requirements=demo.fixture_requirements({'/objective':'Study animal PK.'},units,units[0]['source_id'])
    accept(run,'requirements',{'request_sha256':prepare(run,'requirements')['request_sha256'],'requirements':requirements})
    accept(run,'requirements_review',{'request_sha256':prepare(run,'requirements_review')['request_sha256'],
        'review':demo.fixture_requirements_review(requirements,units)})
    context={'version':'3.0','objective':'Study animal PK.',
        'study':{k:'NOT_FOUND' for k in ('drug','regimen','population','system','measurements','methods')},
        'data':{'available':[],'required':[]},'rules':[],'checks':[],'uncertainties':[]}
    evidence=[{'path':p,'status':'EXPLICIT' if p=='/objective' else 'NOT_FOUND',
        'source_id':units[0]['source_id'] if p=='/objective' else '',
        'quote':'Study animal PK.' if p=='/objective' else '', 'reason':'Authored test.'} for p,v in leaves(context) if p!='/version']
    response={'request_sha256':prepare(run,'context')['request_sha256'],'context':context,'evidence':evidence}
    with pytest.raises(ValueError,match='CC019'): accept(run,'context',response)
    context['uncertainties']=['PROPOSED [MI001] Confirm sampling identity before pk: random effects require experimental-unit identity.']
    evidence.append({'path':'/uncertainties/0','status':'PROPOSED','source_id':'','quote':'',
        'reason':'CC019 material warning from the bounded evidence search.'})
    accept(run,'context',response)
    base=prepare(run,'context_review')
    for branch in split_review.BRANCHES:
        child=split_review.request_for(base,branch,prior={})
        assert child['payload']['missing_information_warnings'][0]['id']=='MI001'
        assert '[MI001]' in child['payload']['context']['uncertainties'][0]
    assert not (run/'handoff/main.json').exists()  # No semantic reviews have passed yet.


def test_frozen_rules_cannot_change_silently(tmp_path,monkeypatch):
    from ctxcomp import engine
    proposal=tmp_path/'proposal.txt'; proposal.write_text('Study animal PK.',encoding='utf-8')
    run=tmp_path/'run'; init_run(run,proposal)
    original=prepare(run,'attachment_plan')
    monkeypatch.setattr(engine,'load_rules',lambda: {'rules':[]})
    assert prepare(run,'attachment_plan')==original
    write_json(run/'audit/processing_rules.json',{'rules':[]})
    with pytest.raises(ValueError,match='Frozen processing rules changed'): load_run(run)


def test_legacy_run_requires_explicit_new_run(tmp_path):
    proposal=tmp_path/'proposal.txt'; proposal.write_text('Study animal PK.',encoding='utf-8')
    run=tmp_path/'run'; init_run(run,proposal)
    bundle,state=load_run(run); bundle.pop('processing_rules'); state['inputs_sha256']=digest(bundle)
    write_json(run/'inputs.json',bundle); write_json(run/'state.json',state)
    with pytest.raises(ValueError,match='predates the complete CC rules'): prepare(run,'requirements')


def test_changed_warning_audit_cannot_be_verified(tmp_path,reference_run):
    run=tmp_path/'run'; replay_until(run,reference_run,'context_review')
    write_json(run/'audit/missing_information_review.json',{'warnings':[]})
    with pytest.raises(ValueError,match='Supporting evidence audit changed'): verify_context(run)


def test_compression_rules_are_not_injected_into_downstream_planner(tmp_path,reference_run):
    run=tmp_path/'run'; replay_until(run,reference_run,'context_review')
    assert 'processing_rules' not in prepare(run,'pipeline')['payload']
    assert prepare(run,'pipeline')['payload']['governance']['rules'][0]['id']=='G001'
    from ctxcomp.rules import attach_rules
    with pytest.raises(ValueError,match='only to context compression'):
        attach_rules({'stage':'animal_pk','instructions':''},load_rules())


def test_standalone_json_contains_resolved_current_rules():
    root=Path(__file__).resolve().parents[2]
    portable=read_json(root/'research_pipeline/docs/interfaces/context_compression.runtime.json')
    assert portable==load_rules()
    assert all('details_file' not in rule for rule in portable['rules'])


def test_merged_pass_scope_reaches_each_review_agent(tmp_path, reference_run):
    run = tmp_path/'run'; replay_until(run, reference_run, 'context')
    base = prepare(run, 'context_review')
    for branch in split_review.BRANCHES:
        rules = split_review.request_for(base, branch, prior={})['payload']['processing_rules']['rules']
        assert 'CC018' not in {r['id'] for r in rules}
        merged = next(r for r in rules if r['id'] == 'CC012')
        assert 'human predictive validity' in merged['pass_meaning']


def test_historical_split_request_without_rules_keeps_its_original_shape(tmp_path,reference_run):
    run=tmp_path/'run'; replay_until(run,reference_run,'context')
    base=prepare(run,'context_review')
    base['payload'].pop('processing_rules')
    base['payload'].pop('scientific_context')
    base['payload'].pop('scientific_context_sha256')
    for branch in split_review.BRANCHES:
        request=split_review.request_for(base,branch,prior={})
        payload=request['payload']
        assert payload['instructions']==split_review.BASE_INSTRUCTIONS+split_review.TASKS[branch]
        assert 'agent_contract' not in payload and 'processing_rules' not in payload
        assert 'source_registry' not in payload and 'missing_information_warnings' not in payload


def test_literal_search_miss_remains_a_bounded_search_result(tmp_path):
    run,q,_=evidence_run(tmp_path)
    q['search_terms']=['term_not_in_source']
    passages,searches=supporting.retrieve(run,load_run(run)[0],[q])
    assert passages==[] and searches[0]['files'][0]['status']=='NO_LITERAL_MATCH'
    assert 'not proof of semantic absence' in searches[0]['method']
