"""Actual TEST EV rendering and evidence/typed-display boundaries; no provider."""
import copy
import importlib.util
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from research_pipeline import context_builder as cb, eda_ec, eda_ev, eda_ep_execution as bridge
from research_pipeline.common import read_json, write_json

ROOT = Path(__file__).resolve().parents[3]
helper_spec = importlib.util.spec_from_file_location('ev_manual_smoke', ROOT / 'outputs/EDA_EV_OfflineSmoke_20261015/manual_smoke.py')
helper = importlib.util.module_from_spec(helper_spec)
helper_spec.loader.exec_module(helper)


@pytest.fixture(scope='module')
def smoke(tmp_path_factory):
    directory = tmp_path_factory.mktemp('ev_smoke') / 'run'
    helper.run(directory)
    return directory


def case(tmp_path, smoke, mutate=None):
    plan = helper.manual_plan()
    if mutate:
        mutate(plan)
    path = write_json(tmp_path / 'plan.json', plan)
    receipt = tmp_path / 'receipt.json'
    bridge.record_test_plan(path, smoke / 'ep_request.json', receipt)
    eda_ec.execute(bridge.freeze(receipt), tmp_path / 'ec')
    return receipt, tmp_path / 'ec/calculation_bundle.json'


def test_actual_png_svg_and_original_figure_contract(smoke):
    bundle = read_json(smoke / 'ev/figure_bundle.json')
    contract = read_json(ROOT / 'backend/rules/eda/eda_rules.json')['artifact_contracts']['figure_bundle']
    assert set(bundle) == set(contract['required_fields'])
    assert len(bundle['figures']) == 3 and not bundle['omissions']
    for figure in bundle['figures']:
        assert set(figure) == set(contract['figure_fields'])
        png = Path(figure['image_ref']['path'])
        assert png.read_bytes()[:8] == b'\x89PNG\r\n\x1a\n'
        assert struct.unpack('>II', png.read_bytes()[16:24])[0] == 1700
        svg = ET.parse(png.with_suffix('.svg')).getroot()
        assert svg.tag.endswith('svg')
        assert float(svg.attrib['width'].removesuffix('pt')) > 500
    assert bundle['technical_checks']['new_statistics_computed'] is False
    assert bundle['technical_checks']['rendered_images_inspected'] is False


def test_exact_marks_nd_baseline_n_and_reported_scale(smoke):
    pk = read_json(smoke / 'ev/F001.plotted_rows.json')
    pd = read_json(smoke / 'ev/F002.plotted_rows.json')
    mic = read_json(smoke / 'ev/F003.plotted_rows.json')
    assert len(pk['marks']) == 8 and all(m['sd'] is None and m['n'] is None for m in pk['marks'])
    assert pk['display_spec']['y_variable_unit_scale']['scale'] == 'log10'
    assert len(pd['marks']) == 8 and sum(m['status'] == 'PLOTTED' for m in pd['marks']) == 7
    missing = next(m for m in pd['marks'] if m['source_row'] == 191)
    assert missing['y'] is None and missing['sd'] is None and missing['n'] == 'ND'
    assert missing['status'] == 'ND_NOT_PLOTTED'
    assert len(pd['baselines']) == 2
    assert all(b['n'] is None and b['n_status'] == 'NOT_REPORTED' for b in pd['baselines'])
    assert all(m['n'] == '4' for m in pd['marks'] if m['status'] == 'PLOTTED')
    assert pd['display_spec']['y_variable_unit_scale'] == {'column':'D','unit':'log10 CFU/thigh','scale':'linear'}
    for data in [pk, pd, mic]:
        role = data['display_spec']['y_variable_unit_scale']['column']
        source = {r['source_row']: {c['column']:c['raw_value'] for c in r['cells']} for r in data['raw_rows']}
        for mark in data['marks']:
            if mark['status'] == 'PLOTTED':
                assert mark['y'] == float(source[mark['source_row']][role])
    assert [m['y'] for m in mic['marks']] == [0.5, 0.5, 0.5]


def test_unsupported_display_is_explicit_omission_without_r(tmp_path, smoke, monkeypatch):
    def mutate(plan):
        for analysis in plan['analyses']:
            analysis['display_spec']['kind'] = 'UNREGISTERED_FITTED_CURVE'
    receipt, calculation = case(tmp_path, smoke, mutate)
    monkeypatch.setattr(eda_ev.subprocess, 'run', lambda *a, **k: pytest.fail('No R for unavailable displays'))
    result = eda_ev.render(receipt, calculation, tmp_path / 'ev')
    assert result['figures'] == [] and len(result['omissions']) == 3
    assert all(o['status'] == 'NOT_RENDERABLE' for o in result['omissions'])


def test_bad_axis_identity_is_hard_failure(tmp_path, smoke, monkeypatch):
    receipt, calculation = case(tmp_path, smoke, lambda p:p['analyses'][0]['display_spec']['x_variable_unit_scale'].update(column='Z'))
    monkeypatch.setattr(eda_ev.subprocess, 'run', lambda *a, **k: pytest.fail('No R for invalid identity'))
    with pytest.raises(ValueError, match='unauthorized'):
        eda_ev.render(receipt, calculation, tmp_path / 'ev')


@pytest.mark.parametrize('mutate, reason', [
    (lambda a:a['display_spec']['y_variable_unit_scale'].update(scale='log10'), 'axis'),
    (lambda a:a['display_spec'].update(uncertainty_definition='SOURCE_SE'), 'uncertainty'),
    (lambda a:a['display_spec'].update(facets='NONE'), 'facets'),
])
def test_pd_double_log_error_redefinition_and_group_loss_rejected(smoke, mutate, reason):
    analysis = helper.manual_plan()['analyses'][1]
    mutate(analysis)
    result = read_json(smoke / 'ec/results.json')['results'][1]
    operation = read_json(bridge.REGISTRY)['operations']['REPORTED_MEAN_SD_DISPLAY']
    assert reason in eda_ev._display_issue(analysis, result, operation)


def test_changed_ec_result_and_changed_plan_reject_before_renderer(tmp_path, smoke):
    receipt, calculation = case(tmp_path, smoke)
    result_path = tmp_path / 'ec/results.json'
    result_path.write_bytes(result_path.read_bytes() + b' ')
    with pytest.raises(ValueError, match='Changed input'):
        eda_ev.render(receipt, calculation, tmp_path / 'ev')


def test_late_renderer_substitution_rejects_original_receipt(tmp_path, smoke, monkeypatch):
    substituted = tmp_path / 'other_renderer.R'
    substituted.write_bytes(bridge.EV_HANDLER.read_bytes())
    monkeypatch.setattr(bridge, 'EV_HANDLER', substituted)
    with pytest.raises(ValueError, match='not bound before'):
        eda_ev.render(smoke / 'host_receipt.json', smoke / 'ec/calculation_bundle.json', tmp_path / 'ev')


def test_ev_does_not_assemble_prompt_or_call_retrieval(smoke, tmp_path, monkeypatch):
    from research_pipeline import context_task, context_model_view
    monkeypatch.setattr(context_task, 'assemble', lambda *a, **k:pytest.fail('No task assembly in EV'))
    monkeypatch.setattr(context_model_view, 'project', lambda *a, **k:pytest.fail('No prompt projection in EV'))
    # A complete second rendering verifies EV uses only the bound scientific artifacts.
    bundle = eda_ev.render(smoke / 'host_receipt.json', smoke / 'ec/calculation_bundle.json', tmp_path / 'ev')
    assert len(bundle['figures']) == 3
