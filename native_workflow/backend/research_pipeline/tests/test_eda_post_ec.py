"""Bounded EP result-review tests with real R and stubbed model responses."""
import copy
from pathlib import Path
import pytest
from ctxcomp import providers
from research_pipeline import eda_post_ec as post, eda_workflow as wf, eda_context
from research_pipeline import context_builder as cb, context_model_view as cmv
from research_pipeline.common import read_json, write_json
from research_pipeline.minimal_context_reducer import expand_payload
from test_eda_workflow import source_inputs, stubbed_provider


def setup_ec(tmp_path, monkeypatch):
    inputs=source_inputs(tmp_path/'inputs');calls=stubbed_provider(monkeypatch)
    root=tmp_path/'run';wf.run(inputs,root,until='EC')
    return inputs,root,calls


def response(frozen):
    return {'version':'EP_FINAL_DISPLAYS_1.0','summary':'Synthetic display decisions.',
        'task_decisions':[{'task_id':t['task_id'],'decision':'KEEP','operation_id':t['operation_id'],
            'selection':copy.deepcopy(t['selection']),'reason':'Supported source display.','additional_note':''}
            for t in frozen['tasks']], 'open_items':[]}


def test_method_library_covers_questions_and_registered_plot_cards():
    _,_,_,_,ref,_=eda_context._contract('EP-plan')
    methods=ref['analysis_method_library']['methods']
    cards={c['id'] for c in ref['plot_method_library']['methods']}
    assert len(methods)==21 and len({m['id'] for m in methods})==21
    assert set().union(*(set(m['plot_method_ids']) for m in methods))==cards
    for method in methods:
        assert all(method[k] for k in ['question','required_context','ec_preparation','post_ec_decision'])


def test_finalizer_context_has_results_without_repeated_source_tables(tmp_path,monkeypatch):
    _,root,_=setup_ec(tmp_path,monkeypatch)
    bundle=post.prepare(root);cb.verify_bundle(bundle)
    visible,_=cmv.project(bundle['request']);payload=expand_payload(visible['payload'])
    assert payload['stage']=='EP-finalize'
    assert 'reading_views' not in payload['data_handoff']
    assert 'dataset_catalog' not in payload['task_context']
    t=payload['calculation_bundle']['tasks'][0]
    assert 'records' not in t and t['record_count']==2
    assert t['status_counts']['y']=={'QUANTIFIED':1,'CENSORED':1}
    assert t['plot']['points'][0]['x']==1/12
    assert payload['processing_rules']==eda_context._fixed_sections(*_fixed_args())['processing_rules']


def _fixed_args():
    pack,call,_,instructions,reference,_=eda_context._contract('EP-plan')
    return pack,call,instructions,reference


def test_resume_runs_one_review_without_repeating_ec_and_adjusts_ev(tmp_path,monkeypatch):
    inputs,root,calls=setup_ec(tmp_path,monkeypatch)
    ec_before=(root/'EC/result.json').read_bytes()
    stub=providers._codex_generate_raw
    def change(req,**kw):
        result=stub(req,**kw)
        if req['payload']['stage']=='EP-finalize':
            d=result['task_decisions'][0];d['decision']='ADJUST';d['selection']['y_scale']='log10'
            d['additional_note']='Display only; censored placeholder remains in the source table.'
        return result
    monkeypatch.setattr(providers,'_codex_generate_raw',change)
    wf.run(inputs,root,until='EV')
    assert calls==['EP-plan','EP-finalize']
    assert (root/'EC/result.json').read_bytes()==ec_before
    final=read_json(root/'EV/render_input.json')['tasks'][0]
    assert final['selection']['y_scale']=='log10'
    assert final['records']==read_json(root/'EC/result.json')['tasks'][0]['records']
    plotted=read_json(root/'EV/TASK0001.plotted_rows.json')
    assert plotted['points'][0]['x']==1/12 and plotted['excluded'][0]['record_id']=='D1:R2'
    assert (root/'EV/TASK0001.png').read_bytes().startswith(b'\x89PNG')
    review=wf.review_inputs(root,'EI')
    assert 'Display only;' in review['calculation_bundle']['analysis_contexts']['TASK0001']['annotations']
    assert review['eda_plan']['post_ec_display_review']['task_decisions'][0]['decision']=='ADJUST'
    wf.run(inputs,root,until='EV');assert calls==['EP-plan','EP-finalize']


@pytest.mark.parametrize('kind',['task_id','dataset','axis','keep_changed','renderer'])
def test_invalid_display_decision_is_rejected(tmp_path,monkeypatch,kind):
    _,root,_=setup_ec(tmp_path,monkeypatch)
    frozen=read_json(root/'EP/accepted/ec_request.json');raw=response(frozen);d=raw['task_decisions'][0]
    if kind=='task_id': d['task_id']='UNKNOWN'
    elif kind=='dataset': d['selection']['dataset_id']='OTHER'
    elif kind=='axis': d['decision']='ADJUST';d['selection']['x']='missing_column'
    elif kind=='keep_changed': d['selection']['x_scale']='log10'
    else: d['operation_id']='UNIMPLEMENTED_BOXPLOT'
    with pytest.raises(Exception):post.apply(raw,frozen)


