"""Deterministic admitted DH -> v6 inputs/catalog/source snapshot. No calls or R.

Consumes Data's released artifacts; does not clean, classify, join or build events.
Context/Rules publication and Data review remain upstream responsibilities.
"""
import argparse
import copy
import re
from pathlib import Path
from . import context_builder as cb, eda_ep_full as source
from .common import read_json, write_json

VERSION = 'EDA_DH_SOURCE_SNAPSHOT_1'


def require(ok, message):
    if not ok: raise ValueError('EDA DH: ' + message)


def bind_tree(value, refs):
    """Verify supplied references, never discover arbitrary neighboring artifacts."""
    if isinstance(value, dict):
        if value.get('snapshot_path') and value.get('snapshot_sha256'):
            bind_tree({'path':value['snapshot_path'],'sha256':value['snapshot_sha256']}, refs)
        if isinstance(value.get('path'), str) and isinstance(value.get('sha256'), str):
            ref = {'path': value['path'], 'sha256': value['sha256']}
            cb.check_refs({'source': ref})
            refs['source:' + str(len(refs))] = ref
        for child in value.values(): bind_tree(child, refs)
    elif isinstance(value, list):
        for child in value: bind_tree(child, refs)


def project_role(meta, file_role):
    """Transport Data's checked role to the existing PK metadata.role path."""
    declared = meta.get('role')
    resolved = declared if declared == file_role else 'UNRESOLVED'
    role = {'PK_OBSERVATIONS': 'PK', 'PD_OBSERVATIONS': 'PD',
            'IN_VITRO_TIME_KILL': 'PD', 'SUPPORTING_EVIDENCE': 'CONTEXT'}.get(resolved, 'UNRESOLVED')
    return {**copy.deepcopy(meta), 'data_role': declared, 'handoff_role': file_role,
            'role': role, 'role_resolution': 'VERIFIED_DATA_ROLE' if role != 'UNRESOLVED' else 'UNRESOLVED',
            'observation_role': resolved in {'PK_OBSERVATIONS', 'PD_OBSERVATIONS', 'IN_VITRO_TIME_KILL'}}


def project_tables(catalog, sources, files):
    tables = []
    for cat in catalog:
        did = cat['dataset_id']; item = sources[did]; meta = item['metadata']
        cols = {c['column']: c for c in meta.get('columns', [])}
        columns = copy.deepcopy(cat['columns'])
        for col in columns:
            cell = next(r['source_cells'][col['id']] for r in item['records'] if col['id'] in r['source_cells'])
            declared = cols.get(re.match(r'[A-Z]+', cell).group(), {})
            for key in ('role', 'time_role', 'time_origin'):
                if key in declared: col[key] = copy.deepcopy(declared[key])
        tables.append({**copy.deepcopy(cat), 'columns': columns,
            'records': copy.deepcopy(item['records']),
            'notes': item['reading_view']['reading_view_markdown'].split('**Notes / limits**', 1)[-1],
            'source_refs': copy.deepcopy(source.verified(files[did]['metadata_file']).get('source_refs', [])),
            'metadata': project_role(meta, files[did]['role'])})
    return tables


def candidates(tables):
    """Offer points only for a unique declared temporal/response pair.

    Registered source recipes are still applied by v6. Ambiguous/wide/categorical
    tables retain their source table; numeric appearance never grants semantics.
    """
    plots = []; gaps = []
    for t in tables:
        did = t['dataset_id']; role = t['metadata']['role']
        xs = [c for c in t['columns'] if c['meaning'] == 'TIME'
              and not re.search(r'interval|regimen|frequency', c['header'], re.I)]
        ys = [c for c in t['columns'] if c['meaning'] == ('CONCENTRATION' if role == 'PK' else 'RESPONSE')]
        reason = ''
        if role not in {'PK', 'PD'}: reason = 'Role unresolved or context only; no observation view inferred.'
        elif len(xs) != 1 or len(ys) != 1: reason = 'Requires one explicit time and response column; registered recipes may offer other supported views.'
        elif any(c['unit'] in {'', 'NOT_FOUND', 'MIXED'} for c in xs + ys): reason = 'Axis unit unresolved.'
        elif not any(source.number(r['source_raw_values'].get(xs[0]['id'])) and r['value_status'].get(xs[0]['id']) == 'QUANTIFIED'
                     and source.number(r['source_raw_values'].get(ys[0]['id'])) and r['value_status'].get(ys[0]['id']) == 'QUANTIFIED' for r in t['records']):
            reason = 'No source-quantified temporal/response coordinates.'
        if reason:
            gaps.append({'dataset_id': did, 'reason': reason}); continue
        x, y = xs[0], ys[0]; vid = did + '_SOURCE_POINTS'
        caption = 'Unchanged source values and statuses; independent points only. No inferred identity, connecting lines, fitted curve or scientific release.'
        recipe = dict(id=vid, title=t['title'], question='Inspect source temporal observations within their verified record level.',
            caption=caption, scale='linear', categorical=False, facet_scales='fixed', ncol=1, legend=True,
            x_label=x['header'] if x['unit'] in x['header'] else x['header'] + ' (' + x['unit'] + ')',
            y_label=y['header'] if y['unit'] in y['header'] else y['header'] + ' (' + y['unit'] + ')',
            series=[dict(dataset_id=did, x=x['id'], y=y['id'], panel=t['title'], group='', projection='numeric',
                error='', n='', category_column='', category_prefix='', filters={}, x_from_header=False)])
        plots.append(dict(id=vid, kind='source_projection', title=t['title'], subtitle=recipe['question'], caption=caption,
            y_scale='linear', panels=[{'series': [{'dataset_id': did}]}], source_recipe=recipe))
    return plots, gaps


