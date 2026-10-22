"""Deterministic planning brain: route only qualified data and scoped context.

A model can propose plans in a future provider, but cannot alter this allowlist
or approve data. Scientific blocking states are retained in every handoff.
"""
from pathlib import Path
from .common import read_json, write_json, sha256


def reference(path):
    return {'path': str(Path(path).resolve()), 'sha256': sha256(path)}


def route_context(run):
    run = Path(run); out = run / 'handoffs'
    main = read_json(run / 'B1/main.json')
    manifest = read_json(run / 'data_preparation/normalization_manifest.json')
    decisions = []
    def context_for(module):
        from .task_rules import project_rules
        projection = project_rules(main, module)
        chosen = [r['text'] for r in projection['rules']]
        return {'version': main.get('version'), 'study': {'drug': main.get('study', {}).get('drug', 'NOT_FOUND')},
                'rules': chosen, 'source': reference(run / 'B1/main.json'),
                'rule_projection':{k:v for k,v in projection.items() if k not in {'rules','audit'}},
                'scope': 'Selected rules from proposal context; exploratory exceptions remain labelled, not silently approved'}
    for branch, species in [('rat_population', 'rat'), ('rat_individual', 'rat'), ('mouse_plasma', 'mouse')]:
        payload = read_json(run / 'model_inputs' / (species + '.json'))
        # Numerical input already contains exactly one species, doses and source evidence.
        payload['task'] = {'module': 'pk_longitudinal', 'species': species,
            'purpose': 'Compare eligible PK candidates for human review',
            'human_prediction_allowed': False, 'data_gate_signed': False}
        payload['context'] = context_for('pk_longitudinal')
        write_json(out / (branch + '.json'), payload)
        decisions.append({'task': branch, 'input': reference(out / (branch + '.json')),
                          'reason': 'Only this species and its dose/source evidence', 'can_parallel_with': ['index']})
    relevant, excluded = [], []
    for dataset in manifest['datasets']:
        identifier = dataset['id']
        # Exposure-response and supporting MIC/binding/regimen data only.
        # Systemic concentration profiles go to PK; they are never treated as indices.
        include = any(x in identifier.lower() for x in ('endpoint', 'time_kill', 'mic', 'binding', 'fraction', 'regimen',
            'target', 'terminal_', 's02_t3_', 'exposure_events', 'rabbit_auc', 'rabbit_cmax', 'bacterial_burden',
            'lung_weight', 'hemorrhage', 'dose_range_conflict'))
        if include: relevant.append({'id': identifier, 'file': dataset['json'], 'metadata': dataset['metadata']})
        else: excluded.append({'id': identifier, 'reason': 'Not a matched index/response or supporting MIC/binding/regimen dataset'})
    write_json(out / 'index.json', {'schema_version': '1.0', 'module': 'pkpd_index',
        'task': {'primary': ['fAUC/MIC', 'fCmax/MIC', '%fT>MIC'], 'models': ['Emax', 'Hill'],
                 'comparison': ['R2', 'AIC', 'AICc', 'BIC'], 'same_response_rows_required': True},
        'datasets': relevant, 'context': context_for('pkpd_index'), 'human_review': 'PENDING', 'scientific_release': False})
    catalogs = [f for f in main['data']['files'] if f['role'] == 'MODEL_CATALOG']
    write_json(out / 'literature.json', {'module': 'literature_search', 'drug': main.get('study',{}).get('drug','NOT_FOUND'),
        'catalogs': [{'id': f['id'], 'path': f['path'], 'sha256': f['sha256']} for f in catalogs],
        'required': ['Same drug and route/model applicability', 'Source evidence and reliability review'], 'observation_data': []})
    write_json(out / 'review.json', {'module': 'human_review', 'report': reference(run / 'data_preparation/main.json'),
        'scope': 'Exploratory result review only', 'human_prediction_allowed': False})
    write_json(out / 'routing_plan.json', {'planner': 'VALIDATED_RULE_BASED', 'schema_version': '1.0',
        'decisions': decisions + [{'task': 'index', 'input': reference(out / 'index.json'), 'can_parallel_with': ['rat_population', 'rat_individual', 'mouse_plasma']}],
        'index_exclusions': excluded, 'full_chat_forwarded': False, 'full_proposal_forwarded': False,
        'review_gate': 'PENDING; no scientific release created'})
    return out
