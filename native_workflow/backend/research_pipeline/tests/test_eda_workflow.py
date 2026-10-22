"""Real R rendering with synthetic source records and explicit model stubs."""
import copy
import json
from pathlib import Path

import pytest
from research_pipeline import eda_workflow as wf, eda_ep_full as ep, eda_context, context_builder as cb
from research_pipeline.common import read_json, write_json
from ctxcomp import providers


def source_inputs(root):
    root.mkdir(parents=True)
    records = [
        {'record_id': 'D1:R1', 'source_raw_values': {'x': 1/12, 'y': 4}, 'value_status': {'x': 'QUANTIFIED', 'y': 'QUANTIFIED'}, 'source_cells': {'x': 'A2', 'y': 'B2'}},
        {'record_id': 'D1:R2', 'source_raw_values': {'x': 2, 'y': 0}, 'value_status': {'x': 'QUANTIFIED', 'y': 'CENSORED'}, 'source_cells': {'x': 'A3', 'y': 'B3'}}]
    write_json(root/'data.json', {'records': records})
    write_json(root/'metadata.json', {'metadata': {'source_item_id': 'SYNTHETIC', 'record_level': 'Synthetic observations; not project evidence',
        'columns': [{'column': 'A', 'header': 'Time', 'unit': 'h'}, {'column': 'B', 'header': 'Response', 'unit': 'arbitrary'}],
        'source_table': {'notes': 'Synthetic test. Censored zero is not an observed zero.'}}})
    return write_json(root/'inputs.json', {'data_handoff': {
        'status': 'READY_FOR_EDA', 'allowed_action': 'DESCRIPTIVE_EDA', 'scientific_release': False, 'fit_ready': False,
        'files': [{'id': 'D1', 'role': 'PK_OBSERVATIONS', 'data': cb.file_ref(root/'data.json'), 'metadata_file': cb.file_ref(root/'metadata.json')}],
        'reading_views': [{'dataset_id': 'D1', 'title': 'Synthetic example', 'group': 'Synthetic',
            'reading_view_markdown': 'D1:R1 D1:R2 **Notes / limits** Synthetic censored example.'}],
        'dataset_action_readiness': [{'dataset_id': 'D1', 'actions': {'DESCRIPTIVE_EDA': {'status': 'READY'}}, 'operation_restrictions': []}],
        'task_requirements': [{'id': 'TEST1'}], 'unresolved_ledger': [{'issue': 'Synthetic unresolved dose basis.'}]},
        'task_context': {'objective': 'Synthetic transport test only', 'project_rules': [], 'implemented_r_operations': []}})


def plan_response(request):
    fields = request['payload']['schema']['properties']['analyses']['items']['required']
    a = {key: 'Not applicable: source display only.' for key in fields}
    a.update(analysis_id='A1', requirement_ids=['TEST1'], source_refs=[], reference_sections=[], dataset_ids=['D1'],
             status='PLANNED', experimental_unit='Synthetic source records',
             display_spec={key: 'Synthetic: censored zero is not plotted; no fitted trajectory.' for key in read_json(eda_context.PACK)['artifact_contracts']['eda_plan']['display_spec_fields']},
             execution={'operation_id': 'SOURCE_XY_POINTS', 'series': [{'dataset_id': 'D1', 'x': 'x', 'y': 'y', 'group_by': '', 'x_scale': 'linear', 'y_scale': 'linear'}],
                        'limitation': 'Synthetic example: no dose inference.'})
    return {'version': 'SYNTHETIC_ONLY', 'objective': 'Synthetic transport test only',
        'input_refs': {'dataset_ids': ['D1'], 'source_ids': [], 'rule_ids': [], 'reference_sections': []},
        'analyses': [a], 'not_planned': [], 'open_items': [],
        'dataset_disposition': [{'dataset_id': 'D1', 'use': 'PLANNED', 'analysis_ids': ['A1'], 'reason': 'Synthetic point display.'}]}


