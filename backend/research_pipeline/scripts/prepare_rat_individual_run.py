"""Bind the current user-requested rat analysis to approved upstream data."""
import csv
import math
import statistics
from pathlib import Path
from collections import Counter
from research_pipeline.common import PROJECT,read_json,write_json,utcnow
from research_pipeline.adequacy import file_ref,check_ref
from research_pipeline.task_rules import project_rules
from research_pipeline.animal_pk_nlmixr2 import validate_qualification

run_id='RAT_PK_20260923_INDIVIDUAL_01'
job=PROJECT/'outputs/Workbench_Preview_v22/state/workbench_jobs'/run_id
job.mkdir(exist_ok=False);inputs=job/'inputs'
normalized_root=PROJECT/'outputs/Workbench_Preview_v22/runs/PMB_UI_20260923_071911_54a71a/data_preparation/normalized'
source=normalized_root/'T0035.json';metadata_path=normalized_root/'T0035.metadata.json';excluded=normalized_root/'T0035.quarantine.json'
records=read_json(source)['records'];meta=read_json(metadata_path)['metadata']
context_path=PROJECT/'outputs/Workbench_Preview_v22/runs/PMB_UI_20260923_073127_06d870/dispatch/pk_context.json'
context=read_json(context_path)
assert meta['species']=='rat' and meta['matrix']=='plasma'
assert len(records)==102 and len({r['subject_label'] for r in records})==11
excluded_ref=file_ref(excluded);source_refs=[file_ref(p) for p in [context_path,source,metadata_path,excluded]]
catalog_path=Path('C:/Users/georg/Downloads/PMB_Agent_Ready_Package/model_library_catalog.csv')
with catalog_path.open(encoding='utf-8-sig') as f:catalog=[r for r in csv.DictReader(f) if r['model_id'] in ['PK_SYS_1C_LIN','PK_SYS_2C_LIN','INPUT_IV_INF']]
assert len(catalog)==3
source_refs.append(file_ref(catalog_path))
projection=project_rules(context,'animal_pk',[{'species':'rat','study_id':'S21'}]);assert not projection['unresolved']
write_json(inputs/'rule_audit.json',projection)
notes={'source_doi':'10.1038/s41467-022-29234-3','source_url':'https://www.nature.com/articles/s41467-022-29234-3',
 'locator':'Methods / Pharmacokinetic studies; current source workbook Rat!A6:L16, Figure 4b PMB block',
 'identity_evidence':'Methods report 11 rats with indwelling jugular and carotid cannulae; source labels Rat 1-11 and cannula-blockage markers support serial within-rat profiles.',
 'dose_mg_kg':1,'infusion_duration_h':1/60,'time_origin':'As reported post dosing; no undocumented time shift',
 'exposure_basis_evidence':'LC-MS/MS plasma PK assay; ultrafiltration appears in separate binding experiment. Total measured plasma concentration interpretation, not a free-fraction conversion.',
 'body_weight':'Reported range 280-330 g; no individual weights available; no range midpoint substitution.',
 'dose_basis':'As-reported PMB dose; no undocumented salt/base correction.',
 'excluded_counts':dict(Counter(r['status'] for r in read_json(excluded)['records'])),
 'censoring':'2 BLQ values at 6 h, numeric assay LLOQ unavailable. Preserved without imputation; quantified-only fit is exploratory and may bias the terminal phase.',
 'other_rat_data':'S07 serum/whole-lung summary has only 3 time rows, distinct study/dose/matrix. Not pooled with S21 plasma.',
 'model_plan':'1C and 2C linear IV infusion; CL and VC lognormal IIV, diagonal omega; additive, proportional and combined residual errors; two data-derived starts each.',
 'three_compartment':'Deferred: first sample is at 0.17 h after a 1-minute infusion; no additional distribution phase established.',
 'catalog_threshold':'Two-compartment structural correlation >0.95 is the current library rejection criterion, not a universal rule.',
 'validation':'No held-out validation or human simulation released.'}
write_json(inputs/'source_qualification.json',notes)
engine_records=[];mapping=[];individual_starts=[]
for label in sorted({r['subject_label'] for r in records},key=lambda s:int(s.split()[-1])):
    block=sorted([r for r in records if r['subject_label']==label],key=lambda r:r['time_h'])
    engine_records.append(dict(ID=label,TIME=0,DV=None,AMT=1,EVID=1,RATE=60,CMT=1))
    x=[r['time_h'] for r in block];y=[math.log(r['concentration_mg_L']) for r in block]
    slope=sum((t-statistics.mean(x))*(c-statistics.mean(y)) for t,c in zip(x,y))/sum((t-statistics.mean(x))**2 for t in x)
    rate=max(-slope,.001);v=math.exp(-(statistics.mean(y)-slope*statistics.mean(x)))
    individual_starts.append({'ID':label,'CL':rate*v,'VC':v})
    for row in block:
        assert row['status']=='QUANTIFIED' and row['concentration_mg_L']>0
        engine_records.append(dict(ID=label,TIME=row['time_h'],DV=row['concentration_mg_L'],AMT=0,EVID=0,RATE=0,CMT=1))
        mapping.append({'ID':label,'TIME':row['time_h'],'record_id':row['record_id'],'source_cell':row['source_cell'],
                        'source_sha256':row['source_sha256'],'original_subject_id':row['subject_id'],
                        'identity_resolution':'SOURCE_METHODS_AND_COLUMN_LABELS'})
