/* Navigation hierarchy only: Workflow → stage → step → detail. Backend stage IDs, gates and execution stay intact. */
'use strict';
const moduleViews = {
 context_bundle: {title:'Context & Project Rules', owners:['context'], children:['compression','prc'], parts:[
  ['compression','Context compression'], ['prc','Project Rules Agent']
 ]},
 compression: {title:'Context compression', parent:'context_bundle', owner:'context', parts:[
  ['gaps','Read proposal & identify gaps'], ['attachments','File evidence agents'], ['reconcile','Reconcile answers & conflicts'],
  ['extract','Extract & classify statements'], ['bindings','Check PK bindings'],
  [['faithfulness','Faithfulness review'],['completeness','Completeness review'],['conflicts','Global conflict review']],
  ['publish','Publish context']
 ]},
 prc: {title:'Project Rules Agent', parent:'context_bundle', owner:'context', parts:[
  ['requirements','Extract project-specific constraints'], ['fields','Bind evidence & consuming steps'],
  ['review','Independent source review'], ['publish','Publish project rules']
 ]},
 data_bundle: {title:'Data Assessment & Preparation', owners:['adequacy','prepare'], children:['data_requirements','data_coverage','data_preparation','data_handoff'], parts:[
  ['data_requirements','DR · Define data requirements'], ['data_coverage','DC · Label data & check coverage'],
  ['data_preparation','DP · Prepare & QC'], ['data_handoff','DH · Validate metadata & hand off']
 ]},
 data_requirements: {title:'DR · Define data requirements', parent:'data_bundle', owner:'adequacy', agent:'DR', parts:[
  ['requirements','Read main.json & project rules'], ['define','Define tasks, data requirements & file access']
 ]},
 data_coverage: {title:'DC · Label data & check coverage', parent:'data_bundle', owner:'adequacy', agent:'DC', parts:[
  ['labels','Review and label each file'], ['review','Independent coverage review'], ['coverage','Record matches & missing data']
 ]},
 data_preparation: {title:'DP · Prepare & QC', parent:'data_bundle', owner:'prepare', agent:'DP', parts:[
  ['plan','Plan source-bound transformations'], ['execute','Run deterministic preparation & QC']
 ]},
 data_handoff: {title:'DH · Validate metadata & hand off', parent:'data_bundle', owner:'prepare', agent:'DH', parts:[
  ['validate','Check metadata, source bindings & data hashes'], ['review','Review scoped data handoff'], ['release','Publish data, metadata & reports']
 ]},
 // Agent design for one species. The module runs this loop once per assessed species;
 // accepted models from every species then feed PK translation.
 pk: {title:'Animal PK modeling', owner:'pk', perSpecies:true, parts:[
  ['evidence','PK Evidence Agent',{note:'Reviewed PK data + EDA → suggestions'}],
  ['candidates','Candidate Specification Agent',{note:'Defines candidate structures and assumptions',
   side:{key:'library',label:'Model Library Agent',note:'Retrieves applicable model structures',edge:'input'}}],
  ['plan','Model Plan Approval Agent',{note:'Records human sign-off before fitting',role:'human'}],
  ['fit','Model Fitting Agent',{note:'Runs qualified numerical adapters'}],
  ['diagnostics','Diagnostic Analysis Agent',{note:'Fit checks and accessible plots'}],
  ['comparison','Model Comparison Agent',{note:'Comparable fits; AIC / BIC if valid'}],
  ['review','Scientific Review Agent',{note:'Presents evidence for human decision',role:'human',
   side:{key:'support',label:'PK Support Agent',note:'Drafts candidate and revision suggestions',edge:'advice',role:'support'}}],
  ['handoff','Report & PK/PD Handoff Agent',{note:'Accepted model, scope and uncertainty',role:'handoff'}]
 ], loops:[{from:'review',to:'plan',label:'Targeted revision'}], next:{module:'translation',label:'Accepted models from all species → PK translation'}},
 translation: {title:'PK translation', planned:true, parts:[
  ['extrapolation','Extrapolation Agent',{note:'Allometry, fu-correction, FCIM and optional IVIVE (database)'}],
  ['compare','Prediction Comparison Agent',{note:'Compare individual predictions and candidate ensembles'}],
  ['validate','Predictive Validation Agent',{note:'Held-out species, doses or independent experiments'}],
  ['review','Scientific Review Agent',{note:'Presents evidence for human acceptance or revision',role:'human'}],
  ['handoff','Report & PK/PD Handoff Agent',{note:'Human PK predictions, assumptions and uncertainty',role:'handoff'}]
 ], loops:[{from:'review',to:'extrapolation',label:'Targeted revision'}],
 previous:{module:'pk',label:'Input: accepted animal PK models from every assessed species'}},
 targets: {title:'PD target estimation', planned:true, parts:[
  ['endpoint','Confirm endpoint & window'], ['estimate','Estimate PD target'], ['review','Review target & uncertainty']
 ]},
 pta: {title:'PTA', planned:true, parts:[
  [['exposure','Human exposure scenarios'],['target','Reviewed PD target']],
  ['regimen','Regimen & MIC scenarios'], ['calculate','Calculate PTA'], ['review','Review & report']
 ]}
};
const uiTitles = {intake:'File intake', context:'Context & Project Rules', adequacy:'Define requirements & label data',
 prepare:'Prepare, validate & hand off', eda:'Exploratory data analysis', dispatch:'Task assignment', pk:'Animal PK modeling',
 index:'PK/PD index screening', results:'Results & review', clinical:'Clinical interpretation'};
