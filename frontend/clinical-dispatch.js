/* Scoped clinical-question drafts. Preview never grants scientific release. */
function clinicalFileUrl(name, draft) {
 return draft ? `${sessionPath()}/clinical-questions/draft/files/${encodeURIComponent(name)}`
  : `${sessionPath()}/nodes/dispatch/artifacts/${encodeURIComponent(name)}`;
}
function renderClinicalDispatch(n) {
 const d=getNode('dispatch'), draft=d?.state.clinical_draft;
 if(n.id!=='dispatch') {
  const h=n.state.assigned_handoff;
  return h ? `<section class="field-card clinical-assignment"><div class="section-label">Assigned branch contract</div><strong>${esc(h.name)}</strong><p>${esc(h.status)} · ${h.dataset_ids.length} datasets</p><p>Only this branch's tasks, files, applicable rules and evidence gaps are included. Scientific model-input release remains separate.</p><button class="button secondary" data-clinical-file="${esc(h.name)}" data-draft="${h.source==='draft'}">Inspect assigned context</button><p><a href="${route('dispatch','clinical')}">Open task assignment ↗</a></p></section>` : '';
 }
 const report=d.state.dispatch_report || draft?.report, isDraft=!d.state.dispatch_report;
 const editable=!!flow.session_id && ['NOT_STARTED','FAILED'].includes(n.state.execution);
 const ready=['context','adequacy','prepare'].every(k=>getNode(k)?.state.approved) && getNode('eda')?.state.execution==='COMPLETED';
 if(tab==='clinical' && report) return `<section class="clinical-dispatch"><div class="section-label">${isDraft?'Draft definitions · editable before confirmation':'Executed task definitions'}</div><p>Review the task definitions below. Unknowns remain explicit. Inspect each branch's scoped tasks and files:</p><div class="template-actions">${['pk','index','clinical'].map(b=>`<button class="text-button" data-clinical-branch="${b}" data-clinical-file="${b}_context.json" data-draft="${isDraft}">${b}_context.json · ${report.summary[b].datasets} datasets ↗</button>`).join('')}</div>${editable?`<button class="text-button" id="prepare-clinical-draft" ${!ready||busy?'disabled':''}>Refresh draft from reviewed inputs</button>`:''}<p><a href="${route('dispatch','input')}">View allocation reasons and missing materials ↗</a></p></section>`;
 return `<section class="clinical-dispatch"><div class="section-label">Assign downstream tasks</div><p>Split the reviewed objective into tasks. Assign data by metadata, include applicable rules, and record dependencies and missing inputs.</p>${editable ? `<button class="button secondary" id="prepare-clinical-draft" ${!ready||busy?'disabled':''}>${draft?'Refresh':'Prepare'} task packages</button>`:''}${!ready?'<p class="help-note">Complete EDA and approve the earlier context, assessment and QC before preparing drafts.</p>':''}
 ${report?`<p class="help-note"><strong>${isDraft?'Drafts available for inspection':'Dispatch outputs generated'}</strong><br>${isDraft?'Drafting does not require EDA approval. Releasing contracts requires EDA approval, confirmed definitions and a dispatch review.':'Review the exact routing outputs before downstream consumption.'}</p><a class="button secondary" href="${route('dispatch','clinical')}">Review task definitions</a><div class="field-list section-gap">${['pk','index','clinical'].map(b=>{const x=report.branches[b],s=report.summary[b];return `<article class="field-card" data-clinical-branch="${b}"><div class="section-label">${b==='pk'?'Animal PK & translation':b==='index'?'PK/PD index':'Clinical interpretation & study loop'}</div><strong>${b}_context.json</strong><p>${s.tasks} tasks · ${s.datasets} assigned datasets</p><p>${esc(x.task_ids.join(' · '))}</p><button class="text-button" data-clinical-file="${b}_context.json" data-draft="${isDraft}">View tasks, files and gaps ↗</button></article>`;}).join('')}</div><details class="field-card"><summary>Unknowns and allocation gaps</summary>${report.unknowns.map(x=>`<p><strong>${esc(x.field)}</strong><br>${esc(x.reason)}</p>`).join('')}${report.unassigned_datasets.map(x=>`<p><strong>${esc(x.dataset_id)}</strong>: ${esc(x.reason)}<br>Needed: ${esc(x.needed_material)}</p>`).join('')}</details><div class="template-actions">${['clinical_questions.json','routing_plan.json','dispatch_report.json'].map(name=>`<button class="text-button" data-clinical-file="${name}" data-draft="${isDraft}">${name} ↗</button>`).join('')}</div>`:''}</section>`;
}
function clinicalContractSummary(data) {
 if(!data.data_files)return '';
 return `<p><strong>Drug:</strong> ${esc(data.drug)}</p>${data.candidate_indices?`<p><strong>Candidate indices:</strong> ${esc(data.candidate_indices.join(' · '))}</p>`:''}<h3>Tasks and targets</h3>${data.tasks.map(t=>`<article class="field-card"><strong>${esc(t.id)} · ${esc(t.question)}</strong><p>Estimand: ${esc(t.estimand)}<br>Endpoint: ${esc(t.endpoint)}<br>Window: ${esc(t.endpoint_window)}<br>Species: ${esc(t.species)}<br>Units: ${esc(t.units)} · Basis: ${esc(t.exposure_basis)}</p></article>`).join('')}<h3>Planned work</h3><ol>${data.work_items.map(t=>`<li>${esc(t)}</li>`).join('')}</ol><details class="field-card"><summary>Branch-specific task definitions</summary>${Object.entries(data.clinical_questions).map(([key,value])=>`<p><strong>${esc(key.replaceAll('_',' '))}</strong><br>${esc(value)}</p>`).join('')}</details>`;
}
function clinicalQuestionEvidence(n,key) {
 const info=n.state.clinical_draft?.field_evidence?.[key];
 if(!info)return '';
 return `<button type="button" class="text-button" data-question-evidence="${esc(key)}">View source statements · ${info.definition_evidence.length+info.related_evidence.length} references</button>`;
}
function bindClinicalDispatch(n) {
 $$('[data-question-evidence]').forEach(button=>button.onclick=()=>{
  const key=button.dataset.questionEvidence,draft=n.state.clinical_draft,info=draft.field_evidence[key];
  const ids=[...info.definition_evidence,...info.related_evidence];
  const edited=n.state.clinical_spec && n.state.clinical_spec.values[key]!==draft.values[key];
  modal('Sources for '+key.replaceAll('_',' '),`<p>${edited?'The confirmed answer was edited by a reviewer. These sources describe its original draft.':'Draft statements come from this project\'s reviewed context and task assessment.'}</p><p>${esc(info.status.replaceAll('_',' '))}. Verbatim retrieval does not resolve scientific conflicts or certify completeness.</p>${ids.map(id=>{const e=draft.evidence_catalog[id];return `<article class="field-card"><strong>${esc(id)} · ${esc(e.source)} · ${esc(e.path)}</strong><p>${esc(e.quote)}</p></article>`;}).join('')||'<p>No supporting statement was located. Keep this answer UNKNOWN until evidence is supplied.</p>'}<h3>Open reviewed requirements</h3>${info.open_requirements.map(g=>`<p><strong>${esc(g.requirement_id)} · ${esc(g.status)}</strong><br>${esc(g.reason)}<br>Needed: ${esc(g.needed_material)}</p>`).join('')||'<p>No related gap was recorded in the assessment; this does not establish completeness.</p>'}`,'TASK PROVENANCE');
 });
 if($('#prepare-clinical-draft')) $('#prepare-clinical-draft').onclick=async()=>{
  if(busy)return;busy=true;
  try {flow=await json(sessionPath()+'/clinical-questions/draft',{method:'POST',body:'{}'});receivedAt=performance.now();toast('Task packages prepared. Review definitions and unresolved inputs before release.');}
  catch(e){toast(e.message);}finally{busy=false;render();}
 };
 if(n.state.can_retry_dispatch) {
  const panel=$('.execution-feedback');
  if(panel&&!$('#retry-dispatch')) panel.insertAdjacentHTML('beforeend','<button class="button" id="retry-dispatch">Retry task assignment</button><a class="button secondary" href="#node=dispatch&tab=clinical">Correct definitions</a>');
  if($('#retry-dispatch')) $('#retry-dispatch').onclick=()=>mutate(sessionPath()+'/nodes/dispatch/start',{},'New task assignment attempt started.');
 }
 $$('[data-clinical-file]').forEach(button=>button.onclick=async()=>{
  try {
   const name=button.dataset.clinicalFile, isDraft=button.dataset.draft==='true';
   const data=await json(clinicalFileUrl(name,isDraft));
   const details=data.data_files?`<p><strong>Objective:</strong> ${esc(data.objective)}</p><h3>Assigned data</h3>${data.data_files.map(x=>`<article class="field-card"><strong>${esc(x.dataset_id)} · ${esc(x.source_title)}</strong><p>${esc(x.role)} · ${esc(x.species)} · ${esc(x.record_level)}</p><p>Data: ${esc(x.csv.path.split(/[\\/]/).pop())}<br>Metadata: ${esc(x.metadata.path.split(/[\\/]/).pop())}</p></article>`).join('') || '<p>No development data assigned.</p>'}<h3>Required materials before calculation</h3>${data.missing_materials.map(x=>`<p><strong>${esc(x.code)}</strong><br>${esc(x.reason)}<br>Needed: ${esc(x.needed_material)}</p>`).join('')}`:'';
   modal(name,`<p>${isDraft?'Draft for inspection; no downstream release.':'Execution artifact; downstream release requires the exact routing approval.'}</p>${clinicalContractSummary(data)}${details}<button id="download-clinical-json" class="button secondary">Download JSON</button><details ${details?'':'open'}><summary>Full scoped JSON</summary><pre class="json-preview">${esc(JSON.stringify(data,null,2))}</pre></details>`,'TASK ASSIGNMENT');
   $('#download-clinical-json').onclick=()=>download(data,name);
  } catch(e){toast(e.message);}
 });
}
