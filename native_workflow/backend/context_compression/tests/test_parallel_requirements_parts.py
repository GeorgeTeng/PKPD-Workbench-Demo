"""Compression rules 1.31.0 (CC002 requirements_parts PARALLEL): every requirements part starts at once."""
import copy
import threading
import pytest

from ctxcomp import requirements_parts as parts
from ctxcomp.engine import accept, prepare, load_run, accepted_response
from ctxcomp.io import read_json
from ctxcomp.providers import run_model
from test_requirements_parts import generator
from test_supporting_scope import cited_run


def together(make, count):
    """The generator, with every inventory part waiting until `count` parts have started."""
    barrier = threading.Barrier(count)
    def generate(request, model=None):
        if 'inventory_part' in request['payload']:
            barrier.wait(timeout=10)
        return make(request, model)
    return generate


def test_the_proposal_and_supporting_parts_start_together(tmp_path):
    run, passage, units, proposal = cited_run(tmp_path); calls = []
    base = prepare(run, 'requirements')
    assert parts.mode(base['payload']) == parts.PARALLEL and parts.enabled(base['payload'])
    make = generator(units, proposal, passage, calls, target='SA01')
    result = run_model(run, generator=together(make, 2), until='requirements', review_executor_id='test')
    assert result == {'status': 'STAGE_READY', 'stage': 'requirements'} and sorted(calls) == ['proposal', 'supporting_A']
    inventory = accepted_response(run, load_run(run)[1], 'requirements')['requirements']
    assert [r['id'] for r in inventory['items']] == ['P01', 'SA01']
    proof = read_json(run/parts.PROOF)
    assert proof['mode'] == parts.PARALLEL
    first = read_json(run/proof['parts']['proposal']['request'])['payload']
    assert 'written at the same time by separate supporting parts' in first['instructions']
    second = read_json(run/proof['parts']['supporting_A']['request'])['payload']
    assert 'proposal_inventory' not in second and 'name only your own items' in second['instructions']
    assert parts.verify_proof(run, base, accepted_response(run, load_run(run)[1], 'requirements'))


def test_a_supporting_part_cannot_link_to_a_proposal_item_it_never_saw(tmp_path):
    run, passage, units, proposal = cited_run(tmp_path); calls = []
    with pytest.raises(parts.PartOutputError, match='supporting_A'):
        run_model(run, generator=generator(units, proposal, passage, calls, target='P01'), until='requirements',
                  review_executor_id='test')
    # The validated proposal part is reused; only the failed part is called again.
    calls.clear()
    run_model(run, generator=generator(units, proposal, passage, calls, target='SA01'), until='requirements',
              review_executor_id='test')
    assert calls == ['supporting_A']
    assert read_json(run/parts.PROOF)['parts']['proposal']['execution'] == 'REUSED'


def test_a_failed_proposal_part_does_not_stop_the_supporting_parts(tmp_path):
    run, passage, units, proposal = cited_run(tmp_path); calls = []
    make = generator(units, proposal, passage, calls, target='SA01')
    def broken(request, model=None):
        response = make(request, model)
        if request['payload'].get('inventory_part', {}).get('part') == 'proposal':
            response = copy.deepcopy(response)
            response['requirements']['items'][0]['science']['relations'] = [
                {'type': 'SUPPORTS', 'target_id': 'P99', 'component_ids': ['C1']}]
        return response
    with pytest.raises(parts.PartOutputError, match='proposal'):
        run_model(run, generator=broken, until='requirements', review_executor_id='test')
    calls.clear()
    run_model(run, generator=make, until='requirements', review_executor_id='test')
    assert calls == ['proposal']
