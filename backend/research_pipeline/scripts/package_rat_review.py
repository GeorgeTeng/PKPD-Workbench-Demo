"""Publish completed rat fits for review without changing execution receipts or refitting."""
import base64
import csv
import html
import math
import shutil
import zipfile
from pathlib import Path
from urllib.parse import quote
import numpy as np
from scipy.linalg import expm
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from research_pipeline.common import PROJECT, read_json, write_json, utcnow
from research_pipeline.adequacy import file_ref, check_ref
from research_pipeline.animal_pk_individual import max_available_rse
from research_pipeline.animal_pk_nlmixr2 import digest

SESSION='flow_f75c012fdd294693847d00f393ff3271'
RUNS=PROJECT/'outputs/Workbench_Preview_v22/runs'
JOBS=PROJECT/'outputs/Workbench_Preview_v22/state/workbench_jobs'
PUBLICATION='RAT_PK_REVIEW_20260923'
ROOT=RUNS/PUBLICATION/'animal_pk'
if ROOT.exists():
    raise RuntimeError('Publication already exists; preserve it and use a new publication ID.')
ROOT.mkdir(parents=True)
all_rows=[];attempts=[];checks=[];agent_calls=[];source_map=[]

def csv_rows(path):
    with Path(path).open(encoding='utf-8-sig',newline='') as f:return list(csv.DictReader(f))

def save_csv(path,rows,columns):
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,columns,extrasaction='ignore');writer.writeheader();writer.writerows(rows)

for round_no,optimizer in [(1,'bobyqa'),(2,'nlminb')]:
    run_id=f'RAT_PK_20260923_INDIVIDUAL_{round_no:02d}'
    source=RUNS/run_id/'animal_pk';job=JOBS/run_id
    assert read_json(job/'status.json')['status']=='WAITING_FOR_HUMAN_REVIEW'
    report=read_json(source/'report.json')
    assert report['fit_calls']==12 and report['llm_calls']==7 and report['model_release'] is False
    # Verify immutable original manifests before copying; original JSON references remain intact.
    for ref in read_json(source/'artifact_manifest.json')['files']:check_ref(ref)
    copied=ROOT/f'round_{round_no:02d}'
    shutil.copytree(source,copied)
    shutil.copytree(job,copied/'workflow_audit',ignore=shutil.ignore_patterns('.snakemake'))
    request=read_json(job/'inputs/individual_request.json')
    for ref in request['source_refs']:
        check_ref(ref)
        destination=ROOT/'sources'/ref['sha256'][:12]/Path(ref['path']).name
        destination.parent.mkdir(parents=True,exist_ok=True)
        if not destination.exists():shutil.copy2(ref['path'],destination)
        source_map.append({'original_ref':ref,'archive_path':destination.relative_to(ROOT).as_posix()})
    calls=list(source.glob('candidates/*/agent/*/execution.json'))+list(source.glob('comparison_agent/*/execution.json'))
    assert len(calls)==7
    for path in calls:
        ex=read_json(path);assert ex['status']=='COMPLETED' and ex['fresh_session']
        agent_calls.append({'round':round_no,'execution_ref':file_ref(path),'invocation_id':ex.get('invocation_id',path.parent.name)})
    for row in read_json(source/'comparison.json')['rows']:
        row['round']=round_no;row['optimizer']=optimizer
        row['max_RSE_percent']=max_available_rse(row['parameters'])
        row['archive_folder']=(Path(f'round_{round_no:02d}')/Path(row['result_folder']).relative_to(source)).as_posix()
        all_rows.append(row)
    for folder in sorted(source.glob('candidates/*/attempts/*')):
        raw=read_json(folder/'raw_result.json');fit=read_json(folder/'fit_result.json');ex=read_json(folder/'execution.json')
        assert ex['status']=='COMPLETED' and ex['returncode']==0
        check_ref(ex['worker_code_ref']);check_ref(fit['raw_result_ref']);check_ref(fit['diagnostics_ref'])
        check_ref(fit['input_ref'])
        assert ex['request_sha256']==digest(read_json(folder/'input.json'))
        n,k,ll=fit['n_observations'],fit['n_parameters'],fit['log_likelihood']
        assert n==102 and fit['n_subjects']==11
        assert math.isclose(raw['AIC'],-2*ll+2*k,abs_tol=1e-7)
        assert math.isclose(raw['BIC'],-2*ll+k*math.log(n),abs_tol=1e-7)
        # Independent matrix-exponential check of finite-infusion typical curves.
        pars={p['parameter']:p['estimate'] for p in raw['parameters']}
        if 'Q' in pars:
            cl,vc,q,vp=[pars[x] for x in ('CL','VC','Q','VP')]
            matrix=np.array([[-(cl+q)/vc,q/vp],[q/vc,-q/vp]])
            forcing=np.array([60.,0.])
        else:
            vc=pars['VC'];matrix=np.array([[-pars['CL']/vc]]);forcing=np.array([60.])
        def conc(t):
            on=min(t,1/60)
            amount=np.linalg.solve(matrix,(expm(matrix*on)-np.eye(len(matrix)))@forcing)
            return float((expm(matrix*max(0,t-1/60))@amount)[0]/vc)
        curve=csv_rows(folder/'typical_curve.csv')
        delta=max(abs(conc(float(p['time_h']))-float(p['typical_concentration_mg_L'])) for p in curve)
        assert delta<1e-7
        preds=csv_rows(folder/'predictions.csv');assert len(preds)==102 and len({p['ID'] for p in preds})==11
        check={'round':round_no,'optimizer':optimizer,'candidate_id':folder.parent.parent.name,'attempt':int(folder.name),
            'AIC':raw['AIC'],'BIC':raw['BIC'],'logLik':ll,'engine_success_signal':raw['engine_convergence_signal'],
            'numerical_eligibility':fit['numerical_eligibility'],'max_curve_check_error_mg_L':delta,
            'critical_messages':raw['critical_numerical_messages'],'archive_folder':(Path(f'round_{round_no:02d}')/folder.relative_to(source)).as_posix()}
        attempts.append(check)
