"""Minimal TEST-only EC dispatch to vetted R source-row handlers."""
from __future__ import annotations

import subprocess
from pathlib import Path

from . import context_builder as cb, eda_ep_execution as bridge
from .common import read_json, write_json
from .engine import rscript_path


def execute(frozen, out):
    """Run explicitly frozen TEST tasks once; never enables production EDA."""
    if frozen.get("version") == "EP_FULL_SOURCE_1.0":
        from .eda_ep_full import execute_ec
        from .eda_ep_quality import require_execution_review
        require_execution_review(frozen)
        return execute_ec(frozen, out)
    bridge.verify(frozen)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    request_path = write_json(out / 'ec_request.json', frozen['request'])
    refs = {**frozen['bindings'], 'ec_dispatch': cb.file_ref(__file__),
            'ec_request': cb.file_ref(request_path)}
    write_json(out / 'host_bindings.json', refs)
    result_path, rds_path = out / 'results.json', out / 'results.rds'
    tasks = frozen['request']['tasks']
    if tasks:
        cb.check_refs(refs)
        bridge.verify(frozen)
        process = subprocess.run([rscript_path(), '--vanilla', str(bridge.HANDLER),
                                  str(request_path.resolve()), str(result_path.resolve()), str(rds_path.resolve())],
                                 capture_output=True, text=True, encoding='utf-8', timeout=45)
        (out / 'r_stdout.txt').write_text(process.stdout, encoding='utf-8')
        (out / 'r_stderr.txt').write_text(process.stderr, encoding='utf-8')
        if process.returncode:
            raise ValueError('EC TEST handler failed: ' + process.stderr.strip())
    else:
        result = {'version': 'EP_EC_RESULT_TEST_1.0', 'handler_version': 'TEST_SOURCE_ROWS_1.0',
                  'result_kind': 'SOURCE_SELECTION_ONLY', 'computed_statistics': False,
                  'figures_rendered': False, 'production_enabled': False, 'results': []}
        write_json(result_path, result)
    output_refs = {'json': cb.file_ref(result_path)}
    if tasks:
        output_refs['rds'] = cb.file_ref(rds_path)
    result = read_json(result_path)
    # Do not publish an output bundle until sources, selectors and all output
    # values/conditions have been independently rechecked after R returns.
    bridge.verify(frozen)
    cb.check_refs(refs)
    bridge._require(result['version'] == 'EP_EC_RESULT_TEST_1.0' and
                    result['handler_version'] == frozen['request']['handler_version'] and
                    result['computed_statistics'] is False and result['figures_rendered'] is False and
                    result['production_enabled'] is False, 'unexpected result contract/version')
    expected_ids = [task['analysis_id'] for task in tasks]
    bridge._require([r['analysis_id'] for r in result['results']] == expected_ids, 'missing/duplicate/reordered EC result')
    for actual, task in zip(result['results'], tasks):
        bridge._require(actual['rows'] == frozen['expected_rows'][task['analysis_id']], 'R output changed source cells or context')
        for field in ['experimental_unit', 'grouping', 'transform_aggregation_order',
                      'censoring_policy', 'input_relationships', 'parameters', 'source_context', 'operation_id']:
            bridge._require(actual[field] == task[field], 'R output changed scientific condition: ' + field)
        bridge._require(actual['computed_statistics'] is False and
                        actual['result_kind'] == 'SOURCE_ROW_SELECTION_NOT_COMPUTED_STATISTICS',
                        'source rows must not be labeled computed statistics')
    cb.check_refs(output_refs)
    provenance = {'version': 'EP_EC_PROVENANCE_TEST_1.0', 'bindings': refs,
                  'request_sha256': frozen['request_sha256'],
                  'r_started': bool(tasks), 'r_version': result.get('r_version'),
                  'source_cells': {r['analysis_id']: [c['source_id'] for row in r['rows'] for c in row['cells']]
                                   for r in result['results']},
                  'plan_origin': read_json(refs['plan']['path'])['version'],
                  'receipt_origin': read_json(refs['receipt']['path'])['origin'],
                  'source_values_exact': True, 'provider_calls': 0,
                  'scientific_approval': False, 'production_enabled': False}
    provenance_path = write_json(out / 'provenance.json', provenance)
    bundle = {'version': 'EC_TEST_SOURCE_SELECTION_1.0', 'plan_ref': refs['plan'],
              'input_refs': refs, 'results_ref': {**output_refs, **({'rds': None} if not tasks else {})},
              'provenance_ref': cb.file_ref(provenance_path),
              'checks': {'r_started': bool(tasks), 'source_values_exact': True,
                         'computed_statistics': False, 'figures_rendered': False,
                         'production_enabled': False, 'data_approved': False},
              'not_calculable': frozen['request']['not_calculable']}
    cb.check_refs(refs)
    cb.check_refs(output_refs)
    write_json(out / 'calculation_bundle.json', bundle)
    return bundle
