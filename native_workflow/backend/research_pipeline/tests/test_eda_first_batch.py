"""Offline v6 tests: real builders/dispatch/accounting; only model/R transports stubbed."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from ctxcomp import providers
from research_pipeline import context_builder as cb, eda_plot_policy as policy
from research_pipeline.common import read_json, write_json


def axis(header='Dose interval (h)', **column):
    t = {'D': {'columns': [dict(id='x', meaning='TIME', unit='h', header=header, **column)]}}
    s = {'kind': 'source_projection', 'x_label': header, 'source_recipe': {'series': [{'dataset_id': 'D', 'x': 'x'}]}}
    policy._axis(s, t)
    return s, t


def test_interval_semantics_and_ticks_are_not_elapsed_time():
    s, t = axis()
    assert s['x_label'] == 'Dose interval (h)'
    assert policy.axis_detail_policy(s, t)['enabled'] is False


@pytest.mark.parametrize('header,extra,expected', [
    ('Time (h)', {}, 'Time (h)'), ('Nominal time (h)', {}, 'Nominal sampling time (h)'),
    ('Pixel time (h)', {}, 'Digitized time (h)'),
    ('Time after infusion end (h)', {}, 'Time after infusion end (h)'),
    ('Time (h)', {'time_origin': 'study start'}, 'Time relative to study start (h)')])
def test_source_time_basis_and_origin(header, extra, expected):
    s, _ = axis(header, **extra); assert s['x_label'] == expected


def fixture(tmp_path):
    """Three explicit released Data datasets, including BLQ and context-only evidence."""
    main = write_json(tmp_path/'main.json', {'objective': 'Synthetic descriptive PK/PD', 'study': {'population': 'nonhuman'},
        'scientific_context': {'boundary': 'offline fixture'}, 'missing_information': {'items': []}})
    review = write_json(tmp_path/'rules_review.json', {'decision': 'PASS'})
    rules = write_json(tmp_path/'rules.json', {'status': 'PROJECT_RULES_PUBLISHED', 'context_contract': 'SOURCE_CONTEXT_REFERENCE_1.0',
        'main_ref': cb.file_ref(main), 'review_ref': cb.file_ref(review),
        'rules': [{'id': 'R1', 'text': 'Preserve source values, statuses and unknown identities.', 'used_in': ['eda', 'animal_pk', 'index']}]})
    files=[]; states=[]; raw=[]
    for did, role, meaning in [('D1','PK_OBSERVATIONS','CONCENTRATION'),('D2','PD_OBSERVATIONS','RESPONSE'),('D3','SUPPORTING_EVIDENCE','CONCENTRATION')]:
        source = tmp_path/(did+'.source.txt'); source.write_text('fixture source '+did,encoding='utf8')
        records = [dict(record_id=did+'R'+str(i), source_file_id='F'+did, source_sha256=cb.file_ref(source)['sha256'],
            source_sheet='S', source_row=i+1, source_cells={'x':'A'+str(i+1),'y':'B'+str(i+1)},
            source_raw_values={'x':i,'y':y}, value_status={'x':'QUANTIFIED','y':'BLQ' if y=='<0.2' else 'QUANTIFIED'})
            for i,y in enumerate([2,1,'<0.2'],1)]
        data = write_json(tmp_path/(did+'.json'), {'records': records})
        metadata = write_json(tmp_path/(did+'.meta.json'), {'metadata': {'source_item_id':'S'+did, 'role':role,
            'record_level':'INDEPENDENT_SOURCE_RECORDS', 'species':'Mouse', 'source_ref':cb.file_ref(source),
            'source_table':{'title':'Fixture '+did,'notes':'No verified longitudinal identity; source status unchanged.','column_map':{'x':'Time (h)','y':'Source response'}},
            'columns':[{'column':'A','header':'Time (h)','unit':'h','meaning':'TIME','time_role':'NOMINAL_TIME'},
                       {'column':'B','header':'Source response','unit':'mg/L' if meaning=='CONCENTRATION' else 'log10 CFU/mL','meaning':meaning}]},'source_refs':[cb.file_ref(source)]})
        files.append({'id':did,'role':role,'data':cb.file_ref(data),'metadata_file':cb.file_ref(metadata)})
        states.append({'dataset_id':did,'actions':{'DESCRIPTIVE_EDA':{'status':'READY'}},'operation_restrictions':['NO_INFERRED_IDENTITIES']})
        raw.append(records)
    manifest = write_json(tmp_path/'normalization_manifest.json', {'datasets':files})
    h = write_json(tmp_path/'eda_context.json', {'status':'READY_FOR_EDA','allowed_action':'DESCRIPTIVE_EDA','scientific_release':False,'fit_ready':False,
        'files':files,'dataset_action_readiness':states,'full_manifest':cb.file_ref(manifest),'rules_ref':cb.file_ref(rules),
        'task_requirements':[],'unknowns':[],'unresolved_items':[]})
    report = write_json(tmp_path/'data_report.json', {'status':'TECHNICAL_DATA_READY','execution_scope':'DESCRIPTIVE_EDA_ONLY',
        'fit_ready':False,'scientific_release':False,'normalization_manifest':cb.file_ref(manifest),'upstream':{'main':cb.file_ref(main)}})
    return h, report, raw


def test_dh_build_is_source_preserving_and_role_bound(tmp_path):
    from research_pipeline import eda_dh_adapter as dh, eda_questions_v6 as q
    h, r, raw = fixture(tmp_path)
    built = dh.build(h,r,tmp_path/'adapter')
    _, tables, views, catalog, _, bindings, _ = q.intake(built['inputs'],None,built['catalog'])
    assert [tables[k]['records'] for k in ['D1','D2','D3']] == raw
    assert tables['D1']['metadata']['role'] == 'PK' and tables['D3']['metadata']['role'] == 'CONTEXT'
    assert tables['D1']['columns'][0]['time_role'] == 'NOMINAL_TIME'
    assert len(views) == 3  # PK linear + semilog, PD points; context remains a table.
    assert all('D3' not in q.candidate_datasets(v) for v in views.values())
    assert 'completed_ec_receipt' not in bindings and 'source_snapshot' in bindings
    assert catalog['match_report'] and all(x['status']=='NOT_APPLIED' for x in catalog['match_report'])
    assert read_json(built['snapshot_receipt']['path'])['model_calls'] == 0


@pytest.mark.parametrize('mutation,match', [
    ('missing','dataset_action_readiness'),('permission','permission denied'),('role','UNRESOLVED'),('source','Changed input'),('context','binding differs')])
def test_dh_boundary_failures_are_explicit(tmp_path,mutation,match):
    from research_pipeline import eda_dh_adapter as dh
    h,r,_=fixture(tmp_path); value=read_json(h)
    if mutation=='missing': value.pop('dataset_action_readiness')
    elif mutation=='permission': value['dataset_action_readiness'][0]['actions']['DESCRIPTIVE_EDA']['status']='RESTRICTED'
    elif mutation=='source':
        Path(value['files'][0]['data']['path']).write_text('{}',encoding='utf8')
    elif mutation=='role':
        meta=read_json(value['files'][0]['metadata_file']['path'])['metadata'];meta['role']='SOURCE_TABLE'
        projected=dh.project_role(meta,'PK_OBSERVATIONS')
        assert projected['role_resolution']==match and not projected['observation_role'];return
    else:
        report=read_json(r);other=write_json(tmp_path/'other.json',{'objective':'wrong'});report['upstream']['main']=cb.file_ref(other);write_json(r,report)
    write_json(h,value)
    with pytest.raises((ValueError,KeyError),match=match):dh.build(h,r,tmp_path/'adapter')


def test_recipe_signature_missing_ambiguous_and_notes_dependency(tmp_path,monkeypatch):
    from research_pipeline import eda_display_catalog as dc
    from research_pipeline import eda_dh_adapter as dh
    h,r,_=fixture(tmp_path);built=dh.build(h,r,tmp_path/'adapter')
    table=read_json(tmp_path/'adapter/source_snapshot.json')['tasks'][0]
    # A minimal source recipe with the existing materializer and strict signature.
    spec=dh.candidates([table])[0][0];recipe=spec['source_recipe'];recipe['id']='REGISTERED'
    recipe['sources']={'ORIGINAL':{'title':table['title'],'columns':[{k:c[k] for k in ('id','header','unit','meaning')} for c in table['columns']],
        'notes_sha256':hashlib.sha256(table['notes'].encode()).hexdigest()}}
    for s in recipe['series']:s['dataset_id']='ORIGINAL'
    path=write_json(tmp_path/'recipes.json',{'recipes':[recipe]});monkeypatch.setattr(dc,'RECIPES',path)
    report=[];assert 'REGISTERED' in dc.augment({}, {'D1':table},match_report=report)
    assert report[0]['status']=='MATCHED'
    table['notes']+=' Identity/time qualification changed.'
    report=[];assert dc.augment({}, {'D1':table},match_report=report)=={}
    assert report[0]['dependencies'][0]['status']=='MISSING' and 'notes_sha256' in report[0]['dependencies'][0]['required_fields']
    table['notes']=table['notes'].replace(' Identity/time qualification changed.','')
    report=[];assert dc.augment({}, {'D1':table,'OTHER':table},match_report=report)=={}
    assert report[0]['dependencies'][0]['status']=='AMBIGUOUS'


def deref(node,schema):
    return deref(schema['$defs'][node['$ref'].split('/')[-1]],schema) if '$ref' in node else node


def stub_transports(monkeypatch, decision='REVISE', omit_final_pk=False):
    from research_pipeline import eda_questions_v6 as q, eda_display_catalog_v5 as dc
    seen=[]
    def model(request, **kwargs):
        stage=request['payload']['stage'];seen.append(stage)
        schema=request['payload']['schema']
        props=schema['properties']
        if stage in {'EP-plan','EP-finalize'}:
            arr=deref(props['analyses' if stage=='EP-plan' else 'task_decisions'],schema)
            analysis=deref(arr['items'],schema)['properties'];view=deref(deref(analysis['views'],schema)['items'],schema)['properties']
            vids=deref(view['view_id'],schema)['enum'];analyses=[]
            for aid,question in q.QUESTIONS:
                selected=vids if aid=='Q_CONTEXT' else []
                if omit_final_pk and stage=='EP-finalize':selected=[v for v in selected if 'DEFAULT_LOG10' not in v]
                analyses.append(dict(analysis_id=aid,question=question,objective_link='Fixture objective',understanding_needed='Preserve evidence and limits.',
                    next_modeling_action='Input qualification only.',dataset_ids=['D1','D2','D3'],
                    views=[dict(view_id=v,purpose='Inspect source records.',scale_rationale='Linear absolute values or semilog positive values, no transformations.',complementary_value='Different supported response scale.') for v in selected],
                    record_level_and_grouping='Independent source records; no lines.',uncertainty_and_status='No invented uncertainty; BLQ retained.',
                    status='PLANNED' if selected else 'NOT_APPLICABLE',reason='Fixture scope.',remaining_unknowns=[],
                    modeling_preparation=dict(usable_now='Source records.',preferred_action='Input qualification.',why='Identity unresolved.',conditional_alternatives=[],essential_clarifications=[])))
            dispositions=[dict(dataset_id=did,status='CONTEXT_ONLY' if did=='D3' else 'DISPLAYED',reason='Retain original evidence within this descriptive fixture scope.',
                handoff=dict(destinations=['PK'] if did!='D2' else ['PD'],role='CONTEXT' if did=='D3' else 'OBSERVATIONS',purpose='Source-grounded input qualification.',pending_checks=['No verified repeated identity.'])) for did in ['D1','D2','D3']]
            result=dict(version='QUESTION_DRIVEN_2',input_refs={'dataset_ids':['D1','D2','D3']},objective='Fixture',analyses=analyses,not_planned=[],open_items=[],dataset_dispositions=dispositions) if stage=='EP-plan' else dict(version='QUESTION_FINAL_2',summary='Fixture decisions.',task_decisions=analyses,open_items=[],dataset_dispositions=dispositions)
        elif stage=='EI-findings':
            result={'version':'QUESTION_FINDINGS_3','input_refs':['SOURCE_TABLES'],'findings':[dict(finding_id='F1',analysis_ids=[x[0] for x in q.QUESTIONS],artifact_refs=['SOURCE_TABLES'],record_scope=[],
                observation='Metadata retains independent source records and BLQ status.',interpretation_if_useful='',alternative_if_interpretation='',downstream_implication='Qualify branch inputs before modeling.',
                visual_support=dict(status='NON_GRAPHICAL',figure_ids=[],features='Existing metadata and handoff decisions only; no EI visual inspection.',limitations=[],element_claims=[]),
                anomaly_assessment=dict(status='NOT_ASSESSED',record_ids=[],observation='Not reassessed during handoff packaging.',possible_explanations=[],recommended_action='Retain existing flags for ER and human review.',affected_analysis='No new anomaly assessment.',data_changed=False))], 'limitations':['Synthetic fixture; R and model transports stubbed.'],'open_items':[]}
        else:
            checks=deref(props['figure_checks'],schema);item=deref(checks['items'],schema)['properties'];ids=deref(item['figure_id'],schema)['enum']
            result=dict(version='QUESTION_REVIEW_1',reviewed_refs=['SOURCE_TABLES'],decision=decision,review_scope='Synthetic offline transport fixture.',
                issues=[] if decision=='PASS' else [dict(issue_id='I1',affected_artifact='SOURCE_TABLES',evidence='Synthetic unresolved review issue.',consequence='No release.',correction_owner='HUMAN',smallest_correction='Resolve in an independently reviewed exact version.')],
                unreviewed_items=[],quality_checks={k:'PASS' for k in ['source_semantics','readability','figure_text_stage_consistency']},
                figure_checks=[dict(figure_id=i,inspection='INSPECTED',note='Synthetic transport fixture only.') for i in ids])
        diag=Path(kwargs['diagnostics_dir']);write_json(diag/'call.json',{'status':'RETURNED','provider':'OFFLINE_STUB','requested_model':kwargs.get('model')})
        return result
    def render(command,**kwargs):
        assert Path(command[2]).name=='source_displays.v5.R', command
        plan=read_json(command[3]);out=Path(command[4]);artifacts=[]
        for p in plan['plots']:
            rows=p['rows'];valid=[r for r in rows if r['y'] is not None and r.get('plot_eligible',True)];missing=[r for r in rows if r not in valid]
            name=p['id'];write_json(out/(name+'.json'),rows);write_json(out/(name+'.context_rows.json'),p.get('context_rows',[]))
            from PIL import Image
            Image.new('RGB',(16,16),'white').save(out/(name+'.png'))
            (out/(name+'.pdf')).write_bytes(b'%PDF-OFFLINE_STUB')
            facts=dict(x_label=p['x_label'],y_label=p['y_label'],figure_index=p['figure_index'],panels=1,
                point_count=len(valid),low_positive_values=[],line_segments=0,x_breaks=sorted({r['x'] for r in rows}),error_bar_count=0,
                status_labels=[r['status_label'] for r in missing],status_display='caption',status_y=[],status_record_ids=[r['record_id'] for r in missing],
                status_note='; '.join(r['status_label'] for r in missing),context_rows=len(p.get('context_rows',[])),zero_qualifications=[],elements=['POINTS','STATUS_TEXT'])
            artifacts.append(dict(id=name,png=name+'.png',pdf=name+'.pdf',data=name+'.json',panels=1,render_facts=facts))
        write_json(out/'manifest.json',{'artifacts':artifacts})
        return SimpleNamespace(returncode=0,stdout='OFFLINE R STUB',stderr='')
    monkeypatch.setattr(providers,'_codex_generate_raw',model)
    monkeypatch.setattr(dc.subprocess,'run',render)
    monkeypatch.setattr(q,'rscript_path',lambda:'OFFLINE_R_STUB')
    return seen


def run_fixture(tmp_path,monkeypatch,decision='REVISE',omit=False):
    from research_pipeline import eda_dh_adapter as dh, eda_questions_v6 as q
    h,r,raw=fixture(tmp_path);built=dh.build(h,r,tmp_path/'adapter');seen=stub_transports(monkeypatch,decision,omit)
    result=q.run_questions(built['inputs'],None,built['catalog'],tmp_path/'run',until='ER')
    return result,seen,raw


def test_real_v6_orchestration_keeps_all_calls_and_mandatory_views(tmp_path,monkeypatch):
    from research_pipeline import eda_review_handoff as gate
    result,seen,raw=run_fixture(tmp_path,monkeypatch,omit=True)
    assert seen==['EP-plan','EP-finalize','EI-findings','ER-review']
    assert result['status']=='REVIEW_REQUIRED' and result['figures']==3
    assert [t['records'] for t in read_json(tmp_path/'run/source_tables.json')]==raw
    assert read_json(tmp_path/'run/verification.json')['status']=='PASS'
    assert read_json(tmp_path/'run/EP_FINALIZE/plan_accounting.json')
    assert read_json(tmp_path/'run/EP_FINALIZE/coverage.json')['recipe_match_report']
    summary=read_json(tmp_path/'run/run_summary.json')
    assert summary['review']['status']=='BLOCKED_INDEPENDENT_REVIEW'
    assert summary['served_models']=='unknown' and not summary['review']['fit_ready']
    decision=read_json(tmp_path/'run/human_decision.template.json');decision.update(actor_type='HUMAN',reviewer='OFFLINE FIXTURE',reviewed_at='2026-10-23T00:00:00Z',decision='APPROVE_DESCRIPTIVE_EDA',images_inspected=True,limitations_acknowledged=True)
    for item in decision['figure_reviews']:item['decision']='ACCEPT'
    path=write_json(tmp_path/'decision.json',decision)
    with pytest.raises(ValueError,match='unresolved independent review'):gate.confirm(tmp_path/'run',path)
    assert not (tmp_path/'run/approved_release.json').exists()


@pytest.mark.parametrize('target',['source','original_source','image','rules'])
def test_changed_bindings_block_exact_packet(tmp_path,monkeypatch,target):
    from research_pipeline import eda_review_handoff as gate
    run_fixture(tmp_path,monkeypatch)
    p=gate.packet(tmp_path/'run')
    key=next(k for k in p['bindings'] if k.startswith('image:')) if target=='image' else 'rules' if target=='rules' else 'source:source:3'
    if target=='original_source':
        path=tmp_path/'D1.source.txt'
    elif target=='source':
        path=tmp_path/'D1.json'
    elif target=='rules':
        # Avoid modifying production Rules: mutate a bound fixture Rules artifact.
        path=tmp_path/'rules.json'
    else:path=Path(p['bindings'][key]['path'])
    path.write_bytes(path.read_bytes()+b'\nchanged')
    with pytest.raises(ValueError,match='Changed input'):gate.packet(tmp_path/'run')


def test_old_packet_approval_cannot_authorize_new_packet(tmp_path,monkeypatch):
    from research_pipeline import eda_review_handoff as gate
    run_fixture(tmp_path,monkeypatch,decision='PASS')
    decision=read_json(tmp_path/'run/human_decision.template.json');decision.update(actor_type='HUMAN',reviewer='OFFLINE FIXTURE',reviewed_at='2026-10-23T00:00:00Z',decision='APPROVE_DESCRIPTIVE_EDA',packet_sha256='0'*64,images_inspected=True,limitations_acknowledged=True)
    with pytest.raises(ValueError,match='approval must name this packet'):gate.confirm(tmp_path/'run',write_json(tmp_path/'old_decision.json',decision))


@pytest.mark.parametrize('provider,variable,default',[('codex','CTXCOMP_CODEX_MODEL','gpt-fixture'),('claude','CTXCOMP_CLAUDE_MODEL','claude-fixture'),('openai','CTXCOMP_OPENAI_MODEL','qwen-fixture')])
def test_eda_resolves_existing_provider_model(tmp_path,monkeypatch,provider,variable,default):
    monkeypatch.setenv('CTXCOMP_MODEL_PROVIDER',provider);monkeypatch.setenv(variable,default)
    assert providers.provider_model()==default and providers.provider_model('explicit-fixture')=='explicit-fixture'
    from research_pipeline import eda_dh_adapter as dh, eda_questions_v6 as q
    h,r,_=fixture(tmp_path);built=dh.build(h,r,tmp_path/'adapter');seen=stub_transports(monkeypatch)
    result=q.run_questions(built['inputs'],None,built['catalog'],tmp_path/'run',until='EV')
    assert result['provider']==provider and result['model']==default and seen==['EP-plan','EP-finalize']


def test_current_reference_and_catalog_are_bound_and_historical_bytes_remain():
    from research_pipeline import eda_context
    from research_pipeline.context_reference_scope import _validate_catalog
    pack=read_json(eda_context.PACK);ref=pack['source']['scientific_reference']
    path=eda_context.PACK.parent/ref['file'];text=path.read_text(encoding='utf8')
    assert cb.file_ref(path)['sha256']==ref['sha256']
    assert 'Main-figure status band:' not in text and 'Retain BLQ status in a separate strip' not in text
    catalog=Path(eda_context.__file__).parent/'resources/context_builder/reference_catalogs'/pack['source']['current_reference_catalog']['file']
    assert _validate_catalog(read_json(catalog),text)
    old=read_json(catalog.with_name('eda.20261013.json'));oldref=eda_context.PACK.parent/'eda_scientific_reference.txt'
    # The old catalog was already stale at intake; preserve it and reject it.
    from research_pipeline.context_reference_scope import ReferenceScopeError
    with pytest.raises(ReferenceScopeError,match='hash'):_validate_catalog(old,oldref.read_text(encoding='utf8'))


def test_checked_context_or_unresolved_roles_cannot_be_observations(tmp_path):
    from research_pipeline import eda_dh_adapter as dh, eda_dataset_routes as routes
    h,r,_=fixture(tmp_path);built=dh.build(h,r,tmp_path/'adapter')
    tables=read_json(tmp_path/'adapter/source_snapshot.json')['tasks']
    dispositions=[dict(dataset_id=t['dataset_id'],handoff=dict(destinations=['PK','PD'],role='OBSERVATIONS',purpose='Synthetic test.',pending_checks=[])) for t in tables]
    with pytest.raises(ValueError,match='contextual or unresolved Data role'):routes.build(tables,dispositions)
    dispositions[2]['handoff']['role']='CONTEXT'
    assert routes.build(tables,dispositions)['datasets'][2]['role']=='CONTEXT'
    tables[0]['metadata']['role_resolution']='UNRESOLVED'
    with pytest.raises(ValueError,match='unresolved Data role'):routes.build(tables,dispositions)


def test_current_context_optional_fields_are_not_old_eda_prerequisites(tmp_path):
    from research_pipeline import eda_dh_adapter as dh
    h,r,_=fixture(tmp_path)
    main=read_json(tmp_path/'main.json');main.pop('scientific_context');main.pop('missing_information')
    main_ref=cb.file_ref(write_json(tmp_path/'main.json',main))
    rules=read_json(tmp_path/'rules.json');rules['main_ref']=main_ref
    handoff=read_json(h);handoff['rules_ref']=cb.file_ref(write_json(tmp_path/'rules.json',rules));write_json(h,handoff)
    report=read_json(r);report['upstream']['main']=main_ref;write_json(r,report)
    built=dh.build(h,r,tmp_path/'adapter');tc=read_json(built['inputs'])['task_context']
    assert tc['context_fields_not_supplied']==['scientific_context','missing_information']
    assert 'scientific_context' not in tc and 'missing_information' not in tc
    assert (tmp_path/'main.json').read_bytes()==Path(main_ref['path']).read_bytes()