assert len(attempts)==24 and len(agent_calls)==14
rows=[]
for candidate in sorted({r['candidate_id'] for r in all_rows}):
    variants=[r for r in all_rows if r['candidate_id']==candidate]
    best=max(variants,key=lambda r:r['logLik'])
    best['delta_AIC_between_optimizers']=abs(variants[0]['AIC']-variants[1]['AIC'])
    best['optimizer_attempts']=4
    rows.append(best)
rows.sort(key=lambda r:r['AIC'])
for row in rows:row['delta_AIC']=row['AIC']-rows[0]['AIC']
assert not any(r['screen_eligible'] for r in rows)

correction={'field':'max_RSE_percent','reason':'Missing structural standard errors must remain unknown. The original summary used 0 when all values were missing.',
    'affected_candidate':'RAT_S21_IV_1C_combined','corrected_value':None,
    'raw_estimates_changed':False,'original_receipts_changed':False,'future_summary_code_fixed':True,
    'publication_rule':'Maximum among available finite structural RSE values; null when none are available. See parameter rows for completeness.'}
write_json(ROOT/'summary_correction.json',correction)
write_json(ROOT/'source_archive_map.json',{'files':source_map,'note':'Original hash-bound audit references are preserved. Use archive_path to locate copies after moving this package.'})
write_json(ROOT/'comparison.json',{'rows':rows,'scientific_selection':'PENDING_HUMAN_REVIEW','model_release':False,
    'ranking_basis':'Same 102 quantified plasma observations from 11 rats, total PMB, 1 mg/kg over 1 min IV. Approximate FOCEI likelihood; all candidates numerically flagged.',
    'summary_correction':correction})
cols=['candidate_id','compartments','error_model','n_subjects','n_observations','n_parameters','logLik','minus2logLik','AIC','BIC','delta_AIC',
    'R2_population','R2_conditional','RMSE_population','RMSE_conditional','max_RSE_percent','max_parameter_correlation','optimizer',
    'delta_AIC_between_optimizers','selected_attempt','screen_eligible','model_release']