def build(handoff_path, report_path, out):
    refs = {'handoff': cb.file_ref(handoff_path), 'report': cb.file_ref(report_path), 'adapter': cb.file_ref(__file__)}
    h, report = read_json(handoff_path), read_json(report_path)
    require(h.get('status') == 'READY_FOR_EDA' and h.get('allowed_action') == 'DESCRIPTIVE_EDA', 'admitted descriptive DH required')
    require(report.get('status') == 'TECHNICAL_DATA_READY' and report.get('execution_scope') == 'DESCRIPTIVE_EDA_ONLY', 'technical descriptive Data report required')
    require(h.get('fit_ready') is False and h.get('scientific_release') is False
            and report.get('fit_ready') is False and report.get('scientific_release') is False, 'unexpected release scope')
    bind_tree(h, refs); bind_tree(report, refs)
    require(h['full_manifest'] == report['normalization_manifest'], 'DH/report manifest differs')
    manifest = source.verified(h['full_manifest'])
    main_ref = report['upstream']['main']; main = source.verified(main_ref)
    rules = source.verified(h['rules_ref'])
    # Data already verified publication. Require its exact canonical binding here;
    # do not create a second Context resolver or serialize a decorated main.
    require(rules.get('status') == 'PROJECT_RULES_PUBLISHED', 'published project Rules required')
    if rules.get('context_contract') == 'SOURCE_CONTEXT_REFERENCE_1.0':
        require(rules.get('main_ref') == main_ref, 'Rules/canonical Context binding differs')
    else:
        # Historical publication used an effective main and a final FirstPart copy.
        # Reuse its existing verifier; never invent a new main/path resolver.
        from .first_part_handoff import verify_final_main
        final = verify_final_main(main_ref['path'])
        require(final['main_ref'] == main_ref and final['project_rules_ref'] == h['rules_ref']
                and final['rules'] == rules['rules'], 'legacy FirstPart/Rules binding differs')
        bind_tree({k: final[k] for k in ('receipt_ref', 'review_ref', 'project_rules_ref')}, refs)
    bind_tree(rules, refs)
    require(source.verified(rules['review_ref']).get('decision') == 'PASS', 'independent project Rules review required')
    require(isinstance(rules.get('rules'), list) and all(isinstance(r, dict) for r in rules['rules']), 'separate full Rules required')
    files = {f['id']: f for f in h['files']}
    require(files and len(files) == len(h['files']), 'missing/duplicate DH datasets')
    datasets = {d['id']: d for d in manifest['datasets']}
    require(len(datasets) == len(manifest['datasets']), 'duplicate manifest dataset')
    states = {s['dataset_id']: s for s in h['dataset_action_readiness']}
    require(len(states) == len(h['dataset_action_readiness']), 'duplicate readiness dataset')
    if 'ready_dataset_ids' in report:
        require(sorted(files) == sorted(report['ready_dataset_ids']), 'Data report and handoff membership differ')
    if 'dataset_action_readiness' in report:
        report_states = {s['dataset_id']: s for s in report['dataset_action_readiness']}
        require(len(report_states) == len(report['dataset_action_readiness']), 'duplicate Data report readiness dataset')
        require(all(did in states and states[did] == report_states.get(did) for did in files),
                'Data report and handoff permissions differ')
    views = []
    for did, f in files.items():
        require(did in datasets and did in states, 'missing manifest/readiness: ' + did)
        require(states[did]['actions']['DESCRIPTIVE_EDA']['status'] == 'READY', 'descriptive permission denied: ' + did)
        require(all(datasets[did][k] == f[k] for k in ('data', 'metadata_file', 'role')), 'manifest/DH dataset differs: ' + did)
        raw = source.verified(f['data']); sidecar = source.verified(f['metadata_file']); meta = sidecar['metadata']
        bind_tree(sidecar, refs)
        require(raw.get('records') and meta.get('source_table'), 'source records/table metadata required: ' + did)
        from .reading_package import reading_view
        require('column_map' in meta['source_table'], 'source column map required: ' + did)
        if 'metadata' in datasets[did]: require(datasets[did]['metadata'] == meta, 'manifest/sidecar metadata differs: ' + did)
        quarantine = source.verified(f['quarantine'])['records'] if f.get('quarantine') else []
        targets = {did, meta['source_item_id']}
        relevant = [finding for finding in report.get('findings', [])
                    if targets & set(re.split(r'[,;\s]+', finding.get('affected_id', '')))]
        if report.get('unresolved_ledger'):
            relevant = [finding for finding in relevant if finding.get('code') != 'UNRESOLVED_LEDGER_NOT_SUPPLIED']
        relevant += [{'reason':item['limitation']} for item in report.get('accepted_limitations', []) if item.get('field') in targets]
        markdown = reading_view({**datasets[did], 'metadata':meta}, raw['records'], quarantine, relevant).decode('utf8')
        refs['reading_formatter'] = cb.file_ref(reading_view.__code__.co_filename)
        # Reuse Data's pure source-reading formatter; no old EP/EC/reading export prerequisite.
        views.append({'dataset_id': did, 'title': meta['source_table']['title'], 'group': meta.get('species', 'NOT_FOUND'),
            'reading_view_markdown': markdown,
            'representation': 'Existing Data source-reading formatter; full records also materialized in v6 admitted_evidence.'})
    require(isinstance(main.get('objective'), str) and main['objective'].strip(), 'canonical objective required')
    context_fields = ('objective', 'study', 'scientific_context', 'missing_information')
    inputs = {'data_handoff': {**copy.deepcopy(h), 'reading_views': views},
        'task_context': {**{k: copy.deepcopy(main[k]) for k in context_fields if k in main},
            'context_fields_not_supplied': [k for k in context_fields if k not in main],
            'project_rules': copy.deepcopy(rules['rules'])}}
    cb.check_refs(refs)
    root = Path(out); root.mkdir(parents=True, exist_ok=False)
    input_path = write_json(root / 'inputs.json', inputs)
    _, catalog, sources, source_refs = source.load_inputs(input_path)
    tables = project_tables(catalog, sources, files)
    snapshot = write_json(root / 'source_snapshot.json', {'version': VERSION, 'tasks': tables, 'computed_statistics': False,
        'bindings': refs, 'scientific_release': False, 'fit_ready': False})
    plots, gaps = candidates(tables)
    cat = write_json(root / 'candidate_views.json', {'version': VERSION, 'input_ref': cb.file_ref(snapshot),
        'plots': plots, 'references': [], 'candidate_gaps': gaps})
    cb.check_refs(refs); cb.check_refs(source_refs)
    receipt = write_json(root / 'snapshot_receipt.json', {'version': VERSION, 'bindings': refs,
        'outputs': {'inputs': cb.file_ref(input_path), 'snapshot': cb.file_ref(snapshot), 'catalog': cb.file_ref(cat)},
        'datasets': len(tables), 'calculations_run': False, 'model_calls': 0, 'R_run': False})
    return {'inputs': str(input_path), 'catalog': str(cat), 'snapshot_receipt': cb.file_ref(receipt), 'candidate_gaps': gaps}


def run(handoff_path, report_path, out, *, model=None, until='EV'):
    root = Path(out); root.mkdir(parents=True, exist_ok=False)
    built = build(handoff_path, report_path, root / 'intake')
    from .eda_questions_v6 import run_questions
    return run_questions(built['inputs'], None, built['catalog'], root / 'run', model=model, until=until)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--handoff', required=True); p.add_argument('--report', required=True); p.add_argument('--out', required=True)
    p.add_argument('--run', action='store_true'); p.add_argument('--until', choices=['EV', 'ER'], default='EV'); p.add_argument('--model')
    a = p.parse_args()
    print(run(a.handoff, a.report, a.out, model=a.model, until=a.until) if a.run else build(a.handoff, a.report, a.out))


if __name__ == '__main__': main()
