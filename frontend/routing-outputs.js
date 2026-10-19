/* Read-only inspector for executed dispatch artifacts. Never recomputes a route. */
const routingOutputTitles={
 'clinical_questions.json':'Generated task definitions',
 'confirmed_clinical_questions.json':'Reviewer-confirmed inputs',
 'pk_context.json':'PK branch task package', 'index_context.json':'Index branch task package',
 'clinical_context.json':'Clinical interpretation task package',
 'routing_plan.json':'File allocation and dependencies', 'dispatch_report.json':'Findings and readiness report'
};
function renderRoutingOutputEntry(n) {
 if(n.id!=='dispatch')return '';
 const artifacts=n.state.artifacts || [];
 if(!artifacts.length)return '<section class="field-card"><strong>No task assignment outputs yet</strong><p>Drafts are under Tasks. Run this step to create the outputs that its review will inspect.</p></section>';
 const r=n.state.dispatch_report,s=r?.summary;
 return `<section class="routing-output-entry"><div class="section-label">Actual execution outputs · ${artifacts.length} files</div><p>Inspect these saved results before submitting a review.</p>${s?`<p>PK: ${s.pk.datasets} datasets · Index: ${s.index.datasets} · Clinical: ${s.clinical.datasets}</p>`:''}<button class="button primary" data-open-routing-report>Inspect task packages</button><div class="routing-output-links">${artifacts.map(a=>`<button class="text-button" data-clinical-file="${esc(a.name)}" data-draft="false">${esc(a.name)} ↗</button>`).join('')}</div><p class="help-note">Executed outputs are available for inspection before approval. Opening or downloading them does not release downstream calculations.</p></section>`;
}
function routingSourceMatch(ref) {
 if(!ref?.path || !ref.sha256)return null;
 const basename=ref.path.split(/[\\/]/).pop();
 for(const n of flow.nodes) {
  if(!['prepare','eda'].includes(n.id))continue;
  const artifact=n.state.artifacts.find(a=>a.sha256===ref.sha256 && a.name===basename);
  if(artifact)return {node:n.id,name:artifact.name};
 }
 return null;
}
function routingSourceButtons(dataset) {
 return [['csv','Data CSV'],['data','Data JSON'],['metadata','Metadata JSON'],['excluded_records','Excluded records']].map(([key,label])=>{
  const match=routingSourceMatch(dataset[key]);
  return match?`<button class="text-button" data-routing-source-node="${match.node}" data-routing-source-name="${esc(match.name)}">${label} ↗</button>`:`<span class="muted">${label}: verified preview link unavailable</span>`;
 }).join('');
}
function routingGaps(items) {
 return (items||[]).map(x=>`<article class="field-card"><strong>${esc(x.code||x.dataset_id||x.field||'Finding')}</strong>${x.status?`<p>Status: ${esc(x.status)}</p>`:''}<p>${esc(x.reason||'Reason not recorded')}</p>${x.needed_material?`<p><strong>Needed:</strong> ${esc(x.needed_material)}</p>`:''}${x.required_by?`<p>Required by: ${esc(x.required_by)} · Condition: ${esc(x.condition||'See project task')}</p>`:''}</article>`).join('')||'<p>No items recorded in this output.</p>';
}
function bindRoutingSourceButtons(onReturn) {
 $$('[data-routing-source-node]').forEach(b=>b.onclick=async()=>{
  await showArtifact(b.dataset.routingSourceNode,b.dataset.routingSourceName);
  if(onReturn && $('#modal').open) {
   $('#modal-body').insertAdjacentHTML('afterbegin','<button class="button secondary" id="back-routing-source">Back to routing output report</button>');
   $('#back-routing-source').onclick=onReturn;
  }
 });
}
async function openRoutingOutputReport() {
 const n=getNode('dispatch'),sid=flow.session_id,signature=n.state.output_signature;
 if(!n.state.artifacts.length)return toast('No executed routing outputs are available yet.');
 modal('Task assignment outputs','<p>Loading the registered, hash-checked execution artifacts…</p>','EXECUTION OUTPUTS');
 const dialog=$('#modal');dialog.classList.add('routing-output-modal');
 dialog.addEventListener('close',()=>dialog.classList.remove('routing-output-modal'),{once:true});
 const artifacts=n.state.artifacts.map(x=>({...x})), results=await Promise.allSettled(artifacts.map(async a=>{
  const response=await api(`/ui-api/workflow/sessions/${encodeURIComponent(sid)}/nodes/dispatch/artifacts/${encodeURIComponent(a.name)}`);
  const blob=await response.blob();return {artifact:a,blob,value:JSON.parse(await blob.text())};
 }));
 if(!dialog.open)return;
 const outputs={},failures=[];
 results.forEach((result,i)=>result.status==='fulfilled'?outputs[artifacts[i].name]=result.value:failures.push({name:artifacts[i].name,error:String(result.reason?.message||result.reason)}));
 const report=outputs['dispatch_report.json']?.value,plan=outputs['routing_plan.json']?.value;
 const datasetMap=new Map();
 for(const branch of ['pk','index','clinical'])for(const d of outputs[branch+'_context.json']?.value.data_files||[])datasetMap.set(d.dataset_id,d);
 const branchNames={pk:'PK',index:'PK/PD index',clinical:'Clinical interpretation'};
 let selectedPanel='overview';
 function fileButton(name,label) {return outputs[name]?`<button class="text-button" data-routing-preview="${esc(name)}">${esc(label||name)} ↗</button>`:`<span class="muted">${esc(name)} unavailable</span>`;}
 function render() {
  const sections={
   overview:()=>`<div class="routing-metrics">${['pk','index','clinical'].map(branch=>{const c=outputs[branch+'_context.json']?.value;return `<article class="field-card"><strong>${branchNames[branch]}</strong><p>${c?.tasks.length??'—'} tasks · ${c?.data_files.length??'—'} datasets</p>${fileButton(branch+'_context.json','Inspect branch package')}</article>`;}).join('')}</div><p>Execution: <strong>${esc(n.state.execution)}</strong> · Review: <strong>${esc(n.state.review?.decision||'PENDING')}</strong></p><p>Index exposure dependency: <strong>${esc(report?.index_exposure_source||'Not recorded')}</strong></p><p>${plan?.file_routes?.length??'—'} dataset routing decisions · ${plan?.unassigned_datasets?.length??'—'} unassigned datasets · ${report?.unknowns?.length??'—'} unresolved question fields</p><p>Dataset counts overlap when an approved source is assigned to more than one branch. They are not animal counts.</p><h3>Why calculation is not yet released</h3><ul>${(report?.why_cannot_pass||[]).map(x=>`<li>${esc(x)}</li>`).join('')}</ul><h3>Planned parallel work and dependencies</h3><pre>${esc(JSON.stringify({parallel_groups:plan?.parallel_groups,dependencies:plan?.dependencies},null,2))}</pre><h3>Execution identity</h3><p>Job: ${esc(n.state.job_id||'Not recorded')}<br>Elapsed: ${duration(n.state.timing.elapsed_seconds)}<br>Output signature: <code>${esc(signature)}</code><br>LangGraph review: ${esc(n.state.langgraph_review?.status||'Not recorded')}</p><p>The saved JSONs describe this execution. Later code changes do not rewrite these results.</p>`,
   questions:()=>{const q=outputs['clinical_questions.json']?.value;return q?`<h3>Executed task definitions</h3><p>Generator: ${esc(q.generator_version||'Historical generator; version not recorded')}</p>${Object.entries(q.values||{}).map(([k,v])=>`<article class="field-card"><strong>${esc(k.replaceAll('_',' '))}</strong><p class="routing-verbatim">${esc(v)}</p></article>`).join('')}${fileButton('confirmed_clinical_questions.json','Inspect the exact reviewer-confirmed inputs')}`:'<p>Question artifact unavailable; inspect Files & diagnostics.</p>';},
   branches:()=>['pk','index','clinical'].map(branch=>{const c=outputs[branch+'_context.json']?.value;return `<section class="routing-branch"><h3>${branchNames[branch]}</h3>${c?`${clinicalContractSummary(c)}<h4>Assigned files</h4>${c.data_files.map(d=>`<details class="field-card"><summary>${esc(d.dataset_id)} · ${esc(d.source_title||'Source title not recorded')}</summary><p>${esc(d.role)} · ${esc(d.species)} · ${esc(d.record_level)} · ${esc(d.exposure_basis)}</p><div class="template-actions">${routingSourceButtons(d)}</div></details>`).join('')||'<p>No files assigned.</p>'}<h4>Findings and required materials</h4>${routingGaps(c.missing_materials)}<details class="field-card"><summary>Applicable project rules</summary><pre>${esc(JSON.stringify(c.rules,null,2))}</pre></details><p><strong>Expected outputs:</strong> ${esc(c.expected_outputs.join(' · '))}</p>${fileButton(branch+'_context.json','View full branch JSON')}`:'<p>Branch artifact unavailable.</p>'}</section>`;}).join(''),
   routing:()=>`<h3>Saved file allocation decisions</h3><label>Filter dataset, target or reason<input id="routing-search" type="search" placeholder="For example: T0035, pk, unassigned"></label><p>No routing is recomputed in this view.</p><div class="routing-table-scroll"><table class="routing-table"><thead><tr><th>Dataset / role</th><th>Destination</th><th>Recorded reason</th><th>Inspect source</th></tr></thead><tbody>${(plan?.file_routes||[]).map(r=>{const d=datasetMap.get(r.dataset_id),metadata=routingSourceMatch(r.metadata_ref);return `<tr data-routing-row><td><strong>${esc(r.dataset_id)}</strong><br>${esc(r.role)}</td><td>${esc(r.targets.join(' · ')||'Unassigned')}</td><td>${esc(r.reason)}</td><td>${d?routingSourceButtons(d):metadata?`<button class="text-button" data-routing-source-node="${metadata.node}" data-routing-source-name="${esc(metadata.name)}">Metadata JSON ↗</button>`:'No registered source link'}</td></tr>`;}).join('')}</tbody></table></div>`,
   gaps:()=>`<h3>Unresolved task definitions</h3>${routingGaps(report?.unknowns)}<h3>Unassigned datasets and reasons</h3>${routingGaps(plan?.unassigned_datasets)}<h3>Unassigned reviewed tasks</h3>${(plan?.unassigned_tasks||[]).map(t=>`<article class="field-card"><strong>${esc(t.id)}</strong><p>${esc(t.question)}</p><p>Estimand: ${esc(t.estimand||'Not recorded')}</p></article>`).join('')||'<p>No unassigned tasks recorded.</p>'}`,
   files:()=>`<h3>Registered execution outputs</h3><p>Preview or download the exact original file. A failed checksum blocks access; it is not replaced by a template.</p>${artifacts.map(a=>`<article class="field-card"><strong>${esc(a.name)}</strong><p>${esc(routingOutputTitles[a.name]||a.kind)}</p><p><code>SHA-256: ${esc(a.sha256)}</code></p>${fileButton(a.name,'Preview JSON')} ${outputs[a.name]?`<button class="text-button" data-routing-download="${esc(a.name)}">Download original file</button>`:''}</article>`).join('')}<button class="button secondary" id="download-routing-inspection">Download inspection bundle JSON</button><p>This bundle contains copies of the routing JSONs and their signatures. Data files remain separate verified attachments accessible under Branch tasks or File routing.</p>`
  };
  const labels={overview:'Overview',questions:'Task definitions',branches:'Branch tasks',routing:'File routing',gaps:'Gaps & reasons',files:'Files & diagnostics'};
  $('#modal-body').innerHTML=`<div class="routing-status"><strong>${n.state.approved?'Reviewed execution outputs':'Executed outputs · pending routing review'}</strong><span> ${artifacts.length} registered files</span><p>Inspection only. No calculations or review decisions are submitted here.</p></div>${failures.length?`<div class="error-box"><strong>Some outputs could not be verified or loaded</strong>${failures.map(f=>`<p>${esc(f.name)}: ${esc(f.error)}</p>`).join('')}</div>`:''}<nav class="routing-tabs" aria-label="Routing output sections">${Object.entries(labels).map(([id,label])=>`<button class="text-button" data-routing-panel="${id}" aria-pressed="${id===selectedPanel}">${label}</button>`).join('')}</nav><section id="routing-output-content">${sections[selectedPanel]()}</section>`;
  $$('[data-routing-panel]').forEach(b=>b.onclick=()=>{selectedPanel=b.dataset.routingPanel;render();$('#modal-body').scrollTop=0;});
  $$('[data-routing-preview]').forEach(b=>b.onclick=()=>{
   const out=outputs[b.dataset.routingPreview];modal(out.artifact.name,`<button class="button secondary" id="back-routing-report">Back to routing output report</button><pre>${esc(JSON.stringify(out.value,null,2))}</pre><button class="button primary" id="download-routing-file">Download original file</button>`,'EXECUTED JSON');
   $('#back-routing-report').onclick=()=>{ $('#modal-title').textContent='Task assignment outputs';render();};
   $('#download-routing-file').onclick=()=>download(out.blob,out.artifact.name);
  });
  $$('[data-routing-download]').forEach(b=>b.onclick=()=>{const out=outputs[b.dataset.routingDownload];download(out.blob,out.artifact.name);});
  bindRoutingSourceButtons(()=>{ $('#modal-title').textContent='Task assignment outputs';render(); });
  if($('#routing-search'))$('#routing-search').oninput=e=>{const q=e.target.value.toLowerCase();$$('[data-routing-row]').forEach(row=>row.hidden=!row.textContent.toLowerCase().includes(q));};
  if($('#download-routing-inspection'))$('#download-routing-inspection').onclick=()=>download({inspection_only:true,session_id:sid,job_id:n.state.job_id,output_signature:signature,artifacts,
    output_copies:Object.fromEntries(Object.entries(outputs).map(([name,o])=>[name,o.value])),load_errors:failures},'clinical_routing_inspection.json');
 }
 render();
}
function bindRoutingOutputEntry() {
 $$('[data-open-routing-report]').forEach(button=>button.onclick=()=>openRoutingOutputReport().catch(e=>toast(e.message)));
}
