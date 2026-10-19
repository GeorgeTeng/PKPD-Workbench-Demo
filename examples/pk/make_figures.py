"""PK structural diagnostics: unchanged observations and separately labelled simulations."""
import json,hashlib,time,zipfile
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.ticker import ScalarFormatter, NullFormatter
from scipy.optimize import least_squares
from research_pipeline.common import read_json,write_json
from research_pipeline.adequacy import file_ref,check_ref
ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).resolve().parent
DATA=ROOT/'outputs/Data_Cleaning_Rerun_20261016/run04/data_preparation'
MANIFEST=read_json(DATA/'normalization_manifest.json')
BINDINGS={'manifest':file_ref(DATA/'normalization_manifest.json')}
PLOT_ROWS={};FIGURES=[]
BLUE='#2466A5';ORANGE='#D56A26';TEAL='#238675';INK='#24364B';GRID='#E1E7EF'
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':11,'axes.titlesize':13,'axes.labelsize':11,
 'axes.spines.top':False,'axes.spines.right':False,'axes.edgecolor':'#8C99A9','axes.labelcolor':INK,
 'text.color':INK,'xtick.color':INK,'ytick.color':INK,'grid.color':GRID,'grid.alpha':.8,
 'axes.axisbelow':True,'legend.frameon':False,'figure.facecolor':'white','savefig.facecolor':'white'})

def dataset(id):
 d=next(x for x in MANIFEST['datasets'] if x['id']==id)
 for k in ('data','metadata_file','observation_view'):
  check_ref(d[k]);BINDINGS[id+':'+k]=d[k]
 return d,read_json(d['data']['path'])['records']

def field(d,header):
 return next(k for k,v in d['metadata']['source_table']['column_map'].items() if v==header)

def style(ax,log=False):
 ax.grid(True,linewidth=.6)
 if log:
  ax.set_yscale('log');ax.yaxis.set_major_formatter(ScalarFormatter())
 ax.set_xlabel('Time (h)');ax.set_ylabel('Concentration (mg/L)')

def save(fig,name,title,kind,footer):
 fig.suptitle(title,fontsize=17,fontweight='bold',x=.055,ha='left',y=.982)
 fig.text(.055,.024,footer,fontsize=9,color='#536376',va='bottom')
 fig.tight_layout(rect=(.025,.09,.99,.93),h_pad=2.0,w_pad=2.4)
 for suffix in ('png','svg'):fig.savefig(OUT/(name+'.'+suffix),dpi=180)
 FIGURES.append({'id':name,'title':title,'kind':kind,'png':file_ref(OUT/(name+'.png')),'svg':file_ref(OUT/(name+'.svg'))})
 plt.close(fig)

# 1. Explicitly simulated structures: no PMB calibration.
t=np.linspace(0,8,500)
c1=10*np.exp(-.5*t);fast=8*np.exp(-2*t);slow=2*np.exp(-.22*t);c2=fast+slow
fig,axes=plt.subplots(2,2,figsize=(13.8,9.8))
a=axes[0,0];style(a);a.plot(t,c1,color=BLUE,lw=2,label='1 compartment: 10 exp(-0.5t)');a.plot(t,c2,color=ORANGE,lw=2,label='2 compartments: 8 exp(-2t) + 2 exp(-0.22t)');a.set_title('A  Linear axes: both start at C(0) = 10');a.legend(fontsize=9)
a=axes[0,1];style(a,True);a.plot(t,c1,color=BLUE,lw=2,label='One exponential: straight on semilog axes');a.plot(t,c2,color=ORANGE,lw=2,label='Two exponentials: a changing slope');a.plot(t,fast,color=ORANGE,ls=':',alpha=.55);a.plot(t,slow,color=TEAL,ls=':',alpha=.75);a.set_ylim(.02,15);a.set_title('B  Semilog axes expose the fast and slow components');a.legend(fontsize=8.5)
a=axes[1,0];a.grid(True,linewidth=.6);a.plot(t,np.full_like(t,.5),color=BLUE,lw=2,label='1 compartment: constant');a.plot(t,(2*fast+.22*slow)/c2,color=ORANGE,lw=2,label='2 compartments: changes toward the terminal rate');a.set(xlabel='Time (h)',ylabel='Instantaneous -d ln(C)/dt (1/h)',title='C  Analytic slopes of the simulated IV curves');a.legend(fontsize=8.5)
a=axes[1,1];style(a,True);a.plot(t,c2,color=ORANGE,lw=2,label='True 2-compartment curve');late=np.array([3.,4.,6.,8.]);a.scatter(late,8*np.exp(-2*late)+2*np.exp(-.22*late),s=55,color=ORANGE,zorder=4,label='Only late samples');a.plot(t,slow,color=TEAL,ls='--',label='Slow exponential component');a.axvspan(0,1,color='#E7EDF5',alpha=.7);a.set_ylim(.2,15);a.set_title('D  Late-only sampling can miss the fast phase');a.legend(fontsize=8.5)
save(fig,'01_one_vs_two_simulated','SIMULATED IV BOLUS  |  What one versus two compartments can look like','SIMULATED',
 'Illustration only; arbitrary parameters, not estimated from PMB data. Linear disposition and first-order elimination assumed.\n'
 'Fast and slow exponential terms are hybrid modes; distribution and elimination occur simultaneously.')

