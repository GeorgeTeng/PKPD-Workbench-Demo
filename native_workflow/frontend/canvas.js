'use strict';
const $ = (q, root = document) => root.querySelector(q);
const $$ = (q, root = document) => [...root.querySelectorAll(q)];
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let englishStrings = {}, englishFragments = [];
function english(text) {return typeof text === 'string' ? (englishStrings[text] ?? text) : text;}
function englishTree(value) {
 if(typeof value === 'string') return english(value);
 if(Array.isArray(value)) return value.map(englishTree);
 if(value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k,v])=>[k,englishTree(v)]));
 return value;
}
function englishMessage(value) {
 if(typeof value !== 'string') return value;
 if(englishStrings[value] !== undefined) return englishStrings[value];
 return englishFragments.reduce((text,[source,target])=>text.split(source).join(target),value);
}
function localizePayload(path, value) {
 if(/\/(rules-draft)$/.test(path)) return englishTree(value);
 if(value?.new_session) value.new_session = localizePayload('/template',value.new_session);
 if(!Array.isArray(value?.nodes)) return value;
 value.nodes = value.nodes.map(n=>({...n,
  title:english(n.title),subtitle:english(n.subtitle),review_requirements:englishTree(n.review_requirements),
  input_contract:englishTree(n.input_contract),output_contract:englishTree(n.output_contract),
  state:{...n.state,reason:englishMessage(n.state.reason),error:englishMessage(n.state.error)}}));
 value.edges = englishTree(value.edges); value.clinical_fields = englishTree(value.clinical_fields);
 if(value.cycle_sources) value.cycle_sources = value.cycle_sources.map(s=>({...s,title:english(s.title)}));
 // User text, uploaded data, evidence, and actual artifact contents retain their original wording.
 return value;
}
const paths = {
 flow:'M4 3h6v5H4z M14 16h6v5h-6z M4 16h6v5H4z M7 8v4h10v4 M7 12v4',
 layers:'m12 3 9 5-9 5-9-5 9-5z M3 12l9 5 9-5 M3 16l9 5 9-5',
 clock:'M12 8v5l3 2 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',
 settings:'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8 M12 2v3 M12 19v3 M2 12h3 M19 12h3 M5 5l2 2 M17 17l2 2 M5 19l2-2 M17 7l2-2',
 plus:'M12 5v14 M5 12h14', pause:'M8 5v14 M16 5v14', minus:'M5 12h14', download:'M12 3v12 m-5-5 5 5 5-5 M4 16v5h16v-5',
 fit:'M9 3H3v6 M15 3h6v6 M9 21H3v-6 M15 21h6v-6', lock:'M6 10h12v11H6z M8 10V6a4 4 0 0 1 8 0v4 M12 14v3',
 paperclip:'m8 13 6-6a3 3 0 0 1 4 4l-8 8a5 5 0 0 1-7-7l8-8 M7 14l7-7',
 close:'m6 6 12 12 M6 18 18 6', arrow:'M5 12h14 m-5-5 5 5-5 5', link:'M9 8l3-3a5 5 0 0 1 7 7l-3 3 M15 16l-3 3a5 5 0 0 1-7-7l3-3 M8 16l8-8',
 file:'M5 3h9l5 5v13H5z M14 3v5h5 M8 12h8 M8 16h6', folder:'M3 6h7l2 2h9v12H3z',
 check:'m5 12 4 4L19 6', refresh:'M20 12a8 8 0 1 1-2.4-5.7 M20 4v5h-5', play:'m8 4 12 8-12 8V4z', info:'M12 10v7 M12 6v1 M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0',
 code:'m8 5-6 7 6 7 M16 5l6 7-6 7 M14 3l-4 18', chart:'M3 3v18h18 M6 16l4-5 4 2 5-8',
 branch:'M6 3v12a4 4 0 1 0 4 4 M6 9h8a4 4 0 0 0 4-4 M18 2v6 M15 5h6', search:'M10 3a7 7 0 1 0 0 14 7 7 0 0 0 0-14 M15 15l6 6'
};
function icon(name) {return `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true"><path d="${paths[name] || paths.file}"/></svg>`;}
function icons(root = document) {$$('[data-icon]', root).forEach(e => e.innerHTML = icon(e.dataset.icon));}
const nodeIcons = {intake:'folder', context:'code', adequacy:'search', prepare:'layers', eda:'search', dispatch:'branch', pk:'chart', index:'chart', results:'file', clinical:'flow'};
const tabs = {input:'Inputs', context:'Context', files:'Outputs', clinical:'Clinical', review:'Review'};
let flow = null, selected = 'intake', tab = 'input', page = 'canvas', pollTimer = null, busy = false, lastPlace = '';
const notices = {NOT_STARTED:'Not started', RUNNING:'Running', PAUSING:'Pausing', PAUSED:'Paused', FAILED:'Failed', COMPLETED:'Awaiting review', NEEDS_ATTENTION:'Needs attention', STALE:'Stale outputs'};
const kindNames = {context:'CONTEXT',data:'Data',evidence:'Evidence',model:'Model',figure:'Figure',report:'Report'};
const kindBadge = kind => `<span class="kind-badge kind-${kind || 'context'}">${kindNames[kind] || 'Files'}</span>`;
function duration(seconds) {const t = Math.max(0,Math.floor(seconds || 0)); return [Math.floor(t/3600),Math.floor(t/60)%60,t%60].map(x => String(x).padStart(2,'0')).join(':');}
let receivedAt = performance.now();
function updateClocks() {
 if(!flow) return; const extra = Math.max(0,(performance.now()-receivedAt)/1000);
 $('#run-clock').textContent = duration(flow.timing.elapsed_seconds + (flow.timing.running ? extra : 0));
 $$('[data-node-clock]').forEach(el => {const timing = getNode(el.dataset.nodeClock)?.state.timing; el.textContent = duration(timing?.elapsed_seconds + (timing?.running ? extra : 0));});
}
setInterval(updateClocks,1000);
const getNode = id => flow?.nodes.find(n => n.id === id);
const route = (id, targetTab = 'input') => `#node=${encodeURIComponent(id)}&tab=${encodeURIComponent(targetTab)}`;
function stateLabel(n) {if(n.execution_adapter === 'DISABLED') return 'Not enabled'; if(n.state.execution === 'REVISION_REQUIRED') return 'Revision required'; return n.state.approved ? (n.state.requires_human_review === false ? 'Verified' : 'Approved') : n.state.review?.decision === 'REJECT' ? 'Rejected' : n.state.review?.decision === 'REQUEST_CHANGES' ? 'Changes requested' : n.state.execution !== 'NOT_STARTED' ? notices[n.state.execution] : n.state.locked_by.length ? 'Locked' : n.id === 'pk' ? 'Plan & review' : n.execution_adapter === 'AWAITING_APPROVED_DATA_ADAPTER' ? 'Not connected' : n.id === 'intake' && !flow.uploads.length ? 'Awaiting files' : 'Not started';}
function stateIcon(n) {return n.state.approved ? 'check' : n.state.locked_by.length || n.execution_adapter === 'AWAITING_APPROVED_DATA_ADAPTER' ? 'lock' : n.state.execution === 'RUNNING' ? 'clock' : 'info';}
function toast(message) {$('#toast').textContent = message; $('#toast').hidden = false; clearTimeout(toast.timer); toast.timer = setTimeout(() => $('#toast').hidden = true, 6000);}
async function api(path, options = {}) {
 const headers = new Headers(options.headers || {}), token = sessionStorage.getItem('pmb-token');
 if(token) headers.set('Authorization', `Bearer ${token}`);
 if(options.body && !(options.body instanceof FormData)) headers.set('Content-Type','application/json');
 const response = await fetch(path, {...options, headers});
 if(!response.ok) {let data; try {data = await response.json();} catch {data = {};}
  throw new Error(englishMessage(typeof data.detail === 'string' ? data.detail : typeof data.message === 'string' ? data.message : `Request failed (${response.status})`));}
 return response;
}
async function json(path, options) {return localizePayload(path,await (await api(path, options)).json());}
const sessionPath = () => `/ui-api/workflow/sessions/${encodeURIComponent(flow.session_id)}`;
function download(value, name, type = 'application/json') {
 const blob = value instanceof Blob ? value : new Blob([JSON.stringify(value,null,2)], {type});
 const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function modal(title, body, kicker = 'CONTEXT') {$('#modal-title').textContent = title; $('#modal-kicker').textContent = kicker; $('#modal-body').innerHTML = body; icons($('#modal')); if(!$('#modal').open) $('#modal').showModal();}
function showTemplate(id) {
 const n = getNode(id); modal(`${n.title} · output template`, `<p>This is an interface template. Actual results will appear separately after execution.</p><pre>${esc(JSON.stringify(n.context_template,null,2))}</pre><div class="modal-actions"><button class="button secondary" id="download-template">${icon('download')}Download template JSON</button></div>`, 'CONTEXT TEMPLATE');
 $('#download-template').onclick = () => download(n.context_template, `${id}.template.json`);
}
async function showArtifact(id, name, mode = 'preview') {
 const target = mode === 'open' ? window.open('about:blank','_blank') : null;
 if(target) target.opener = null;
 try {
  if(mode === 'open' && !target) throw new Error('Allow this local workbench to open a new tab, then try Open again.');
  const response = await api(`${sessionPath()}/nodes/${encodeURIComponent(id)}/artifacts/${encodeURIComponent(name)}`), blob = await response.blob();
  if(mode === 'download') {download(blob,name); return;}
  if(mode === 'open') {await openArtifactWindow(blob,name,target); return;}
  let preview = '<p>Download this attachment in its original format. Its contents are not compressed into the context summary.</p>';
  let fullText = null, jsonValue, parsedJSON = false;
  if(/\.(jsonl?|csv|tsv|txt|md|r|py|yaml|yml|log|html|xml|smk)$/i.test(name)) {
   let display = await blob.text();
   if(/\.json$/i.test(name)) {try {jsonValue = JSON.parse(display); parsedJSON = true; display = JSON.stringify(jsonValue,null,2);} catch {/* Preserve the original text. */}}
   fullText = display;
   preview = `<pre class="artifact-text-preview" id="artifact-preview-text">${esc(display.slice(0,12000))}</pre>${display.length>12000 ? `<p class="artifact-modal-note" id="artifact-truncation-note">Showing the first 12,000 of ${display.length.toLocaleString()} characters. The original file is complete.</p><button class="text-button" id="artifact-expand">Show full content</button>` : ''}`;
  } else if(/\.(png|svg|jpe?g|gif|webp)$/i.test(name)) {
   const imageUrl=URL.createObjectURL(blob);
   preview=`<img class="artifact-figure" src="${imageUrl}" alt="${esc(name)}" style="display:block;width:100%;height:auto">`;
   $('#modal').addEventListener('close',()=>URL.revokeObjectURL(imageUrl),{once:true});
  }
  if(parsedJSON) preview = metadataTree(jsonValue);
  modal(name, `<p class="artifact-modal-note">Execution artifact · ${esc(getNode(id).title)} · file version verified · ${artifactSize(blob.size)}</p><div class="artifact-modal-tools"><button id="artifact-open" class="button secondary">${icon('link')}Open full file ↗</button><button id="artifact-download" class="button primary">${icon('download')}Download original</button></div>${preview}`, 'EXECUTION OUTPUT');
  $('#artifact-download').onclick = () => download(blob,name);
  $('#artifact-open').onclick = () => {const opened=window.open('about:blank','_blank');if(!opened){toast('Allow this local workbench to open a new tab.');return;}opened.opener=null;openArtifactWindow(blob,name,opened).catch(error=>{opened.close();toast(error.message);});};
  if($('#artifact-expand'))$('#artifact-expand').onclick=()=>{$('#artifact-preview-text').textContent=fullText;$('#artifact-expand').remove();$('#artifact-truncation-note').textContent='Full content shown. Download preserves the original file bytes.';};
 } catch(error) {if(target)target.close();toast(error.message);}
}
function renderGraph() {if(page === 'canvas') renderWorkflowGraph();}
// Back button and breadcrumbs: every page below the workflow can go one level up.
function renderNav() {
 const nav = $('#wb-nav'), trail = navTrail();
 nav.hidden = page === 'canvas';
 if(nav.hidden) {nav.innerHTML = ''; return;}
 const up = trail[trail.length - 2] || trail[0];
 nav.innerHTML = `<a class="back-button" href="${up[1]}">← Back</a><ol class="crumbs">${trail.map(([label,href],i) => `<li>${i === trail.length - 1 ? `<span aria-current="page">${esc(label)}</span>` : `<a href="${href}">${esc(label)}</a>`}</li>`).join('')}</ol>`;
}
function nodeLinks(ids) {return ids.map(id => `<a href="${route(id)}">${esc(getNode(id)?.title || id)}</a>`).join('<span>·</span>');}
function emptyBox(title, detail, kind = 'file') {return `<div class="empty-box"><span class="empty-icon">${icon(kind)}</span><strong>${esc(title)}</strong><p>${esc(detail)}</p></div>`;}
function renderInput(n) {
 const sources=n.depends_on.length?`<div class="receiver">From ${nodeLinks(n.depends_on)}</div>`:'';
 const fields=n.input_contract.map((f,i)=>`<details class="compact-contract" data-preserve-details="input-${i}"><summary>${icon('file')}<span class="contract-title">${esc(f.name)}</span></summary><div class="contract-detail">${compactContent(f.description)}</div></details>`).join('');
 const files=n.id==='intake'?`<div class="upload-list">${flow.uploads.length?flow.uploads.map(f=>`<div class="attachment-row">${icon('file')}<span>${esc(f.name)}</span></div>`).join(''):'<p class="muted">Add a proposal and supporting files.</p>'}<button id="add-files" class="button secondary" ${!flow.session_id||n.state.execution!=='NOT_STARTED'||busy?'disabled':''}>${icon('plus')}Add files</button></div>`:'';
 return `${typeof renderClinicalDispatch==='function'?renderClinicalDispatch(n):''}${sources}${typeof supplementalInputs==='function'?supplementalInputs(n):''}${files}<details class="input-requirements" data-preserve-details="required-inputs"><summary>Required inputs</summary>${fields}</details>`;
}
function renderContext(n) {
 const files=n.state.artifacts.filter(a=>!a.kind||a.kind==='context');
 return `${files.length?artifactBrowser(n.id,files,'context'):'<p class="muted">No context generated yet.</p>'}<details class="contract-section" data-preserve-details="template"><summary>Output template</summary><button class="text-button" data-template="${n.id}">View JSON</button></details>`;
}
function renderFiles(n) {
 return `${typeof renderRoutingOutputEntry==='function'?renderRoutingOutputEntry(n):''}${n.id==='eda'?'<a class="button secondary" href="#node=eda&view=figures">View figures →</a>':''}${n.state.artifacts.length?artifactBrowser(n.id,n.state.artifacts):'<p class="muted">No files generated yet.</p>'}<details class="contract-section" data-preserve-details="planned-outputs"><summary>Expected outputs</summary>${n.output_contract.map((f,i)=>`<p><button class="text-button" data-contract-file="${i}">${esc(f.name)}</button></p>`).join('')}</details>`;
}
function renderClinical(n) {
 if(n.id === 'dispatch') {
  const saved = n.state.clinical_spec, draft=n.state.clinical_draft, definitions=saved || draft, editable = !!flow.session_id && ['NOT_STARTED','FAILED'].includes(n.state.execution);
  if(!definitions) return `${typeof renderClinicalDispatch === 'function' ? renderClinicalDispatch(n) : ''}<div class="help-note">Prepare the draft first. This will prepare tasks from the reviewed inputs; then confirm their definitions and exposure dependencies.</div>`;
  return `${typeof renderClinicalDispatch === 'function' ? renderClinicalDispatch(n) : ''}<div class="section-label">Confirm task definitions</div><div class="help-note">These definitions accompany branch context. For unknowns, enter <strong>UNKNOWN: reason</strong> and record evidence gaps and limits of use. Confirming definitions does not replace this step\'s review.</div><form id="clinical-form" class="review-form">${flow.clinical_fields.map(f => `<label>${esc(f.label)}${typeof clinicalQuestionEvidence === 'function' ? clinicalQuestionEvidence(n,f.key) : ''}<textarea name="${f.key}" required minlength="2" maxlength="10000" placeholder="${esc(f.help)}" ${!editable ? 'disabled' : ''}>${esc(definitions?.values[f.key] || '')}</textarea></label>`).join('')}<label>Index exposure source<select name="index_exposure_source" ${!editable ? 'disabled' : ''}><option value="UNKNOWN">Unconfirmed · routing remains locked</option><option value="AVAILABLE_MATCHED_DATA" ${definitions?.index_exposure_source === 'AVAILABLE_MATCHED_DATA' ? 'selected' : ''}>Matched exposure available · parallel execution allowed</option><option value="REQUIRES_PK_PREDICTIONS" ${definitions?.index_exposure_source === 'REQUIRES_PK_PREDICTIONS' ? 'selected' : ''}>Needs current PK predictions · add a dependency</option></select></label><label>Reviewer<input name="reviewer" required maxlength="100" value="${esc(saved?.reviewer || '')}" ${!editable ? 'disabled' : ''}></label><label class="confirm-label"><input type="checkbox" name="confirmed" required ${!editable ? 'disabled' : ''}>I have checked the task definitions, data sources, and unknowns.</label><button class="button primary" ${!editable || busy ? 'disabled' : ''}>${saved ? 'Update definitions' : 'Save and confirm definitions'}</button></form>${saved ? `<div class="help-note">Last confirmed: ${esc(saved.reviewer)} · ${esc(new Date(saved.at).toLocaleString('en-GB'))}</div>` : ''}`;
 }
 const sources = flow.cycle_sources || [], eligible = !!flow.session_id && sources.length > 0;
 const changes = [
  ['REVISE_PROPOSAL','intake','Revise the proposal / study objective'],
  ['ADD_DATA','intake','Collect or upload missing data'],
  ['RETRIEVE_EVIDENCE','context','Retrieve more literature / evidence'],
  ['REASSESS_ADEQUACY','adequacy','Reassess data adequacy'],
  ['CORRECT_DATA','prepare','Correct data mapping / QC'],
  ['REVISE_EDA','eda','Revisit EDA and coverage'],
  ['REVISE_CLINICAL_QUESTION','dispatch','Revise task definitions / endpoints'],
  ['REVISE_PK','pk','Revise the PK analysis'],
  ['REVISE_INDEX','index','Revise PK/PD index analysis'],
  ['REVIEW_RESULTS','results','Reconcile model results']
 ];
 return `<div class="section-label">Clinical review across the whole study</div><div class="cycle-banner"><strong>Proposal → evidence → data → models → clinical review → next proposal</strong><p>A data gap or clinical concern can open a new cycle before modeling finishes. The final clinical report still requires both model branches and human acceptance.</p></div><div class="field-list section-gap"><div class="field-card"><div class="field-name">Decision relevance & evidence gaps</div><p>Can the available evidence answer the research question? Identify missing data, uncertain translation assumptions, or a proposal that needs revision.</p></div><div class="field-card"><div class="field-name">Regimen feasibility & safety</div><p>Review route, dosing, practical constraints, target population, safety endpoints, and threshold sources. Missing evidence remains unassessable.</p></div></div><div class="section-gap"><div class="section-label">Request a study revision</div><form id="cycle-form" class="review-form"><label>Finding that triggered this review<select name="source_node" ${!eligible ? 'disabled' : ''}>${sources.length ? sources.map((source,i)=>`<option value="${source.id}" ${i===sources.length-1 ? 'selected' : ''}>${esc(source.title)} · ${source.execution==='NEEDS_ATTENTION' ? 'Data issue' : 'Output available'}</option>`).join('') : '<option>No output or issue report yet</option>'}</select></label><label>What needs to change?<select name="change_type">${changes.map(([kind,target,label])=>`<option value="${kind}" data-target="${target}">${label}</option>`).join('')}</select></label><label>Clinical or scientific reason<textarea name="reason" required minlength="5" placeholder="Explain the decision the current evidence cannot support, or why the proposal needs to change"></textarea></label><label>Concrete next-cycle request<textarea name="requested_changes" required minlength="5" placeholder="Specify proposal sections to revise, missing variables or samples to collect, evidence to retrieve, or analyses to revisit"></textarea></label><label>Reviewer<input name="reviewer" required maxlength="100"></label><label class="confirm-label"><input type="checkbox" name="confirmed" required>I confirm this study revision. The current cycle is retained and this request does not approve its results.</label><button class="button primary" ${!eligible || busy ? 'disabled' : ''}>Create next study cycle</button></form></div><div class="help-note">${eligible ? 'The new cycle records the finding, evidence versions, requested changes, and revision target. It starts with input registration and fresh review; earlier approvals are not inherited.' : 'A completed output or a valid data-issue report is needed. The loop can then start from intake, adequacy, QC, EDA, or a later result; it does not require a completed final clinical report.'}</div>`;
}
function renderReview(n) {
 const state = n.state, record = state.review;
 const outputEntry = state.artifacts.length ? `<div class="review-file-entry"><div class="section-label">Files for inspection <span class="muted">${state.artifacts.length} file${state.artifacts.length === 1 ? '' : 's'}</span></div><div class="upstream-shortcuts"><button class="text-button" data-upstream-files="${esc(n.id)}">${icon('folder')}Open file browser</button><a class="text-button" href="${route(n.id,'context')}">View context →</a></div></div>` : '';
 if(state.requires_human_review === false || (n.review_policy?.startsWith('AUTOMATIC') && state.execution === 'NOT_STARTED')) return `${outputEntry}<div class="section-label">Automatic technical checks</div><div class="help-note">${esc(state.gate_reason || 'No separate human signature is needed for this step. Validated outputs unlock the next eligible step. Scientific review remains at decision points.')}</div>`;
 const graphNote = state.langgraph_review ? `<details class="graph-receipt"><summary>Review record</summary>LangGraph ${state.langgraph_review.status === 'INTERRUPTED' ? 'interrupt · awaiting a human decision' : esc(state.langgraph_review.status)}<br><span>Checkpoint ${esc(state.langgraph_review.checkpoint_id)}</span></details>` : '';
 const requirements = `<div class="section-label">Review checklist</div><ul class="gate-list">${n.review_requirements.map(text => `<li><span class="check-outline ${state.approved ? 'checked' : ''}">${state.approved ? icon('check') : ''}</span><span>${esc(text)}</span></li>`).join('')}</ul>`;
 const history = record ? `<div class="field-card review-record"><strong>${esc(stateLabel(n))}</strong><br>Reviewer: ${esc(record.reviewer)}<br>${typeof objectiveRecord === 'function' ? objectiveRecord(record) : ''}${record.rationale ? `${esc(record.rationale)}<br>` : ''}<span class="muted">${esc(new Date(record.at).toLocaleString('en-GB'))}</span></div>` : '';
 const form = state.can_review ? `<div class="section-gap"><form id="review-form" class="review-form"><label>Reviewer<input name="reviewer" required maxlength="100" autocomplete="name"></label>${typeof renderObjectiveCheck === 'function' ? renderObjectiveCheck(n) : ''}<label>Decision<select name="decision"><option value="APPROVE" selected>Approve · no issues</option><option value="REQUEST_CHANGES">Request changes · keep downstream locked</option><option value="REJECT">Reject · keep downstream locked</option></select></label><label><span id="review-comment-label">Additional comments (optional)</span><textarea name="rationale" maxlength="10000" placeholder="No comment needed to approve"></textarea></label><label class="confirm-label"><input type="checkbox" name="confirmed" required>I have checked this step\'s outputs and confirm this decision applies to this step.</label><button class="button primary" type="submit" ${busy ? 'disabled' : ''}>Submit review</button></form></div>` : !state.approved ? `<div class="section-gap">${emptyBox('Review is not available yet','Complete this step and approve its prerequisites before submitting a review.','lock')}</div>` : '';
 return `${typeof renderMissingInformation === 'function' ? renderMissingInformation(n) : ''}${outputEntry}${typeof renderRoutingOutputEntry === 'function' ? renderRoutingOutputEntry(n) : ''}${graphNote}${requirements}${history}${form}${n.id === 'clinical' ? `<div class="section-gap"><button id="publish-report" class="button primary" ${!flow.can_publish || busy ? 'disabled' : ''}>${icon('download')}Publish report and audit archive</button><div class="help-note">After final human acceptance, create a local archive of files, input references, rule snapshots, and review records.</div></div>` : ''}<div class="help-note">Approval is bound to these output versions. Changed files invalidate the approval and downstream release.</div>`;
}
function runReason(n) {
 if(flow.control_status === 'PAUSING') return 'Pause requested. Stopping unfinished computation; the workflow shows Paused after the executor acknowledges it.';
 if(flow.control_status === 'PAUSED') return 'Paused. Resume preserves completed blocks and reruns unfinished blocks; review requirements still apply.';
 if(!flow.session_id && n.id === 'intake') return 'Create a blank run, then add files.';
 if(n.state.approved) return n.state.requires_human_review === false ? 'Technical checks passed; the next eligible step is available.' : 'This step is complete and approved; inspect downstream steps.';
 if(n.state.execution === 'RUNNING') return 'This step is running; review follows completion.';
 if(n.state.execution === 'COMPLETED') return 'Execution is complete. Submit a decision under Review.';
 return n.state.error || n.state.reason || 'Inputs are ready; this step can run.';
}
function renderInspector() {
 const n = getNode(selected); if(!n || page!=='step') return;
 // Retain local edits while polling the same definitions, but never restore an
 // earlier blank or edited form over a newly generated/confirmed draft.
 const clinicalVersion = n.id==='dispatch' && tab==='clinical'
  ? `:${n.state.clinical_draft?.signature || 'no-draft'}:${n.state.clinical_spec_ref?.sha256 || 'unconfirmed'}` : '';
 const key = `${flow.session_id}:${selected}:${tab}${clinicalVersion}`, same = $('#inspector').dataset.scope === key;
 const fields = same ? $$('form input,form select,form textarea',$('#inspector')).map(e => ({name:e.name,value:e.value,checked:e.checked})) : [];
 const scroll = same ? $('.detail-body')?.scrollTop || 0 : 0;
 const disclosureState = same ? new Map($$('[data-preserve-details]',$('#inspector')).map(e=>[e.dataset.preserveDetails,e.open])) : new Map();
 const focusedSearch = same && document.activeElement?.matches('[data-artifact-search]') ? {scope:document.activeElement.closest('[data-browser-scope]').dataset.browserScope,start:document.activeElement.selectionStart,end:document.activeElement.selectionEnd} : null;
 const ruleSearchFocus = same && document.activeElement?.id === 'eda-rule-search' ? {start:document.activeElement.selectionStart,end:document.activeElement.selectionEnd} : null;
 const folderScroll = same ? new Map($$('[data-folder-key]',$('#inspector')).map(e=>[e.dataset.folderKey,e.querySelector('.artifact-folder-files')?.scrollTop || 0])) : new Map();
 const activeTabs = Object.entries(tabs).filter(([key]) => (key !== 'clinical' || ['dispatch','clinical'].includes(n.id)) && (key !== 'eda' || n.id === 'eda'));
 if(!activeTabs.some(([key]) => key === tab)) tab = 'input';
 $('#inspector').dataset.scope = key;
 const number = stageInfo[n.id]?.number || stageInfo[stageOf(n.id)]?.number || '';
 $('#inspector').innerHTML = `<header class="page-head">${number ? `<span class="page-num">${number}</span>` : ''}<div><h1>${esc(uiTitle(n))}</h1><p>${esc(stageInfo[n.id]?.summary || n.subtitle || '')}</p></div><div class="page-head-meta">${statusChip(stateLabel(n))}<span class="step-duration" title="Active time">${icon('clock')}<span data-node-clock="${n.id}">${duration(n.state.timing.elapsed_seconds)}</span></span></div></header><div class="detail-tabs ${activeTabs.length === 5 ? 'five-tabs' : ''}" aria-label="Step details">${activeTabs.map(([key,label]) => `<button data-tab="${key}" class="${tab === key ? 'active' : ''}" aria-pressed="${tab === key}">${key === 'clinical' ? (n.id === 'clinical' ? 'Study loop' : 'Tasks') : label}</button>`).join('')}</div><div class="detail-body">${flow.parent_cycle ? `<details class="cycle-note"><summary>Previous cycle</summary> ${esc(flow.parent_cycle.reason)}<br><strong>Requested changes:</strong> ${esc(flow.parent_cycle.requested_changes)}<br>Revisit: ${esc(getNode(flow.parent_cycle.target)?.title)} · register inputs and review again.<br><a href="/?flow=${encodeURIComponent(flow.parent_cycle.session_id)}${route(flow.parent_cycle.source_node || 'clinical','files')}">View source ↗</a></details>` : ''}${compactInspectorFeedback(n)}${typeof renderContextStages === 'function' ? renderContextStages(n) : ''}${typeof renderAnimalPkEntry === 'function' ? renderAnimalPkEntry(n) : ''}${({input:renderInput,context:renderContext,files:renderFiles,clinical:renderClinical,review:renderReview}[tab])(n)}</div><div class="inspector-footer"><p>${icon('lock')}<span>${esc(runReason(n))}</span></p><button class="button primary" id="run-step" ${!n.state.can_run || busy ? 'disabled' : ''}>${icon(n.state.can_run ? 'play' : 'lock')}${n.state.execution === 'RUNNING' ? 'Step running' : 'Run this step'}</button></div>`;
 if(n.id==='pk')$('.inspector-footer',$('#inspector')).innerHTML = `<p>${icon('info')}<span>Animal PK runs per species in its own workspace.</span></p><button class="button primary" id="open-pk-control-footer" ${flow.session_id?'':'disabled'}>Open species workspaces ${icon('arrow')}</button>`;
 // Match same-named fields by position: radio groups and checkbox lists share one name.
 const current = $$('form input,form select,form textarea',$('#inspector')), seen = {};
 fields.forEach(f => {const i = seen[f.name] = (seen[f.name] ?? -1) + 1, el = current.filter(e => e.name === f.name)[i]; if(!el || el.type === 'file') return; if(['checkbox','radio'].includes(el.type)) {if(el.value === f.value && !el.disabled) el.checked = f.checked;} else el.value = f.value;});
 $$('[data-preserve-details]',$('#inspector')).forEach(e=>{if(disclosureState.has(e.dataset.preserveDetails))e.open=disclosureState.get(e.dataset.preserveDetails);});
 bindArtifactBrowsers($('#inspector'));
 $$('[data-folder-key]',$('#inspector')).forEach(e=>{if(folderScroll.has(e.dataset.folderKey))e.querySelector('.artifact-folder-files').scrollTop=folderScroll.get(e.dataset.folderKey);});
 if(focusedSearch){const input=$$('[data-browser-scope]',$('#inspector')).find(e=>e.dataset.browserScope===focusedSearch.scope)?.querySelector('[data-artifact-search]');if(input){input.focus({preventScroll:true});if(focusedSearch.start!=null)input.setSelectionRange(focusedSearch.start,focusedSearch.end);}}
 if(ruleSearchFocus && $('#eda-rule-search')){$('#eda-rule-search').focus({preventScroll:true});$('#eda-rule-search').setSelectionRange(ruleSearchFocus.start,ruleSearchFocus.end);}
 $('.detail-body').scrollTop = scroll;
 if($('#add-files')) $('#add-files').onclick = () => $('#flow-files').click();
 if($('#download-inline-template')) $('#download-inline-template').onclick = () => download(n.context_template,`${n.id}.template.json`);
 if(typeof bindContextRevision === 'function') bindContextRevision(n);
 if(typeof bindContextStages === 'function') bindContextStages(n);
 if(typeof bindExecutionFeedback === 'function') bindExecutionFeedback(n);
 if(typeof bindClinicalDispatch === 'function') bindClinicalDispatch(n);
 if(typeof bindRoutingOutputEntry === 'function') bindRoutingOutputEntry();
 if(typeof bindAnimalPkEntry === 'function') bindAnimalPkEntry();
 if(typeof bindCoverageGaps === 'function') bindCoverageGaps();
 if($('#open-pk-control-footer'))$('#open-pk-control-footer').onclick=()=>openAnimalPk();
 if($('#run-step'))$('#run-step').onclick = () => mutate(`${sessionPath()}/nodes/${selected}/start`,{},'Step started; human review follows completion.');
 if($('#review-form')) {
  const form = $('#review-form'), decision = form.elements.decision, comment = form.elements.rationale;
  const updateCommentRequirement = () => {
   const required = decision.value !== 'APPROVE';
   comment.required = required;
   if(required) comment.minLength = 5; else comment.removeAttribute('minlength');
   $('#review-comment-label').textContent = required ? 'Specific reason (required)' : 'Additional comments (optional)';
   comment.placeholder = required ? 'Explain the changes or rejection (at least 5 characters)' : 'No comment needed to approve';
  };
  decision.onchange = updateCommentRequirement;
  updateCommentRequirement();
  if(typeof bindObjectiveCheck === 'function') bindObjectiveCheck(form);
 }
 if($('#review-form')) $('#review-form').onsubmit = e => {
  e.preventDefault(); const f = new FormData(e.currentTarget);
  mutate(`${sessionPath()}/nodes/${selected}/review`,{decision:f.get('decision'),reviewer:f.get('reviewer'),rationale:f.get('rationale'),confirmed:f.get('confirmed') === 'on',output_signature:n.state.output_signature,...(typeof objectivePayload === 'function' ? objectivePayload(e.currentTarget) : {})},'Review decision recorded.');
 };
 if($('#clinical-form')) $('#clinical-form').onsubmit = e => {
  e.preventDefault(); const f = new FormData(e.currentTarget);
  mutate(`${sessionPath()}/clinical-questions`,{values:Object.fromEntries(flow.clinical_fields.map(item => [item.key,f.get(item.key)])),reviewer:f.get('reviewer'),confirmed:f.get('confirmed') === 'on',index_exposure_source:f.get('index_exposure_source'),draft_signature:n.state.clinical_draft?.signature || null},'Task definitions saved; assignment still requires review.');
 };
 if($('#cycle-form')) $('#cycle-form').onsubmit = async e => {
  e.preventDefault(); if(busy) return; const f = new FormData(e.currentTarget), target = e.currentTarget.elements.change_type.selectedOptions[0].dataset.target; busy = true; render();
  try {
   const result = await json(`${sessionPath()}/cycles`,{method:'POST',body:JSON.stringify({target,source_node:f.get('source_node'),change_type:f.get('change_type'),reason:f.get('reason'),requested_changes:f.get('requested_changes'),reviewer:f.get('reviewer'),confirmed:f.get('confirmed') === 'on'})});
   modal('Next cycle created',`<p>The study revision is recorded with its evidence references. Start by registering the revised proposal or added data. The requested target describes what to revisit; it does not bypass input verification or review.</p><pre>${esc(JSON.stringify(result.request,null,2))}</pre><div class="modal-actions"><button id="download-cycle" class="button secondary">Download feedback JSON</button><a class="button primary" href="/?flow=${encodeURIComponent(result.new_session.session_id)}${route(result.request.entry_stage || 'intake','input')}">Open next cycle</a></div>`,'CLINICAL FEEDBACK');
   $('#download-cycle').onclick = () => download(result.request,'next_cycle_request.json'); await refresh();
  } catch(error) {toast(error.message);} finally {busy = false; render();}
 };
 if($('#publish-report')) $('#publish-report').onclick = async () => {
  if(busy) return; busy = true; render();
  try {const response = await api(`${sessionPath()}/publish`,{method:'POST'}); download(await response.blob(),'report_and_audit.zip'); toast('Local research report and audit archive created.'); await refresh();}
  catch(error) {toast(error.message);} finally {busy = false; render();}
 };
 updateClocks();
}
function renderList() {
 if(page === 'supplements') renderSupplements();
 if(page === 'module') renderModuleWorkspace();
}
function render() {
 renderGraph(); renderInspector(); renderList(); renderNav();
 if(typeof notifyModelHeartbeats === 'function') notifyModelHeartbeats();
 $('#file-count').textContent = `${flow.stats.files} file${flow.stats.files === 1 ? '' : 's'}${flow.supplements?.length ? ' · '+flow.supplements.length+' data branches' : ''}`; $('#completion-count').textContent = `${flow.stats.approved} of ${flow.nodes.length} steps approved`;
 $('#mode-label').textContent = flow.session_id ? (flow.parent_cycle ? 'Follow-up cycle' : 'Current run') : 'No run yet';
 $('#no-run').hidden = !!flow.session_id;
 const active = flow.nodes.some(n => ['RUNNING','PAUSING'].includes(n.state.execution)) || (flow.supplements || []).some(b=>['RUNNING','PAUSING'].includes(b.status)), complete = flow.stats.approved === flow.nodes.length;
 $('#run-state').className = 'run-state tone-' + statusTone(flow.control_status === 'PAUSING' ? 'Pausing' : flow.control_status === 'PAUSED' ? 'Paused' : active ? 'Running' : flow.nodes.some(n=>n.state.execution==='FAILED') ? 'Failed' : flow.nodes.some(n=>['REVISION_REQUIRED','NEEDS_ATTENTION','STALE'].includes(n.state.execution)) || flow.nodes.some(n=>n.state.execution==='COMPLETED'&&!n.state.approved) ? 'Awaiting review' : complete ? 'Approved' : '');
 $('#run-state').innerHTML = `<i></i>${flow.control_status === 'PAUSING' ? 'Pausing' : flow.control_status === 'PAUSED' ? 'Paused' : complete ? 'Review complete' : active ? 'Step running' : flow.nodes.some(n=>n.state.execution==='REVISION_REQUIRED') ? 'Revision required' : flow.nodes.some(n=>n.state.execution==='FAILED') ? 'Execution stopped' : flow.stats.completed ? 'Awaiting human review' : flow.supplements?.some(b=>['BLOCKED','FAILED','STALE'].includes(b.status)) ? 'Supplemental data need attention' : flow.supplements?.some(b=>b.status==='WAITING_FOR_REVIEW') ? 'Supplemental review pending' : flow.supplements?.length ? 'Supplemental data available' : 'Not started'}`;
 $('#pause-flow').disabled = busy || (!flow.can_pause && !flow.can_continue);
 $('#pause-flow').innerHTML = `${icon(flow.can_continue ? 'play' : 'pause')}<span>${flow.can_continue ? 'Resume' : flow.control_status === 'PAUSING' ? 'Pausing…' : 'Pause'}</span>`;
 $('#create-flow').disabled = busy; $('#create-flow span:last-child').textContent = flow.session_id ? 'New blank run' : 'Create blank run';
 updateClocks(); clearTimeout(pollTimer); if(active || flow.control_status === 'PAUSING') pollTimer = setTimeout(refresh,1500);
}
// Pages: canvas (the workflow), module (a stage and its steps), step (one executable step),
// eda-gallery and supplements. Only one is shown at a time.
function changePage(next) {
 page = next; document.body.dataset.screen = page;
 $('#canvas-panel').hidden = page !== 'canvas';
 $('#inspector').hidden = page !== 'step';
 $('#list-panel').hidden = !['module','eda-gallery','supplements'].includes(page);
 if(flow) {renderGraph(); renderList(); renderNav();}
}
function hashChanged() {
 const query=new URLSearchParams(location.hash.slice(1)), view=query.get('view');
 selected=getNode(query.get('node'))?query.get('node'):selected||'intake';
 tab=tabs[query.get('tab')]?query.get('tab'):'input';
 if(view==='module')changePage('module');
 else if(view==='supplements')changePage('supplements');
 else if(query.has('node'))changePage('step');
 else changePage('canvas');
 if(flow){renderInspector();}
 // A new place starts at the top; switching tabs within a step keeps the position.
 const place=[page,query.get('node'),query.get('module')].join(':');
 if(place!==lastPlace){window.scrollTo(0,0);lastPlace=place;}
}
async function refresh() {try {flow = await json(sessionPath()); receivedAt = performance.now(); render();} catch(error) {toast(error.message); clearTimeout(pollTimer);}}
async function mutate(url, payload, message) {
 if(busy) return; busy = true; render();
 try {flow = await json(url,{method:'POST',body:JSON.stringify(payload)}); receivedAt = performance.now(); toast(message);}
 catch(error) {toast(error.message);}
 finally {busy = false; render();}
}
async function initialize() {
 try {
  if(!englishFragments.length) {
   englishStrings = await (await fetch('/assets/strings.en.json')).json();
   englishFragments = Object.entries(englishStrings).filter(([key])=>key.length>1).sort((a,b)=>b[0].length-a[0].length);
  }
  const id = new URLSearchParams(location.search).get('flow');
  flow = await json(id ? `/ui-api/workflow/sessions/${encodeURIComponent(id)}` : '/ui-api/workflow/template');
  receivedAt = performance.now();
  hashChanged(); render();
 } catch(error) {$('#diagram').innerHTML = emptyBox('Cannot load the workflow',error.message,'info'); toast(error.message);}
}
icons();
document.addEventListener('click', e => {
 const contractFile = e.target.closest('[data-contract-file]'); if(contractFile) {
  e.preventDefault(); const n = getNode(selected), f = n.output_contract[Number(contractFile.dataset.contractFile)];
  modal(f.name,`<p>${kindBadge(f.kind)} · planned file, not an actual data download</p><p>${esc(f.description)}</p><p>Receiving steps: ${f.to.length ? f.to.map(id => esc(getNode(id).title)).join(' / ') : 'Final archive'}</p><p>${f.kind === 'context' ? 'JSON holds this step\'s task, definitions, rules, and verifiable file references.' : 'Attachments carry the actual data/evidence separately from context. Preview or download generated artifacts under Actual files.'}</p><pre>${esc(JSON.stringify(f,null,2))}</pre>`,'FILE CONTRACT'); return;
 }
 const template = e.target.closest('[data-template]'); if(template) {e.preventDefault(); showTemplate(template.dataset.template); return;}
 const artifact = e.target.closest('[data-artifact]'); if(artifact) {e.preventDefault(); showArtifact(artifact.dataset.artifactNode || selected,artifact.dataset.artifact,artifact.dataset.artifactMode || 'preview'); return;}
 const button = e.target.closest('[data-tab]'); if(button) {location.hash = route(selected,button.dataset.tab); return;}
 const pageButton = e.target.closest('[data-page]'); if(pageButton) {const hash='#view='+pageButton.dataset.page;if(location.hash===hash)hashChanged();else location.hash=hash;return;}
 const nodeAnchor = e.target.closest('a[href^="#node="]'); if(nodeAnchor && location.hash === nodeAnchor.getAttribute('href')) hashChanged();
});
window.addEventListener('hashchange',hashChanged);
$('#close-modal').onclick = () => $('#modal').close();
$('#modal').onclick = e => {if(e.target === $('#modal')) {const r = $('#modal').getBoundingClientRect(); if(e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) $('#modal').close();}};
$('#pause-flow').onclick = () => {if(flow?.session_id) mutate(`${sessionPath()}/${flow.can_continue ? 'continue' : 'pause'}`,{},flow.can_continue ? 'Resumed; unfinished blocks will rerun.' : 'Pause requested; wait for executor confirmation.');};
$('#create-flow').onclick = $('#no-run-create').onclick = async () => {
 if(busy) return; busy = true; $('#create-flow').disabled = true;
 try {flow = await json('/ui-api/workflow/sessions',{method:'POST'}); receivedAt = performance.now(); const url = new URL(location.href); url.searchParams.set('flow',flow.session_id); url.hash = route('intake'); history.pushState(null,'',url); selected = 'intake'; tab = 'input'; changePage('step'); toast('Blank run created. Add the proposal and data files.');}
 catch(error) {toast(error.message);} finally {busy = false; if(flow) render(); else $('#create-flow').disabled = false;}
};
window.addEventListener('popstate',initialize);
$('#flow-files').onchange = async e => {
 const files = [...e.target.files]; if(!files.length || !flow.session_id || busy) return;
 busy = true; render();
 try {
  const ids = flow.uploads.map(f => f.upload_id);
  for(const file of files) {const body = new FormData(); body.append('file',file); const result = await json('/pipeline/v1/attachments',{method:'POST',body}); ids.push(result.upload_id);}
  flow = await json(`${sessionPath()}/files`,{method:'POST',body:JSON.stringify({upload_ids:ids})}); toast('Files registered; file intake can run.');
 } catch(error) {toast(error.message);} finally {busy = false; e.target.value = ''; render();}
};
$('#settings').onclick = () => {
 modal('Local connection', '<p>This workbench connects to local executors through a same-origin API. Computation starts only when you select Run this step.</p><label>Workbench access token (only if configured on the server)<input id="api-token" class="settings-input" type="password" autocomplete="off"></label><p>This is the local service token, managed separately from model credentials.</p><div class="modal-actions"><button id="save-token" class="button primary">Save connection</button></div>','LOCAL CONNECTION');
 $('#api-token').value = sessionStorage.getItem('pmb-token') || '';
 $('#save-token').onclick = () => {sessionStorage.setItem('pmb-token',$('#api-token').value.trim()); $('#modal').close(); initialize();};
};
initialize();
