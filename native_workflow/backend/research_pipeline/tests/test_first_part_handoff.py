"""Synthetic reviews test contracts, not live scientific faithfulness."""
import copy
import pytest
from ctxcomp import engine
from research_pipeline import first_part_handoff as f
from research_pipeline.common import read_json, write_json
from test_project_rule_agent import bundle, run


@pytest.fixture
def prepared(bundle, monkeypatch):
    root, ref, value = bundle
    value['compression_run'] = str(root/'compression')
    write_json(ref['path'], value)
    ref.update(f.prc.file_ref(ref['path']))
    report = run((root, ref, value))
    # Compression is separately integration-verified in the real run; this fixture
    # exercises actual PRC publication verification and unified review contracts.
    monkeypatch.setattr(engine, 'verify_context', lambda _: {'status':'VALID'})
    proof = f.prepare(report['project_rules_ref'], root/'combined')
    return root, proof


def passing(req, **kwargs):
    p = req['payload']
    return {'main_sha256':p['main_sha256'], 'request_sha256':req['request_sha256'],
        'decision':'PASS', 'checks':[{'id':i,'verdict':'PASS','reason':'Synthetic check'} for i in f.CHECKS],
        'source_coverage':[{'unit_id':u['id'],'verdict':'PASS','locations':['/objective'],
            'source_spans':[{'source_id':u['source_id'],'unit_id':u['id'],'quote':u['text']}],
            'reason':'Synthetic source coverage'} for u in p['source_units']],
        'findings':[], 'necessary_overlap_explanation':'Fixture: distinct scientific and obligation uses.'}


def test_full_embedded_rules_roundtrip_preserves_reviewed_bytes(prepared):
    root, proof = prepared
    old = read_json(proof['original_main_ref']['path'])
    new = read_json(proof['main_ref']['path'])
    assert {k for k in old if old[k] != new[k]} == {'version','rules'}
    pack = f.prc.verify_published(proof['pack_ref'])
    assert new['rules'] == pack['rules']
    req = read_json(proof['request_ref']['path'])
    assert 'candidate' not in req['payload'] and 'project_rules' not in req['payload']
    assert 'PRIVATE_HUMAN' not in str(req)
    f.review(root/'combined', generator=passing)
    verified = f.publish(root/'combined', root/'published_combined')
    assert verified['status'] == 'VALID'
    assert verified['main_ref']['sha256'] == proof['main_ref']['sha256']
    assert not verified['scientific_approval']
    assert f.prc.verify_published(proof['pack_ref']) == pack


def test_new_review_locations_are_existing_records_and_sections(prepared):
    _, proof = prepared
    req = read_json(proof['request_ref']['path'])
    p = req['payload']
    locations = p['schema']['properties']['source_coverage']['items']['properties']['locations']['items']['enum']
    assert p['location_contract'] == f.LOCATION_CONTRACT
    assert '/objective' in locations and '/rules/0' in locations
    for pointer in locations:
        f._pointer(p['main'], pointer)
    raw = passing(req)
    raw['source_coverage'][0]['locations'] = ['/rules/R001']
    with pytest.raises(Exception):
        f.validate_review(raw, req)


def test_legacy_location_contract_reconstructs_without_new_fields(prepared):
    root, proof = prepared
    value = f.prc.validate_input(proof['input_ref'])
    main = read_json(proof['main_ref']['path'])
    old = f.review_request(main, proof['main_ref']['sha256'], value)
    assert 'location_contract' not in old['payload']
    assert old['payload']['instructions'] == f.INSTRUCTIONS
    proof.pop('location_contract')
    write_json(proof['request_ref']['path'], old)
    proof['request_ref'] = f.prc.file_ref(proof['request_ref']['path'])
    write_json(root/'combined/preparation.json', proof)
    assert f._verify_preparation(proof)[1] == old
    f.review(root/'combined', generator=passing)
    assert f.publish(root/'combined', root/'legacy_final')['status'] == 'VALID'


@pytest.mark.parametrize('model', ['gpt-6-sol', 'gpt-6-luna'])
def test_new_luna_and_historical_sol_keep_actual_model(prepared, model):
    root, _ = prepared
    def generator(request, **options):
        assert options['model'] == model
        return passing(request)
    f.review(root/'combined', model=model, generator=generator)
    result = f.publish(root/'combined', root/'published_model')
    assert result['status'] == 'VALID'
    assert read_json(result['receipt_ref']['path'])['review_model'] == model


@pytest.mark.parametrize('mutation', ['mainhash','requesthash','duplicate_check','missing_unit','bad_span','bad_pointer','negative_index','falsepass'])
def test_invalid_review_rejected(prepared, mutation):
    _, proof = prepared
    req = read_json(proof['request_ref']['path']); response = passing(req)
    if mutation == 'mainhash': response['main_sha256'] = '0'*64
    if mutation == 'requesthash': response['request_sha256'] = '0'*64
    if mutation == 'duplicate_check': response['checks'][1] = copy.deepcopy(response['checks'][0])
    if mutation == 'missing_unit': response['source_coverage'].pop()
    if mutation == 'bad_span': response['source_coverage'][0]['source_spans'][0]['quote'] = 'invented quote'
    if mutation == 'bad_pointer': response['source_coverage'][0]['locations'] = ['/not_a_field']
    if mutation == 'negative_index': response['source_coverage'][0]['locations'] = ['/rules/-1/text']
    if mutation == 'falsepass': response['checks'][0]['verdict'] = 'REVISE'
    with pytest.raises(Exception): f.validate_review(response, req)


def test_revise_preserved_and_blocks_publication(prepared):
    root, _ = prepared
    def revise(req, **kwargs):
        out = passing(req); out['decision']='REVISE';out['checks'][0]['verdict']='REVISE'
        return out
    assert f.review(root/'combined', generator=revise)['decision'] == 'REVISE'
    with pytest.raises(ValueError): f.publish(root/'combined', root/'forbidden')
    assert not (root/'forbidden').exists()
    with pytest.raises(ValueError): f.review(root/'combined', generator=passing)


@pytest.mark.parametrize('target', ['main','receipt','source','review','request'])
def test_tamper_rejected_after_publish(prepared, target):
    root, proof = prepared
    f.review(root/'combined', generator=passing)
    result = f.publish(root/'combined', root/'final')
    paths = {'main':root/'final/main.json','receipt':root/'final/receipt.json',
        'source':read_json(proof['input_ref']['path'])['source_refs'][0]['path'],
        'review':root/'combined/review.json','request':root/'combined/request.json'}
    value = read_json(paths[target])
    if isinstance(value, list): value.append({'changed':True})
    else: value['changed'] = True
    write_json(paths[target], value)
    if target == 'receipt':
        value['main_ref']['sha256']='0'*64;write_json(paths[target],value)
    with pytest.raises(Exception): f.verify_final_main(result['main_ref']['path'])


def test_model_record_cannot_be_relabelled(prepared):
    root, _ = prepared
    with pytest.raises(ValueError): f.review(root/'combined', model='different-model', generator=passing)
    assert not (root/'combined/review.json').exists()
    f.review(root/'combined', generator=passing)
    timing = read_json(root/'combined/model_timing.json')
    timing['model'] = 'different-model'
    write_json(root/'combined/model_timing.json',timing)
    with pytest.raises(ValueError): f.publish(root/'combined', root/'forbidden')
