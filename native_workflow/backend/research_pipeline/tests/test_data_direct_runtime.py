import pytest
from research_pipeline import data_direct_runtime as rt
from research_pipeline.common import read_json, write_json, PipelineError


@pytest.fixture
def case(tmp_path):
    source = write_json(tmp_path/'input.json', {'fact': 'original'})
    schema = {'type': 'object', 'additionalProperties': False,
              'properties': {'request_sha256': {'type': 'string'}}, 'required': ['request_sha256']}
    request = rt.make_request({'instructions': 'Only test this contract.'}, schema)
    return tmp_path/'run', request, {'input': rt.file_ref(source)}


def answer(request, **kwargs):
    return {'request_sha256': request['request_sha256']}


def test_exact_accepted_reuse_without_second_call(case):
    out, request, bindings = case
    calls = []
    def generate(request, **kwargs):
        calls.append(request)
        return answer(request)
    expected = rt.invoke(out, request, bindings, lambda raw: None, generator=generate)
    assert rt.invoke(out, request, bindings, lambda raw: None, generator=generate) == expected
    assert len(calls) == 1 and not (out/'runtime.lock').exists()


def test_synthetic_cannot_be_reused_as_real(case):
    out, request, bindings = case
    rt.invoke(out, request, bindings, lambda raw: None, generator=answer)
    with pytest.raises(PipelineError, match='Synthetic'):
        rt.invoke(out, request, bindings, lambda raw: None)


def test_input_changed_during_response_blocks_handoff(case):
    out, request, bindings = case
    def mutate(request, **kwargs):
        write_json(bindings['input']['path'], {'fact': 'changed'})
        return answer(request)
    with pytest.raises(PipelineError, match='Active input changed'):
        rt.invoke(out, request, bindings, lambda raw: None, generator=mutate)
    assert not (out/'accepted.json').exists()
    assert read_json(next((out/'attempts').glob('*/status.json')))['status'] == 'FAILED'


@pytest.mark.parametrize('damage', ['hash', 'schema', 'served_model', 'semantic'])
def test_invalid_response_retained_without_implicit_retry(case, damage):
    out, request, bindings = case
    calls = []
    def generate(request, **kwargs):
        calls.append(1)
        if damage == 'served_model':
            write_json(kwargs['diagnostics_dir']/'call.json', {'served_model': 'other-model'})
        raw = answer(request)
        if damage == 'hash': raw['request_sha256'] = 'wrong'
        if damage == 'schema': raw['extra'] = 'not allowed'
        return raw
    def validate(raw):
        if damage == 'semantic': rt.fail('Contradictory claim')
    with pytest.raises((ValueError, Exception)):
        rt.invoke(out, request, bindings, validate, generator=generate)
    assert not (out/'accepted.json').exists()
    assert list((out/'attempts').glob('*/response.json'))
    with pytest.raises(PipelineError, match='Previous attempt retained'):
        rt.invoke(out, request, bindings, validate, generator=generate)
    assert len(calls) == 1


def test_pause_and_lock_prevent_dispatch(case):
    out, request, bindings = case
    out.mkdir()
    (out/'PAUSE').touch()
    with pytest.raises(PipelineError, match='Paused'):
        rt.invoke(out, request, bindings, lambda raw: None, generator=answer)
    (out/'PAUSE').unlink()
    (out/'runtime.lock').touch()
    with pytest.raises(FileExistsError):
        rt.invoke(out, request, bindings, lambda raw: None, generator=answer)
