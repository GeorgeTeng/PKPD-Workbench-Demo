"""Build a read-only review package from completed R/agent artifacts; never refit."""
import base64
import csv
import html
import json
import math
import zipfile
from pathlib import Path
from urllib.parse import quote
from research_pipeline.common import BACKEND, PROJECT,read_json,write_json,utcnow
from research_pipeline.adequacy import file_ref,check_ref

run_id='MOUSE_PK_20260923_MEANS_03'
session='flow_f75c012fdd294693847d00f393ff3271'
root=PROJECT/'outputs/Workbench_Preview_v22/runs'/run_id/'animal_pk'
job=PROJECT/'outputs/Workbench_Preview_v22/state/workbench_jobs'/run_id
report=read_json(root/'report.json');comparison=read_json(root/'comparison.json')
assert read_json(job/'status.json')['status']=='WAITING_FOR_HUMAN_REVIEW'
rows=comparison['rows'];assert len(rows)==12
verifications=[]
for row in rows:
    assert row['converged']
    n,k,ll=row['n_observations'],row['n_parameters'],row['logLik']
    assert math.isclose(row['AIC'],-2*ll+2*k,abs_tol=1e-7)
    assert math.isclose(row['BIC'],-2*ll+k*math.log(n),abs_tol=1e-7)
    assert math.isclose(row['AICc'],row['AIC']+2*k*(k+1)/(n-k-1),abs_tol=1e-7)
    # Independent likelihood reconstruction from the exported observations and predictions.
    folder=Path(row['result_folder'])
    with (folder/'predictions.csv').open(encoding='utf-8') as f:records=list(csv.DictReader(f))
    y=[float(x['concentration_mg_L']) for x in records];p=[float(x['predicted_mg_L']) for x in records]
    residual=[math.log(a/b) if row['error_model']=='lognormal' else a-b for a,b in zip(y,p)]
    sigma2=sum(x*x for x in residual)/len(residual)
    reconstructed=-len(y)*math.log(2*math.pi*sigma2)/2-sum(x*x for x in residual)/(2*sigma2)
    if row['error_model']=='lognormal':reconstructed-=sum(math.log(x) for x in y)
    assert math.isclose(ll,reconstructed,abs_tol=1e-6)
    verifications.append({'candidate_id':row['candidate_id'],'full_likelihood_AIC_AICc_BIC':'PASSED'})
calls=list(root.glob('candidates/*/agent/*/execution.json'))+list(root.glob('comparison_agent/*/execution.json'))
assert len(calls)==7
assert all(read_json(p)['status']=='COMPLETED' and read_json(p)['fresh_session'] for p in calls)
for path in root.glob('candidates/*/numerical_execution.json'):
    ex=read_json(path);assert ex['return_code']==0
    check_ref(ex['code_ref']);check_ref(ex['input_ref'])
    assert Path(ex['code_ref']['path']).parent==path.parent
attempts=[a for path in root.glob('candidates/*/numerical/optimization_attempts.json') for a in read_json(path)]
assert len(attempts)==192
assert not any('without starting value' in a['message'] for a in attempts)
write_json(root/'verification.json',{'status':'PASSED','verified_at':utcnow(),'numerical_checks':verifications,
    'fresh_completed_agent_calls':7,'attempted_optimizations':len(attempts),
    'converged_optimizations':sum(a['converged'] for a in attempts),'snapshot_code_and_input_hashes':'PASSED',
    'scientific_model_acceptance':False})