save_csv(ROOT/'comparison.csv',rows,cols)
save_csv(ROOT/'all_24_attempts.csv',attempts,['round','optimizer','candidate_id','attempt','AIC','BIC','logLik','engine_success_signal','numerical_eligibility','critical_messages','archive_folder'])
write_json(ROOT/'all_24_attempts.json',{'attempts':attempts})
params=[dict(candidate_id=r['candidate_id'],**p) for r in rows for p in r['parameters']]
save_csv(ROOT/'parameters.csv',params,['candidate_id','parameter','estimate','unit','log_scale_SE','delta_method_RSE_percent','confidence_interval_95'])
verification={'status':'ENGINEERING_ARTIFACT_CHECKS_PASSED','created_at':utcnow(),'completed_R_fits':24,'fresh_completed_agent_calls':14,
    'original_manifest_hashes_verified':True,'worker_snapshot_and_input_hashes_verified':True,'AIC_BIC_algebra_verified':True,
    'finite_IV_infusion_curve_independently_verified':True,'max_curve_check_error_mg_L':max(a['max_curve_check_error_mg_L'] for a in attempts),
    'fit_engine':'nlmixr2 FOCEI','scientific_numerical_screen_passed':False,'independent_predictive_validation':False,'human_model_acceptance':False}
write_json(ROOT/'verification.json',verification)
review={'status':'NEEDS_HUMAN_SCIENTIFIC_REVIEW','priority_candidate':rows[0]['candidate_id'],'accepted_candidate':None,'model_release':False,
    'why_not_passed':[
      'All six candidates retain gradient/covariance engine warnings across the optimizer review; a success exit alone does not establish a stable optimum.',
      'The lowest-AIC 2C combined candidate also reports that the last objective was not at a minimum. Its Wald uncertainty remains conditional on unresolved numerical issues.',
      'The 2C additive candidate violates the current catalog parameter-correlation criterion (>0.95).',
      'The 1C combined candidate has unavailable covariance/structural uncertainty and an additive-error boundary; RSE is NA.',
      'Two BLQ records at 6 h cannot be treated with a study-specific censored likelihood until the numeric LLOQ is available.'
    ],
    'review_actions':[
      'Inspect preserved fit.rds scaleInfo, gradients, parameter correlations and objective behavior. Resolve numerical problems before accepting a candidate.',
      'Review profile and residual plots, particularly early peaks and terminal observations. Consider justified random-effects or residual-model revision if problems persist.',
      'Retrieve the study assay LLOQ and evaluate BLQ sensitivity; never import another study limit or replace BLQ by zero.',
      'If predictive validation is required, plan animal-level validation and report failed folds; conditional R2 is an in-sample fit measure.'
    ],
    'review_agent_information_boundary':'The fresh text review agents received structured results and warnings, not the PNG/CSV residual and shrinkage contents. Their statements that these diagnostics were not supplied describe their inputs. The actual R artifacts are included here for human review.',
    'missing_materials':['Study-specific numeric plasma assay LLOQ','Individual body weights if absolute per-animal CL/V or covariate analysis is intended'],
    'not_required_for_this_fit':['Human PK','Human protein binding','Rat PD endpoint pairing'],
    'assumptions':['Verified serial identities from source methods and columns','Per-kg PK on the reported dose scale','Quantified-only exploratory likelihood','Diagonal lognormal IIV on CL and VC'],
    'summary_correction':correction}
write_json(ROOT/'human_review_summary.json',review)
write_json(ROOT/'human_review_template.json',{'status':'AWAITING_USER_DECISION','reviewer':None,'candidate_ids':[r['candidate_id'] for r in rows],
    'decision':None,'allowed_decisions':['RETAIN_FOR_EXPLORATORY_REVIEW','REVISE','REJECT'],'requested_changes':[],
    'final_scientific_acceptance':False,'human_scaling_release':False})
write_json(ROOT/'publication_request.json',{'kind':'READ_ONLY_DERIVED_REVIEW_PUBLICATION','source_job_ids':['RAT_PK_20260923_INDIVIDUAL_01','RAT_PK_20260923_INDIVIDUAL_02'],
    'refits_performed_by_publication':0,'user_request':'接下来是大鼠的模拟','scientific_acceptance':False})

# Overview uses exported R curves; no new fitted model or altered observations.
fig,axes=plt.subplots(1,2,figsize=(12,4.6),layout='constrained')
for row in rows:
    values=csv_rows(ROOT/row['archive_folder']/'typical_curve.csv')
    t=np.array([float(x['time_h']) for x in values]);c=np.array([float(x['typical_concentration_mg_L']) for x in values])
    for ax in axes:ax.plot(t,c,label=f"{row['compartments']}C {row['error_model']}",linewidth=1.6)