function uiTitle(n) {return uiTitles[n.id] || n.title;}
function moduleRoute(id,part='') {return '#view=module&module='+encodeURIComponent(id)+(part?'&part='+encodeURIComponent(part):'');}
function stageParent(id) {return ({context:'context_bundle',adequacy:'data_bundle',prepare:'data_bundle'})[id];}

// The main page: twelve stages in three phases. Numbers follow the scientific sequence.
const stageInfo = {
 intake:{number:'01', summary:'Register the proposal and the source data files.'},
 context_bundle:{number:'02', summary:'Compress the proposal into reviewed context and project rules.'},
 data_bundle:{number:'03', summary:'Check the data against the requirements, then prepare and QC it.'},
 eda:{number:'04', summary:'Temporarily disabled. Prepared data remain available in the Data steps.'},
 dispatch:{number:'05', summary:'Define the analysis tasks and route data to the modeling branches.'},
 pk:{number:'06A', summary:'Fit, compare and review animal PK models, one species at a time.'},
 index:{number:'06B', summary:'Match exposure to the PD endpoint; Emax / Hill models.'},
 translation:{number:'07A', summary:'Predict human PK from the accepted animal models.'},
 targets:{number:'07B', summary:'Estimate the PD target and its uncertainty.'},
 pta:{number:'08', summary:'Probability of target attainment across regimens and MICs.'},
 results:{number:'09', summary:'Assemble the results of both branches for review.'},
 clinical:{number:'10', summary:'Judge feasibility and safety; close the study or start a new cycle.'}
};
const workflowMap = [
 {title:'Evidence and data', stages:['intake','context_bundle','data_bundle','eda','dispatch']},
 {title:'Modeling', note:'Two branches run in parallel', lanes:[{id:'pk-branch',title:'PK branch',stages:['pk','translation']},{id:'pkpd-branch',title:'PK/PD branch',stages:['index','targets']}]},
 {title:'Decision', note:'Both branches join here', stages:['pta','results','clinical']}
];
// Connections drawn on the main page. A fork bends just above its targets, a merge just below its sources.
const workflowEdges = [
 ['intake','context_bundle'],['context_bundle','data_bundle'],['data_bundle','eda'],['eda','dispatch'],
 ['dispatch','pk-branch','target'],['dispatch','pkpd-branch','target'],
 ['pk','translation'],['index','targets'],
 ['pk-branch','pta','source'],['pkpd-branch','pta','source'],
 ['pta','results'],['results','clinical']
];
function stageRoute(id) {return moduleViews[id]?moduleRoute(id):route(id);}
function stageTitle(id) {return moduleViews[id]?moduleViews[id].title:uiTitle(getNode(id));}
function stageOf(id) {return Object.keys(stageInfo).find(s=>s===id||moduleViews[s]?.owners?.includes(id));}

