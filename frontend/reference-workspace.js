'use strict';
const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
const esc = x => String(x ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const session = new URLSearchParams(location.search).get('session');
const base = `/ui-api/workflow/sessions/${encodeURIComponent(session || '')}/pk-reference-pilot`;
let current = null, busy = false, renderKey = '', libraryKey = '', libraryData = null;
const human = value => String(value || 'Not run').replaceAll('_',' ').toLowerCase().replace(/^./, c=>c.toUpperCase());
$('#back').href = `/?flow=${encodeURIComponent(session || '')}#view=module&module=context_bundle`;
async function request(path, method='GET', body) {
 const headers = {}, token = sessionStorage.getItem('pmb-token');
 if(token) headers.Authorization = `Bearer ${token}`;
 if(body) headers['Content-Type'] = 'application/json';
 const r = await fetch(path,{method,headers,body:body ? JSON.stringify(body) : undefined});
 if(!r.ok) {let x;try{x=await r.json();}catch{x={};}throw Error(typeof x.detail === 'string' ? x.detail : `Request failed (${r.status})`);}
 return r;
}
function routeView() {
 const wanted = new URLSearchParams(location.hash.slice(1)).get('view'), view = ['revision','findings','files','library'].includes(wanted) ? wanted : 'overview';
 $$('[data-panel]').forEach(el=>el.hidden=el.dataset.panel!==view);
 $$('[data-view]').forEach(el=>{if(el.dataset.view===view)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');});
 document.title = `${view==='overview'?'Reference review':human(view)} · Research Workbench`;
}
function clock() {
 if(!current) return;
 const j=current.job, s=j?.started_at?Math.max(0,Math.floor(((j.finished_at?Date.parse(j.finished_at):Date.now())-Date.parse(j.started_at))/1000)):0;
 const elapsed=[Math.floor(s/3600),Math.floor(s/60)%60,s%60].map(v=>String(v).padStart(2,'0')).join(':');
 $('#run-label').textContent = j ? (['RUNNING','QUEUED'].includes(j.status)?'':'Recorded run · ')+human(j.status) : 'Ready for assessment';
 const stage=j?.model_progress?.stage_label || (/[\u3400-\u9fff]/.test(j?.stage||'') ? 'Workflow execution' : j?.stage || '');
 $('#status').textContent = j ? `${j.started_at?new Date(j.started_at).toLocaleString('en-GB')+' · ':''}${elapsed} · ${stage}` : 'No reference assessment has been run for this project.';
}
function dl(fields) {return '<dl class="source-details">'+fields.filter(([,v])=>v).map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(Array.isArray(v)?v.join(', '):v)}</dd>`).join('')+'</dl>';}
function stageStatus(x, stage) {
 const status=x.job?.blocks?.find(b=>b.stage===stage)?.status;
 if(status==='NOT_RUN'&&['RUNNING','QUEUED'].includes(x.job?.status))return 'Waiting';
 return human(status);
}
function renderLibrary() {
 if(!current) return;
 const type=$('#library-type').value, query=$('#library-search').value.trim().toLowerCase();
 const lib=current.library, rows=type==='sources'?lib.sources:type==='rules'?lib.cards:(libraryData?.models || []);
 const role=$('#library-role').value; $('#library-role').disabled=type!=='sources';
 const filtered=rows.filter(v=>(type!=='sources'||!role||v.translation_role===role)&&(!query||JSON.stringify(v).toLowerCase().includes(query)));
 $('#library-count').textContent=`${filtered.length} of ${rows.length} ${type==='sources'?'publications':type==='models'?'model candidates':'evidence checks'}`;
 $('#library').innerHTML=filtered.map(v=> {
  if(type==='sources') return `<details><summary>${esc(v.title)} <span class="badge">${esc(v.drug)}</span></summary><div><div class="source-meta"><a href="${esc(v.url)}" target="_blank" rel="noopener">Read publication ↗</a><span class="badge">${esc(v.relationship_to_pmb || 'Method / same-drug evidence')}</span></div>${dl([['DOI',v.doi],['Translation role',human(v.translation_role)],['Study',v.summary],['Validation',v.validation],['Data',v.data_availability],['Code',v.code_availability],['Evidence location',v.locator]])}</div></details>`;
  if(type==='models') return `<details><summary>${esc(v.model_name)} <span class="badge">${esc(v.drug_id)}</span></summary><div>${dl([['Species',v.species],['Routes',v.routes],['Matrices',v.matrices],['Structure',v.structure],['Estimation',v.estimation],['Evidence',v.source_ids],['Use boundary',v.eligible_use],['Missing / review',v.review_requirements],['Status',v.scientific_acceptance]])}<button class="secondary" data-model="${esc(v.model_id)}">Open candidate JSON</button></div></details>`;
  return `<details><summary>${esc(v.id)} · ${esc(v.title)}</summary><div><p>${esc(v.suggested_check)}</p>${dl([['Applicability',v.applicability_conditions],['Limits',v.limitations]])}${v.source_ids.map(id=>{const source=lib.sources.find(s=>s.id===id);return source?`<p><a href="${esc(source.url)}" target="_blank" rel="noopener">${esc(source.title)} ↗</a></p>`:'';}).join('')}</div></details>`;
 }).join('') || '<div class="empty">No matching records. Try a drug name or a broader term.</div>';
}
function render(x) {
 current=x; $('#enabled').checked=x.enabled; $('#run').disabled=$('#revise').disabled=busy||!x.can_run||x.can_pause; $('#pause').hidden=!x.can_pause;
 $('#error').textContent=x.job?.error || ''; clock();
 $('#input-review').hidden=!x.context_review_pending;
 $('#version').textContent='Library '+x.library.schema_version;
 $('#source-count').textContent=`${x.library.sources.length} publications · ${x.library.translation_role_counts?.ANIMAL_TO_HUMAN_PK_PREDICTION||0} animal-to-human PK prediction papers · ${x.library.cards.length} evidence checks`;
 $('#file-count').textContent=`${x.files.length} files`;
 const checks=x.report?.assessment?.card_checks || [];
 $('#findings-count').textContent=x.report?`${checks.length} findings`:stageStatus(x,'pk_reference_review');
 $('#changes-count').textContent=x.revision_changes?`${x.revision_changes.changes.length} proposed additions`:stageStatus(x,'main_reference_revision');
 $('#review-status').textContent=x.revision_review?human(x.revision_review.status):stageStatus(x,'main_reference_revision_review');
 const lk=JSON.stringify(x.library); if(lk!==libraryKey){libraryKey=lk;renderLibrary();}
 const key=JSON.stringify([x.report,x.source_matches_current,x.revision_review,x.revision_changes,x.files,x.job?.status,x.job?.blocks]); if(key===renderKey)return; renderKey=key;
 const opened=new Set($$('details[data-key][open]').map(d=>d.dataset.key));
 if(x.report) $('#findings').innerHTML=`${x.source_matches_current===false?'<p class="notice">This assessment used an earlier proposal. Run a new assessment before using its advice.</p>':''}<p class="muted">${esc(x.report.assessment.scope_reason)}</p>${checks.map(c=>`<details class="finding" data-key="finding-${esc(c.card_id)}"><summary><strong>${esc(c.card_id)} · ${esc(x.library.cards.find(r=>r.id===c.card_id)?.title||c.relevant_step)}</strong><span class="badge">${esc(human(c.applicability))}</span></summary><div class="finding-body">${dl([['Finding',c.reason],['Proposed action',c.proposed_action],['To clarify',c.missing_information],['Relevant step',c.relevant_step]])}<details><summary>Evidence citations</summary><pre>${esc(JSON.stringify({context:c.context_evidence,sources:c.source_evidence},null,2))}</pre></details></div></details>`).join('')}`;
 const r=x.revision_review, changes=x.revision_changes;
 $('#revision').innerHTML=r?`<p><span class="badge">${esc(human(r.status))}</span> ${esc(r.review.summary)}</p><p class="notice">${esc(r.next_step)}</p>${changes?changes.changes.map(v=>`<details data-key="change-${esc(v.id)}"><summary>${esc(v.id)} · ${esc(v.destination)} · ${esc(v.needed_at)}</summary><div>${dl([['Addition',v.text],['Reason',v.reason],['Evidence',v.card_ids],['JSON path',v.path]])}</div></details>`).join(''):''}<details data-key="independent-review"><summary>Independent review checklist</summary><pre>${esc(JSON.stringify(r.review,null,2))}</pre></details><a href="#view=files">Open revised JSON and change log →</a>`:'<div class="empty">No revised context yet. Run “Check & revise context” to generate proposed changes.</div>';
 if(!r&&['RUNNING','QUEUED'].includes(x.job?.status))$('#revision').innerHTML='<div class="empty">Assessment is in progress. Proposed changes will appear after revision and independent review finish.</div>';
 const groups={Results:[],Inputs:[],Audit:[]};
 x.files.forEach(f=>groups[/(^|__)audit(__|$)|model_calls|events\.jsonl|stderr\.log/.test(f.name)?'Audit':f.name==='input.json'||f.name==='library.json'?'Inputs':'Results'].push(f));
 $('#files').innerHTML=Object.entries(groups).map(([name,files])=>`<details data-key="files-${name}" ${name==='Results'?'open':''}><summary>${name} <span class="badge">${files.length}</span></summary><div class="files">${files.map(f=>{const parts=f.name.split('__');const short=parts.pop();return `<div class="file"><span title="${esc(f.name)}">${esc(short)}${parts.length?`<small class="file-folder">${esc(parts.join(' / '))}</small>`:''}</span><span><button class="secondary" data-open="${esc(f.url)}" data-name="${esc(f.name)}">Open</button> <button class="secondary" data-download="${esc(f.url)}" data-name="${esc(f.name)}">Download</button></span></div>`;}).join('')}</div></details>`).join('');
 $$('details[data-key]').forEach(d=>{if(opened.has(d.dataset.key))d.open=true;});
}
async function refresh(){if(busy)return;try{render(await(await request(base)).json());}catch(e){$('#error').textContent=e.message;}}
async function action(fn){busy=true;$('#run').disabled=$('#revise').disabled=true;try{await fn();$('#error').textContent='';}catch(e){$('#error').textContent=e.message;}finally{busy=false;await refresh();}}
$('#run').onclick=()=>action(()=>request(base+'/start','POST',{revise_main:false,allow_unreviewed_context:!!current?.context_review_pending}));
$('#revise').onclick=()=>action(()=>request(base+'/start','POST',{revise_main:true,allow_unreviewed_context:!!current?.context_review_pending}));
$('#pause').onclick=()=>action(()=>request(base+`/jobs/${encodeURIComponent(current.job.id)}/pause`,'POST'));
$('#enabled').onchange=()=>action(()=>request(base+'/configuration','POST',{enabled:$('#enabled').checked}));
$('#library-search').oninput=renderLibrary; $('#library-type').onchange=renderLibrary; $('#library-role').onchange=renderLibrary;
document.addEventListener('click',async e=>{
 const b=e.target.closest('[data-open],[data-download],[data-model]');if(!b)return;
 try{
  if(b.dataset.model){const v=libraryData.models.find(m=>m.model_id===b.dataset.model);$('#preview-title').textContent=v.model_id;$('#preview-body').innerHTML=metadataTree(v);$('#preview').showModal();return;}
  const blob=await(await request(b.dataset.open||b.dataset.download)).blob();
  if(b.dataset.open){let text=await blob.text();if(/\.json$/i.test(b.dataset.name)){try{text=JSON.stringify(JSON.parse(text),null,2);}catch{}}$('#preview-title').textContent=b.dataset.name.replaceAll('__',' / ');try{$('#preview-body').innerHTML=metadataTree(JSON.parse(text));}catch{$('#preview-body').textContent=text;}$('#preview').showModal();}
  else{const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=b.dataset.name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
 }catch(error){$('#error').textContent=error.message;}
});
$('#close').onclick=()=>$('#preview').close();
window.addEventListener('hashchange',routeView);routeView();
document.querySelectorAll('[data-library-file]').forEach(b=>{b.dataset.download=base+'/model-library/files/'+b.dataset.libraryFile;b.dataset.name=b.dataset.libraryFile;});
if(session){refresh();setInterval(refresh,5000);setInterval(clock,1000);request(base+'/model-library').then(r=>r.json()).then(x=>{libraryData=x;renderLibrary();}).catch(()=>{$('#library-type option[value="models"]').disabled=true;});}else{$('#error').textContent='Open this workspace from a project Context step.';}
