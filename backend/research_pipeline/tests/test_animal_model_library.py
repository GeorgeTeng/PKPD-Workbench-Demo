from research_pipeline.animal_model_library import search_models, load_model_library, DIRECTORY
from research_pipeline.references import canonical_drug
from research_pipeline.model_catalog import load_catalog
from research_pipeline.pk_reference_pilot import load_library

def test_pmb_first_and_no_unrelated_match():
    exact=search_models('PMB')['models']
    assert len(exact)==3 and all(x['match_type']=='SAME_DRUG' for x in exact)
    matches=search_models('PMB',include_related=True)['models']
    assert len(matches)==5 and all(x['drug_id']=='polymyxin_b' for x in matches[:3])
    assert not search_models('unknown compound',include_related=True)['models']

def test_aliases_prodrug_and_scoped_data():
    assert canonical_drug('EVER206')==canonical_drug('SPR206')
    assert canonical_drug('CMS')!=canonical_drug('colistin')
    assert len(search_models('EVER206',species='mice',route='SC')['models'])==1
    assert not search_models('PMB',species='rabbit')['models']
    assert not search_models('PMB',route='PO')['models']
    assert any(x['match_type']=='PRODRUG_RELATED' for x in search_models('colistin',include_related=True)['models'])

def test_library_provenance_and_acceptance_boundaries():
    lib=load_library();models=load_model_library()
    assert len(lib['sources'])==23 and len(lib['cards'])==17
    assert lib['translation_role_counts']['ANIMAL_TO_HUMAN_PK_PREDICTION']==7
    assert all(s.get('translation_role') for s in lib['sources'])
    assert not {'F3652022','BRII2026'} & {s['id'] for s in lib['sources']}
    assert all(m['published_parameter_values_included'] is False and m['parameter_transfer_authorized'] is False for m in models['models'])
    assert all(m['scientific_acceptance']=='PENDING_HUMAN_REVIEW' for m in models['models'])
    assert not any('faddi_365' in r['drugs'] for r in models['relations'])
    catalog=load_catalog(DIRECTORY/'model_library_catalog_expanded.csv')
    assert len(catalog['models'])==40
    assert all(m['implementation']=='NOT_IMPLEMENTED' for m in catalog['models'] if m['model_id'].startswith('LIT_'))
