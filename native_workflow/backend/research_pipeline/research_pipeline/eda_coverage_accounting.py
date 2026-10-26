"""Host-derived field accounting from immutable selected view mappings, not model guesses."""
import copy
from . import eda_display_catalog as catalog

def resolve(dispositions, selected, candidates, tables, *, match_report=None):
    if not isinstance(dispositions, list): raise ValueError('Dataset dispositions required')
    ids = [d['dataset_id'] for d in dispositions]
    if len(ids) != len(set(ids)) or set(ids) != set(tables):
        raise ValueError('Every admitted dataset must have exactly one disposition')
    if not set(selected) <= set(candidates): raise ValueError('Unknown selected view')
    result = copy.deepcopy(dispositions); differences = []
    for d in result:
        did = d['dataset_id']
        views = [v for v in selected if did in catalog.sources(candidates[v])]
        shown = set().union(*(catalog.fields(candidates[v], did) for v in views))
        expected = sorted(catalog.relevant_fields(tables[did]) - shown)
        if 'unshown_columns' in d and d['unshown_columns'] != expected:
            differences.append({'dataset_id':did,'model_reported':copy.deepcopy(d['unshown_columns']),
                                'host_verified':expected,'selected_views':views})
        d['unshown_columns'] = expected
    # Keep every existing status, scientific reason and executability check.
    verified = catalog.coverage(result, selected, candidates, tables, match_report=match_report)
    return result, {'version':'EDA_HOST_FIELD_ACCOUNTING_1','method':'display_fields minus selected source_fields',
                    'model_discrepancies':differences,'data_modified':False,
                    'scientific_decisions_modified':False,'verified_coverage':verified}
