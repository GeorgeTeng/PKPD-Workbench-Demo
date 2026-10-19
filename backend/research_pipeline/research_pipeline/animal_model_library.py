"""Source-verified structural candidates, separate from fit configurations and acceptance."""
from pathlib import Path
from .common import read_json, PipelineError, sha256
from .references import canonical_drug

DIRECTORY=Path(__file__).parent/'resources/pk_references'
MODEL_LIBRARY=DIRECTORY/'animal_models.json'

def load_model_library():
    data=read_json(MODEL_LIBRARY)
    if data.get('authority')!='CANDIDATES_ONLY' or data.get('parameter_transfer_authorized') is not False:
        raise PipelineError('MODEL_LIBRARY_BOUNDARY','Literature models are review candidates only.')
    sources={s['id'] for s in read_json(DIRECTORY/'library.json')['sources']}
    identifiers=set()
    for row in data['models']:
        if row['model_id'] in identifiers or not row['source_ids'] or set(row['source_ids'])-sources:
            raise PipelineError('MODEL_LIBRARY_PROVENANCE','Duplicate model ID or unresolved source.')
        if row.get('parameter_transfer_authorized') is not False or row.get('scientific_acceptance')!='PENDING_HUMAN_REVIEW':
            raise PipelineError('MODEL_LIBRARY_ACCEPTANCE','Registration cannot accept models or transfer parameters.')
        identifiers.add(row['model_id'])
    return data

def search_models(drug=None,species=None,route=None,include_related=False,query=''):
    data=load_model_library();target=canonical_drug(drug) if drug else None
    related={}
    if target and include_related:
        for relation in data['relations']:
            if target in relation['drugs']:
                for other in relation['drugs']:
                    if other!=target:related[other]=relation
    names={'mice':'mouse','rats':'rat','rabbits':'rabbit'}
    species=names.get(str(species).lower(),str(species).lower()) if species else None
    result=[]
    for row in data['models']:
        actual=canonical_drug(row['drug_id'])
        if target and actual!=target and actual not in related:continue
        if species and species not in row['species']:continue
        if route and str(route).upper() not in row['routes']:continue
        text=' '.join(str(row.get(k,'')) for k in ['model_name','drug_id','structure','source_ids']).casefold()
        if query and not all(t in text for t in query.casefold().split()):continue
        match='SAME_DRUG' if target==actual else related[actual]['kind'] if target else 'UNFILTERED'
        result.append({**row,'match_type':match,'match_evidence':related[actual]['source_ids'] if target and actual!=target else row['source_ids']})
    result.sort(key=lambda x:(x['match_type']!='SAME_DRUG',x['model_id']))
    return {**data,'models':result,'total_models':len(data['models']),'target_drug':target,
            'library_sha256':sha256(MODEL_LIBRARY),'ranking_note':'Exact drug first; ordering is not a model quality or predictive-validity score.'}