function moduleStatus(id) {
 const m=moduleViews[id];
 if(m.planned)return 'Planned';
 // Parent failure or approval must not masquerade as an individual agent receipt.
 if(id==='compression'||id==='prc')return 'Within context';
 if(m.agent)return 'Fresh agent · '+m.agent;
 const nodes=(m.owners||[m.owner]).map(getNode).filter(Boolean);
 if(!nodes.length)return 'Not started';
 const active=nodes.find(n=>['RUNNING','PAUSING','PAUSED'].includes(n.state.execution));
 if(active)return stateLabel(active);
 const issue=nodes.find(n=>['FAILED','STALE','NEEDS_ATTENTION','REVISION_REQUIRED'].includes(n.state.execution));
 if(issue)return stateLabel(issue);
 if(id==='context_bundle'&&nodes[0].state.approved&&!nodes[0].state.artifacts?.some(a=>a.name==='project_rules.json'))return 'Rules not published';
 if(nodes.every(n=>n.state.approved))return 'Cleared';
 return stateLabel(nodes.find(n=>!n.state.approved));
}
// Sub-agents have no separate receipt; their status is the owning step's.
function shownStatus(id) {const s=moduleStatus(id);return s==='Within context'||s.startsWith('Fresh agent')?'':s;}
function stageStatus(id) {return moduleViews[id]?moduleStatus(id):stateLabel(getNode(id));}
function statusTone(label) {
 if(['Approved','Verified','Cleared'].includes(label))return 'done';
 if(['Running','Pausing','Paused'].includes(label))return 'active';
 if(['Failed','Rejected'].includes(label))return 'danger';
 if(['Awaiting review','Changes requested','Revision required','Stale outputs','Needs attention','Rules not published'].includes(label))return 'attention';
 if(label==='Planned')return 'planned';
 return 'neutral';
}
function statusChip(label) {return label?`<span class="chip tone-${statusTone(label)}">${esc(label)}</span>`:'';}
function stepCount(id) {
 const m=moduleViews[id];if(!m)return 'Single step';
 const n=m.children?m.children.length:moduleParts(m).length;
 return `${n} ${m.children||!m.parts.some(x=>x[2])?'step':'agent'}${n===1?'':'s'}`;
}
function stageCard(id) {
 const info=stageInfo[id], m=moduleViews[id], status=stageStatus(id);
 const nodes=m?(m.owners||(m.owner?[m.owner]:[])).map(getNode).filter(Boolean):[getNode(id)];
 const running=nodes.find(x=>['RUNNING','PAUSING'].includes(x.state.execution));
 const meta=running?`${icon('clock')}<span data-node-clock="${running.id}">${duration(running.state.timing.elapsed_seconds)}</span>`:esc(stepCount(id));
 return `<a class="stage tone-${statusTone(status)}${m?.planned?' is-planned':''}" id="node-${id}" href="${stageRoute(id)}" aria-label="${esc(info.number+' '+stageTitle(id)+', '+status)}"><span class="stage-num">${info.number}</span><span class="stage-title">${esc(stageTitle(id))}</span><span class="stage-summary">${esc(info.summary)}</span><span class="stage-foot">${statusChip(status)}<span class="stage-meta">${meta}</span>${icon('arrow')}</span></a>`;
}
function renderWorkflowGraph() {
 const needsPk=getNode('index')?.depends_on.includes('pk');
 const prev=flow?.parent_cycle?.session_id;
 const sample=kind=>`<svg viewBox="0 0 36 10" aria-hidden="true"><path class="flow-line ${kind}" d="M1 5H35"/></svg>`;
 const legend=`<dl class="map-legend"><div>${sample('handoff')}<dt>Solid</dt><dd>Handoff after your review</dd></div><div>${sample('planned')}<dt>Dashed</dt><dd>Planned, not connected yet</dd></div><div>${sample('loop')}<dt>Amber</dt><dd>Outer study loop</dd></div>${needsPk?`<div>${sample('dependency')}<dt>Dotted</dt><dd>Waits for reviewed PK exposure</dd></div>`:''}</dl>`;
 const lane=l=>`<div class="lane" id="${l.id}"><h3>${esc(l.title)}${l.id==='pkpd-branch'&&needsPk?'<small>Waits for reviewed PK exposure</small>':''}</h3>${l.stages.map(stageCard).join('')}</div>`;
 const loop=`<div class="loop-foot" id="outer-loop-note"><span class="loop-badge">${icon('refresh')}Outer loop</span><p><strong>Clinical interpretation → File intake.</strong> A clinical finding or data gap can revise the proposal or add data. That opens a new study cycle, which starts again at File intake and is reviewed afresh; earlier approvals are not carried over.</p><span class="loop-links"><a href="${route('clinical','clinical')}">Open study loop ${icon('arrow')}</a>${prev?`<a href="/?flow=${encodeURIComponent(prev)}#view=workflow">Previous cycle ${icon('arrow')}</a>`:''}</span></div>`;
 $('#diagram').innerHTML=workflowMap.map((phase,i)=>`<section class="phase phase-${i+1}" aria-labelledby="phase-${i}"><h2 class="phase-title" id="phase-${i}"><span class="phase-name"><span>Phase ${i+1}</span>${esc(phase.title)}${phase.note?`<em>${esc(phase.note)}</em>`:''}</span></h2>${phase.lanes?`<div class="lanes">${phase.lanes.map(lane).join('')}</div>`:`<div class="stage-grid">${phase.stages.map(stageCard).join('')}${i===0?legend:''}</div>`}</section>`).join('')+loop+'<svg class="flow-lines" aria-hidden="true"></svg>';
 drawFlowLines();
}
// Draws every connection from the boxes' current positions, so the diagram holds at any width.
function drawFlowLines() {
 const d=$('#diagram'), svg=d?.querySelector('.flow-lines');
 if(!svg||!d.offsetParent) return;
 const box=d.getBoundingClientRect();
 const rect=id=>{const e=d.querySelector('#node-'+id)||d.querySelector('#'+id); if(!e) return null; const r=e.getBoundingClientRect(); return {l:Math.round(r.left-box.left),r:Math.round(r.right-box.left),t:Math.round(r.top-box.top),b:Math.round(r.bottom-box.top),cx:Math.round((r.left+r.right)/2-box.left),cy:Math.round((r.top+r.bottom)/2-box.top)};};
 const head=(x,y,dir)=>({right:`M${x-8} ${y-5}L${x-1} ${y}L${x-8} ${y+5}`,left:`M${x+8} ${y-5}L${x+1} ${y}L${x+8} ${y+5}`,down:`M${x-5} ${y-8}L${x} ${y-1}L${x+5} ${y-8}`})[dir];
 const out=[], draw=(kind,path,tip)=>out.push(`<path class="flow-line ${kind}" d="${path}"/><path class="flow-head ${kind}" d="${head(...tip)}"/>`);
 const edge=(from,to,bend,kind)=>{
  const s=rect(from), t=rect(to); if(!s||!t) return;
  const top=Math.max(s.t,t.t), bottom=Math.min(s.b,t.b);
  if(bottom-top>24){const y=Math.round((top+bottom)/2); return s.r<=t.l?draw(kind,`M${s.r} ${y}H${t.l-1}`,[t.l,y,'right']):draw(kind,`M${s.l} ${y}H${t.r+1}`,[t.r,y,'left']);}
  if(Math.abs(s.cx-t.cx)<4) return draw(kind,`M${t.cx} ${s.b}V${t.t-1}`,[t.cx,t.t,'down']);
  const y=bend==='target'?t.t-18:bend==='source'?s.b+18:Math.round((s.b+t.t)/2);
  draw(kind,`M${s.cx} ${s.b}V${y}H${t.cx}V${t.t-1}`,[t.cx,t.t,'down']);
 };
 const planned=id=>!!moduleViews[id]?.planned;
 workflowEdges.forEach(([a,b,bend])=>edge(a,b,bend,planned(a)||planned(b)?'planned':'handoff'));
 if(getNode('index')?.depends_on.includes('pk')) edge('pk','index',null,'dependency');
 // Outer study loop: out of the bottom of Clinical interpretation, up the left rail, into File intake.
 const c=rect('clinical'), a=rect('intake'), note=rect('outer-loop-note');
 if(c&&a&&note){const rail=Math.round(parseFloat(getComputedStyle(d).paddingLeft)/3); draw('loop',`M${c.cx} ${c.b}V${note.t-14}H${rail}V${a.cy}H${a.l-1}`,[a.l,a.cy,'right']);}
 svg.setAttribute('width',box.width); svg.setAttribute('height',box.height); svg.innerHTML=out.join('');
}
globalThis.addEventListener?.('resize',()=>requestAnimationFrame(drawFlowLines));
globalThis.addEventListener?.('load',drawFlowLines);