# 2. Actual IV group means, both reported time coordinates retained.
d,rows=dataset('T0020');tk=field(d,'Time (h)');pk=field(d,'Pixel time (h)');ck=field(d,'Mean (mg/L)')
x=np.array([r[tk] for r in rows],float);xp=np.array([r[pk] for r in rows],float);y=np.array([r[ck] for r in rows],float)
assert np.all(y>0)
PLOT_ROWS['T0020']=[{'record_id':r['record_id'],'nominal_time_h':r[tk],'digitized_time_h':r[pk],'concentration_mg_L':r[ck]} for r in rows]
fig,axes=plt.subplots(2,2,figsize=(13.8,9.8))
for a,xx,title,log in [(axes[0,0],x,'A  All observations: linear scale',False),(axes[0,1],x,'B  All observations: semilog scale',True)]:
 style(a,log);a.scatter(xx,y,s=65,color=BLUE,zorder=4);a.set_title(title);a.set_xlabel('Source nominal time (h)')
a=axes[1,0];style(a,True);sel=x<=.6;a.scatter(x[sel],y[sel],s=65,color=BLUE,label='Nominal coordinate');a.scatter(xp[sel],y[sel],s=65,facecolors='none',edgecolors=ORANGE,marker='s',label='Digitized coordinate');a.set_xlim(0,.6);a.set_yticks([12,16,20,24]);a.yaxis.set_minor_formatter(NullFormatter());a.set_title('C  Early window: only three source mean points');a.set_xlabel('Source time coordinate (h)');a.legend(fontsize=9)
a=axes[1,1];a.grid(True,axis='x',linewidth=.6);a.scatter(x,np.ones_like(x),marker='|',s=500,color=BLUE,label='Nominal');a.scatter(xp,np.zeros_like(xp),marker='|',s=500,color=ORANGE,label='Digitized');a.set_yticks([0,1],['Digitized','Nominal']);a.set_ylim(-.5,1.5);a.set_xlabel('Source time coordinate (h)');a.set_title('D  Sampling: starts near 5 min; only two points at 3-6 h')
for xx in x:a.annotate(f'{xx:.3g}',(xx,1),xytext=(0,12),textcoords='offset points',ha='center',fontsize=8,rotation=45)
save(fig,'02_actual_IV_structure_views','OBSERVED T0020  |  Mouse IV plasma means: inspect shape and sampling','OBSERVED',
 'Eight digitized group means, not individual trajectories; no numerical SD supplied. No real-data PK fit or terminal slope estimated.\n'
 'Nominal and digitized times remain separate. The sharp 2-3 h decrease and sparse late tail need source/fit diagnostics, not a compartment label.')

# 3. Actual SC curves: compare source series, no dose normalization or pooling.
fig,axes=plt.subplots(1,2,figsize=(13.8,6.7));colors=plt.cm.viridis(np.linspace(.08,.88,5))
for id,color in zip(['T0028','T0029','T0030','T0031','T0032'],colors):
 d,rows=dataset(id);tk=field(d,'Time (h)');ck=field(d,'Mean plasma concentration (mg/L)')
 xx=np.array([r[tk] for r in rows],float);yy=np.array([r[ck] for r in rows],float)
 label=d['metadata']['source_table']['title'].split('SC ',1)[1].split(' plasma',1)[0]
 PLOT_ROWS[id]=[{'record_id':r['record_id'],'source_time_h':r[tk],'concentration_mg_L':r[ck]} for r in rows]
 for a in axes:a.scatter(xx,yy,color=color,s=42,label=label,zorder=4)