data_ref=file_ref(write_json(inputs/'rat_individual_events.json',{'metadata':{
    'species':'rat','record_level':'INDIVIDUAL_LONGITUDINAL','permission':'DEVELOPMENT_CANDIDATE',
    'route':'IV_INFUSION','time_unit':'h','dose_unit':'mg/kg','rate_unit':'mg/kg/h','parameter_basis':'PER_KG',
    'concentration_unit':'mg/L','exposure_basis':'total','matrix':'plasma','blq_handling':'QUANTIFIED_ONLY_EXPLORATORY',
    'excluded_records_ref':excluded_ref,'scientific_release':False,'qualification_notes_ref':file_ref(inputs/'source_qualification.json')},'records':engine_records}))
write_json(inputs/'record_mapping.json',{'records':mapping,'raw_data_modified':False})
approval_ref=file_ref(write_json(inputs/'user_execution_authorization.json',{'status':'APPROVED',
    'scope':'EXPLORATORY_RAT_INDIVIDUAL_PK','kind':'USER_REQUESTED_EXECUTION',
    'user_request':'接下来是大鼠的模拟','scope_interpretation':'Continue species-specific exploratory PK fitting after the reviewed mouse run; model choices and limitations documented by the analyst.',
    'input_refs':[data_ref,excluded_ref],'scientific_acceptance':False,'human_prediction_release':False}))
base={p:math.exp(statistics.mean(math.log(s[p]) for s in individual_starts)) for p in ['CL','VC']}
omega={p:min(1,max(.02,statistics.variance(math.log(s[p]) for s in individual_starts))) for p in ['CL','VC']}
write_json(inputs/'initialization.json',{'method':'Within-rat log-concentration regressions; geometric mean CL/VC for initialization only; all fits use finite IV infusion.',
    'individual_estimates':individual_starts,'base':base,'omega_initial':omega,'published_fitted_parameters_used':False,
    'technical_bounds':'Data-derived initial scale divided/multiplied by 10000; not biological acceptance limits.'})
source_refs += [data_ref,file_ref(inputs/'record_mapping.json'),file_ref(inputs/'source_qualification.json'),file_ref(inputs/'initialization.json')]
common={'species':'rat','drug':'polymyxin B','analysis_id':'RAT_S21_IV_PLASMA','source_refs':source_refs,
 'approval_ref':approval_ref,'rules':projection['rules'],'rule_scope':{'unresolved':projection['unresolved']},
 'qualification_notes':notes,'catalog_rows':catalog}
candidates=[]
for nc in [1,2]:
 for error in ['additive','proportional','combined']:
    key=f'RAT_S21_IV_{nc}C_{error}'
    configurations=[]
    for i in range(2):
        initial={k:v for k,v in base.items()}
        if nc==2:initial.update(Q=base['CL']*(.5 if i==0 else 2),VP=base['VC']*(1 if i==0 else 2));initial['VC']*=.5
        if i:initial['CL']*=1.4;initial['VC']*=1.4
        residual={}
        if error in ['additive','combined']:residual['additive']=statistics.median(r['concentration_mg_L'] for r in records)*.1
        if error in ['proportional','combined']:residual['proportional']=.2
        configurations.append({'engine':'nlmixr2','estimator':'focei','error_model':error,'initial':initial,
          'bounds':{p:[v/10000,v*10000] for p,v in ({**base,**({'Q':base['CL'],'VP':base['VC']} if nc==2 else {})}).items()},
          'random_effects':['CL','VC'],'omega_initial':omega,'residual_initial':residual,
          'seed':20260923+i,'cores':1,'max_outer_iterations':1000,'optimizer':'bobyqa'})
    qualification={'candidate_id':key,'species':'rat','analysis_id':'RAT_S21_IV_PLASMA','compartments':nc,
      'fit_ready':True,'input_refs':[data_ref,excluded_ref,*source_refs],'approval_ref':approval_ref,
      'normalized_data_ref':data_ref,'pause_file':str(job/'pause.flag')}
    for config in configurations:validate_qualification({**qualification,'fit_config':config})
    candidates.append(file_ref(write_json(inputs/(key+'.json'),{**common,'id':key,'compartments':nc,
       'error_model':error,'qualification':qualification,'configurations':configurations})))
master_ref=file_ref(write_json(inputs/'individual_request.json',{**common,'id':'RAT_S21_COMPARISON','candidates':candidates}))
write_json(job/'request.json',{'id':run_id,'created_at':utcnow(),'session_id':'flow_f75c012fdd294693847d00f393ff3271',
 'mode':'animal_pk_individual','individual_request':master_ref,'out':str(PROJECT/'outputs/Workbench_Preview_v22/runs'/run_id),
 'job_dir':str(job),'stop_after':'animal_pk_individual'})
print(job/'request.json')
