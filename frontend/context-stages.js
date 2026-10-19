// Context steps of the current run: which are done, reused from an earlier job, stopped or waiting, and
// a button to run one again (that step and every later one) without starting the whole context over.
const contextStageNames = {attachment_plan:'Plan attachment reading', attachment_evidence:'Read attachments',
 requirements:'Extract requirements', requirements_review:'Review requirements', context:'Build context', context_review:'Review context'};
let contextStages = {key:'', sid:'', data:null, at:0, loading:false};

function contextStagesKey(n) {return `${flow.session_id}:${n.state.execution}`;}
async function loadContextStages(n) {
 const key = contextStagesKey(n);
 if(contextStages.loading) return;
 contextStages.loading = true;
 try {
  const data = await json(sessionPath() + '/context-stages'), changed = JSON.stringify(data) !== JSON.stringify(contextStages.data);
  contextStages = {key, sid:flow.session_id, data, at:performance.now(), loading:false};
  if(changed && selected === 'context') render();
 } catch(error) {contextStages = {key, sid:flow.session_id, data:null, at:performance.now(), loading:false};}
}
function contextStageRow(row, running, data) {
 const label = running ? ['active','Running'] : {ACCEPTED:['done','Done'], REUSED:['done','Reused'], PENDING:['planned','Waiting'],
  STOPPED:row.stopped_status === 'REVISE' ? ['attention','Revision required'] : ['danger','Stopped']}[row.status];
 const note = row.status === 'REUSED' ? `Answer reused from an earlier job with the same inputs and model; all checks ran again. ${row.reused_from || ''}`
  : row.status === 'STOPPED' ? String(row.reason || '').slice(0, 300) : '';
 const rerunnable = !running && row.status !== 'PENDING';
 return `<li class="context-stage"><div><strong>${esc(contextStageNames[row.stage] || row.stage)}</strong>${note ? `<small>${esc(note)}</small>` : ''}</div><span class="chip tone-${label[0]}">${label[1]}</span>${rerunnable ? `<button class="text-button" data-rerun-stage="${esc(row.stage)}" ${!data.can_rerun || busy ? 'disabled' : ''} title="${esc(data.can_rerun ? 'Run this step and every later step again' : data.rerun_blocker || '')}">Run again from here</button>` : '<span></span>'}</li>`;
}
function renderContextStages(n) {
 if(n.id !== 'context' || !flow.session_id) return '';
 const fresh = contextStages.key === contextStagesKey(n), age = performance.now() - contextStages.at;
 if(!fresh || age > (n.state.execution === 'RUNNING' ? 4000 : 30000)) loadContextStages(n);
 const data = contextStages.sid === flow.session_id ? contextStages.data : null;
 if(!data) return '';
 const firstOpen = n.state.execution === 'RUNNING' ? data.stages.findIndex(r => !['ACCEPTED','REUSED'].includes(r.status)) : -1;
 const open = ['FAILED','REVISION_REQUIRED','NEEDS_ATTENTION'].includes(n.state.execution) ? 'open' : '';
 return `<details class="feedback-disclosure context-stages" data-preserve-details="context-stages" ${open}><summary>${icon('info')}Context steps<span>Expand</span></summary><ol class="context-stage-list">${data.stages.map((row,i) => contextStageRow(row, i === firstOpen, data)).join('')}</ol>${!data.can_rerun && data.rerun_blocker ? `<p class="help-note">${esc(data.rerun_blocker)}</p>` : ''}<p class="help-note">Steps already accepted in an earlier job with identical inputs and the same model are reused instead of calling the model again. Running a step again always makes a fresh model call.</p></details>`;
}
function bindContextStages(n) {
 $$('[data-rerun-stage]', $('#inspector')).forEach(button => button.onclick = () => openStageRerun(button.dataset.rerunStage));
}
function openStageRerun(stage) {
 const name = contextStageNames[stage] || stage;
 modal(`Run again from “${name}”`, `<p>“${esc(name)}” and every later context step run again in this run with a fresh model call. Earlier accepted steps are kept. Earlier answers stay in the audit, and nothing is approved.</p><form id="stage-rerun-form" class="review-form"><label>Submitted by<input name="submitted_by" maxlength="100" autocomplete="name" placeholder="Workbench user"></label><label class="confirm-label"><input type="checkbox" name="confirmed" required>Run “${esc(name)}” and the later steps again.</label><div id="stage-rerun-error" class="error-box" hidden></div><button class="button primary" type="submit">Run again</button></form>`, 'CONTEXT STEP');
 const form = $('#stage-rerun-form');
 form.onsubmit = async event => {
  event.preventDefault(); if(busy) return;
  busy = true; const button = form.querySelector('[type=submit]'); button.disabled = true; $('#stage-rerun-error').hidden = true;
  try {
   flow = await json(`${sessionPath()}/context-stages/${encodeURIComponent(stage)}/rerun`, {method:'POST',
    body:JSON.stringify({submitted_by:form.elements.submitted_by.value.trim() || 'Workbench user', confirmed:true})});
   receivedAt = performance.now(); selected = 'context'; contextStages = {key:'', sid:'', data:null, at:0, loading:false};
   $('#modal').close(); toast(`Running “${name}” again; earlier accepted steps are kept.`);
  } catch(error) {$('#stage-rerun-error').textContent = error.message; $('#stage-rerun-error').hidden = false;}
  finally {busy = false; button.disabled = false; render();}
 };
}
