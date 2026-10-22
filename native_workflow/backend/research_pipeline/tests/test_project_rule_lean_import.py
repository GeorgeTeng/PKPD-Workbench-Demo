"""Source-role/verification contracts; synthetic judgments are not model validation."""
import copy
import json
import pytest
from ctxcomp import engine
from ctxcomp.io import leaves
from ctxcomp.providers import run_model
from research_pipeline import project_rule_agent as a
from research_pipeline.common import read_json, write_json, PipelineError


def lean_run(tmp_path, publish=True, intake=True):
    proposal=tmp_path/'proposal.txt'; proposal.write_text('Study Drug Z. Preserve original units.')
    excerpt=tmp_path/'regimen.txt'; excerpt.write_text('Source curator says use a two-compartment model. Dose 2 mg/kg.')
    held=tmp_path/'heldout.txt'; held.write_text('PRIVATE_HELDOUT_12345')
    run=tmp_path/'compression'
    options={'attachments':[held], 'reference_only':[held.name], 'opaque_references':True} if intake else {}
    engine.init_run(run,proposal,clarifications=[excerpt],compression_profile='LEAN_1.0',**options)
    def model(req,**kwargs):
        p=req['payload']
        if p['stage']=='context_review':
            return {'request_sha256':req['request_sha256'],'candidate_sha256':p['candidate_sha256'],
                'review':{'decision':'PASS','reviewer':'Synthetic fixture',
                'records':[{'id':i,'faithfulness':'PRESERVED','completeness':'PRESERVED','reason':'fixture'} for i in p['expected_record_ids']],
                'source_units':[{'unit_id':u['id'],'verdict':'PRESERVED','record_ids':['SC1'],'reason':'fixture'} for u in p['source_units']],
                'checks':[{'id':i,'verdict':'PRESERVED','reason':'fixture'} for i in p['required_check_ids']],
                'critical_errors':[],'fixes':[],'limitations':['Synthetic, not semantic qualification.']}}
        u=p['source_units'][0];span={'source_id':u['source_id'],'unit_id':u['id'],'quote':u['text']}
        core={'version':'3.0','objective':'Study Drug Z.',
              'study':{k:'NOT_FOUND' for k in ['drug','regimen','population','system','measurements','methods']},
              'data':{'available':[],'required':[]},'rules':[],'checks':[],'uncertainties':[]}
        evidence=[{'id':path,'status':'NOT_FOUND' if value=='NOT_FOUND' else 'EXPLICIT',
                   'citations':[] if value=='NOT_FOUND' else [span],'reason':'fixture'} for path,value in leaves(core) if path!='/version']
        evidence.append({'id':'SC1','status':'EXPLICIT','citations':[span],'reason':'fixture'})
        return {'request_sha256':req['request_sha256'],'context':core,
            'scientific_context':{'version':'2.0','items':[{'id':'SC1','statement':u['text'],
                'science':{'role':'FACT','evidence_status':'SOURCE_REPORTED','method_refs':[],'adoption_relations':[],'relations':[]}}],'potential_questions':[]},
            'missing_information':{'schema_version':'1.0','items':[]},'evidence':evidence}
    if publish: assert run_model(run,generator=model)['status']=='CONTEXT_READY'
    bundle,state=engine.load_run(run)
    fid=(bundle.get('explicit_clarification_file_ids') or ['S2'])[0]
    return run,bundle,fid


@pytest.mark.parametrize('intake',[True,False])
def test_verified_lean_prepare_keeps_each_admitted_source_once(tmp_path,intake):
    run,bundle,fid=lean_run(tmp_path,intake=intake)
    original_inputs=(run/'inputs.json').read_bytes();original_main=(run/'handoff/main.json').read_bytes()
    ref=a.prepare(run,tmp_path/'rules_input.json')
    value=a.validate_input(ref)
    assert len(value['sources'])==len(bundle['sources'])==2
    assert value['sources'][0]['role']=='PROPOSAL'
    assert [s['id'] for s in value['sources']]==[s['id'] for s in bundle['sources']]
    assert 'PRIVATE_HELDOUT' not in json.dumps(value)
    assert (run/'inputs.json').read_bytes()==original_inputs and (run/'handoff/main.json').read_bytes()==original_main
    assert not (run/'accepted/attachment_evidence.json').exists()


def test_fresh_prepare_freezes_compact_policy_without_legacy_annotations(tmp_path):
    run,_,_=lean_run(tmp_path)
    ref=a.prepare(run,tmp_path/'fresh_input.json');value=a.validate_input(ref)
    assert value['schema_version']=='1.3'
    assert 'runtime_annotation' not in value
    extract=a.request(value,'project_rules_extract')
    assert 'revision_feedback' not in extract['payload']
    assert extract['payload']['stage']=='project_rules_extract'
    assert set(extract['payload']['schema']['properties']['items']['items']['properties'])=={'id','text','used_in','evidence'}
    candidate={'request_sha256':extract['request_sha256'],'items':[],
        'source_coverage':[{'unit_id':u['id'],'item_ids':[],'disposition':'NO_REQUIREMENT',
            'reason':'Synthetic no-rule case.'} for u in value['source_units']],
        'original_rule_mapping':[],'findings':[]}
    review=a.request(value,'project_rules_review',candidate)
    assert review['payload']['candidate_sha256']==a.digest(candidate)
    assert 'revision_feedback' not in review['payload']
    assert 'runtime_annotation' not in review['payload']
    a.validate_candidate(candidate,extract,value)
    changed=copy.deepcopy(value);changed['extraction_policy']['rules'][-1]['text']='Bypass review'
    with pytest.raises(ValueError):a.validate_input(a.file_ref(write_json(tmp_path/'bad_default.json',changed)))