def test_failed_review_stops_before_ev_without_retry(tmp_path,monkeypatch):
    inputs,root,calls=setup_ec(tmp_path,monkeypatch)
    stub=providers._codex_generate_raw
    def invalid(req,**kw):
        result=stub(req,**kw)
        if req['payload']['stage']=='EP-finalize':result['task_decisions']=[]
        return result
    monkeypatch.setattr(providers,'_codex_generate_raw',invalid)
    with pytest.raises(Exception):wf.run(inputs,root,until='EV')
    assert calls==['EP-plan','EP-finalize'] and not (root/'EV').exists()
    with pytest.raises(ValueError,match='no automatic retry'):wf.run(inputs,root,until='EV')
    assert calls==['EP-plan','EP-finalize']


def test_defer_preserves_rows_and_notes_in_table_fallback(tmp_path,monkeypatch):
    _,root,_=setup_ec(tmp_path,monkeypatch)
    frozen=read_json(root/'EP/accepted/ec_request.json');raw=response(frozen);d=raw['task_decisions'][0]
    d.update(decision='DEFER',operation_id='SOURCE_TABLE',reason='A required graphical feature is unavailable.')
    d['selection'].update(x='',y='',group_by='',x_scale='linear',y_scale='linear')
    final=post.apply(raw,frozen)[0];original=frozen['tasks'][0]
    assert final['records']==original['records'] and final['notes']==original['notes']
    assert final['context']['caption_limits']==original['context']['caption_limits']
    assert final['plot']=={'points':[],'excluded':[]}


def test_distinct_panel_notes_reach_ei_without_overwriting_each_other(tmp_path,monkeypatch):
    inputs=source_inputs(tmp_path/'inputs');calls=stubbed_provider(monkeypatch)
    stub=providers._codex_generate_raw
    def panels(req,**kw):
        raw=stub(req,**kw)
        if req['payload']['stage']=='EP-plan':
            series=raw['analyses'][0]['execution']['series']
            second=copy.deepcopy(series[0]);second['y_scale']='log10';series.append(second)
        elif req['payload']['stage']=='EP-finalize':
            for i,d in enumerate(raw['task_decisions']):d['additional_note']='Distinct panel note '+str(i)
        return raw
    monkeypatch.setattr(providers,'_codex_generate_raw',panels)
    root=tmp_path/'run';wf.run(inputs,root,until='EV')
    review=wf.review_inputs(root,'EI')
    contexts=review['calculation_bundle']['analysis_contexts']
    assert 'Distinct panel note 0' in contexts['TASK0001']['annotations']
    assert 'Distinct panel note 1' in contexts['TASK0002']['annotations']
    assert review['figure_bundle']['artifacts'][1]['context_location'].endswith('TASK0002')
    assert calls==['EP-plan','EP-finalize']


def test_table_can_be_promoted_to_supported_source_points(tmp_path,monkeypatch):
    inputs=source_inputs(tmp_path/'inputs');calls=stubbed_provider(monkeypatch)
    stub=providers._codex_generate_raw
    def promote(req,**kw):
        raw=stub(req,**kw)
        if req['payload']['stage']=='EP-plan':
            ex=raw['analyses'][0]['execution'];ex['operation_id']='SOURCE_TABLE'
            ex['series'][0].update(x='',y='',group_by='')
        elif req['payload']['stage']=='EP-finalize':
            d=raw['task_decisions'][0];d.update(decision='ADJUST',operation_id='SOURCE_XY_POINTS')
            d['selection'].update(x='x',y='y')
        return raw
    monkeypatch.setattr(providers,'_codex_generate_raw',promote)
    root=tmp_path/'run';wf.run(inputs,root,until='EV')
    before=read_json(root/'EC/result.json')['tasks'][0]
    after=read_json(root/'EV/render_input.json')['tasks'][0]
    assert before['operation_id']=='SOURCE_TABLE' and before['plot']['points']==[]
    assert after['operation_id']=='SOURCE_XY_POINTS' and len(after['plot']['points'])==1
    assert before['records']==after['records']
    assert (root/'EV/TASK0001.png').is_file() and calls==['EP-plan','EP-finalize']


def test_post_ec_unresolved_work_survives_to_human_packet(tmp_path,monkeypatch):
    inputs=source_inputs(tmp_path/'inputs');stubbed_provider(monkeypatch)
    stub=providers._codex_generate_raw
    def defer(req,**kw):
        raw=stub(req,**kw)
        if req['payload']['stage']=='EP-finalize':
            d=raw['task_decisions'][0]
            d.update(decision='DEFER',operation_id='SOURCE_TABLE',reason='Synthetic status-strip renderer is unavailable.')
            d['selection'].update(x='',y='',group_by='',x_scale='linear',y_scale='linear')
            raw['open_items']=['Synthetic future calculation remains unimplemented.']
        return raw
    monkeypatch.setattr(providers,'_codex_generate_raw',defer)
    root=tmp_path/'run';wf.run(inputs,root)
    packet=read_json(root/'human_review.json')
    assert 'Synthetic future calculation remains unimplemented.' in packet['summary']['open_items']
    assert any('TASK0001: graphical display deferred' in x for x in packet['summary']['open_items'])
    assert packet['human_confirmation'] is None and not (root/'eda_handoff.json').exists()
