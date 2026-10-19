import copy
import pytest
from research_pipeline import context_probe as probe
from research_pipeline.common import read_json, write_json
from ctxcomp import providers
from test_context_linear import coverage


def test_snapshot_probe_preserves_source_without_dispatch(tmp_path, monkeypatch):
    monkeypatch.setattr(providers, 'codex_generate', lambda *a, **kw: pytest.fail('No provider call'))
    request = coverage(['RQ1'])
    source = write_json(tmp_path/'source.json', request)
    original = source.read_bytes()
    result = probe.probe(source, tmp_path/'replay', repetitions=2)
    assert result['request_unchanged'] and result['provider_calls'] == 0
    assert all(result['preserved_sections'].values())
    assert len(result['timing_samples_seconds']) == 2
    assert all(t >= 0 for t in result['median_seconds'].values())
    assert source.read_bytes() == original
    assert read_json(tmp_path/'replay/context_manifest.json')['historical_snapshot_only']
    with pytest.raises(FileExistsError): probe.probe(source, tmp_path/'replay', 1)


def test_probe_detects_evidence_loss(tmp_path, monkeypatch):
    original = probe.mv.project
    def changed(request):
        wire, manifest = original(request)
        wire = copy.deepcopy(wire)
        wire['payload']['source_units'] = {'invented': 'changed'}
        return wire, manifest
    monkeypatch.setattr(probe.mv, 'project', changed)
    source = write_json(tmp_path/'source.json', coverage(['RQ1']))
    with pytest.raises(ValueError, match='projection change'):
        probe.probe(source, tmp_path/'replay', 1)
    assert not (tmp_path/'replay').exists()