def stubbed_provider(monkeypatch, fail_ei=False, decision='PASS'):
    calls = []
    def stub(request, **kwargs):
        stage = request['payload']['stage']; calls.append(stage)
        if stage == 'EP-plan': return plan_response(request)
        if stage == 'EP-finalize':
            return {'version':'EP_FINAL_DISPLAYS_1.0','summary':'Synthetic display review only.',
                'task_decisions':[{'task_id':t['task_id'],'decision':'KEEP','operation_id':t['operation_id'],
                    'selection':copy.deepcopy(t['selection']),'reason':'Source display remains supported.','additional_note':''}
                    for t in request['payload']['calculation_bundle']['tasks']], 'open_items':[]}
        refs = {'analysis_ids': ['A1'], 'artifact_ids': ['TASK0001']}
        if stage == 'EI-findings':
            return {'version': 'SYNTHETIC_ONLY', 'input_refs': refs,
                'findings': [{'finding_id': 'F1', 'analysis_ids': ['A1'], 'artifact_refs': ['INVALID' if fail_ei else 'TASK0001'],
                    'record_scope': ['D1:R1'], 'observation': 'Synthetic source point is retained.',
                    'interpretation_if_useful': 'Not applicable.', 'alternative_if_interpretation': 'Not applicable.',
                    'downstream_implication': 'No project inference; synthetic interface evidence only.'}],
                'limitations': ['Synthetic model responses, not scientific review.'], 'open_items': []}
        return {'version': 'SYNTHETIC_ONLY', 'reviewed_refs': refs, 'decision': decision,
            'review_scope': 'Synthetic text-only contract check. No visual inspection.', 'issues': [],
            'unreviewed_items': ['Rendered image has not been supplied to the model.']}
    monkeypatch.setattr(providers, '_codex_generate_raw', stub)
    return calls


def test_full_linear_run_preserves_notes_and_stops_for_human(tmp_path, monkeypatch):
    inputs = source_inputs(tmp_path/'inputs'); calls = stubbed_provider(monkeypatch)
    root = tmp_path/'run'
    result = wf.run(inputs, root, model='test-stub')
    assert result['status'] == 'WAITING_FOR_HUMAN_REVIEW'
    assert calls == ['EP-plan', 'EP-finalize', 'EI-findings', 'ER-review']
    assert not (root/'eda_handoff.json').exists()
    assert read_json(root/'EV/TASK0001.plotted_rows.json')['excluded'][0]['record_id'] == 'D1:R2'
    assert read_json(root/'EV/TASK0001.plotted_rows.json')['points'][0]['x'] == 1/12
    table = (root/'EV/TASK0001.html').read_text(encoding='utf-8')
    assert 'Synthetic: censored zero' in table and 'no dose inference' in table
    assert (root/'EV/TASK0001.png').read_bytes().startswith(b'\x89PNG')
    for stage in ['EI','ER']:
        payload = read_json(root/stage/'prepared/request.json')['payload']
        assert 'reading_views' not in payload['data_handoff']
        assert wf.expand_grid(payload['calculation_bundle']['source_tables']['D1']['records'])[1]['source_raw_values']['y'] == 0
        assert all('records' not in t for t in payload['calculation_bundle']['results'])
    wf.run(inputs, root, model='test-stub')
    assert len(calls) == 4
    assert read_json(root/'human_review.json')['summary']['upstream_open_items']['unresolved_ledger']


def test_resume_after_ep_does_not_repeat_ep(tmp_path, monkeypatch):
    inputs = source_inputs(tmp_path/'inputs'); calls = stubbed_provider(monkeypatch); root=tmp_path/'run'
    assert wf.run(inputs,root,until='EP')['status']=='STOPPED_AFTER_EP'
    assert calls==['EP-plan']
    assert wf.run(inputs,root)['status']=='WAITING_FOR_HUMAN_REVIEW'
    assert calls==['EP-plan','EP-finalize','EI-findings','ER-review']


def test_invalid_findings_stop_without_review_or_retry(tmp_path, monkeypatch):
    inputs=source_inputs(tmp_path/'inputs');calls=stubbed_provider(monkeypatch,fail_ei=True);root=tmp_path/'run'
    with pytest.raises(ValueError,match='unknown finding artifact'):wf.run(inputs,root)
    assert calls==['EP-plan','EP-finalize','EI-findings'] and not (root/'ER').exists()
    with pytest.raises(ValueError,match='no automatic retry'):wf.run(inputs,root)
    assert len(calls)==3


def test_missing_data_change_cannot_reuse_completed_ep(tmp_path, monkeypatch):
    inputs=source_inputs(tmp_path/'inputs');calls=stubbed_provider(monkeypatch);root=tmp_path/'run'
    wf.run(inputs,root,until='EP')
    write_json(tmp_path/'inputs/data.json',{'records':[]})
    with pytest.raises(ValueError):wf.run(inputs,root)
    assert calls==['EP-plan']


