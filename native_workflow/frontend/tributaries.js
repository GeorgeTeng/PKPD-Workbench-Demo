/* Additional data are processed independently and released once, after QC/EDA. */
let supplementDraft = null;
function supplementalInputs(n) {
 const inputs = n.state.supplemental_inputs || [];
 return inputs.length ? `<div class="section-gap"><div class="section-label">Supplemental inputs</div>${inputs.map(b=>`<div class="field-card"><strong>${esc(b.label)}</strong><p>${esc(b.status)}</p>${b.files.map(name=>`<button class="text-button" data-supp-file="${esc(name)}" data-branch="${esc(b.branch_id)}">${esc(name)} ↗</button>`).join('')}</div>`).join('')}<button class="text-button" data-page="supplements">Open additional data →</button></div>` : '';
}
function renderSupplements() {
 const branches = flow.supplements || [];
 const previous = $('#supplement-form');
 if(previous) supplementDraft = Object.fromEntries(new FormData(previous).entries());
 const activeInput = previous?.contains(document.activeElement);
 // Do not replace a selected file input or active editor during status polling.
 if(previous && (previous.elements.files.files.length || activeInput)) {renderSupplementCards(branches); return;}
 $('#list-panel').innerHTML = `<div class="eyebrow">ADDITIONAL DATA / BRANCH INPUT</div><h2 class="section-gap">Add data to a downstream step</h2><p>Files may be registered for later use. Supplemental processing is disabled while EDA is unavailable.</p><div class="help-note">Choose the destination. File contents and declared metadata determine compatibility. Existing main-workflow prerequisites still apply.</div><details class="supplement-add" ${branches.length ? '' : 'open'}><summary>Register additional data</summary><form id="supplement-form" class="review-form supplemental-form"><label>Correct an earlier branch (optional)<select name="supersedes"><option value="">New additional data</option>${branches.filter(b=>['DRAFT','BLOCKED','REVISION_REQUIRED','STALE','FAILED'].includes(b.status)).map(b=>`<option value="${b.id}">${esc(b.label)}</option>`).join('')}</select></label><label>Branch name<input name="label" required placeholder="Additional animal PK or missing evidence"></label><fieldset><legend>Downstream destinations</legend>${[['pk','Animal PK'],['index','PK/PD index'],['clinical','Clinical interpretation']].map(([v,label])=>`<label class="confirm-label"><input type="checkbox" name="target_${v}" value="${v}">${label}</label>`).join('')}</fieldset><label>Data files<input name="files" class="supplement-file-input" type="file" multiple required accept=".csv,.xlsx,.json"></label><div><button type="button" id="choose-supp-files" class="button secondary">Choose data files</button> <span id="supp-file-names">No files selected</span></div><label>Dataset role<select name="role"><option value="pk_observations">PK concentration observations</option><option value="exposure_response">Matched exposure-response indices</option><option value="mic">MIC support</option><option value="binding">Binding support</option><option value="pd_observations">PD observations</option><option value="clinical_evidence">Clinical evidence table</option></select></label><div class="supplement-grid">${[['drug','Drug / analyte'],['species','Species'],['route','Route'],['matrix','Matrix'],['concentration_basis','Concentration basis (total / free)'],['record_level','Record level (individual / group_summary)'],['sampling_design','Sampling (serial / sparse / terminal)'],['time_unit','Source time unit'],['concentration_unit','Source concentration unit'],['dose_unit','Dose unit']].map(([name,label])=>`<label>${label}<input name="${name}" placeholder="Unknown if undocumented"></label>`).join('')}</div><label>XLSX sheet (required for spreadsheets)<input name="sheet" placeholder="Exact worksheet name"></label><details><summary>Column mapping, analysis definition and source references</summary><p>Use source-column → canonical-column mapping. PK fields: subject_id, time_h, concentration_mg_L. Declare source units above. Mixed identity columns are split after reading.</p><label>Configuration JSON<textarea name="config" rows="12" spellcheck="false">${esc(JSON.stringify({column_map:{},metadata:{formulation:'NOT_FOUND',parameter_definition:'NOT_FOUND'},analysis_options:{},evidence_locators:[]},null,2))}</textarea></label><p>PK compatibility checks need explicit doses (time_h, duration_h, dose_mg or dose_mg_kg). Index screening needs index_columns, response_column and metadata.index_definitions. Missing requirements appear in the assessment.</p></details><button type="submit" class="button primary" ${!flow.session_id || busy ? 'disabled' : ''}>Register supplemental branch</button></form></details><div id="supplement-cards" class="section-gap"></div>`;
 if(supplementDraft) for(const [k,v] of Object.entries(supplementDraft)) {
  const el = $('#supplement-form').elements[k]; if(!el || el.type==='file') continue;
  if(el.type==='checkbox') el.checked = true; else el.value = v;
 }
 $('#supplement-form').onsubmit = registerSupplement;
 $('#choose-supp-files').onclick=()=>$('#supplement-form').elements.files.click();
 $('#supplement-form').elements.files.onchange=()=>{$('#supp-file-names').textContent=[...$('#supplement-form').elements.files.files].map(f=>f.name).join(' · ') || 'No files selected';};
 renderSupplementCards(branches);
}
function renderSupplementCards(branches) {
 const container = $('#supplement-cards'); if(!container) return;
 container.innerHTML = `<h2>Supplemental branches</h2>${branches.length ? branches.map(b=>{
  const findings = b.feedback?.why_cannot_pass || [], needs = b.feedback?.missing_materials || [];
  const reviewable = ['WAITING_FOR_REVIEW','BLOCKED'].includes(b.status);
  const status = {DRAFT:'Registered',RUNNING:'Processing',PAUSING:'Pausing',PAUSED:'Paused',FAILED:'Execution failed',BLOCKED:'Needs correction',WAITING_FOR_REVIEW:'Awaiting review',APPROVED:'Released to selected inputs',REVISION_REQUIRED:'Revision requested',REJECTED:'Rejected / disconnected',SUPERSEDED:'Replaced by corrected branch',STALE:'Files changed'}[b.status] || b.status;
  const figures = b.artifacts.filter(a=>a.kind==='figure');
  return `<article class="supplement-card"><div class="section-label">${esc(b.label)} <span>${esc(status)}</span></div><p>Active time: <strong>${duration(b.timing?.elapsed_seconds || 0)}</strong></p><p>Destination: ${b.targets.map(t=>esc(getNode(t)?.title || t)).join(' · ')}</p><div class="branch-track"><span>Sources</span>→<span>Clean & split</span>→<span>QC / metadata</span>→<span>EDA</span>→<span>Review</span>→<span>Downstream</span></div>${b.runtime?.blocks ? `<p>${b.runtime.blocks.map(x=>`${esc(x.stage)}: ${esc(x.status)}`).join(' · ')}</p>` : ''}${b.error ? `<div class="error-box">${esc(b.error)}</div>` : ''}${findings.length ? `<h3>Why this cannot pass</h3><ul>${findings.map(f=>`<li><strong>${esc(f.code || f.category || '')}</strong> ${esc(f.reason)}${f.source_detail ? `<details><summary>Source detail</summary><p>${esc(englishMessage(f.source_detail))}</p></details>` : ''}</li>`).join('')}</ul><h3>Missing data or materials</h3><ul>${needs.map(m=>`<li>${esc(m.dataset_id || '')} ${esc(m.required)}</li>`).join('')}</ul>` : b.feedback ? `<p>No blocking input errors. ${esc(b.feedback.remaining_gate)}</p>` : ''}${b.feedback?.review_items?.length ? `<details><summary>Items to review (${b.feedback.review_items.length})</summary><ul>${b.feedback.review_items.map(f=>`<li>${esc(f.reason)} — ${esc(f.required_material)}</li>`).join('')}</ul></details>` : ''}${b.datasets.map(d=>`<div class="field-card"><strong>${esc(d.id)}</strong><p>${esc(d.role)} · ${d.summary.candidate_rows} candidate rows · ${d.summary.quarantined_rows} quarantined</p></div>`).join('')}<div class="contract-files">${b.artifacts.filter(a=>/metadata\.json$|feedback\.(json|md)$|eda\.json$|datasets\/.*\.(json|csv)$/.test(a.name)).map(a=>`<button class="text-button" data-supp-file="${esc(a.name)}" data-branch="${b.id}">${esc(a.name)} ↗</button>`).join('')}${b.handoffs.map(a=>`<button class="text-button" data-supp-file="${esc(a.name)}" data-branch="${b.id}">${esc(a.name)} ↗</button>`).join('')}${figures.map(a=>`<button class="text-button" data-supp-file="${esc(a.name)}" data-branch="${b.id}">${esc(a.name.split('/').pop())} ↗</button>`).join('')}</div>${b.status==='DRAFT' ? `<button class="button primary" data-supp-action="start" data-branch="${b.id}" ${b.can_start ? '' : 'disabled'}>Processing unavailable</button>` : ''}${b.status==='RUNNING' ? `<button class="button secondary" data-supp-action="pause" data-branch="${b.id}">Pause branch</button>` : ''}${b.status==='PAUSED' ? `<button class="button secondary" data-supp-action="continue" data-branch="${b.id}" ${b.can_continue ? '' : 'disabled'}>Resume unavailable</button>` : ''}${reviewable ? `<button class="button primary" data-supp-review="${b.id}">${b.status==='BLOCKED' ? 'Review blocking findings' : 'Review & release inputs'}</button>` : ''}<p class="muted">${b.id} · Numerical models and clinical acceptance are separate steps.</p></article>`;
 }).join('') : emptyBox('No supplemental branches','Register additional data and select its destination.','layers')}`;
}
async function registerSupplement(event) {
 event.preventDefault(); if(busy) return;
 const form = event.currentTarget, data = new FormData(form);
 const targets = ['pk','index','clinical'].filter(t=>data.has('target_'+t));
 if(!targets.length) {toast('Choose at least one downstream destination.'); return;}
 let config; try {config=JSON.parse(data.get('config'));} catch {toast('Configuration must be valid JSON.'); return;}
 const files = [...form.elements.files.files]; if(!files.length) return;
 busy=true; form.querySelector('button[type=submit]').disabled=true;
 try {
  const datasets=[];
  for(const [i,file] of files.entries()) {
   const body=new FormData(); body.append('file',file);
   const uploaded=await json('/pipeline/v1/attachments',{method:'POST',body});
   const metadata={...config.metadata,role:data.get('role')};
   for(const key of ['drug','species','route','matrix','concentration_basis','record_level','sampling_design','time_unit','concentration_unit','dose_unit']) metadata[key]=String(data.get(key)||'NOT_FOUND').trim() || 'NOT_FOUND';
   metadata.analyte=config.metadata?.analyte || metadata.drug;
   datasets.push({id:'dataset_'+String(i+1).padStart(3,'0'),upload_id:uploaded.upload_id,metadata,
    table:{...(data.get('sheet') ? {sheet:data.get('sheet')} : {}),column_map:config.column_map || {},...(config.header_row ? {header_row:config.header_row} : {})},
    analysis_options:config.analysis_options || {}, evidence_locators:config.evidence_locators || []});
  }
  await json(`${sessionPath()}/supplements`,{method:'POST',body:JSON.stringify({label:data.get('label'),targets,datasets,supersedes:data.get('supersedes') || null})});
  supplementDraft=null; form.reset(); form.remove(); toast('Branch registered. Run preparation and EDA when ready.'); await refresh();
 } catch(error) {toast(error.message);} finally {busy=false; if(flow) render();}
}
document.addEventListener('click',async event=>{
 const file=event.target.closest('[data-supp-file]');
 if(file) {
  try {
   const name=file.dataset.suppFile, response=await api(`${sessionPath()}/supplements/${file.dataset.branch}/artifacts/${name.split('/').map(encodeURIComponent).join('/')}`), blob=await response.blob();
   if(name.endsWith('.png')) {const url=URL.createObjectURL(blob); modal(name,`<img class="supplement-figure" src="${url}" alt="Generated descriptive EDA plot">`,'ACTUAL EDA'); $('#modal').addEventListener('close',()=>URL.revokeObjectURL(url),{once:true});}
   else {const content=await blob.text(); modal(name,`<pre>${esc(content)}</pre><button id="download-supp" class="button secondary">Download file</button>`,'ACTUAL ARTIFACT'); $('#download-supp').onclick=()=>download(blob,name.split('/').pop());}
  } catch(error) {toast(error.message);} return;
 }
 const action=event.target.closest('[data-supp-action]');
 if(action && !busy) {
  busy=true;
  try {await json(`${sessionPath()}/supplements/${action.dataset.branch}/${action.dataset.suppAction}`,{method:'POST'}); await refresh();}
  catch(error) {toast(error.message);} finally {busy=false; render();} return;
 }
 const review=event.target.closest('[data-supp-review]'); if(!review) return;
 const branch=flow.supplements.find(b=>b.id===review.dataset.suppReview), blocked=branch.status==='BLOCKED';
 modal('Review supplemental inputs',`<p>Review metadata, cleaning, quarantine, adequacy findings and EDA together. Approval releases only this data package.</p><form id="supp-review-form" class="review-form"><label>Decision<select name="decision">${!blocked ? '<option value="APPROVE">Approve · no issues</option>' : ''}<option value="REQUEST_CHANGES">Request changes</option><option value="REJECT">Reject</option></select></label><label>Reviewer<input name="reviewer" required></label><label>Comment (optional for approval)<textarea name="rationale"></textarea></label><label class="confirm-label"><input name="confirmed" type="checkbox" required>I reviewed these outputs and their limitations.</label><button class="button primary">Submit review</button></form>`,'HUMAN REVIEW');
 const form=$('#supp-review-form'), update=()=>{form.elements.rationale.required=form.elements.decision.value!=='APPROVE'; form.elements.rationale.minLength=form.elements.decision.value==='APPROVE'?0:5;}; update(); form.elements.decision.onchange=update;
 form.onsubmit=async e=>{e.preventDefault(); if(busy)return; busy=true;
  const f=new FormData(form);
  try {await json(`${sessionPath()}/supplements/${branch.id}/review`,{method:'POST',body:JSON.stringify({decision:f.get('decision'),reviewer:f.get('reviewer'),rationale:f.get('rationale'),confirmed:f.has('confirmed'),output_signature:branch.output_signature})}); $('#modal').close(); await refresh();}
  catch(error){toast(error.message);}finally{busy=false;render();}
 };
});
