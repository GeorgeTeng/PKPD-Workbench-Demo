"""User-requested exploratory rat PK review; does not sign the B2 or model gate."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
from research_pipeline.common import read_json, write_json, sha256, utcnow, PROJECT
from research_pipeline.engine import rscript_path
from research_pipeline.model_catalog import load_catalog, require_catalog_models


def ref(path):
    return {'path':str(Path(path).resolve()),'sha256':sha256(path)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--catalog',type=Path,required=True)
    args=parser.parse_args()
    out=args.out.resolve(); out.mkdir(parents=True,exist_ok=False)
    record={'status':'RUNNING','started_at':utcnow(),'pid':os.getpid(),'script':ref(__file__)}
    write_json(out/'execution.json',record)
    try:
        b2=PROJECT/'outputs/Data_Preparation_PMB_2026-09-18_retry_1628'
        source=b2/'normalized/rat_plasma_IV.json'
        audit_path=PROJECT/'outputs/Model_Debug_XLSX_2026-09-18_01/workbook_audit/audit.json'
        audit=read_json(audit_path)
        if sha256(audit['workbook'])!=audit['sha256']: raise ValueError('Metadata source workbook changed')
        if audit['rat_metadata_correction']['workbook_declared_basis']!=['total']: raise ValueError('Total concentration not documented')
        if audit['rat_metadata_correction']['concentration_discrepancies']: raise ValueError('Rat source mismatch')
        payload=read_json(source)
        rows=payload['records']; quantified=[r for r in rows if r['status']=='QUANTIFIED']
        if len(quantified)!=102 or len({r['subject_id'] for r in quantified})!=11: raise ValueError('Rat input count changed')
        write_json(out/'excluded_records.json',{'records':[r for r in rows if r['status']!='QUANTIFIED'],
            'handling':'Preserved without imputation; exploratory complete-observation fit, exclusion impact remains for review.'})
        meta=payload['metadata'] | {'concentration_basis':'total','data_origin':'observed',
             'regimen_type':'single_dose','analysis_scope':'USER_REQUESTED_EXPLORATORY_RESULTS_FOR_REVIEW'}
        doses=[{'time_h':0,'dose_mg_kg':1,'duration_h':1/60}]
        catalog=load_catalog(args.catalog)
        assessments=[]
        for n in (1,2):
            assessments.append(require_catalog_models(catalog,[f'PK_SYS_{n}C_LIN','INPUT_IV_INF'],
                'pk_longitudinal',{'mode':'individual','compartments':n},meta,{'doses':doses}))
        write_json(out/'catalog_assessments.json',{'models':assessments})
        provenance={'source':ref(source),'catalog':catalog['source'],'total_concentration_evidence':ref(audit_path),
                    'total_concentration_locator':'PK_Rat_Individual!R2:R103',
                    'user_requested_scope':'一边跑动物PK；这些模型需审核后给出拟合最好的。',
                    'review_status':'PENDING','prior_B2_gate_modified':False,
                    'scope_limit':'Exploratory within-rat fitting only; no automated release or human extrapolation.'}
        input_path=out/'input.json'
        write_json(input_path,{'records':quantified,'metadata':meta,'doses':doses,'provenance':provenance})
        rscript=PROJECT/'pkpd_r/scripts/review_rat_pk_candidates.R'
        command=[rscript_path(),'--vanilla',str(rscript),str(input_path),str(out/'results')]
        record.update(command=command,R_script=ref(rscript),input=ref(input_path),scope=provenance['scope_limit'])
        write_json(out/'execution.json',record)
        with (out/'R.stdout.log').open('w',encoding='utf-8') as stdout,(out/'R.stderr.log').open('w',encoding='utf-8') as stderr:
            process=subprocess.Popen(command,cwd=PROJECT,stdout=stdout,stderr=stderr,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            record['R_pid']=process.pid;write_json(out/'execution.json',record)
            code=process.wait()
        if code: raise RuntimeError(f'R process exit {code}; inspect R.stderr.log')
        result=read_json(out/'results/output.json')
        record.update(status=result['status'],result=ref(out/'results/output.json'))
    except Exception as exc:
        record.update(status='STOPPED_ON_ERROR',error={'type':type(exc).__name__,'message':str(exc)})
        raise
    finally:
        record['finished_at']=utcnow();write_json(out/'execution.json',record)
    print(record['status'],str(out))


if __name__=='__main__':
    main()
