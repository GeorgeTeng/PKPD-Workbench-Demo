"""Build fresh model inputs; reuse only reverified prior source metadata evidence."""
import argparse
from pathlib import Path
from research_pipeline.common import read_json, write_json, sha256
from research_pipeline.model_catalog import load_catalog, require_catalog_models


def ref(path):
    return {'path': str(Path(path).resolve()), 'sha256': sha256(path)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--previous-run', type=Path, required=True)
    a = p.parse_args(); run = a.run.resolve(); normalized = run / 'data_preparation/normalized'
    out = run / 'model_inputs'; out.mkdir(exist_ok=False)
    prior = read_json(a.previous_run / 'rat_population/input.json')
    evidence = prior['provenance']['total_concentration_evidence']
    if sha256(evidence['path']) != evidence['sha256']: raise ValueError('Rat metadata evidence changed')
    audit = read_json(evidence['path'])
    if sha256(audit['workbook']) != audit['sha256']: raise ValueError('Original rat metadata workbook changed')
    correction = audit['rat_metadata_correction']
    if correction['workbook_declared_basis'] != ['total'] or correction['concentration_discrepancies']:
        raise ValueError('Rat total-basis evidence failed')
    previous_source = prior['provenance']['source']
    if sha256(previous_source['path']) != previous_source['sha256']: raise ValueError('Prior rat source changed')
    old = read_json(previous_source['path']); new = read_json(normalized / 'rat_plasma_IV.json')
    fields = ['record_id', 'source_cell', 'source_raw_value', 'time_h', 'concentration_mg_L',
              'status', 'subject_id', 'dose_mg_kg', 'dose_time_h', 'duration_h', 'route', 'matrix']
    project = lambda rows: [{k: r.get(k) for k in fields} for r in rows]
    if project(old['records']) != project(new['records']):
        raise ValueError('Rat data changed: previous metadata bridge cannot be reused without reassessment')
    quantified = [r for r in new['records'] if r['status'] == 'QUANTIFIED']
    doses = {tuple(r[k] for k in ('dose_time_h', 'dose_mg_kg', 'duration_h')) for r in quantified}
    if len(doses) != 1: raise ValueError('New rat dosing design requires reassessment')
    time, amount, duration = doses.pop()
    md = new['metadata'] | {'concentration_basis': 'total', 'data_origin': 'observed',
                           'analysis_scope': 'USER_REQUESTED_EXPLORATORY_RESULTS_FOR_REVIEW'}
    dose = [{'time_h': time, 'dose_mg_kg': amount, 'duration_h': duration}]
    catalog = load_catalog(run / 'attachments/F0003.csv')
    assessments = [require_catalog_models(catalog, [f'PK_SYS_{n}C_LIN', 'INPUT_IV_INF'],
        'pk_longitudinal', {'mode': 'individual', 'compartments': n}, md, {'doses': dose}) for n in (1, 2)]
    write_json(out / 'catalog_assessments.json', {'models': assessments})
    write_json(out / 'rat_excluded.json', {'records': [r for r in new['records'] if r['status'] != 'QUANTIFIED'],
        'policy': 'No imputation; quantified-only exploratory fitting pending review'})
    write_json(out / 'rat.json', {'records': quantified, 'metadata': md, 'doses': dose,
        'provenance': {'source': ref(normalized / 'rat_plasma_IV.json'), 'catalog': catalog['source'],
            'total_concentration_evidence': evidence, 'metadata_source_workbook': ref(audit['workbook']),
            'total_concentration_locator': prior['provenance']['total_concentration_locator'],
            'bridge_check': 'All source identities, concentrations, missingness and dose fields equal prior reaudited rat table',
            'prior_source': previous_source, 'human_review': 'PENDING', 'fit_results_reused': False,
            'scope': 'Exploratory rat model comparison; B2 gate not signed; no human extrapolation'}})
    mouse = read_json(normalized / 'mouse_plasma_IP.json')
    write_json(out / 'mouse.json', {**mouse, 'provenance': {'source': ref(normalized / 'mouse_plasma_IP.json'),
        'human_review': 'PENDING', 'scope': 'Previously authorized descriptive time-summary comparison; no IIV or total/free inference'}})
    write_json(out / 'execution.json', {'status': 'INPUTS_PREPARED', 'script': ref(__file__),
        'rat_source_equivalence_checked': True, 'rat_quantified': len(quantified),
        'rat_animals': len({r['subject_id'] for r in quantified}), 'mouse_source_rows': len(mouse['records'])})
    print('Fresh model inputs prepared', out)


if __name__ == '__main__': main()