findings={
 'MOUSE_S02_SC_PLASMA':{'label':'S02 · Subcutaneous · five doses','n':'39 digitized group means',
 'disposition':'Model revision needed before translational use',
 'text':'The 1C lognormal curve has the lowest AIC among numerically screened candidates (146.068), but systematic residual patterns across doses and a rate-gap RSE of 293% limit interpretation. Both 2C fits have nonfinite uncertainty. The five dose groups were fitted jointly. No dose group was treated as a separate PK model.',
 'next':'Review dose proportionality, early absorption sampling and error assumptions. Any extension beyond the approved 1C/2C family needs a documented revised analysis plan.'},
 'MOUSE_S05_IV_PLASMA':{'label':'S05 · Intravenous','n':'8 digitized group means',
 'disposition':'Retain both additive-error candidates for review',
 'text':'2C additive has AIC 28.588 and BIC 28.985; 1C additive has AIC 30.079 and BIC 30.317. The AIC difference is 1.491, below the project\'s 2-unit threshold. AICc favors 1C (36.079 versus 58.588). 2C parameter correlation is 0.979; Q and Vp RSE are about 84% and 83%. The total dose/analyte interpretation remains conditional on uploaded source notes.',
 'next':'Review both curves and the weakly identified distribution phase. More reliable early/late sampling and source-method qualification are needed before claiming a unique translational model.'},
 'MOUSE_S21_IP_PLASMA':{'label':'S21 · Intraperitoneal','n':'9 time means derived from 27 source values',
 'disposition':'1C lognormal is the provisional descriptive candidate',
 'text':'1C lognormal gives AIC 9.261, AICc 19.261, BIC 10.050 and raw R² 0.970. Both 2C fits have nonfinite local uncertainty. Cross-time animal identities remain unverified; apparent CL/F and alternative absorption/disposition labels must be retained.',
 'next':'Review the descriptive curve. Verified individual/cohort identity and study-compatible dose/assay metadata are needed before animal-level variability or absolute PK interpretation.'}
}
write_json(root/'human_review_summary.json',{'status':'PENDING_HUMAN_REVIEW','findings':findings,
    'prefit_approval_verified':True,'prefit_approval_ref':read_json(job/'inputs/summary_request.json')['approval_ref'],
    'scientific_acceptance':False,'human_simulation_released':False,
    'not_established':['Animal IIV/NLME','Independent predictive validation','Unbound exposure','Human PK prediction'],
    'audit_note':'The comparison agent did not receive the approval record or full record-level dictionary. Its statement that they were not supplied is not evidence that pre-fit review was missing. The runner validated the hash-bound user approval before fitting.'})
write_json(root/'human_review_template.json',{'status':'AWAITING_USER_DECISION','reviewer':None,
    'comparison_ref':file_ref(root/'comparison.json'),'prefit_authorization_is_final_acceptance':False,
    'studies':[{'analysis_id':k,'decision':None,'selected_candidate_ids':[],'requested_changes':[]} for k in findings],
    'allowed_decisions':['RETAIN_FOR_EXPLORATORY_USE','REVISE','REJECT'],
    'human_pk_release':False})

# Separate structural comparisons within each error model from error-model comparisons.
structured=[]
for group in findings:
    for error in ['lognormal','additive']:
        items=[r for r in rows if r['analysis_id']==group and r['error_model']==error]
        best=min(r['AIC'] for r in items)
        structured.extend({'analysis_id':group,'error_model':error,'candidate_id':r['candidate_id'],
            'AIC':r['AIC'],'delta_AIC_same_error':r['AIC']-best,'numerically_eligible':r['numerically_eligible']} for r in items)
write_json(root/'structural_comparison.json',{'rows':structured,'same_records_within_group':True,
    'error_model_comparison_note':'Gaussian and lognormal densities are both evaluated on the same observed concentration scale with all constants and the lognormal Jacobian. Structural rankings are also provided separately within each error family. No cross-study ranking is permitted.'})