// Location trail for the Back button and breadcrumbs: [label, href] from the workflow down.
function moduleTrail(id) {const t=[];for(let x=id;moduleViews[x];x=moduleViews[x].parent)t.unshift([moduleViews[x].title,moduleRoute(x)]);return t;}
function navTrail() {
 const q=new URLSearchParams(location.hash.slice(1)), home=['Workflow','#view=workflow'];
 if(page==='module'){
  const id=moduleAlias(q.get('module')), m=moduleViews[id];
  if(!m)return [home];
  const part=moduleParts(m).find(x=>x[0]===q.get('part'));
  return [home,...moduleTrail(id),...(part?[[part[1],moduleRoute(id,part[0])]]:[])];
 }
 if(page==='step'){
  const n=getNode(selected), parent=stageParent(selected), trail=parent?moduleTrail(parent):[];
  // A step that shares its stage's name is that stage's run-and-review level.
  return [home,...trail,[trail.at(-1)?.[0]===uiTitle(n)?'Run and review':uiTitle(n),route(selected)]];
 }
 if(page==='supplements')return [home,['Additional data','#view=supplements']];
 return [home];
}
// Links saved before the four-agent Data split (D01–D05) still open the matching page.
function moduleAlias(id) {return ({adequacy:'data_requirements',prepare:'data_preparation',data_adequacy:'data_coverage',data_metadata:'data_handoff'})[id]||id;}