axes[1].set_yscale('log')
for ax in axes:
    ax.set(xlabel='Time (h)',ylabel='Typical total plasma PMB (mg/L)',xlim=(0,6));ax.grid(alpha=.18)
axes[0].legend(fontsize=8)
fig.suptitle('Rat IV 1 mg/kg over 1 minute · typical eta = 0 curves · all candidates flagged',fontsize=11)
fig.savefig(ROOT/'typical_curves.png',dpi=170);plt.close(fig)

BASE=f'/ui-api/workflow/sessions/{SESSION}/animal-pk/agent-runs/{PUBLICATION}/files/'
def url(path):return BASE+'/'.join(quote(p,safe='') for p in Path(path).parts)
def link(path,label):return '<a href="'+url(path)+'" target="_blank">'+html.escape(label)+'</a>'
def fmt(value):
    if value is None:return 'NA'
    if isinstance(value,bool):return 'Pass' if value else 'Not passed'
    return f'{value:.3f}' if isinstance(value,(float,int)) else str(value)
def table(data,columns):
    return '<div class="scroll"><table><thead><tr>'+''.join('<th>'+html.escape(label)+'</th>' for _,label in columns)+'</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+html.escape(fmt(row.get(key)))+'</td>' for key,_ in columns)+'</tr>' for row in data)+'</tbody></table></div>'
def img(path,alt):return '<img loading="lazy" alt="'+html.escape(alt)+'" src="data:image/png;base64,'+base64.b64encode((ROOT/path).read_bytes()).decode()+'">'
style='''body{margin:0;background:#f5f7f8;color:#233840;font:15px/1.6 system-ui,sans-serif}main{max-width:1180px;margin:auto;padding:28px}section,header{background:white;border:1px solid #dce4e8;border-radius:12px;padding:24px;margin-bottom:18px}a{color:#176b80}h1{margin:8px 0;font-size:30px}h2{margin:0 0 8px;font-size:22px}.badge{display:inline-block;border-radius:20px;background:#fff0ce;color:#77580b;padding:4px 12px}.muted{color:#596d76}.links{display:flex;flex-wrap:wrap;gap:9px 22px}.scroll{overflow:auto}table{width:100%;border-collapse:collapse;font-size:13px}th,td{padding:9px;text-align:left;white-space:nowrap;border-bottom:1px solid #e1e7eb}th{background:#f4f7f8}details{padding:12px;border:1px solid #dce4e8;border-radius:8px;margin-top:12px}summary{cursor:pointer;font-weight:600}img{max-width:100%;height:auto}.note{border-left:3px solid #d6a241;padding-left:14px}pre{white-space:pre-wrap;font-size:12px}@media(max-width:600px){main{padding:10px}section,header{padding:16px}h1{font-size:25px}}'''
page=['<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Rat PK · Model review</title><link rel="icon" href="data:,"><style>'+style+'</style><main>',
    '<header><a href="/assets/animal-pk-control.html?session='+SESSION+'">← Animal PK workspace</a><h1>Rat PK · Individual NLME review</h1><div class="badge">All candidates flagged · human review pending</div><p>Polymyxin B · 11 rats · 102 quantified concentrations · 6 model configurations · 24 R fits · 14 fresh review-agent calls</p><p class="muted">LangGraph → Prefect → Snakemake → R / nlmixr2 FOCEI. This page summarizes two completed runs and performs no refitting.</p><div class="links">',
    link('comparison.csv','Metrics CSV'),link('comparison.json','Results JSON'),link('parameters.csv','Parameters CSV'),link('human_review_summary.json','Reasons and next actions'),link('verification.json','Execution verification'),link('review_package.zip','Complete audit ZIP'),'</div></header>',
    '<section><h2>Current assessment</h2><p>The 2C combined-error model has the lowest approximate AIC/BIC and is the first candidate to investigate. It is <strong>not accepted</strong>: gradient/covariance and objective-minimum warnings remain with both optimizers.</p><p class="note">No candidate passed all numerical criteria. Successful process exits and close optimizer agreement are not scientific acceptance. Human scaling remains blocked.</p>',
    table(rows,[('compartments','Compartments'),('error_model','Residual error'),('AIC','AIC'),('BIC','BIC'),('delta_AIC','ΔAIC'),('R2_population','R² population'),('R2_conditional','R² individual'),('max_RSE_percent','Max structural RSE %'),('screen_eligible','Numerical screen')]),
    '<p class="muted">Rows use the highest returned log-likelihood for each configuration across both optimizers and starts; all 24 attempts remain available. FOCEI metrics are approximate. Conditional individual R² uses fitted animal effects and does not measure external prediction.</p>',
    img(Path('typical_curves.png'),'Typical rat concentration time curves'),
    '<details><summary>Methods, source qualification and limitations</summary><ul><li>1 mg/kg IV over 1 minute; observations 0.17–6 h. Linear 1C/2C disposition; diagonal lognormal IIV on CL and VC; additive/proportional/combined errors.</li><li>bobyqa and nlminb each used two starts per configuration. Three candidates ran in parallel, one R CPU thread per fit.</li><li>CL/Q are L/h/kg; VC/VP are L/kg. No individual weight or free fraction was invented. Curves are typical eta=0 predictions, not population arithmetic means or predictive intervals.</li><li>Two BLQ records at 6 h have unknown LLOQ; six other missing observations were preserved outside the likelihood. Quantified-only fitting may bias terminal estimates.</li><li>S07 serum/whole-lung group means were kept separate. No 3C fit: the first sample follows the short infusion, with insufficient evidence for another distribution phase.</li><li>No bootstrap, VPC, animal-level cross-validation or human prediction has been completed.</li><li>The original paper reported noncompartmental analysis; these NLME candidates are a new exploratory reanalysis.</li></ul><a href="https://www.nature.com/articles/s41467-022-29234-3" target="_blank">Source paper · Methods / Pharmacokinetic studies</a> · '+link('round_01/workflow_audit/inputs/source_qualification.json','Source and exclusions')+'</details></section>',
    '<section><h2>Why the models did not pass</h2><ul>'+''.join('<li>'+html.escape(x)+'</li>' for x in review['why_not_passed'])+'</ul><h3>Next review actions</h3><ol>'+''.join('<li>'+html.escape(x)+'</li>' for x in review['review_actions'])+'</ol><p class="muted">The text review agents did not receive the residual images or CSV contents. Those diagnostics exist in the R outputs below; review-agent statements about missing inputs are not proof of missing artifacts.</p>'+link('human_review_template.json','Download review decision template')+'</section>',
    '<section><h2>Model folders</h2><p>Open a candidate to inspect parameters, every rat profile, residuals and the original model code.</p>']