base=f'/ui-api/workflow/sessions/{session}/animal-pk/agent-runs/{run_id}/files/'
def url(path):return base+'/'.join(quote(p,safe='') for p in Path(path).parts)
def a(path,label):return '<a href="'+url(path)+'" target="_blank">'+html.escape(label)+'</a>'
def num(value):return f'{value:.3f}' if isinstance(value,(int,float)) else 'NA'
def table(items,cols):
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+html.escape(label)+'</th>' for _,label in cols)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(num(r.get(key)) if isinstance(r.get(key),(int,float)) and not isinstance(r.get(key),bool) else str(r.get(key,'NA')))+'</td>' for key,_ in cols)+'</tr>' for r in items)+'</tbody></table></div>'
page=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Mouse PK · Exploratory review</title>',
 '''<style>body{margin:0;background:#f6f8fa;color:#20333d;font:16px/1.55 system-ui,sans-serif}main{max-width:1180px;margin:auto;padding:32px}a{color:#176a85}header,.study,.method{background:white;padding:24px;border:1px solid #dbe3e8;border-radius:12px;margin-bottom:20px}h1{font-size:30px;margin:10px 0}h2{margin:0 0 8px}h3{margin-bottom:6px}.muted{color:#536875}.badge{display:inline-block;background:#fff0cc;color:#6d5208;border-radius:20px;padding:4px 12px;font-size:14px}.scroll{overflow:auto}table{border-collapse:collapse;width:100%;font-size:13px}th,td{border-bottom:1px solid #dde5e9;padding:9px;text-align:left;white-space:nowrap}th{background:#f3f6f8}details{margin:12px 0;border:1px solid #dbe3e8;border-radius:8px;padding:12px}summary{cursor:pointer;font-weight:600}img{max-width:100%;height:auto}.links{display:flex;flex-wrap:wrap;gap:10px 22px}.note{border-left:3px solid #d7aa43;padding-left:12px}button{padding:8px 12px;cursor:pointer}@media print{details>*{display:block}a{color:inherit}.links{display:none}}</style><main>''',
 '<header><a href="/?flow='+session+'#node=pk&tab=input">← Animal PK workflow</a><div class="badge">Pending human model review</div><h1>Mouse PK · Exploratory mean curves</h1><p>Polymyxin B · 3 study groups · 12 fit combinations · 16 starts per fit · 7 fresh review-agent calls</p><p class="muted">R minpack.lm::nlsLM computes estimates. LangGraph → Prefect → Snakemake controls execution. No animal random effects were fitted.</p><div class="links">',
 a('comparison.csv','Download full metrics CSV'),a('comparison.json','Open full results JSON'),a('human_review_summary.json','Review findings'),a('human_review_template.json','Review decision template'),a('verification.json','Verification evidence'),a('review_package.zip','Download complete package'),'</div></header>',
 '<section class="method"><h2>How to read the results</h2><p>AIC/BIC comparisons apply only to identical observations within one study. AICc adds a small-sample penalty. R² is descriptive; numerical eligibility does not establish model adequacy or human predictive validity.</p><p class="note">Lognormal curves estimate a conditional median of reported means; additive-error curves estimate a conditional expectation. Error-family comparisons use complete concentration-density likelihoods. Structural comparisons within each error family are also supplied.</p><details><summary>Methods, units and limitations</summary><ul><li>1C/2C IV bolus models; 1C/2C first-order-input SC/IP models. Each study retains its own parameters.</li><li>k includes fitted curve parameters plus one residual-variance parameter. OFV = −2 logLik; AIC = OFV + 2k; BIC = OFV + k log(n).</li><li>Local Wald intervals and RSE exclude digitization and biological uncertainty. Means are assumed independent for this exploratory likelihood.</li><li>SC/IP CL/F and V/F are apparent parameters on the reported dose scale. F and absorption/disposition labels are not established.</li><li>CV, animal IIV, shrinkage, free exposure and human PK validation are not established. nlmixr2/NLME was not used for unverified individual identities.</li><li>Pre-fit user authorization was verified. Final scientific acceptance remains pending. Earlier failed/superseded attempts are retained separately.</li></ul>'+a('structural_comparison.json','Structural comparison JSON')+'</details></section>'
]
cols=[('compartments','Compartments'),('error_model','Error'),('AIC','AIC'),('AICc','AICc'),('BIC','BIC'),('R2_raw','R² raw'),('RMSE_raw','RMSE raw'),('converged_starts','Converged starts / 16'),('max_RSE_percent','Max RSE %'),('numerically_eligible','Numerical screen')]
for group,info in findings.items():
    items=[r for r in rows if r['analysis_id']==group]
    page+=['<section class="study"><h2>'+info['label']+'</h2><p class="muted">'+info['n']+'</p><h3>'+info['disposition']+'</h3><p>'+html.escape(info['text'])+'</p><p><strong>Next review:</strong> '+html.escape(info['next'])+'</p>',table(items,cols)]
    for r in items:
        folder=Path(r['result_folder']);rel=folder.relative_to(root)
        png=folder/'fit_and_diagnostics.png'
        image=base64.b64encode(png.read_bytes()).decode()
        page+=['<details><summary>'+html.escape(str(r['compartments'])+'C · '+r['error_model'])+' — curves, parameters and files</summary>',
            '<p>'+html.escape('; '.join(r['reasons']) or 'Finite local intervals; review residuals and identifiability before scientific selection.')+'</p>',
            '<img alt="'+r['candidate_id']+' fitted curves and residual diagnostics" src="data:image/png;base64,'+image+'">',
            '<h3>Curve parameters</h3>',table(r['parameters'],[('parameter','Parameter'),('estimate','Estimate'),('SE','SE'),('RSE_percent','RSE %'),('CI95_lower','95% lower'),('CI95_upper','95% upper'),('unit','Unit')]),
            '<h3>Conditional PK parameters</h3><p class="muted">IV CL/Q: L/h/kg; IV volumes: L/kg; half-life: h. Extravascular values retain F and the reported dose scale.</p>',
            table(r['conditional_pk_parameters'],[('parameter','Parameter'),('estimate','Estimate'),('RSE_percent','RSE %'),('CI95_lower','95% lower'),('CI95_upper','95% upper')]),
            '<div class="links">',*[a(rel/name,name) for name in ['parameters.csv','conditional_pk_parameters.csv','predictions.csv','profile_diagnostics.csv','exposure_summary.csv','fitted_curves.csv','fit_and_diagnostics.png']],'</div></details>']
    page+=['</section>']
