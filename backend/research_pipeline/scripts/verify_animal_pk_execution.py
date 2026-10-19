"""Opt-in full scheduler/provider/R smoke using synthetic data only.

This creates an isolated test run. It never approves a real study or model.
"""
import argparse
import runpy
from pathlib import Path
from uuid import uuid4

from research_pipeline.common import BACKEND, PROJECT, write_json, read_json, utcnow
from research_pipeline.adequacy import file_ref
from research_pipeline.animal_pk import build_plan
from research_pipeline.animal_pk_control import save_qualification
from research_pipeline.graph_execution import run_controlled


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',required=True)
    args=parser.parse_args()
    root=Path(args.out).resolve(); root.mkdir(parents=True,exist_ok=False)
    synthetic=runpy.run_path(str(BACKEND/'research_pipeline/tests/test_animal_pk_nlmixr2.py'))['synthetic_qualification']
    q=synthetic(root/'inputs')
    q['fit_config'].update(random_effects=[],omega_initial={},max_outer_iterations=1000)
    data_ref=q['normalized_data_ref']; meta=read_json(data_ref['path'])['metadata']
    meta['role']='PK_OBSERVATIONS'
    metadata=file_ref(write_json(root/'inputs/metadata.json',{'dataset_id':'SYNTHETIC','data_file':data_ref,'metadata':meta}))
    csv=root/'inputs/source.csv';csv.write_text('synthetic_only\ntrue\n')
    context=file_ref(write_json(root/'inputs/pk_context.json',{'module':'pk','drug':'SYNTHETIC_TEST_ONLY',
        'clinical_questions':{'purpose':'Verify scheduler and fresh agent execution; no scientific inference or human prediction.'},
        'tasks':['Check the explicitly qualified synthetic IV fitting pipeline.'],
        'data_access':{'human_pk':False},'rules':[],
        'data_files':[{'dataset_id':'SYNTHETIC','role':'PK_OBSERVATIONS','data':data_ref,'csv':file_ref(csv),
            'metadata':metadata,'excluded_records':file_ref(write_json(root/'inputs/exclusions.json',{'records':[]}))}]}))
    plan=build_plan(context); plan_ref=file_ref(write_json(root/'plan.json',plan))
    candidate=plan['analysis_units'][0]['candidates'][0]
    q.update(candidate_id=candidate['id'],analysis_id='SYNTHETIC',configuration_id='synthetic_no_iiv',
        source_provenance={'assigned_dataset_ref':data_ref,'transformation_description':'Synthetic simulation in normalized units.',
            'dose_evidence':'Known generated 2 mg IV bolus events.', 'identity_evidence':'Generated independent subjects with repeated measurements.'})
    authorization=file_ref(write_json(root/'synthetic_authorization.json',{'synthetic':True,'status':'APPROVED',
        'scope':'TEST_FIXTURE_ONLY_NO_REAL_DATA_OR_MODEL_RELEASE'}))
    envelope=save_qualification(plan,candidate['id'],{'configurations':[q],'max_attempts':1,'confirmed':True,
        'reviewer':'SYNTHETIC TEST FIXTURE; not a real study approval'},root/'control',authorization)
    request={'agent':next(a for a in plan['agents'] if a['id']==candidate['model_agent']),
        'step_contracts':{s['role']:next(a for a in plan['agents'] if a['id']==s['agent_id']) for s in candidate['steps']},
        'qualification_ref':envelope['qualification_ref'],'plan_signature':plan['plan_signature'],
        'source_refs':[authorization,envelope['qualification_ref']], 'upstream_refs':{},'upstream_run_ids':{},
        'approval_ref':authorization,'instruction':'This is an execution smoke test with synthetic data. Review only the declared numerical contract and tool output; no scientific or clinical acceptance is requested.'}
    request_ref=file_ref(write_json(root/'agent_request.json',request))
    job=root/'job';job.mkdir()
    spec={'id':'SYNTHETIC_PK_'+uuid4().hex[:10],'created_at':utcnow(),'mode':'animal_pk_execution',
        'pk_plan':plan_ref,'agent_request':request_ref,'out':str(root/'run'),'job_dir':str(job),'stop_after':'animal_pk_execution'}
    spec_path=write_json(job/'request.json',spec)
    result=run_controlled(spec_path)
    write_json(root/'verification.json',{'synthetic_only':True,'real_provider_calls':True,'real_R_fitting':True,
        'status':result,'real_study_modified':False,'human_model_approval':False})
    print(result['status'])
    return 0 if result['status']=='PK_AGENT_COMPLETED' else 1


if __name__=='__main__':
    raise SystemExit(main())