def test_revise_does_not_become_handoff(tmp_path, monkeypatch):
    inputs=source_inputs(tmp_path/'inputs');stubbed_provider(monkeypatch,decision='REVISE');root=tmp_path/'run'
    assert wf.run(inputs,root)['status']=='REVIEW_REQUIRED'
    assert not (root/'eda_handoff.json').exists()


def test_confirmation_binds_exact_packet_and_preserves_upstream_ledger(tmp_path, monkeypatch):
    inputs=source_inputs(tmp_path/'inputs');stubbed_provider(monkeypatch);root=tmp_path/'run'
    wf.run(inputs,root)
    packet=read_json(root/'human_review.json')
    decision={'actor_type':'HUMAN','reviewer':'SYNTHETIC_TEST_ONLY','reviewed_at':'TEST_ONLY',
        'packet_sha256':'wrong','decision':'APPROVE_DESCRIPTIVE_EDA','images_inspected':True,
        'limitations_acknowledged':True,'accepted_unreviewed_items':packet['summary']['unreviewed_items'],
        'accepted_open_items':packet['summary']['open_items'],'accepted_deferred_analysis_ids':[]}
    path=write_json(tmp_path/'synthetic_human_decision.json',decision)
    with pytest.raises(ValueError,match='not for this packet'):wf.confirm(root,path)
    decision['packet_sha256']=packet['content_sha256'];write_json(path,decision)
    result=wf.confirm(root,path)
    assert result['open_items']['data']['unresolved_ledger'] and result['scientific_release'] is False
    assert result['downstream_started'] is False
    with pytest.raises(ValueError,match='already exists'):wf.confirm(root,path)


def test_reviewer_must_disclose_uninspected_images():
    inputs={'eda_plan':{'analyses':[]},'figure_bundle':{'artifacts':[]}}
    raw={'version':'test','reviewed_refs':{'analysis_ids':[],'artifact_ids':[]},'decision':'PASS','review_scope':'Text only.','issues':[],'unreviewed_items':[]}
    with pytest.raises(ValueError,match='uninspected'):wf.validate_output('ER',raw,inputs)


def test_reconcile_keeps_deferred_figure_and_only_declared_table():
    raw={'analyses':[{'analysis_id':'A1','status':'DEFERRED','dataset_ids':['D1'],
        'question':'Planned figure','reason':'Status-aware figure remains unimplemented.',
        'display_spec':{'kind':'Scatter','x_variable_unit_scale':'h','y_variable_unit_scale':'mg/L','facets':'Study','marks':'Status marks'},
        'execution':{'operation_id':'SOURCE_TABLE','series':[{'dataset_id':'D1'}],'limitation':'Table fallback only.'}}],
        'dataset_disposition':[{'dataset_id':'D1','use':'PLANNED','analysis_ids':['A1'],'reason':'Retain data.'}]}
    before=copy.deepcopy(raw)
    result,changes=wf.reconcile_ep(raw)
    assert raw==before and len(changes)==1
    assert result['analyses'][0]['status']=='DEFERRED' and result['analyses'][0]['execution']['operation_id']=='NONE'
    assert result['analyses'][1]['execution']==before['analyses'][0]['execution']
    assert result['dataset_disposition'][0]['analysis_ids']==['A1','A1_TABLE_FALLBACK']
    raw['analyses'][0]['execution']['operation_id']='SOURCE_XY_POINTS'
    assert wf.reconcile_ep(raw)==(raw,[])


def test_saved_ep_is_reused_with_original_context(tmp_path, monkeypatch):
    inputs=source_inputs(tmp_path/'inputs');calls=stubbed_provider(monkeypatch)
    first=tmp_path/'first';second=tmp_path/'second'
    wf.run(inputs,first,until='EP')
    wf.run(inputs,second,saved_ep=first/'EP')
    assert calls==['EP-plan','EP-finalize','EI-findings','ER-review']
    assert read_json(second/'EP/reconciliation.json')['origin']=='SAVED_RESPONSE'
    assert read_json(first/'EP/prepared/request.json')==read_json(second/'EP/prepared/request.json')


