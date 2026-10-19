"""Vocabulary integrity and binding safeguards, not an LLM accuracy benchmark."""
import json
import re

from ctxcomp.rules import load_rules


def key(value):
    # Collapse typography; retain /, > and % because they change PK meaning.
    return re.sub(r"[\s_-]+", "", value.casefold())


def test_english_vocabulary_has_one_home_per_term_and_valid_aliases():
    profile = load_rules()['pk_binding_knowledge']
    assert json.dumps(profile, ensure_ascii=False).isascii()
    owners = {}
    concept_ids = set()
    names = set()
    references = {r['id'] for r in profile['references']}
    assert len(references) == len(profile['references'])
    for group in profile['groups']:
        assert group['level'] in {'CORE', 'CONDITIONAL'}
        assert set(group['references']) <= references
        assert group['references']
        for concept in group['concepts']:
            assert concept['id'] not in concept_ids
            concept_ids.add(concept['id'])
            assert key(concept['name']) not in names
            names.add(key(concept['name']))
            assert concept['check']
            for alias, target in concept.get('aliases', {}).items():
                assert target in concept['terms']
                assert alias not in concept['terms']
            tokens = concept['terms'] + list(concept.get('aliases', {})) + concept.get('symbols', [])
            for token in tokens:
                normalized = key(token)
                assert normalized not in owners, (token, owners.get(normalized), concept['id'])
                owners[normalized] = concept['id']


def test_supporting_metadata_stays_small_without_species_name_lists():
    profile = load_rules()['pk_binding_knowledge']
    assert len(profile['supporting_metadata'].split()) <= 25
    assert 'species' in profile['supporting_metadata']
    tokens = {key(t) for g in profile['groups'] for c in g['concepts'] for t in c['terms']}
    assert not tokens & {'mouse', 'rat', 'rabbit', 'dog', 'monkey', 'strain', 'sex', 'age'}
    assert 'CC005' in profile['shared_guidance']
    assert len(profile['data_qualifiers']) == 2


def test_related_quantities_and_ambiguous_symbols_are_not_merged_as_aliases():
    profile = load_rules()['pk_binding_knowledge']
    concepts = {c['id']: c for g in profile['groups'] for c in g['concepts']}
    for concept, distinct in {
        'clearance': {'CL', 'CL/F', 'CLu', 'CLint'},
        'volume': {'Vc', 'Vp', 'Vss', 'Vz', 'V/F'},
        'auc': {'AUC0-t', 'AUC0-inf', 'AUC0-24', 'AUCtau'},
        'indices': {'fT>MIC', '%fT>MIC', 'fAUC/MIC', 'fCmax/MIC'},
    }.items():
        assert distinct <= set(concepts[concept]['terms'])
        assert not distinct & set(concepts[concept].get('aliases', {}))
    assert 'Q' in concepts['exchange']['symbols']
    assert 'F' in concepts['bioavailability']['symbols']
    assert 'EC50' in concepts['response']['terms']
    assert 'EC50' not in concepts['potency']['terms']
    assert 'FU' not in concepts['binding'].get('aliases', {})
    assert 'whitelist' in profile['use']


def test_conditional_diagnostics_and_translation_do_not_impose_project_rules():
    profile = load_rules()['pk_binding_knowledge']
    groups = {g['id']: g for g in profile['groups']}
    assert all(groups[i]['level'] == 'CONDITIONAL' for i in ('CPK06', 'CPK07', 'CPK08'))
    assert profile['authority'] == 'TERMINOLOGY_AND_BINDING_GUIDANCE_ONLY'
    concepts = {c['id']: c for g in profile['groups'] for c in g['concepts']}
    assert 'not blanket obligations' in concepts['predictivechecks']['check']
    assert 'human outputs remain prospective' in concepts['validation']['check']
    assert 'Source definitions override' in profile['use']