for row in rows:
    rel=Path(row['archive_folder']);folder=ROOT/rel
    messages=row['diagnostics']['run_information']
    raw=read_json(folder/'raw_result.json')
    page+=['<details><summary>'+html.escape(f"{row['compartments']}C · {row['error_model']} · AIC {row['AIC']:.2f}")+' — not passed</summary>',
       '<p>'+html.escape(f"Displayed run: {row['optimizer']}, start {row['selected_attempt']}. AIC difference between optimizer representatives: {row['delta_AIC_between_optimizers']:.4f}.")+'</p>',
       '<ul>'+''.join('<li>'+html.escape(x)+'</li>' for x in messages)+'</ul>',
       table(row['parameters'],[('parameter','Parameter'),('estimate','Estimate'),('unit','Unit'),('delta_method_RSE_percent','RSE %'),('confidence_interval_95','95% Wald interval')]),
       '<p class="muted">Intervals and RSE are provisional while numerical warnings remain. Missing values are NA; the original 1C combined summary was corrected only in this derived publication. The raw fit outputs and original receipts are unchanged.</p>',
       img(rel/'individual_fits_linear.png','Individual linear scale profiles'),img(rel/'individual_fits_semilog.png','Individual semilog profiles'),img(rel/'residual_diagnostics.png','Residual diagnostic plots'),
       '<details><summary>Variability, shrinkage and fitted model summary</summary><pre>'+html.escape((folder/'fit_summary.txt').read_text(encoding='utf-8'))+'</pre>'+table(csv_rows(folder/'shrinkage.csv'),[('','Statistic'),('eta.cl','eta CL'),('eta.vc','eta VC'),('IWRES','IWRES')])+'</details>',
       '<div class="links">'+link(rel/'model.R','R model')+link(rel/'input.json','Fit input')+link(rel/'raw_result.json','Raw estimates')+link(rel/'predictions.csv','Predictions')+link(rel/'typical_curve.csv','Typical curve CSV')+link(rel/'covariance.csv','Covariance')+link(rel/'omega.csv','IIV matrix')+link(rel/'shrinkage.csv','Shrinkage')+link(rel/'fit.rds','Fitted R object')+link(rel/'execution.json','R execution')+'</div></details>']