page+=['<section class="method"><h2>Source and execution audit</h2><ul><li>S02: <a href="https://pmc.ncbi.nlm.nih.gov/articles/PMC5890666/">Landersdorfer et al.</a> — experimental design / Figure 1; published fitted parameters were not imported.</li><li>S05: <a href="https://journals.asm.org/doi/abs/10.1128/aac.00211-17">Lin et al.</a> — publication identity checked; detailed IV input qualification remains conditional on uploaded source notes.</li><li>S21: <a href="https://www.nature.com/articles/s41467-022-29234-3">Roberts et al.</a> — Methods and Figure 4; PMB plasma observations only in this group.</li></ul><p>The package includes source references and record IDs, exact R code snapshots, seeds, optimizer attempt logs, numerical results, each fresh agent request/response, workflow receipts and verification. No published benchmark results or human PK concentrations were fitted.</p><div class="links">'+a('report.json','Agent review audit')+a('human_review_summary.json','Scientific review summary')+'</div></section></main></html>']
(root/'review.html').write_text('\n'.join(page),encoding='utf-8')
# A static, read-only viewer uses the existing hash-validated download API.
web=PROJECT/'reports'
(web/'mouse-pk-review-20260923.html').write_text('\n'.join(page),encoding='utf-8')

archive=root/'review_package.zip'
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for p in root.rglob('*'):
        if p.is_file() and p not in [archive,root/'artifact_manifest.json']:
            z.write(p,p.relative_to(root))
    for p in job.rglob('*'):
        if p.is_file() and '.snakemake' not in p.parts:
            z.write(p,Path('workflow_audit')/p.relative_to(job))
    master=read_json(job/'inputs/summary_request.json')
    for name in ['approval_ref','preflight_ref']:
        ref=master[name];check_ref(ref);z.write(ref['path'],Path('source_decisions')/Path(ref['path']).name)
    z.write(BACKEND/'research_pipeline/scripts/package_mouse_summary_review.py','code/package_mouse_summary_review.py')
manifest=[{'name':p.relative_to(root).as_posix(),**file_ref(p),'kind':'result'} for p in root.rglob('*') if p.is_file() and p!=root/'artifact_manifest.json']
write_json(root/'artifact_manifest.json',{'files':manifest})
write_json(PROJECT/'outputs/Workbench_Preview_v22/runs/animal_pk_agent_runs'/session/(run_id+'.json'),{
    'job_id':run_id,'session_id':session,'agent_id':'MOUSE_SUMMARY_REVIEW','mode':'animal_pk_summary',
    'request_ref':file_ref(job/'inputs/summary_request.json'),'created_at':utcnow(),
    'authorization':'Explicit user-approved exploratory mean-curve plan; not generic NLME plan approval.'})
print(json.dumps({'review_url':'http://127.0.0.1:8773/assets/mouse-pk-review-20260923.html',
    'artifact_count':len(manifest),'package':str(archive),'checks':len(verifications),'fresh_agents':len(calls)},indent=2))
