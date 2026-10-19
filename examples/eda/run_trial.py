"""Latest cleaned-source subset -> existing TEST EP/EC/EV; no EI/ER or production enablement."""
import copy,json,re,time,traceback
from collections import defaultdict
from decimal import Decimal,InvalidOperation
from pathlib import Path
from ctxcomp import providers
from research_pipeline import context_builder as cb,project_rule_agent,eda_ep_execution as bridge
from research_pipeline import eda_ep,eda_ep_transport,eda_ec,eda_ev
from research_pipeline.common import read_json,write_json,utcnow
from research_pipeline.context_linear import export_preview
from jsonschema import Draft202012Validator
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
RUN=ROOT/'outputs/Data_Cleaning_Rerun_20261016/run04'
MODEL='gpt-6-luna'
SELECTED=['T0028','T0013','T0010']

def equal_source(raw,text):
    if isinstance(raw,(int,float)) and not isinstance(raw,bool):
        try:return Decimal(str(raw))==Decimal(text)
        except InvalidOperation:return False
    return ('' if raw is None else str(raw))==text

def build_inputs():
    context=read_json(RUN/'inputs/context.json')
    main=read_json(context['upstream_main']['path'])
    rules=project_rule_agent.validate_effective_context(main)['rules']
    source=read_json(context['upstream_data']['source_view']['path'])
    inventory=read_json(context['inventory']['path'])
    datasets=read_json(RUN/'data_preparation/normalization_manifest.json')['datasets']
    handoff=read_json(RUN/'data_preparation/handoffs/eda_context.json')
    report=read_json(RUN/'data_preparation/data_report.json')
    profiles={x['item_id']:x for x in source['profiles']}
    registry=read_json(bridge.REGISTRY)
    items=[];cell_checks=0;adaptations=[]
    for id,operation in zip(SELECTED,registry['operations'].values()):
        d=next(x for x in datasets if x['id']==id)
        assert id in report['ready_dataset_ids']
        assert any(x['id']==id for x in handoff['files'])
        sid=d['metadata']['source_item_id'];profile=profiles[sid]
        assert d['metadata']['record_level']==profile['record_level']
        records=read_json(d['data']['path'])['records']
        assert not read_json(d['quarantine']['path'])['records']
        for row in records:
            for key,cell in row['source_cells'].items():
                assert equal_source(row['source_raw_values'][key],source['source_units'][sid+':'+cell]),(id,cell)
                cell_checks+=1
        by_row=defaultdict(list);numbers={r['source_row'] for r in records}
        headers={c['column']:c['header'] for c in profile['columns']}
        for key,value in source['source_units'].items():
            if key==sid:
                by_row[None].append({'column':'__metadata__','header':None,'source_id':key,'raw_value':value})
            elif key.startswith(sid+':'):
                match=re.fullmatch(r'([A-Z]+)([0-9]+)',key[len(sid)+1:]);assert match,key
                col,n=match[1],int(match[2])
                by_row[n].append({'column':col,'header':headers.get(col) if n in numbers else None,
                                 'source_id':key,'raw_value':value})
        rows=[]
        for n in sorted(by_row,key=lambda n:-1 if n is None else n):
            cells=by_row[n]
            rows.append({'dataset_id':sid,'source_row':n,
                'row_type':'SOURCE_METADATA' if n is None else 'SOURCE_ROW' if n in numbers else 'NOTE',
                'role':profile['role'],'record_level':profile['record_level'],'record_kind':'TABLE',
                'cells':cells,'row_source_ids':[c['source_id'] for c in cells]})
        assert len([r for r in rows if r['row_type']=='SOURCE_ROW'])==len(records)
        items.append({'item_id':sid,'profile':profile,'source_rows':rows,'source_binding':{
            'cleaned_data':d['data'],'metadata':d['metadata_file'],'observation_view':d['observation_view'],
            'cleaning_report':cb.file_ref(RUN/'data_preparation/data_report.json'),
            'authorized_display_handoff':cb.file_ref(RUN/'data_preparation/handoffs/eda_context.json')}})
        old_id=operation['dataset_id'];operation['dataset_id']=sid
        operation['experimental_unit']=profile['record_level']
        assert operation['role']==profile['role']
        for col,unit in operation['units'].items():
            assert next(c['unit'] for c in profile['columns'] if c['column']==col)==unit
        adaptations.append({'cleaned_dataset_id':id,'source_item_id':sid,'template_source_item_id':old_id,
            'same_vetted_display_and_column_roles':True,'source_rows':len(records)})
    latest_rules=copy.deepcopy(rules)
    prototype=read_json(ROOT/'outputs/EDA_ContextBuilder_TEST_20261015/ep_inputs.json')
    fixture=copy.deepcopy(prototype['task_context']['fixture_scope'])
    fixture['authorized_item_ids']=[i['item_id'] for i in items]
    selected_targets=set(SELECTED)|set(fixture['authorized_item_ids'])
    limitations=['Latest cleaning permits separate-series descriptive display only. TEST admission describes this EDA adapter, not a new scientific release.',
        'No cross-table, regimen-to-response, animal or matrix joins; no fits, NCA, target estimation or PTA.',
        'Keep digitized time as source-reported plotted time; an exact dose-relative time origin is not established by this trial.',
        'T0013 uses its own source-table baseline only. T0010 is strain-level MIC, not a population distribution.']
    limitations += [f['affected_id']+': '+f['reason'] for f in report['findings']
                   if set(re.split(r'[,;\s]+',f['affected_id']))&selected_targets]
    inputs={'data_handoff':{'status':eda_ep.TEST_STATUS,'admission':'FIXTURE_ONLY_UNVERIFIED_FOR_PRODUCTION',
        'source_items':items,'source_view_ref':context['upstream_data']['source_view'],
        'inventory_ref':context['inventory'],'scope_note':'Three latest cleaned tables, source-cell values verified against run04; registered TEST display templates only.',
        'unresolved_and_limitations':limitations},
        'task_context':{'objective':main['objective'],'study':main.get('study',{}),
            'project_rules':latest_rules,'scientific_context':main.get('scientific_context',{}),
            'fixture_scope':fixture,'implemented_r_operations':prototype['task_context']['implemented_r_operations'],
            'not_implemented_operations':prototype['task_context']['not_implemented_operations']}}
    registry_path=write_json(OUT/'operation_registry.test.json',registry)
    bridge.REGISTRY=registry_path
    write_json(OUT/'source_selection.json',{'datasets':adaptations,'verified_cleaned_cells':cell_checks,
        'cleaning_handoff':cb.file_ref(RUN/'data_preparation/handoffs/eda_context.json'),
        'registry_changes':'Dataset IDs and exact source record-level wording only; no new plotting handlers or statistics.',
        'not_covered':['individual concentration series','censored time-kill','population MIC distribution'],
        'production_eda_enabled':False})
    return write_json(OUT/'ep_inputs.json',inputs),Path(context['upstream_main']['path'])

