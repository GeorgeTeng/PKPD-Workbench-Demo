"""Run an explicitly scoped 1-hour static concentration endpoint review in R."""
import argparse
import os
from pathlib import Path
import subprocess
from research_pipeline.common import PROJECT, read_json, write_json, sha256, utcnow
from research_pipeline.engine import rscript_path
from research_pipeline.model_catalog import load_catalog, require_catalog_models


def ref(path):
    return {'path':str(Path(path).resolve()),'sha256':sha256(path)}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    parser.add_argument('--catalog',type=Path,required=True)
    args=parser.parse_args()
    out=args.out.resolve();out.mkdir(parents=True,exist_ok=False)
    record={'status':'RUNNING','started_at':utcnow(),'pid':os.getpid(),'script':ref(__file__)}
    write_json(out/'execution.json',record)
    try:
        b2=PROJECT/'outputs/Data_Preparation_PMB_2026-09-18_retry_1628/normalized'
        selected=[];other=[];sources=[];selection=[]
        for strain in ('BAA1705','KP619'):
            source=b2/f'kp_{strain}_time_kill.json';sources.append(ref(source))
            payload=read_json(source);rows=payload['records']
            groups={r['experiment_group_key'] for r in rows}
            common=None
            for group in groups:
                times={r['time_h'] for r in rows if r['experiment_group_key']==group and
                       r['status']=='QUANTIFIED' and r['CENS']==0 and r['time_h']>0}
                common=times if common is None else common & times
            endpoints=[r for r in rows if r['time_h']==1]
            if 1 not in common or len(endpoints)!=6 or len({r['experiment_group_key'] for r in endpoints})!=6:
                raise ValueError(f'{strain}: endpoint support changed')
            if any(r['status']!='QUANTIFIED' or r['CENS']!=0 for r in endpoints):
                raise ValueError('Censoring or missing response at selected endpoint')
            selected.extend(endpoints);other.extend(r for r in rows if r['time_h']!=1)
            selection.append({'strain':strain,'common_uncensored_positive_times_h':sorted(common),
                              'selected_time_h':1,'selection_basis':'Common early uncensored endpoint; chosen before model fitting'})
        catalog=load_catalog(args.catalog)
        assessments=[require_catalog_models(catalog,[identifier],'pkpd_index',
            {'mode':'endpoint_emax','estimate_hill':hill},{},{})
            for identifier,hill in [('PD_EMAX',False),('PD_SIGMOID',True)]]
        write_json(out/'catalog_assessments.json',{'models':assessments})
        write_json(out/'other_timepoints.json',{'records':other,'handling':'Retained; outside declared 1-hour endpoint, not deleted from source'})
        provenance={'sources':sources,'catalog':catalog['source'],'selection':selection,
          'source_paper':'https://doi.org/10.1371/journal.pone.0171834',
          'source_paper_model':'Longitudinal physiologically structured population model; not the present simplified Emax/Hill refit',
          'scope':'Exploratory nominal static concentration-response, not best PK/PD index selection',
          'source_fit_ready_preserved':True,'prior_B2_gate_modified':False,'human_review':'PENDING',
          'sparse_hill_policy':'Explicit exploratory mode with 2 residual df; default pipeline guard unchanged; no adequacy approval'}
        input_path=out/'input.json';write_json(input_path,{'records':selected,'provenance':provenance})
        script=PROJECT/'pkpd_r/scripts/review_static_emax.R'
        command=[rscript_path(),'--vanilla',str(script),str(input_path),str(out/'results')]
        record.update(command=command,R_script=ref(script),R_endpoint=ref(PROJECT/'pkpd_r/R/endpoint.R'),input=ref(input_path))
        write_json(out/'execution.json',record)
        with (out/'R.stdout.log').open('w',encoding='utf-8') as stdout,(out/'R.stderr.log').open('w',encoding='utf-8') as stderr:
            process=subprocess.Popen(command,cwd=PROJECT,stdout=stdout,stderr=stderr,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            record['R_pid']=process.pid;write_json(out/'execution.json',record)
            code=process.wait()
        if code: raise RuntimeError(f'R exit {code}; inspect R.stderr.log')
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