for a,log,title in zip(axes,[False,True],['A  Linear axes emphasize high concentrations','B  Semilog axes reveal each dose series']):
 style(a,log);a.set_xlabel('Source plotted time (h)');a.set_title(title);a.legend(title='As-reported SC dose',fontsize=8.5,title_fontsize=9)
save(fig,'03_actual_SC_dose_series','OBSERVED T0028-T0032  |  SC group means: absorption complicates structural interpretation','OBSERVED',
 'Separate source series, as-reported PMB sulphate doses; no dose normalization, fitted lines, pooling, or individual-animal interpretation.\n'
 'A rising phase or curved semilog profile after SC dosing can reflect absorption; it does not by itself establish two compartments.')

# 4. Actual rat source-column concentrations and a cell-status map, no trajectories.
d,rows=dataset('T0037');tk=field(d,'Time (h)');keys=[k for k,h in d['metadata']['source_table']['column_map'].items() if h.startswith('Rat ')]
labels=[d['metadata']['source_table']['column_map'][k] for k in keys];times=np.array([r[tk] for r in rows],float)
fig,axes=plt.subplots(1,2,figsize=(15,7));a=axes[0];style(a,True);colors=plt.cm.tab20(np.arange(len(keys)))
status=np.zeros((len(keys),len(rows)),int);codes={'QUANTIFIED':0,'BLQ':1,'MISSING_CANNULA_BLOCKAGE':2,'NOT_SAMPLED':3,'EMPTY_SLOT':4};details=[]
for i,key in enumerate(keys):
 for j,row in enumerate(rows):
  state=row['value_status'].get(key,'UNKNOWN');value=row.get(key);status[i,j]=codes.get(state,4)
  details.append({'record_id':row['record_id'],'source_column':labels[i],'source_time_h':row[tk],'raw_value':value,'status':state})
  if state=='QUANTIFIED' and isinstance(value,(int,float)) and value>0:a.scatter(row[tk],value,s=26,color=colors[i],label=labels[i] if j==0 else None,alpha=.8)
a.set_xlabel('Source-reported time (h)');a.set_title('A  Quantified source-column values only; no joined lines')
from matplotlib.lines import Line2D
a.legend(handles=[Line2D([],[],marker='o',linestyle='',color=color,label=label) for color,label in zip(colors,labels)],title='Source column',ncol=2,fontsize=8,title_fontsize=9,loc='upper right')
PLOT_ROWS['T0037']=details
from matplotlib.colors import ListedColormap,BoundaryNorm
cmap=ListedColormap(['#DCE9F5','#E7A053','#C45B62','#B7C2CE','#E4E4E4'])
a=axes[1];a.imshow(status,aspect='auto',cmap=cmap,norm=BoundaryNorm(np.arange(-.5,5,1),5));a.set_yticks(range(len(keys)),labels);a.set_xticks(range(len(times)),[f'{t:.3g}' for t in times],rotation=45);a.set_xlabel('Source-reported time (h)');a.set_title('B  Cell availability: Q, BLQ, blockage (*), not sampled (-)')
chars={0:'Q',1:'BLQ',2:'*',3:'-',4:'?'}
for i in range(len(keys)):
 for j in range(len(times)):a.text(j,i,chars[status[i,j]],ha='center',va='center',fontsize=8,color=INK)
save(fig,'04_actual_rat_values_and_status','OBSERVED T0037  |  Concentration coverage and censoring before individual PK work','OBSERVED',
 'Column names are retained as source-series labels; the prepared view does not authorize longitudinal animal joins. IV administration was over 1 minute.\n'
 'Unknown-limit BLQ and missing cells are shown as statuses, never concentration zero; no real-data fit, imputation or interindividual variability estimate.')

# 5. Same simulated observations, same log-error objective, two candidate fits.
rng=np.random.default_rng(20261016)
ts=np.array([.03,.08,.17,.3,.5,.8,1.2,2,3,4,6,8.])
truth=8*np.exp(-2*ts)+2*np.exp(-.22*ts);obs=truth*np.exp(rng.normal(0,.10,len(ts)))
def one(theta,time):
 A,k=np.exp(theta);return A*np.exp(-k*time)
def two(theta,time):
 A,B,beta,gap=np.exp(theta);return A*np.exp(-(beta+gap)*time)+B*np.exp(-beta*time)