page+=['</section><section><h2>Audit and reproduction</h2><p>The complete ZIP contains both original run folders, exact R workers and model code, fit inputs, RDS objects, all agent requests/responses, LangGraph checkpoints, Prefect/Snakemake status and logs, source-file copies and a mapping of original paths to archive paths.</p><p>Engineering checks verified all source/output hashes, 24 R execution records, 14 fresh completed reviews, AIC/BIC arithmetic and an independent matrix-exponential reconstruction of the finite-infusion curves. These checks do not clear the scientific numerical warnings.</p><div class="links">'+link('all_24_attempts.csv','All 24 attempts')+link('source_archive_map.json','Source archive mapping')+link('summary_correction.json','Summary correction record')+link('review_package.zip','Complete audit ZIP')+'</div></section></main></html>']
page_text=''.join(page)
(ROOT/'review.html').write_text(page_text,encoding='utf-8')
(PROJECT/'reports/rat-pk-review-20260923.html').write_text(page_text,encoding='utf-8')
(ROOT/'README.md').write_text('# Rat individual PK review\n\nAll six configurations remain flagged; no scientific model is accepted.\n\n11 rats, 102 quantified observations, 24 R fits, 14 fresh review calls.\n\nLowest approximate AIC/BIC: 2C combined error, AIC '+f"{rows[0]['AIC']:.3f}"+'. Review numerical warnings before selection.\n\nOpen review.html for plots; comparison.csv/json, parameters.csv and all_24_attempts.csv contain numerical outputs. Missing RSE is NA, never zero.\n\nOriginal execution JSON retains original absolute paths and hashes; source_archive_map.json locates copied source files. Each attempts directory includes its exact R worker, self-contained input.json records and RDS. Create a new output directory before rerunning a numerical attempt. With matching R packages, run Rscript --vanilla animal_pk_nlmixr2.R input.json <new-output-directory>/raw_result.json. Set PKPD_R_LIB if your R library is elsewhere. Preserve the original audit inputs and outputs.\n\nNo human PK simulation or validation is released.\n',encoding='utf-8')
shutil.copy2(__file__,ROOT/'package_rat_review.py')
write_json(ROOT/'report.json',{'kind':'READ_ONLY_DERIVED_REVIEW_PUBLICATION','status':'NEEDS_HUMAN_SCIENTIFIC_REVIEW','model_release':False,
    'verification':verification,'review':review})
zip_path=ROOT/'review_package.zip'
with zipfile.ZipFile(zip_path,'w',zipfile.ZIP_DEFLATED) as z:
    for p in sorted(ROOT.rglob('*')):
        if p.is_file() and p!=zip_path:z.write(p,p.relative_to(ROOT).as_posix())
write_json(ROOT/'artifact_manifest.json',{'files':[{'name':p.relative_to(ROOT).as_posix(),**file_ref(p),'kind':'review_publication'}
    for p in sorted(ROOT.rglob('*')) if p.is_file() and p!=ROOT/'artifact_manifest.json'],'model_release':False})
write_json(RUNS/'animal_pk_agent_runs'/SESSION/(PUBLICATION+'.json'),{'job_id':PUBLICATION,'session_id':SESSION,'agent_id':'RAT_REVIEW_PUBLICATION',
    'mode':'PK_REVIEW_PUBLICATION','request_ref':file_ref(ROOT/'publication_request.json'),'created_at':utcnow(),
    'note':'Derived artifact registration for downloads only; not a fabricated execution job or workflow-plan approval.'})
print({'publication':str(ROOT),'report_url':'http://127.0.0.1:8773/assets/rat-pk-review-20260923.html','zip_bytes':zip_path.stat().st_size,
    'best_descriptive_candidate':rows[0]['candidate_id'],'AIC':rows[0]['AIC'],'BIC':rows[0]['BIC'],'accepted':False})
