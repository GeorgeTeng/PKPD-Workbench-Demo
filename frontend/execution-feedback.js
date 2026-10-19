/* Execution failures and heartbeat messages do not imply scientific acceptance. */
const shownHeartbeats = new Set();
let edaSelectedDataset = null;
function renderEdaResults(n) {
 const r=n.state.eda_report,s=r.summary;
 const d=r.datasets.find(x=>x.dataset_id===edaSelectedDataset) || r.datasets[0];
 if(!d) return '<section class="execution-feedback"><h3>EDA completed with no assigned datasets</h3></section>';
 edaSelectedDataset=d.dataset_id;
 return `<section class="execution-feedback eda-results"><div class="section-label">Exploratory data analysis · executed</div><h3>EDA completed; review findings</h3><div class="field-card"><p><strong>${s.datasets}</strong> datasets · <strong>${s.pk_tables}</strong> PK tables · <strong>${s.figures}</strong> figures</p><p>${s.observed_window_auc_profiles} eligible observed-window AUC profiles. ${s.quarantined_records} QC-excluded records remain excluded.</p></div><p>${esc(r.review_scope)}</p><label>Inspect a source dataset<select id="eda-dataset-select" style="width:100%;margin:8px 0 16px">${r.datasets.map(x=>`<option value="${esc(x.dataset_id)}" ${x.dataset_id===d.dataset_id?'selected':''}>${esc(x.dataset_id+' · '+x.title)}</option>`).join('')}</select></label><article class="field-card"><strong>${esc(d.title)}</strong><p>${esc(d.role)} · ${esc(d.metadata.record_level)}</p><p>${d.retained_records} retained · ${d.quarantined_records} quarantined · independent animals: ${esc(d.independent_animal_count)}</p>${d.time_min_h!=null?`<p>Observed window: ${d.time_min_h}–${d.time_max_h} h · ${d.unique_times} distinct times</p>`:''}${d.plots.filter(x=>x.name.endsWith('.png')).map(x=>`<p><a href="${route('eda','context')}" data-artifact="${esc(x.name)}">View ${esc(x.name)} ↗</a></p>`).join('') || '<p>No scientific plot is supported by this table mapping.</p>'}</article><h4>What could be calculated</h4>${d.calculability_by_panel.map(x=>`<div class="field-card"><strong>${esc(x.panel_id)} · ${esc(x.status.replaceAll('_',' '))}</strong>${x.reason?`<p>${esc(x.reason)}</p>`:''}${x.needed_material&&x.needed_material!=='NONE'?`<p><strong>Needed:</strong> ${esc(x.needed_material)}</p>`:''}</div>`).join('')}<h4>Findings and missing materials</h4>${[...d.findings,...r.findings.filter(x=>x.dataset_id==='ALL')].map(x=>`<details class="field-card"><summary>${esc(x.code.replaceAll('_',' '))}</summary><p>${esc(x.reason)}</p><p><strong>Needed:</strong> ${esc(x.needed_material)}</p></details>`).join('')}<p><a href="${route('prepare','context')}">Inspect approved QC and source metadata ↗</a></p><p>Files contains PNG/SVG figures, coverage tables, exposure metrics and the scoped downstream JSON. Curve shape does not establish compartment number or human predictive validity.</p>${n.state.can_retry_eda?'<button id="retry-eda" class="button">Retry EDA</button>':''}</section>`;
}
function modelClock(value) { return value ? esc(new Date(value).toLocaleTimeString('en-GB')) : 'Not observed'; }
function currentModelCalls(p) {
 const calls=p.parallel_calls || [p], branches=calls.filter(x=>['context_faithfulness','context_completeness','context_conflicts'].includes(x.stage) || x.stage?.startsWith('context_faithfulness--'));
 // Attachment evidence runs several calls at once; show each one still running.
 const evidence=calls.filter(x=>x.stage?.startsWith('attachment_evidence--') && x.status==='RUNNING');
 return (branches.length ? branches : evidence.length ? evidence : [p]).slice().sort((a,b)=>Number(b.status==='RUNNING')-Number(a.status==='RUNNING'));
}
function contextReviewNote(p) {
 // The run's frozen review mode sets the order; start times cannot, because a reused call has no progress file.
 const mode=p.context_review_mode, parts=currentModelCalls(p).some(x=>x.stage?.startsWith('context_faithfulness--'));
 if(mode==='parallel_v3') return 'The faithfulness review runs in parts alongside the completeness and global conflict reviews. All are required for release; a global PASS cannot override a failed branch.';
 if(mode==='parallel_v2' || (!mode && parts)) return 'The faithfulness review runs in parts alongside the completeness review. Global conflict review starts after all of them return valid reviews. All are required for release.';
 return 'Faithfulness and completeness run in parallel. Global conflict review starts after both return valid reviews. All three are required for release.';
}
function evidenceProgressNote(p) {
 const calls=(p.parallel_calls || [p]).filter(x=>x.stage?.startsWith('attachment_evidence--')), count=s=>calls.filter(x=>x.status===s).length;
 return `Attachment evidence runs several calls at once: file searches first, then one reconciliation per question. ${count('RETURNED')} returned · ${count('RUNNING')} running.`;
}
function renderModelCall(p) {
 const phases={AWAITING_MODEL_OUTPUT:'Waiting for assistant output',WAITING_AFTER_ERROR_EVENT:'An error or reconnect event was received',MODEL_OUTPUT_RECEIVED_WAITING_TURN_END:'Assistant output received; waiting for turn completion',MODEL_TURN_COMPLETE_WAITING_CLI_EXIT:'Model turn complete; waiting for CLI exit',RETURNED:'CLI has exited',CANCELLED:'Call cancelled',TIMEOUT:'Explicit deadline reached'};
 return `<article class="field-card model-call" data-stage="${esc(p.stage || '')}"><div class="section-label">${esc(p.stage_label)}</div><p><strong>${esc(phases[p.phase] || p.status || 'Waiting')}</strong></p><p>${p.monitor_current && p.process_alive ? 'Local process is alive.' : p.cli_process_exited_at ? 'Local process has exited.' : 'No fresh liveness confirmation.'} Elapsed: ${duration(p.elapsed_seconds)} · Forced deadline: ${p.timeout_seconds == null ? 'None' : esc(p.timeout_seconds)+' s'}</p><p>Events received: ${p.model_event_count ?? 0} · Last type: ${esc(p.last_event_type || 'Not recorded')} · Received: ${modelClock(p.last_model_event_at)}</p><dl><dt>First assistant response</dt><dd>${modelClock(p.first_response_at)}</dd><dt>Assistant output completed</dt><dd>${modelClock(p.model_output_completed_at)}</dd><dt>Model turn completed</dt><dd>${modelClock(p.model_turn_completed_at)}</dd><dt>CLI process exited</dt><dd>${modelClock(p.cli_process_exited_at)}</dd></dl>${p.last_transport_or_model_error ? `<p class="help-note">Latest error event: ${esc(typeof p.last_transport_or_model_error.message==='string' ? p.last_transport_or_model_error.message : JSON.stringify(p.last_transport_or_model_error.message))}</p>` : ''}${p.last_heartbeat ? `<p><strong>Status message ${p.last_heartbeat.sequence}</strong> · ${modelClock(p.last_heartbeat.at)}<br>${esc(p.last_heartbeat.message)}</p>` : ''}</article>`;
}
function renderExecutionFeedback(n) {
 const amendment=n.state.scope_amendment;
 const scope=amendment ? `<section class="scope-amendment field-card"><div class="section-label">Confirmed scope clarification</div><p>${esc(amendment.instruction)}</p><details><summary>${amendment.changes.length} changes to this run's effective Context</summary>${amendment.changes.map(c=>`<p><strong>${esc(c.path)}</strong></p><p>${esc(c.after)}</p>`).join('')}</details><p class="help-note">The approved original Context is preserved. This clarification does not approve scientific results.</p></section>` : '';
 return scope + renderExecutionState(n);
}
function renderDatasetActionReadiness(report) {
 if(report?.preparation_policy !== 'DATASET_ACTION_V1' || !Array.isArray(report.dataset_action_readiness)) return '';
 const actions = [['SOURCE_INSPECTION','Source inspection'],['DESCRIPTIVE_EDA','Descriptive EDA'],['PK_MODELING','PK modeling']];
 const status = value => value?.status === 'READY' ? 'Ready for scoped action' : value?.status === 'RESTRICTED' ? 'Restricted' : 'Not assessed';
 return `<section class="dataset-action-readiness"><h4>Dataset and action readiness</h4><p>Readiness is specific to each dataset and action. Restrictions on one action do not close unrelated work. Technical processing, scientific release, and model fitting are separate decisions.</p>${report.dataset_action_readiness.map(item => {const related=(report.findings||[]).filter(f=>(f.dataset_id||f.affected_id)===item.dataset_id);return `<details class="field-card"><summary>${esc(item.dataset_id || 'Dataset')} · ${esc(item.source_item_id || 'source not identified')}</summary><dl>${actions.map(([key,label]) => {const result=item.actions?.[key]; return `<dt>${label}</dt><dd><strong>${esc(status(result))}</strong>${Array.isArray(result?.reasons) && result.reasons.length ? `<ul>${result.reasons.map(reason=>`<li>${esc(reason)}</li>`).join('')}</ul>` : ''}</dd>`;}).join('')}</dl>${item.operation_restrictions?.length ? `<p><strong>Restricted operations:</strong></p><ul>${item.operation_restrictions.map(r=>`<li><strong>${esc(r.operation.replaceAll('_',' '))}</strong>: ${r.reasons.map(esc).join('; ')}</li>`).join('')}</ul>` : ''}${related.length?`<p><strong>Related scoped findings (see required stage):</strong></p>${related.map(f=>`<p><strong>${esc(f.code||'Finding')}</strong> · ${esc(f.required_by||'stage not reported')}<br>${esc(f.reason||'Reason not reported')}<br><strong>Needed:</strong> ${esc(f.needed_material||'Not reported')}</p>`).join('')}` : ''}</details>`;}).join('')}</section>`;
}
function renderExecutionState(n) {
 const f=n.state.failure, p=n.state.model_progress;
 const coverage=typeof renderCoverageGaps==='function' ? renderCoverageGaps(n) : '';
 if(coverage) return coverage;
 if(n.id==='context' && n.state.pre_eda_source_job_id) return `<section class="execution-feedback"><div class="section-label">Automated pre-EDA preparation</div><h3>Build formal handoff and prepare data</h3><p>Starting here runs the existing formal First Part v4 review and publish against the Project Rules already bound to this approved Context, then starts fresh source inventory, DR v6, Coverage/Necessity/summary, authorized DirectDataReview, and technical cleaning/QC. Scientific checks remain active. The workflow stops before EDA and fitting.</p><p>${n.state.pre_eda_rules_available ? 'A published Rules pack is available for this approved Context.' : 'No published Project Rules pack is bound to this Context; the formal handoff cannot start yet.'}</p><button class="button primary" id="start-pre-eda" ${n.state.pre_eda_rules_available ? '' : 'disabled'}>Authorize this run and start</button><p id="pre-eda-status" role="status"></p></section>`;
 if(n.id==='eda' && n.state.eda_report && n.state.execution==='COMPLETED') return renderEdaResults(n);
 if(n.id==='prepare' && n.state.preparation_report && ['COMPLETED','NEEDS_ATTENTION'].includes(n.state.execution)) {
  const r=n.state.preparation_report, s=r.summary;
  const technical = r.technical_processing_complete === true || (r.preparation_policy !== 'DATASET_ACTION_V1' && r.cleaning_complete === true);
  const findings = Array.isArray(r.findings) ? r.findings : [];
  const summary = s && typeof s === 'object' ? `<div class="field-card"><p><strong>${esc(s.development_tables ?? 'Not reported')}</strong> development tables · <strong>${esc(s.retained_records ?? 'Not reported')}</strong> retained source records · <strong>${esc(s.quarantined_records ?? 'Not reported')}</strong> quarantined records</p><p>These counts are not independent animal counts.</p><p>${Object.entries(s.partitions || {}).map(([k,v])=>`${esc(k.replaceAll('_',' '))}: ${esc(v)}`).join('<br>')}</p></div>` : '';
  const flags = `<div class="field-card"><p>Technical processing: <strong>${technical ? 'Complete' : 'Incomplete or not reported'}</strong></p><p>Cleaning QC: <strong>${r.cleaning_complete === true ? 'Complete' : 'Incomplete'}</strong></p><p>Handoff review: <strong>${r.handoff_review_complete === true ? 'Complete' : 'Incomplete or not reported'}</strong></p><p>Fit readiness: <strong>${r.fit_ready === true ? 'Ready' : 'Not established'}</strong></p><p>Scientific release: <strong>${r.scientific_release === true ? 'Released' : 'Not released'}</strong></p>${r.preparation_policy !== 'DATASET_ACTION_V1' ? '<p>Legacy report schema: dataset/action readiness is unavailable; legacy status flags are shown only with their original meaning.</p>' : ''}</div>`;
  return `<section class="execution-feedback preparation-report"><div class="section-label">Source-bound data preparation & QC</div><h3>${technical ? 'Technical processing completed' : 'Technical processing incomplete'}</h3><p>${esc(r.execution_scope || 'Execution scope not reported')}</p>${flags}${summary}<p>${esc(r.review_scope || '')}</p>${renderDatasetActionReadiness(r)}<h4>Findings and missing materials</h4>${findings.map(x=>`<details class="field-card"><summary>${esc(x.dataset_id || x.affected_id || 'Finding')} · ${esc(String(x.code || 'finding').replaceAll('_',' '))}</summary><p>${esc(x.reason || '')}</p><p><strong>Needed:</strong> ${esc(x.needed_material || 'Not reported')}</p></details>`).join('')}<p>Files contains the normalized sources, provenance, quarantine records, QC report, and scoped downstream handoffs.</p><p>Sample-size sufficiency: ${esc(r.sample_size_status || 'Not established')}. No model fitting or human validation has run.</p>${n.state.can_retry_preparation ? '<div class="template-actions"><button id="edit-preparation-plan" class="button">Correct mapping</button><button id="retry-preparation" class="button">Retry preparation</button></div>' : ''}</section>`;
 }
 if(n.id==='prepare' && n.state.preparation_scope==='DIAGNOSTIC_PREPARATION_ONLY' && n.state.execution==='NOT_STARTED') return `<section class="execution-feedback"><h3>Diagnostic preparation is available</h3><p>The approved adequacy assessment still contains unresolved requirements. This run will split sources, isolate restricted data and report QC findings. It will preserve the original assessment and will not release model fitting.</p></section>`;
 if(n.id==='adequacy' && n.state.adequacy_report && n.state.execution==='COMPLETED') {
  const r=n.state.adequacy_report;
  return `<section class="execution-feedback adequacy-report"><div class="section-label">Project data assessment · reviewed by LLM</div><h3>${r.can_enter_qc ? 'Initial inputs can enter QC' : 'Data assessment needs attention'}</h3><p>${esc(r.assessment_status)} · ${esc(r.scope)}</p><p class="help-note">This checks entry to data preparation. It does not authorize fitting or establish reliable human predictions.</p>${r.why_cannot_pass.length ? `<h4>Why this cannot pass</h4><ul>${r.why_cannot_pass.map(x=>`<li>${esc(x.reason)}<br><strong>Needed:</strong> ${esc(x.needed_material || 'Review the cited finding.')}</li>`).join('')}</ul>` : '<p>No current QC-entry blocker was identified.</p>'}<h4>Missing materials and unresolved requirements</h4>${r.missing_materials.length ? r.missing_materials.map(x=>`<article class="field-card"><strong>${esc(x.required_by.replaceAll('_',' '))} · ${esc(x.requirement_id)}</strong><p>${esc(x.reason)}</p><p><strong>Needed:</strong> ${esc(x.needed_material)}</p></article>`).join('') : '<p>No structural requirement was marked missing; scientific sufficiency is still unverified.</p>'}<details><summary>Tasks and independent review</summary><p>Independent review: ${esc(r.llm_review.decision)}</p>${r.tasks.map(x=>`<p><strong>${esc(x.id)} · ${esc(x.estimand)}</strong><br>${esc(x.question)}<br>Species: ${esc(x.species)} · Endpoint: ${esc(x.endpoint)} · Window: ${esc(x.endpoint_window)} · Basis: ${esc(x.exposure_basis)}</p>`).join('')}</details><p>Context contains the full requirements, quotations and QC handoff. Files contains the report, gap table and model audit. Use Request study revision to add data or revise the scope when blocked.</p></section>`;
 }
 if(n.execution_adapter==='AWAITING_APPROVED_DATA_ADAPTER' && !n.state.locked_by.length) return `<section class="execution-feedback adapter-missing"><div class="section-label">Implementation connection missing</div><h3>This step has no execution adapter yet</h3><p>${n.depends_on.length && n.depends_on.every(id=>getNode(id)?.state.approved) ? 'The upstream step is complete and its approval is saved.' : 'This node currently defines an interface only.'} Approval cannot start a node without a registered executable target.</p><h4>Required implementation</h4><p>Connect a runner that reads the assigned input files, performs this step's checks, writes its declared outputs, and returns a structured status to the workflow.</p><p><strong>Expected outputs:</strong> ${esc(n.output_contract.map(x=>x.name).join(' · '))}</p><p class="help-note">This is a software connection gap. It does not mean that your data failed adequacy checks. Repeating Context compression will not resolve it.</p></section>`;
 if(f && n.state.execution==='FAILED') return `<section class="execution-feedback"><div class="section-label">Execution needs attention · ${esc(f.code)}</div><h3>${esc(f.title)}</h3><p><strong>Stopped at:</strong> ${esc(f.stage_label)}</p><p>${esc(f.summary)}</p><div class="template-actions">${n.state.can_retry_context ? '<button class="button primary" id="retry-context">Retry context</button>' : ''}<button class="text-button" id="download-execution-feedback">Download diagnosis JSON</button>${['LOCAL_FILE_REPLACE_BLOCKED','MODEL_BINDING_INVALID','MODEL_BINDING_REPAIR_FAILED'].includes(f.code) ? '' : '<button class="text-button" id="check-model-status">Check model connection</button>'}</div><h4>What the logs establish</h4><ul>${f.known_facts.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><p class="help-note">${esc(f.uncertainty)}</p><h4>What to do next</h4><ol>${f.suggested_actions.map(x=>`<li>${esc(x)}</li>`).join('')}</ol><h4>Proposal / missing materials</h4><p>${esc(f.materials_note)}</p>${flow.context_revision_child ? `<p><a href="/?flow=${encodeURIComponent(flow.context_revision_child)}#node=context&tab=context">Open the submitted retry ↗</a></p>` : ''}${renderBindingCorrections(f)}<details><summary>Technical details</summary><pre class="json-preview">${esc(n.state.technical_error || '')}</pre></details></section>`;
 if(p && ['RUNNING','PAUSING'].includes(n.state.execution)) return `<section class="model-progress"><div class="section-label">Model execution</div><p class="help-note">${currentModelCalls(p).some(x=>x.stage?.startsWith('context_') && x.stage!=='context_review') ? contextReviewNote(p) : p.stage?.startsWith('adequacy_') ? 'Requirements are derived from reviewed main.json and inspected table metadata, then checked by a separate LLM review.' : p.stage==='context_review' ? 'This historical run uses a single context review. New Workbench runs use parallel review.' : p.stage?.startsWith('attachment_evidence--') ? evidenceProgressNote(p) : 'The final-review mode is fixed when this run registers its inputs.'}</p>${currentModelCalls(p).map(renderModelCall).join('')}<p class="help-note">Status messages are recorded every 5 minutes. Local process liveness does not verify remote model progress. These are client event-receive times, not server first-token measurements; the CLI may emit the first response only when output is complete. Use Pause to stop manually.</p></section>`;
 return n.state.error ? `<section class="execution-feedback"><h3>This step needs attention</h3><p>Inspect the recorded details, correct the reported problem, then start a new attempt.</p>${renderBindingCorrections(f)}<details><summary>Technical details</summary><pre class="json-preview">${esc(n.state.error)}</pre></details></section>` : '';
}
function bindExecutionFeedback(n) {
 if(n.id==='context' && n.state.pre_eda_source_job_id && $('#start-pre-eda')) {
  $('#start-pre-eda').onclick=async()=>{
  if(busy)return;busy=true;$('#start-pre-eda').disabled=true;$('#pre-eda-status').textContent='Starting fresh pre-EDA workflow…';
  try{const job=await json(`/ui-api/workflow/sessions/${encodeURIComponent(flow.session_id)}/pre-eda`,{method:'POST',body:JSON.stringify({confirmed_user_authorization:true,auto_approve_human_gates:true})});$('#pre-eda-status').textContent=`Started ${job.id} · ${job.status}. Progress and retained stage outputs: /ui-api/jobs/${job.id}`;toast('Formal First Part and fresh pre-EDA workflow started. It will stop before EDA and fitting.');}
  catch(error){$('#pre-eda-status').textContent=error.message;$('#start-pre-eda').disabled=false;}
  finally{busy=false;}
  };
 }
 if($('#eda-dataset-select')) $('#eda-dataset-select').onchange=e=>{edaSelectedDataset=e.target.value;renderInspector();};
 if(n.id==='eda' && n.state.can_retry_eda) {
  if(!$('#retry-eda')) $('.execution-feedback')?.insertAdjacentHTML('beforeend','<button id="retry-eda" class="button">Retry EDA</button>');
  if($('#retry-eda')) $('#retry-eda').onclick=async()=>{if(busy)return;busy=true;try{flow=await json(sessionPath()+'/nodes/eda/start',{method:'POST',body:'{}'});receivedAt=performance.now();toast('New EDA attempt started from the approved QC files.');}catch(error){toast(error.message);}finally{busy=false;render();}};
 }
 if(n.id==='prepare' && n.state.can_retry_preparation) {
  if(!$('#retry-preparation')) {
   const panel=$('.execution-feedback');
   if(panel) panel.insertAdjacentHTML('beforeend','<button id="edit-preparation-plan" class="button">Correct mapping</button><button id="retry-preparation" class="button">Retry preparation</button>');
  }
  if($('#retry-preparation')) $('#retry-preparation').onclick=async()=>{if(busy)return;busy=true;try{flow=await json(sessionPath()+'/nodes/prepare/start',{method:'POST',body:'{}'});receivedAt=performance.now();toast('New preparation attempt started. Prior outputs and approvals are preserved.');}catch(error){toast(error.message);}finally{busy=false;render();}};
  if($('#edit-preparation-plan')) $('#edit-preparation-plan').onclick=async()=>{
   try {
    const template=await json(sessionPath()+'/preparation-plan');
    modal('Correct source mapping',`<p>Map supported fields to exact source headers. Keep units in the headers. Original values and restricted partitions are preserved.</p><label>Preparation plan JSON<textarea id="preparation-plan-json" rows="18" style="width:100%">${esc(JSON.stringify(template,null,2))}</textarea></label><label>Reason for correction<textarea id="preparation-plan-reason" rows="3" style="width:100%"></textarea></label><button class="button primary" id="save-preparation-plan">Save correction and rerun</button>`,'PREPARATION');
    $('#save-preparation-plan').onclick=async()=>{if(busy)return;busy=true;try{
     const plan=JSON.parse($('#preparation-plan-json').value),rationale=$('#preparation-plan-reason').value;
     flow=await json(sessionPath()+'/preparation-plan',{method:'POST',body:JSON.stringify({output_signature:n.state.output_signature,plan,rationale,confirmed:true})});
     flow=await json(sessionPath()+'/nodes/prepare/start',{method:'POST',body:'{}'});receivedAt=performance.now();document.querySelector('dialog[open]')?.close();toast('Mapping correction saved; preparation started.');
    }catch(error){toast(error.message);}finally{busy=false;render();}};
   }catch(error){toast(error.message);}
  };
 }
 if(n.state.can_retry_adequacy) {
  const panel=$('.execution-feedback');
  if(panel) {const button=document.createElement('button');button.className='button primary';button.textContent='Retry data adequacy';button.id='retry-adequacy';panel.append(button);
   button.onclick=async()=>{if(busy)return;busy=true;try{flow=await json(sessionPath()+'/nodes/adequacy/start',{method:'POST',body:'{}'});receivedAt=performance.now();toast('New adequacy attempt started. Approved Context is preserved.');}catch(error){toast(error.message);}finally{busy=false;render();}};
  }
 }
 if($('#download-execution-feedback')) $('#download-execution-feedback').onclick=()=>download(n.state.failure,'execution_diagnosis.json');
 if($('#check-model-status')) $('#check-model-status').onclick=async()=>{
  try {const status=await json('/ui-api/model/status'); modal('Model connection status',`<p>${status.installed ? 'The model interface is available.' : 'The model interface is unavailable.'} ${status.logged_in === null ? 'Login is not checked by this interface.' : status.logged_in ? 'Login or model is available.' : 'Login or model is unavailable.'}</p><p>A login check does not verify that generation will complete.</p><pre>${esc(JSON.stringify(status,null,2))}</pre>`,'CONNECTION');}
  catch(error){toast(error.message);}
 };
 if($('#retry-context')) $('#retry-context').onclick=async()=>{
  if(busy) return; busy=true; const endpoint=sessionPath()+'/context-retries', previous=flow.session_id; render();
  try {
   const next=await json(endpoint,{method:'POST',body:JSON.stringify({failure_signature:n.state.failure.signature,confirmed:true})});
   flow=next; receivedAt=performance.now(); selected='context'; tab='context';
   const url=new URL(location.href); url.searchParams.set('flow',next.session_id); url.hash=route('context','context'); history.pushState(null,'',url);
   toast(next.session_id===previous ? 'Context continues in this run: accepted steps are reused and the stopped step runs again. No forced model deadline; status messages every 5 minutes.'
    : 'This run could not continue because its code or inputs changed, so a new run started with the original files. No forced model deadline; status messages every 5 minutes.');
  } catch(error){toast(error.message);} finally {busy=false; render();}
 };
}
function notifyModelHeartbeats() {
 for(const n of flow.nodes) {
  const progress=n.state.model_progress;
  if(!progress || !['RUNNING','PAUSING'].includes(n.state.execution)) continue;
  for(const p of currentModelCalls(progress)) {
  const h=p.last_heartbeat;
  if(!h || p.status!=='RUNNING') continue;
  const id=`${flow.session_id}:${p.call_id}:${h.sequence}`;
  if(shownHeartbeats.has(id)) continue; shownHeartbeats.add(id);
  toast(`${p.stage_label} · ${duration(h.elapsed_seconds)} · ${p.monitor_current && p.process_alive ? 'Local process alive. '+h.message : 'Call finished or liveness report is stale; inspect the run.'}`);
  }
 }
}
function renderBindingCorrections(f) {
 if(!['MODEL_BINDING_INVALID','MODEL_BINDING_REPAIR_FAILED'].includes(f?.code) || !f.validation_details?.issues?.length) return '';
 const d=f.validation_details;
 return `<details class="binding-corrections"><summary>Binding corrections (${d.issues.length})</summary><p>${esc(d.check_scope || '')}</p>${d.issues.map(x=>`<details class="field-card"><summary>${esc(x.item_id)} · ${esc(x.field)}</summary><p><strong>Submitted value:</strong> ${esc(x.proposed_value)}</p><p><strong>Reason:</strong> ${esc(x.reason)}</p>${x.evidence.map(e=>`<p><strong>Source excerpt (${esc(e.source_id)} / ${esc(e.unit_id)}):</strong> ${esc(e.quote)}${e.source_verified ? '' : ' — source check failed'}</p>`).join('')}<p><strong>Correction:</strong> ${esc(x.what_to_change)}</p><p>${esc(x.path)}</p></details>`).join('')}</details>`;
}