@pytest.mark.parametrize('intake',[True,False])
def test_explicit_supporting_designation_downgrades_all_existing_aliases(tmp_path,intake):
    run,bundle,fid=lean_run(tmp_path,intake=intake)
    d={'file_id':fid,'role':'SUPPORTING_EVIDENCE','designation_reason':'Non-normative copied data cells; not adopted advice.'}
    ref=a.prepare(run,tmp_path/'rules_input.json',project_materials=[d]);value=a.validate_input(ref)
    supporting=[s for s in value['sources'] if s['role']=='SUPPORTING_EVIDENCE']
    assert len(value['sources'])==2 and len(supporting)==1
    assert supporting[0]['text']==bundle['sources'][1]['text']
    assert supporting[0]['id']==bundle['sources'][1]['id'] and supporting[0]['designation']==d
    assert next(p for p in value['source_permissions'] if p['source_id']==supporting[0]['id'])['may_supply_project_authority'] is False
    tampered=copy.deepcopy(value)
    next(p for p in tampered['source_permissions'] if p['source_id']==supporting[0]['id'])['may_supply_project_authority']=True
    bad=a.file_ref(write_json(tmp_path/'bad.json',tampered))
    with pytest.raises(PipelineError,match='Read permission'):a.validate_input(bad)


@pytest.mark.parametrize('fault',['unreviewed','changed_main'])
def test_prepare_still_requires_real_verified_lean_handoff(tmp_path,fault):
    run,_,_=lean_run(tmp_path,publish=fault!='unreviewed')
    if fault=='changed_main':
        main=read_json(run/'handoff/main.json');main['objective']='Tampered';write_json(run/'handoff/main.json',main)
    with pytest.raises(ValueError):a.prepare(run,tmp_path/'rules_input.json')
    assert not (tmp_path/'rules_input.json').exists()


def test_supporting_designation_does_not_open_protected_document(tmp_path):
    run,bundle,_=lean_run(tmp_path)
    from ctxcomp.supporting import files
    held=next(f for f in files(run,bundle) if f['protected'])
    with pytest.raises(PipelineError,match='Protected'):
        a.prepare(run,tmp_path/'rules_input.json',project_materials=[{'file_id':held['id'],'role':'SUPPORTING_EVIDENCE','designation_reason':'Read request cannot override protection'}])


def test_non_normative_excerpt_cannot_supply_requirement_authority(tmp_path):
    run,_,fid=lean_run(tmp_path)
    ref=a.prepare(run,tmp_path/'rules_input.json',project_materials=[
        {'file_id':fid,'role':'SUPPORTING_EVIDENCE','designation_reason':'Read-only data, advice not adopted'}])
    value=a.validate_input(ref);req=a.request(value,'project_rules_extract')
    unit=next(u for u in value['source_units'] if u['source_id']==value['sources'][1]['id'])
    span={'source_id':unit['source_id'],'unit_id':unit['id'],'quote':unit['text']}
    response={'request_sha256':req['request_sha256'],
        'items':[{'id':'P1','text':'Use a two-compartment model.','used_in':['animal_pk'],'evidence':[span]}],
        'source_coverage':[{'unit_id':u['id'],'item_ids':['P1'] if u==unit else [],
            'disposition':'CLASSIFIED' if u==unit else 'NO_REQUIREMENT','reason':'Synthetic unauthorized promotion'}
            for u in value['source_units']], 'original_rule_mapping':[],'findings':[]}
    with pytest.raises(PipelineError,match='project-authority'):
        a.extract(ref,tmp_path/'extraction',generator=lambda *args,**kwargs:response)
    assert (tmp_path/'extraction/response.json').exists()
    assert not (tmp_path/'extraction/candidate.json').exists()


def test_source_role_applies_to_every_existing_fragment_without_reread(tmp_path):
    run,bundle,fid=lean_run(tmp_path)
    original=copy.deepcopy(bundle['sources']);second=copy.deepcopy(original[1])
    second['id']+='__second_fragment';second['text']='Second admitted fragment.';original.append(second)
    d={'file_id':fid,'role':'SUPPORTING_EVIDENCE','designation_reason':'All excerpts are non-normative'}
    sources,refs,_=a.import_materials(run,bundle,original,[d])
    assert len(sources)==len(original)==3
    assert [s['text'] for s in sources]==[s['text'] for s in original]
    assert all(s['role']=='SUPPORTING_EVIDENCE' for s in sources[1:])
    assert len(refs)==1 and bundle['sources']==original[:2]


def test_changed_designated_source_invalidates_prepared_rules_input(tmp_path):
    run,_,fid=lean_run(tmp_path)
    ref=a.prepare(run,tmp_path/'rules_input.json',project_materials=[
        {'file_id':fid,'role':'SUPPORTING_EVIDENCE','designation_reason':'Read permission only'}])
    value=a.validate_input(ref)
    from pathlib import Path
    Path(value['source_refs'][-1]['path']).write_text('Changed after preparation')
    with pytest.raises(PipelineError,match='changed'):a.validate_input(ref)