def main():
    if (OUT/'gateway_run').exists():raise ValueError('Existing attempt is immutable.')
    started=time.perf_counter();state={'started_at':utcnow(),'requested_model':MODEL,'scientific_release':False,
        'EI_started':False,'ER_started':False,'provider_calls':0,'status':'PREPARING_TEST'}
    write_json(OUT/'run_status.json',state)
    try:
        inputs,main_input=build_inputs()
        selection=[{'path':['scientific_reference','text'],'catalog':cb.file_ref(bridge.CATALOG),
                    'selected':['01','02','03','06','08','11','15']}]
        prepared,audit=bridge.prepare(inputs,rule_context_path=main_input,reference_selection=selection)
        export_preview(prepared['request'],OUT/'ep_context');write_json(OUT/'intake_audit.json',audit)
        strict=eda_ep_transport.schema(prepared['request']['payload']['schema'],read_json(bridge.REGISTRY),
                                      scope=bridge._semantic_scope(prepared)[1])
        write_json(OUT/'strict_transport_schema.json',strict)
        state.update(status='EP_RUNNING',provider_calls=1);write_json(OUT/'run_status.json',state)
        ep_started=time.perf_counter()
        raw=providers.codex_generate(prepared['request'],model=MODEL,timeout=None,
                                    cli_schema=strict,context_scope=OUT/'gateway_run')
        state['ep_seconds']=round(time.perf_counter()-ep_started,3)
        Draft202012Validator(prepared['request']['payload']['schema']).validate(raw)
        slots=list((OUT/'gateway_run/contextbuilder').glob('*/response.json'));assert len(slots)==1
        receipt=OUT/'ep_model_receipt.json'
        bridge.record_model_plan(OUT/'ep_context/request.json',slots[0].parent,receipt)
        frozen=bridge.freeze(receipt)
        state['planned_tasks']=[t['operation_id'] for t in frozen['request']['tasks']]
        ec_started=time.perf_counter();eda_ec.execute(frozen,OUT/'ec')
        state['ec_seconds']=round(time.perf_counter()-ec_started,3)
        ev_started=time.perf_counter();figures=eda_ev.render(receipt,OUT/'ec/calculation_bundle.json',OUT/'ev')
        state['ev_seconds']=round(time.perf_counter()-ev_started,3)
        state.update(status='EP_EC_EV_RENDERED_AWAITING_VISUAL_INSPECTION',figure_count=len(figures['figures']),
            omissions=figures['omissions'],served_model_verified=False)
    except BaseException as exc:
        state.update(status='FAILED_RETAINED',error=str(exc),traceback=traceback.format_exc());raise
    finally:
        state.update(elapsed_seconds=round(time.perf_counter()-started,3),finished_at=utcnow())
        write_json(OUT/'run_status.json',state);print(json.dumps(state,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
