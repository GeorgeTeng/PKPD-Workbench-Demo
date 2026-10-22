"""Numerical regression checks with synthetic data, never research observations."""
import json
import math
import os
import subprocess
from pathlib import Path
import numpy as np
from scipy.linalg import expm
from scipy.stats import norm
from research_pipeline.common import PROJECT, write_json
from research_pipeline.engine import rscript_path

root=PROJECT/'outputs/Summary_PK_Adapter_Test_20260923/multistart_regression'
root.mkdir(parents=True,exist_ok=True)
env=dict(os.environ,R_LIBS_USER='C:/Users/georg/Documents/Codex/ScienceEnv/R-library',OMP_NUM_THREADS='1')
times=[.03,.06,.1,.15,.25,.4,.6,.9,1.3,1.8,2.5,3.5,5,7,10,14]
checks=[]
for route,nc in [('IV',1),('IV',2),('SC',1),('SC',2)]:
    case=f'SYNTHETIC_{route}_{nc}C'; folder=root/case
    folder.mkdir(exist_ok=True)
    def concentration(t,dose):
        if route=='IV':
            return dose*(5*math.exp(-.5*t) if nc==1 else 4*math.exp(-3*t)+math.exp(-.25*t))
        # Independent matrix-exponential reference, with a depot, central and peripheral state.
        cl,vc,q,vp,ka=.15,.3,(.25 if nc==2 else 0),.6,2.5
        matrix=np.array([[-ka,0,0],[ka,-(cl+q)/vc,q/vp],[0,q/vc,-q/vp]])
        return float((expm(matrix*t)@np.array([dose,0,0]))[1]/vc)
    records=[{'time_h':t,'dose_mg_kg':2,'concentration_mg_L':concentration(t,2)*math.exp(.012*math.sin(i)),
        'source_record_ids':[f'synthetic_{i}']} for i,t in enumerate(times)]
    request={'records':records,'route':route,'compartments':nc,'seed':20260923,'analysis_id':case,
        'observation_unit':'Synthetic known generating curve','source_refs':[]}
    input_path=write_json(folder/'input.json',request)
    command=[rscript_path(),'--vanilla',str(PROJECT/'pkpd_r/scripts/fit_summary_pk.R'),str(input_path),str(folder/'result')]
    result=subprocess.run(command,env=env,encoding='utf-8',capture_output=True)
    (folder/'R.log').write_text(result.stdout+result.stderr,encoding='utf-8')
    assert result.returncode==0,(case,result.stderr)
    data=json.loads((folder/'result/numerical_results.json').read_text())
    attempts=json.loads((folder/'result/optimization_attempts.json').read_text())
    assert len(attempts)==32
    assert not any('without starting value' in x['message'] for x in attempts)
    assert any(x['converged'] and x['start']>1 for x in attempts)
    for row in data['rows']:
        assert row['converged'] and row['R2_raw']>.999,(case,row)
        n,k,ll=row['n_observations'],row['n_parameters'],row['logLik']
        assert abs(row['AIC']-(-2*ll+2*k))<1e-7
        assert abs(row['BIC']-(-2*ll+k*math.log(n)))<1e-7
        import csv
        predictions=list(csv.DictReader((folder/'result'/row['error_model']/'predictions.csv').open()))
        y=np.array([float(x['concentration_mg_L']) for x in predictions])
        p=np.array([float(x['predicted_mg_L']) for x in predictions])
        residual=np.log(y/p) if row['error_model']=='lognormal' else y-p
        expected=norm.logpdf(residual,scale=np.sqrt(np.mean(residual**2))).sum()
        if row['error_model']=='lognormal':expected-=np.log(y).sum()
        assert abs(expected-ll)<1e-6,(expected,ll)
        if route=='IV':
            params={p['parameter']:p['estimate'] for p in row['conditional_pk_parameters']}
            expected_cl=.1 if nc==1 else 1/(4/3+1/.25)
            assert abs(params['CL_L_h_kg']/expected_cl-1)<.03
        checks.append({'case':case,'error':row['error_model'],'R2_raw':row['R2_raw'],
            'converged_starts':row['converged_starts'],'attempted_starts':row['attempted_starts'],
            'full_likelihood_AIC_BIC_verified':True})
write_json(root/'verification.json',{'status':'PASSED','checks':checks,'synthetic_only':True})
print(json.dumps({'status':'PASSED','cases':4,'fits':8,'checks':checks},indent=2))