def test_explicit_handler_migration_keeps_original_model_context(tmp_path, monkeypatch):
    inputs=source_inputs(tmp_path/'inputs');calls=stubbed_provider(monkeypatch)
    first=tmp_path/'first';second=tmp_path/'second'
    snapshot=tmp_path/'old_handler.R';snapshot.write_bytes(ep.HANDLER.read_bytes())
    wf.run(inputs,first,until='EP')
    changed=tmp_path/'new_handler.R';changed.write_bytes(snapshot.read_bytes()+b'\n# Synthetic test-only handler version\n')
    monkeypatch.setattr(ep,'HANDLER',changed)
    wf.run(inputs,second,saved_ep=first/'EP',previous_handler=snapshot)
    assert calls==['EP-plan','EP-finalize','EI-findings','ER-review']
    mapping=read_json(second/'EP/reconciliation.json')
    assert mapping['handler_migration']['model_resampled'] is False
    assert mapping['original_request_sha256']==read_json(first/'EP/prepared/request.json')['request_sha256']


def test_review_grid_round_trips_missing_null_precision_and_status():
    rows = [{'record_id': 'R'+str(i), 'source_raw_values': {'time': 1/12, 'y': i},
             'time': 1/12, 'source_cells': {'time': 'A'+str(i), 'y': 'B'+str(i)},
             'value_status': {'time': 'QUANTIFIED', 'y': 'QUANTIFIED'},
             'long_note': 'Uncertain dose basis; no unbound conversion. '*8,
             'optional': None} for i in range(20)]
    del rows[0]['optional']; rows[1]['optional'] = []
    rows[2]['value_status']['y'] = 'CENSORED'
    rows[3]['source_raw_values']['y'] = None
    before = copy.deepcopy(rows)
    packed = wf.compact_grid(rows)
    assert isinstance(packed, dict) and len(json.dumps(packed)) < len(json.dumps(rows))
    assert wf.reducer.canonical(wf.expand_grid(packed)) == wf.reducer.canonical(before)
    assert rows == before


def test_reuse_completed_prefix_never_runs_ep_ec_ev_again(tmp_path, monkeypatch):
    inputs = source_inputs(tmp_path/'inputs'); calls = stubbed_provider(monkeypatch)
    first = tmp_path/'first'; second = tmp_path/'second'
    wf.run(inputs, first, until='EV')
    original = {str(p): p.read_bytes() for p in first.rglob('*') if p.is_file()}
    def forbidden(*args, **kwargs):
        raise AssertionError('Completed stage must not execute again')
    monkeypatch.setattr(wf.eda_ec, 'execute', forbidden)
    monkeypatch.setattr(wf.eda_ev, 'render', forbidden)
    monkeypatch.setattr(ep, 'prepare', forbidden)
    assert wf.run(inputs, second, completed_run=first)['status'] == 'WAITING_FOR_HUMAN_REVIEW'
    assert calls == ['EP-plan', 'EP-finalize', 'EI-findings', 'ER-review']
    assert all(Path(p).read_bytes() == content for p,content in original.items())
    assert all(read_json(second/(s+'.receipt.json'))['execution_repeated'] is False for s in ['EP','EC','EV'])
    wf.run(inputs, second, completed_run=first)
    assert len(calls) == 4


def test_completed_prefix_tampering_stops_before_model(tmp_path, monkeypatch):
    inputs = source_inputs(tmp_path/'inputs'); calls = stubbed_provider(monkeypatch)
    first = tmp_path/'first'
    wf.run(inputs, first, until='EV')
    (first/'EV/TASK0001.html').write_text('Changed', encoding='utf-8')
    with pytest.raises(Exception, match='Changed input'):
        wf.run(inputs, tmp_path/'second', completed_run=first)
    assert calls == ['EP-plan', 'EP-finalize']


def test_r_json_precision_roundtrip_and_legacy_regression(tmp_path):
    import subprocess
    import os
    values = [1/12, 0.1, 1.2345678901234567, 1.2345678901234567e-20, 1.2345678901234567e20]
    source = write_json(tmp_path/'values.json', values)
    script = tmp_path/'roundtrip.R'
    script.write_text("a <- commandArgs(TRUE)\nv <- jsonlite::read_json(a[[1]])\njsonlite::write_json(v,a[[2]],digits=17,auto_unbox=TRUE)\njsonlite::write_json(v,a[[3]],digits=NA,auto_unbox=TRUE)\n", encoding='utf-8')
    environment = dict(os.environ)
    environment['R_LIBS_USER'] = str(Path(ep.rscript_path()).parents[2]/'R-library')
    completed = subprocess.run([ep.rscript_path(), '--vanilla', str(script), str(source),
                               str(tmp_path/'fixed.json'), str(tmp_path/'legacy.json')], capture_output=True, text=True, env=environment)
    assert completed.returncode == 0, completed.stderr
    assert read_json(tmp_path/'fixed.json') == values
    assert read_json(tmp_path/'legacy.json')[0] != values[0]


