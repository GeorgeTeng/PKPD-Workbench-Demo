"""Prompt and source-bound transport tests; synthetic extraction is not model validation."""
import copy
import pytest
from ctxcomp import lean_compression as lean
from ctxcomp.engine import init_run,load_run,prepare,accept
from test_lean_compression import setup,candidate


def test_partial_regimen_contract_reaches_every_call_and_keeps_source_scope(tmp_path):
    run=setup(tmp_path);bundle,state=load_run(run);generation=prepare(run,'context')
    response=candidate(generation);accept(run,'context',response)
    independent=prepare(run,'context_review')
    targeted=lean.patch_request(bundle,lean.content(response),{'fixes':[]},run)
    assert bundle['compression_profile']['version']=='1.14'
    assert bundle['compression_profile']['regimen_preservation']=='SOURCE_SCOPED_PARTIAL_1.0'
    for req in (generation,independent,targeted):
        text=req['payload']['instructions']
        assert lean.REGIMEN_PRESERVATION in text
        assert 'route alone' in text and 'multiple independent regimens' in text
        assert 'Sampling times are not dose events' in text
        assert 'a total daily dose is not a per-administration dose' in text
        assert 'never join components across independent studies' in text
        assert 'Mark unspecified components as unknown or not stated' in text
        assert 'No new attachment search is authorized' in text
        for field in ('dose basis','frequency or interval','treatment duration','loading and maintenance',
                      'infusion rate or duration','time origin or dose-event offset'):
            assert field in text
        assert req['payload']['source_units']==bundle['source_units']


def test_regimen_contract_is_frozen_and_old_schema_unchanged(tmp_path,monkeypatch):
    run=setup(tmp_path);bundle,state=load_run(run)
    current=lean.request(run,bundle,state,'context');old=copy.deepcopy(bundle)
    old['compression_profile']['version']='1.9';old['compression_profile'].pop('regimen_preservation')
    old['compression_profile'].pop('citation_placement')
    for key in ('generation_instructions','review_instructions'):
        old['compression_profile'][key]=old['compression_profile'][key].removesuffix(lean.REFERENCE_ARRAY_FORMAT).removesuffix(lean.SOURCE_OWNER_COMPLETENESS).removesuffix(lean.EXACT_CITATION_PLACEMENT).removesuffix(lean.REGIMEN_PRESERVATION)
    historical=lean.request(run,old,state,'context')
    monkeypatch.setattr(lean,'REGIMEN_PRESERVATION','UNFROZEN CHANGE')
    assert lean.request(run,bundle,state,'context')==current
    assert lean.request(run,old,state,'context')==historical
    assert 'Regimen extraction is source-scoped' not in historical['payload']['instructions']
    for key in ('candidate_schema','review_schema','patch_schema','stages','max_patches'):
        assert old['compression_profile'][key]==bundle['compression_profile'][key]


@pytest.mark.parametrize('statements,overview',[
    (['Rat study: intravenous administration; dose and interval were not stated.'],
     'Partial rat regimen: IV; other components not stated [F001].'),
    (['Mouse experiment A: 8 mg/kg total daily dose; fraction sizes not stated.',
      'Rat experiment B: intravenous administration; samples at 1 and 2 hours; dose not stated.'],
     'Multiple independent partial regimens: mouse A [F001], rat B [F002].')])
def test_partial_and_separate_regimens_survive_to_independent_review(tmp_path,statements,overview):
    proposal=tmp_path/'proposal.txt';proposal.write_text('\n\n'.join(statements),encoding='utf-8')
    run=tmp_path/'run';init_run(run,proposal,compression_profile=lean.ID)
    req=prepare(run,'context');response=candidate(req);units=req['payload']['source_units']
    first={'source_id':units[0]['source_id'],'unit_id':units[0]['id'],'quote':statements[0]}
    # Explicit authored output tests transport and evidence validation, not extraction by a model.
    response['evidence']=[e for e in response['evidence'] if e['id']!='F001']
    for evidence in response['evidence']:
        if evidence['citations']:evidence['citations']=[copy.deepcopy(first)]
    template=response['scientific_context']['items'][0];items=[];citations=[]
    for i,statement in enumerate(statements):
        rid='F'+str(i+1).zfill(3);item=copy.deepcopy(template);item.update(id=rid,statement=statement);items.append(item)
        cite={'source_id':units[i]['source_id'],'unit_id':units[i]['id'],'quote':statement};citations.append(cite)
        response['evidence'].append(dict(id=rid,status='EXPLICIT',citations=[cite],reason='Exact authored source'))
    response['scientific_context']['items']=items;response['context']['study']['regimen']=overview
    evidence=next(e for e in response['evidence'] if e['id']=='/study/regimen')
    evidence.update(status='EXPLICIT',citations=citations,reason='Source-scoped partial regimen overview')
    accept(run,'context',response)
    supplied=prepare(run,'context_review')['payload']['candidate']
    assert supplied['context']['study']['regimen']==overview
    assert [item['statement'] for item in supplied['scientific_context']['items']]==statements
    assert supplied['evidence']==response['evidence']
