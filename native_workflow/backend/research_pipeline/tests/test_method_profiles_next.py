"""Opt-in knowledge contracts; no fitting, simulation, project data or live calls."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ctxcomp.io import digest
from research_pipeline import method_profiles as legacy
from research_pipeline import method_profiles_next as m
from research_pipeline.adequacy import check_ref
from research_pipeline.common import PipelineError, read_json


def profile(pid):
    return next(p for p in m.load_library()['profiles'] if p['id'] == pid)


def candidate(pid):
    return {'id': 'NEXT_' + pid, 'origin': 'METHOD_CANDIDATE', 'kind': 'DATA',
            'method_profile_ids': [pid], 'conditions': ['Requested by the project objective'],
            'evidence': [{'source': 'method:' + pid, 'quote': profile(pid)['applies_when']},
                         {'source': 'main:/objective', 'quote': 'Assess target and PTA inputs'}]}


def test_frozen_legacy_files_profiles_and_schema_are_unchanged():
    assert hashlib.sha256(legacy.LIBRARY_PATH.read_bytes()).hexdigest() == 'f89b56e86024a0c60cd7ae7279b0964cae5d6a056b11f2e08143c627dc6d25b4'
    assert hashlib.sha256(Path(legacy.__file__).read_bytes()).hexdigest() == '5fbdcf49dded22f7849116b5d7e3abd789419a1af3c74f8442997603dc24f1db'
    old, new = legacy.load_library(), m.load_library()
    assert len(old['profiles']) == 10 and len(new['profiles']) == 12
    assert new['profiles'][:10] == old['profiles']
    assert {p['id'] for p in new['profiles'][10:]} == {'MP010', 'MP012'}
    assert new['lineage']['version'] == old['version']
    assert new['lineage']['file_sha256'] == hashlib.sha256(legacy.LIBRARY_PATH.read_bytes()).hexdigest()
    assert all('PTA' not in variant['properties']['family']['enum'] for variant in legacy.PROFILE['anyOf'])
    with pytest.raises(ValueError):
        legacy.check_context(m.planning_context())
    with pytest.raises(PipelineError, match='Unknown method'):
        legacy.scoped_context(legacy.planning_context(), ['MP010', 'MP012'])


def test_new_context_scopes_profiles_sources_and_conventions_without_mutation():
    context = m.planning_context()
    assert m.check_context(context)['version'] == m.VERSION
    packet = m.scoped_context(context, ['MP010', 'MP012'])
    assert {p['id'] for p in packet['profiles']} == {'MP010', 'MP012'}
    assert {s['id'] for s in packet['sources']} == {'S07', 'S08', 'S20'}
    assert packet['library_sha256'] == context['library_sha256']
    assert packet['scientific_release'] is False
    packet['profiles'][0]['required_inputs'].append('Mutated copy')
    assert 'Mutated copy' not in str(context)
    assert not m.scoped_context(context, [])['profiles']
    with pytest.raises(PipelineError, match='Unknown method'):
        m.scoped_context(context, ['MP404'])


@pytest.mark.parametrize('pid', ['MP010', 'MP012'])
def test_new_ids_have_usable_evidence_and_requirement_references(pid):
    context = m.planning_context()
    sources = m.evidence_sources(context)
    assert json.loads(sources['method:' + pid]) == profile(pid)
    need = candidate(pid)
    m.validate_requirements([need], context)
    need['kind'] = 'SOURCE_PERMISSION'
    with pytest.raises(PipelineError, match='cannot authorize'):
        m.validate_requirements([need], context)


@pytest.mark.parametrize('fault', ['unknown_method', 'unlinked_evidence', 'no_objective', 'no_conditions'])
def test_new_requirement_citations_do_not_bypass_existing_authority_contract(fault):
    need = candidate('MP012')
    if fault == 'unknown_method':
        need['method_profile_ids'] = ['MP404']
    elif fault == 'unlinked_evidence':
        need['evidence'][0]['source'] = 'method:MP010'
    elif fault == 'no_objective':
        need['evidence'].pop()
    else:
        need['conditions'] = []
    with pytest.raises(PipelineError):
        m.validate_requirements([need], m.planning_context())


@pytest.mark.parametrize('fault', ['digest', 'governance', 'authority', 'release'])
def test_next_frozen_context_rejects_drift_and_authority_promotion(fault):
    context = m.planning_context()
    if fault == 'digest':
        context['library']['profiles'][-1]['required_inputs'].append('Changed')
    elif fault == 'governance':
        context['general_rules_sha256'] = 'changed'
    elif fault == 'authority':
        context['authority'] = 'PROJECT_RULES'
    else:
        context['scientific_release'] = True
    with pytest.raises(PipelineError):
        m.check_context(context)


@pytest.mark.parametrize('fault', ['duplicate', 'source', 'trigger', 'analysis_field'])
def test_next_library_schema_and_references_reject_invalid_knowledge(fault):
    library = copy.deepcopy(m.load_library())
    p = library['profiles'][-1]
    if fault == 'duplicate':
        p['id'] = library['profiles'][0]['id']
    elif fault == 'source':
        p['source_ids'] = ['MISSING']
    elif fault == 'trigger':
        p['condition_triggers']['data_checks'].pop()
    else:
        p['post_analysis_checks'] = ['Run PTA now']
    with pytest.raises(ValueError):
        m.validate_library(library)


def test_selected_next_context_keeps_valid_digest_and_new_profile_citations():
    context = m.planning_context()
    selected = copy.deepcopy(context['library'])
    selected['profiles'] = [p for p in selected['profiles'] if p['id'] in {'MP010', 'MP012'}]
    refs = {sid for p in selected['profiles'] for sid in p['source_ids']}
    selected['sources'] = [s for s in selected['sources'] if s['id'] in refs]
    context.update(library=selected, library_sha256=digest(selected))
    assert set(m.evidence_sources(context)) == {'method:MP010', 'method:MP012'}
    m.validate_requirements([candidate('MP010'), candidate('MP012')], context)


def test_target_estimation_is_not_winner_selection_or_exposure_summary():
    p = profile('MP012')
    assert 'Exposure summary, index comparison and target estimation are distinct tasks' in p['applies_when']
    assert 'does not require a winning index first' in p['applies_when']
    assert any('paired exposure-response observations within each panel' in v for v in p['conditional_inputs'])
    assert any('cross-index common-record comparison is unavailable' in v for v in p['acceptable_alternatives'])
    assert any('Fair cross-index comparison additionally needs common compatible response records' in v for v in p['data_checks'])
    assert any('not mandatory effects for every project' in v for v in p['required_inputs'])
    assert any('interpolation from extrapolation' in v for v in p['data_checks'])
    assert any('Group means and technical replicates are not independent individual responses' in v for v in p['conditional_inputs'])


def test_planned_outputs_do_not_become_missing_raw_data_or_qualified_outputs():
    conventions = m.load_library()['planning_conventions']
    assert set(conventions['gap_kinds']) == {'DESIGN_DEFINITION', 'EXISTING_SOURCE_REVIEW', 'PLANNED_MODEL_OUTPUT', 'NEW_DATA'}
    planned = conventions['gap_kinds']['PLANNED_MODEL_OUTPUT']
    assert 'not automatically missing source data' in planned
    assert 'a plan is not an available or qualified output' in planned
    for pid in ('MP010', 'MP012'):
        assert 'PLANNED_MODEL_OUTPUT' in str(profile(pid)['acceptable_alternatives'])
    assert 'project exclusion is not missing data' in conventions['scope']


def test_per_mic_pta_and_mic_weighted_attainment_have_different_dependencies():
    p = profile('MP010')
    assert p['family'] == 'PTA'
    assert any('A MIC distribution is not required for per-MIC PTA' in v for v in p['required_inputs'])
    weighted = next(v for v in p['conditional_inputs'] if v.startswith('Only for MIC-weighted attainment'))
    assert all(term in weighted for term in ('counts', 'denominator', 'censoring', 'coverage', 'target organism population'))
    assert any('Do not replace unknown probabilities with a mean' in v and 'silently renormalize partial weights' in v for v in p['data_checks'])
    assert any('deterministic typical-exposure/target comparison' in v for v in p['acceptable_alternatives'])
    assert any('between-unit variability' in v and 'parameter uncertainty' in v for v in p['required_inputs'])
    assert 'Missing MIC weights affect weighted attainment only' in p['missing_effect']


def test_cli_exports_loadable_context_with_actual_scoped_evidence_and_requirements(tmp_path):
    out = tmp_path / 'next_method_context.json'
    result = subprocess.run([sys.executable, '-m', 'research_pipeline.method_profiles_next',
                             '--profiles', 'MP010', 'MP012', '--out', str(out)],
                            capture_output=True, text=True, check=True)
    manifest = json.loads(result.stdout)
    check_ref({'path': manifest['path'], 'sha256': manifest['sha256']})
    context = read_json(out)
    assert context['full_library_sha256'] == m.planning_context()['library_sha256']
    assert context['library_sha256'] != context['full_library_sha256']
    assert len(m.check_context(context)['profiles']) == 2
    assert len(m.scoped_context(context, ['MP010', 'MP012'])['profiles']) == 2
    sources = m.evidence_sources(context)
    assert set(sources) == {'method:MP010', 'method:MP012'}
    needs = [candidate('MP010'), candidate('MP012')]
    m.validate_requirements(needs, context)
    for need in needs:
        span = need['evidence'][0]
        assert span['quote'] in json.loads(sources[span['source']])['applies_when']
    saved_bytes = out.read_bytes()
    with pytest.raises(PipelineError, match='already exists'):
        m.export_context(['MP010'], out)
    assert out.read_bytes() == saved_bytes


def test_export_rejects_empty_or_unknown_profile_sets_before_writing(tmp_path):
    for ids in ([], ['MP404']):
        out = tmp_path / 'not_created.json'
        with pytest.raises(PipelineError):
            m.export_context(ids, out)
        assert not out.exists()