def test_bound_review_schema_rejects_dataset_rows_and_nested_targets():
    from jsonschema import Draft202012Validator
    inputs = {'eda_plan': {'analyses': [{'analysis_id':'A1'}, {'analysis_id':'A1_DEFERRED'}]},
              'figure_bundle': {'artifacts': [{'artifact_id':'TASK0001'}]},
              'calculation_bundle': {'source_tables': {'D1': {'records':[{'record_id':'D1:R1'}]}}}}
    schema = wf.response_schema('EI', inputs)
    rows = schema['properties']['findings']['items']['properties']['record_scope']
    Draft202012Validator(rows).validate(['D1:R1'])
    Draft202012Validator(rows).validate([])
    assert list(Draft202012Validator(rows).iter_errors(['D1']))
    scope = schema['properties']['input_refs']['properties']['analysis_ids']
    assert list(Draft202012Validator(scope).iter_errors(['A1']))
    Draft202012Validator(scope).validate(['A1','A1_DEFERRED'])
    target = wf.response_schema('ER', inputs)['properties']['issues']['items']['properties']['affected_artifact']
    Draft202012Validator(target).validate('eda_findings')
    assert list(Draft202012Validator(target).iter_errors('eda_findings.findings'))


def test_review_projection_keeps_analysis_task_ids_explicit(tmp_path, monkeypatch):
    from research_pipeline import context_model_view as cmv
    inputs = source_inputs(tmp_path/'inputs'); stubbed_provider(monkeypatch)
    root = tmp_path/'run'; wf.run(inputs, root, until='EV')
    review = wf.review_inputs(root,'EI')
    # Repeated task associations must not become modal defaults/missing cells.
    review['calculation_bundle']['results'] *= 4
    bundle = eda_context.prepare('EI-findings', review, wf.response_schema('EI',review))
    visible, audit = cmv.project(bundle['request'])
    assert visible['payload']['calculation_bundle'] == review['calculation_bundle']
    assert visible['payload']['eda_plan'] == review['eda_plan']
    assert all(t['analysis_id']=='A1' for t in visible['payload']['calculation_bundle']['results'])
    assert 'calculation_bundle' in audit['minimal_context']['readable_sections_without_reencoding']


def test_optional_interpretation_requires_alternative_only_when_present():
    from jsonschema import Draft202012Validator
    schema = wf.response_schema('EI')['properties']['findings']['items']
    raw = {'finding_id':'F1','analysis_ids':['A1'],'artifact_refs':[],'record_scope':[],
           'observation':'Reported observation.', 'interpretation_if_useful':'',
           'alternative_if_interpretation':'','downstream_implication':'Descriptive only.'}
    Draft202012Validator(schema).validate(raw)
    inputs = {'eda_plan':{'analyses':[{'analysis_id':'A1','dataset_ids':[]}]},
              'figure_bundle':{'artifacts':[]},'calculation_bundle':{'source_tables':{}}}
    response = {'version':'TEST','input_refs':{'analysis_ids':['A1'],'artifact_ids':[]},
                'findings':[raw],'limitations':[],'open_items':[]}
    wf.validate_output('EI',response,inputs)
    raw['interpretation_if_useful']='A hypothesis.'
    with pytest.raises(ValueError,match='alternative explanation'):
        wf.validate_output('EI',response,inputs)
    raw['observation']=''
    assert list(Draft202012Validator(schema).iter_errors(raw))


def test_saved_ei_reuses_exact_response_without_second_model_call(tmp_path,monkeypatch):
    inputs=source_inputs(tmp_path/'inputs');calls=stubbed_provider(monkeypatch)
    prefix=tmp_path/'prefix';first=tmp_path/'first';second=tmp_path/'second'
    wf.run(inputs,prefix,until='EV')
    wf.run(inputs,first,completed_run=prefix,until='EI')
    before=(first/'EI/output.json').read_bytes()
    wf.run(inputs,second,completed_run=prefix,saved_ei=first/'EI')
    assert calls==['EP-plan','EP-finalize','EI-findings','ER-review']
    assert (first/'EI/output.json').read_bytes()==before
    assert read_json(second/'EI/output.json')==read_json(first/'EI/output.json')
    assert read_json(second/'EI/reused_response.json')['new_model_call'] is False