f1=least_squares(lambda z:np.log(obs)-np.log(one(z,ts)),np.log([5,.4]),bounds=([-8,-7],[6,3]))
fits=[least_squares(lambda z:np.log(obs)-np.log(two(z,ts)),np.log(start),bounds=([-8,-8,-7,-7],[6,6,1.5,4])) for start in [[8,2,.22,1.78],[5,5,.4,1.6],[3,7,.1,.9]]]
f2=min(fits,key=lambda fit:sum(fit.fun**2))
p1=one(f1.x,ts);p2=two(f2.x,ts)
assert f1.success and f2.success and np.all(np.isfinite(p1)) and np.all(np.isfinite(p2))
fig,axes=plt.subplots(2,2,figsize=(13.8,9.8));a=axes[0,0];style(a,True);a.scatter(ts,obs,color=INK,s=45,label='Simulated observations',zorder=4);a.plot(t,one(f1.x,t),color=BLUE,label='One-compartment fit');a.plot(t,two(f2.x,t),color=ORANGE,label='Two-compartment fit');a.set_title('A  Both candidates fitted to exactly the same simulated points');a.legend(fontsize=8.5)
a=axes[0,1];a.grid(True,linewidth=.6);a.axhline(0,color='#8090A0',ls='--');a.plot(ts,np.log(obs/p1),'o-',color=BLUE,label='One compartment');a.plot(ts,np.log(obs/p2),'s-',color=ORANGE,label='Two compartments');a.set(xlabel='Time (h)',ylabel='Log residual: ln(observed / predicted)',title='B  A systematic time pattern suggests structural mismatch');a.legend(fontsize=9)
a=axes[1,0];a.grid(True,linewidth=.6);limits=[min(obs.min(),p1.min(),p2.min())*.8,max(obs.max(),p1.max(),p2.max())*1.2];a.plot(limits,limits,color='#8090A0',ls='--');a.scatter(p1,obs,color=BLUE,label='One compartment');a.scatter(p2,obs,color=ORANGE,marker='s',label='Two compartments');a.set_xscale('log');a.set_yscale('log');a.set(xlabel='Predicted concentration (mg/L)',ylabel='Simulated observed concentration (mg/L)',title='C  Observed versus predicted: inspect the identity line');a.legend(fontsize=9)
a=axes[1,1];a.grid(True,linewidth=.6);a.axhline(0,color='#8090A0',ls='--');a.scatter(p1,np.log(obs/p1),color=BLUE,label='One compartment');a.scatter(p2,np.log(obs/p2),color=ORANGE,marker='s',label='Two compartments');a.set_xscale('log');a.set(xlabel='Predicted concentration (mg/L)',ylabel='Log residual: ln(observed / predicted)',title='D  Residual versus prediction also checks concentration trends');a.legend(fontsize=9)
save(fig,'05_simulated_fit_diagnostics','SIMULATED DATA  |  How candidate-fit diagnostics can distinguish structure','SIMULATED_FITS',
 'Generating model is two compartments; log-error SD = 0.10, seed 20261016. Both fits minimize the same log-residual sum of squares.\n'
 'These are fixed-effects toy fits, not PMB fits, CWRES or a VPC. Real model selection also requires uncertainty, identifiability and predictive checks.')
PLOT_ROWS['SIMULATED_FITS']={'time_h':ts.tolist(),'observations':obs.tolist(),'truth':truth.tolist(),'one_predictions':p1.tolist(),'two_predictions':p2.tolist(),
 'one_parameters_A_k':np.exp(f1.x).tolist(),'two_parameters_A_B_beta_alpha_minus_beta':np.exp(f2.x).tolist(),
 'one_log_rss':float(sum(f1.fun**2)),'two_log_rss':float(sum(f2.fun**2)),'noise_sd_log':.10,'seed':20261016}
write_json(OUT/'plot_values.json',PLOT_ROWS)
for ref in BINDINGS.values():check_ref(ref)
write_json(OUT/'figure_manifest.json',{'figures':FIGURES,'input_bindings':BINDINGS,'real_data_fitted':False,
 'real_data_imputed':False,'model_selected_for_real_data':False,'formal_eda_pipeline_executed':False,
 'simulations':'Illustrative linear one/two compartment examples, not drug-specific estimates.'})
with zipfile.ZipFile(OUT/'pk_diagnostic_figures.zip','w',zipfile.ZIP_DEFLATED) as z:
 for f in FIGURES:
  for key in ('png','svg'):z.write(f[key]['path'],Path(f[key]['path']).name)
 for name in ('figure_manifest.json','plot_values.json','make_figures.py'):z.write(OUT/name,name)
print(json.dumps({'figures':len(FIGURES),'output':str(OUT),'simulated_log_rss':{'one':float(sum(f1.fun**2)),'two':float(sum(f2.fun**2))},'real_data_fitted':False},indent=2))