// Every block in display order: sequence parts, parallel parts and attached side agents.
function moduleParts(m) {
 return m.parts.flatMap(x=>Array.isArray(x[0])?x:[x]).flatMap(x=>x[2]?.side?[x,[x[2].side.key,x[2].side.label,x[2].side]]:[x]);
}
const agentRoles={agent:'Agent',human:'Human decision gate',support:'Advisory agent',handoff:'Report & handoff'};
// Connections of one agent block, read from the module definition (sequence, side agents, loops).
function agentRelations(m,key) {
 const main=m.parts.filter(x=>!Array.isArray(x[0])), i=main.findIndex(x=>x[0]===key), name=k=>moduleParts(m).find(x=>x[0]===k)?.[1]||k, rel=[];
 const host=main.find(x=>x[2]?.side?.key===key);
 if(host)rel.push([host[2].side.edge==='advice'?'Advises':'Feeds',host[1]]);
 if(i>0)rel.push(['Receives from',main[i-1][1]]);
 if(i>=0&&main[i][2]?.side)rel.push([main[i][2].side.edge==='advice'?'Advice from':'Input from',main[i][2].side.label]);
 if(i>=0&&i<main.length-1)rel.push(['Hands off to',main[i+1][1]]);
 (m.loops||[]).forEach(l=>{if(l.from===key)rel.push([l.label+' to',name(l.to)]);if(l.to===key)rel.push([l.label+' from',name(l.from)]);});
 return rel;
}
function moduleArtifacts(id,owner) {
 const files=owner?.state.artifacts||[];
 const agent=moduleViews[id]?.agent;
 if(agent){
  const names={DR:['requirements.json','method_context.json'],DC:['inventory.json','data_labels.json','adequacy.json','review.json','qc_context.json','requirement_matrix.json'],DP:['preparation_plan.json','cleaning_log.json','normalized_manifest.json'],DH:['metadata_review.json','data_report.json','eda_context.json','pk_context.json','index_context.json']};
  // Audit folders are named per call: DC-label and DC-review both belong to DC.
  return files.filter(a=>names[agent].some(name=>a.name===name||a.name.endsWith('__'+name))||a.name.match(/__audit__([A-Z]+)(-[a-z]+)?__/)?.[1]===agent);
 }
 if(id==='prc')return files.filter(a=>/project_rules|rule_audit|publication_candidate/.test(a.name));
 if(id==='compression')return files.filter(a=>!/project_rules|rule_audit|publication_candidate/.test(a.name));
 return files;
}
const moduleSpecies={};
function loadModuleSpecies(session) {
 if(!session||moduleSpecies[session])return;
 moduleSpecies[session]={loading:true};
 json(`/ui-api/workflow/sessions/${encodeURIComponent(session)}/animal-pk/control`)
  .then(p=>{moduleSpecies[session]={species:(p.species||[]).map(s=>s.species)};})
  .catch(()=>{moduleSpecies[session]={species:[]};})
  .finally(()=>{const el=$('#module-species');if(el)el.innerHTML=speciesChips(session);});
}
function speciesChips(session) {
 const s=moduleSpecies[session];
 if(!session||!s||(!s.loading&&!s.species.length))return '<span class="muted">Species appear here after PK work is assigned.</span>';
 if(s.loading)return '<span class="muted">Loading species…</span>';
 return s.species.map(x=>`<span class="species-chip">${esc(x)}</span>`).join('');
}
const moduleNotes={
 compression:'Runs inside Context & Project Rules. Individual agents do not report a separate status.',
 prc:'Runs inside Context & Project Rules. Individual agents do not report a separate status.',
 pk:'This agent design runs once per species. Runs, models and reviews live in the species workspaces.'
};
function renderModuleWorkspace() {
 const q=new URLSearchParams(location.hash.slice(1)), id=moduleAlias(q.get('module')), m=moduleViews[id];
 if(!m){$('#list-panel').innerHTML=emptyBox('Stage not found','Go back to the workflow and open a stage from there.','info');return;}
 const part=q.get('part'), flat=moduleParts(m), current=flat.find(x=>x[0]===part);
 const owners=(m.owners||(m.owner?[m.owner]:[])).map(getNode).filter(Boolean), owner=m.owner?getNode(m.owner):null;
 const agents=flat.some(x=>x[2]);
 const detail=current?`<div class="block-detail">${current[2]?`<dl class="kv"><dt>Role</dt><dd>${esc(agentRoles[current[2].role||'agent'])}</dd>${current[2].note?`<dt>Task</dt><dd>${esc(current[2].note)}</dd>`:''}${m.perSpecies?'<dt>Scope</dt><dd>One species per run</dd>':''}${agentRelations(m,current[0]).map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join('')}</dl>`:`<p>Part of ${esc(m.title)}. Status, outputs and review are recorded for the whole step under Run and review.</p>`}</div>`:'';
 let index=0;
 const block=([key,label,info],number)=>{
  const child=!!m.children?.includes(key), chosen=part===key;
  // Plain sub-steps have no role or connections of their own to open.
  if(!child&&!agents)return `<div class="block is-static">${number?`<span class="block-num">${number}</span>`:''}<span class="block-body"><span class="block-title">${esc(label)}</span></span></div>`;
  const href=child?moduleRoute(key):moduleRoute(id,chosen?'':key);
  const role=info?.role&&info.role!=='agent'?`<span class="block-role">${esc(agentRoles[info.role])}</span>`:'';
  const link=`<a class="block${child?' is-group':''}${info?' role-'+(info.role||'agent'):''}${chosen?' is-selected':''}" href="${href}"${chosen?' aria-expanded="true"':child?'':' aria-expanded="false"'}>${number?`<span class="block-num">${number}</span>`:''}<span class="block-body"><span class="block-title">${esc(label)}</span>${info?.note?`<span class="block-note">${esc(info.note)}</span>`:''}${role}</span>${child?`<span class="block-more">${esc(stepCount(key))}${icon('arrow')}</span>`:`<span class="block-toggle" aria-hidden="true">${chosen?'−':'+'}</span>`}</a>`;
  return chosen?`<div class="block-open">${link}${detail}</div>`:link;
 };
 const unit=x=>{
  index++;
  // Steps whose names already carry a code (DR, DC…) need no extra number.
  const n=/^[A-Z][A-Z\d]{1,2} · /.test(Array.isArray(x[0])?x[0][1]:x[1])?0:index;
  if(Array.isArray(x[0]))return `<div class="block-parallel" aria-label="Run in parallel">${x.map(p=>block(p,n)).join('')}</div>`;
  if(x[2]?.side){const s=x[2].side;return `<div class="block-with-side">${block(x,n)}<div class="block-side ${s.edge}"><span class="side-label">${s.edge==='advice'?'Advises':'Feeds'}</span>${block([s.key,s.label,s])}</div></div>`;}
  return block(x,n);
 };
 const label=k=>flat.find(x=>x[0]===k)?.[1]||k;
 const loops=(m.loops||[]).map(l=>`<a class="block-loop" href="${moduleRoute(id,l.to)}">↺ ${esc(l.label)}: ${esc(label(l.from))} → ${esc(label(l.to))}</a>`).join('');
 const files=owner?moduleArtifacts(id,owner):[];
 const session=flow?.session_id||'';
 const ownerRow=n=>`<div class="owner-row"><div><strong>${esc(uiTitle(n))}</strong>${statusChip(stateLabel(n))}</div><a class="button ${n.state.can_run||n.state.can_review?'primary':'secondary'}" href="${route(n.id)}">Open step ${icon('arrow')}</a></div>`;
 const note=m.agent?(m.owner==='adequacy'?'DR and DC run in sequence inside this step, each with a fresh scoped request.':'DP and DH run in sequence inside this step, each with a fresh scoped request.'):moduleNotes[id]||'';
 const controls=m.planned?`<section class="card"><h2>Run and review</h2><p class="muted">Framework only. Execution is not implemented yet.</p></section>`
  :owners.length?`<section class="card"><h2>Run and review</h2>${owners.map(ownerRow).join('')}${note?`<p class="card-note">${esc(note)}</p>`:''}${id==='pk'&&session?`<a class="button primary wide" href="${animalPkControlUrl()}">Open species workspaces ${icon('arrow')}</a>`:''}${id==='context_bundle'&&session?`<a class="button secondary wide" href="/assets/pk-reference-pilot.html?session=${encodeURIComponent(session)}">Literature review ${icon('arrow')}</a>`:''}</section>`:'';
 const status=shownStatus(id);
 $('#list-panel').innerHTML=`<header class="page-head">${stageInfo[id]?`<span class="page-num">${stageInfo[id].number}</span>`:''}<div><h1>${esc(m.title)}</h1>${stageInfo[id]?`<p>${esc(stageInfo[id].summary)}</p>`:''}</div>${statusChip(status)}</header>
 ${moduleControlNotice(owners)}
 <div class="split"><section class="steps" aria-label="${agents?'Agents':'Steps'}"><h2 class="section-title">${m.children?'Steps':agents?'Agents':'Steps'} <span>${m.children?'Open a step to see its parts':agents?'Select an agent to see its role and connections':'Run in this order inside one step'}</span></h2>
 ${m.perSpecies?`<div class="species-scope"><p><strong>One workflow per species.</strong> Each assessed species runs its own copy of these agents. Accepted models from all species go to PK translation.</p><div class="species-chips" id="module-species">${speciesChips(session)}</div></div>`:''}
 ${m.previous?`<a class="block-io" href="${moduleRoute(m.previous.module)}">${esc(m.previous.label)}</a>`:''}
 <div class="block-flow">${m.parts.map(unit).join('')}</div>
 ${loops}${m.next?`<a class="block-io" href="${moduleRoute(m.next.module)}">${esc(m.next.label)} ${icon('arrow')}</a>`:''}
 ${m.loops||flat.some(x=>x[2]?.side)?'<p class="flow-legend">Solid line: required handoff · Dashed: advice or revision</p>':''}</section>
 <aside class="side">${controls}${files.length?`<section class="card"><h2>Outputs</h2>${artifactBrowser(owner.id,files,'module')}</section>`:''}</aside></div>`;
 if(m.perSpecies)loadModuleSpecies(session);
 bindArtifactBrowsers($('#list-panel'));
}

function moduleControlNotice(owners) {
 const n=owners.find(n=>['FAILED','REVISION_REQUIRED'].includes(n.state.execution));
 if(!n)return '';
 const child=n.id==='context'&&flow.context_revision_child;
 const url=child?`/?flow=${encodeURIComponent(child)}${route('context','context')}`:route(n.id,'context');
 return `<section class="field-card notice-danger"><strong>${esc(n.state.failure?.title || 'This step needs attention')}</strong><p>${esc(n.state.failure?.summary || n.state.error || 'Open the step to inspect its findings.')}</p>${child?'<p>A retry already exists. Continue from that run.</p>':''}<a class="button primary" href="${url}">${child?'Open latest retry':'Open diagnosis & retry'}</a></section>`;
}
