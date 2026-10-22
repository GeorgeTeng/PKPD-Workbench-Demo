/* Human gates added by the backend: IN001 source-coverage gaps at File intake and the
   CC004 objective judgment at Context review. Neither decision claims scientific acceptance. */
const objectiveChoices = [
 ['CONFIRMED','Correct','The compressed objective matches the proposal.'],
 ['CORRECTED','Correct it','Write the right objective. It is recorded as your scope change; the original main.json is kept.'],
 ['INCORRECT','Wrong','The objective is wrong. Compression must be revised.'],
 ['OFF_SCOPE','Off target','The objective drifts from the project. Compression must be revised.'],
 ['MISSING','Missing','There is no usable objective.']
];
const objectiveLabel = value => objectiveChoices.find(c=>c[0]===value)?.[1] || value;

function renderObjectiveCheck(n) {
 if(n.id !== 'context') return '';
 const review = n.state.objective_review || {}, canCorrect = review.correction_available !== false;
 const objective = review.objective
  ? `<blockquote class="objective-text">${esc(review.objective)}</blockquote>`
  : '<p class="help-note">Open main.json under Outputs and read its objective before judging it.</p>';
 const options = objectiveChoices.map(([value,label,help],i)=>{
  const off = value === 'CORRECTED' && !canCorrect;
  return `<label class="objective-option${off ? ' is-disabled' : ''}"><input type="radio" name="objective_decision" value="${value}" ${i === 0 ? 'required' : ''} ${off ? 'disabled' : ''}><span><strong>${label}</strong><small>${off ? 'Not available: project rules were already published for this objective. Choose Wrong and write the correct objective in your reason, then rerun with a corrected proposal.' : help}</small></span></label>`;
 }).join('');
 return `<fieldset class="objective-check"><legend>Is the overall objective right?</legend><p class="objective-hint">Judge the compressed objective against the proposal. Only <strong>Correct</strong> or <strong>Correct it</strong> can be approved.</p>${objective}<div class="objective-options">${options}</div><label id="objective-correction-field" hidden>Correct objective<textarea name="objective_correction" maxlength="10000" placeholder="The full research objective as it should read"></textarea></label></fieldset>`;
}

// Keeps the decision consistent with the objective judgment, as the backend requires.
function bindObjectiveCheck(form) {
 const fieldset = form.querySelector('.objective-check');
 if(!fieldset) return;
 const decision = form.elements.decision, correction = form.elements.objective_correction, field = $('#objective-correction-field');
 const sync = () => {
  const choice = form.elements.objective_decision.value, corrected = choice === 'CORRECTED', negative = ['INCORRECT','OFF_SCOPE','MISSING'].includes(choice);
  field.hidden = !corrected; correction.required = corrected;
  if(corrected) correction.minLength = 5; else correction.removeAttribute('minlength');
  [...decision.options].forEach(o=>{o.disabled = (corrected && o.value !== 'APPROVE') || (negative && o.value === 'APPROVE');});
  if(corrected) decision.value = 'APPROVE';
  if(negative && decision.value === 'APPROVE') decision.value = 'REQUEST_CHANGES';
  decision.dispatchEvent(new Event('change'));
  if(corrected) {
   form.elements.rationale.required = true; form.elements.rationale.minLength = 5;
   $('#review-comment-label').textContent = 'Reason for the correction (required)';
   form.elements.rationale.placeholder = 'Why the compressed objective needed correcting (at least 5 characters)';
  }
 };
 fieldset.addEventListener('change', sync);
 if(form.elements.objective_decision.value) sync();  // A choice kept across a refresh.
}
function objectivePayload(form) {
 if(!form.querySelector('.objective-check')) return {};
 const choice = form.elements.objective_decision.value;
 return {objective_decision: choice, ...(choice === 'CORRECTED' ? {objective_correction: form.elements.objective_correction.value} : {})};
}
function objectiveRecord(record) {
 if(!record?.objective_decision) return '';
 return `Objective: ${esc(objectiveLabel(record.objective_decision))}${record.objective_correction ? ` · corrected to “${esc(record.objective_correction)}”` : ''}<br>`;
}

function renderCoverageGaps(n) {
 const c = n.state.coverage;
 if(n.id !== 'intake' || !c?.gaps?.length) return '';
 const open = new Set(c.unresolved_gap_ids || []), done = Object.fromEntries((c.resolutions || []).map(r=>[r.gap_id,r]));
 const editable = open.size > 0 && !!flow.session_id && flow.control_status === 'READY';
 const gaps = c.gaps.map(g=>{
  const r = done[g.id];
  return `<label class="gap-item${r ? ' is-resolved' : ''}"><input type="checkbox" name="gap_ids" value="${esc(g.id)}" ${r ? 'checked disabled' : ''} ${!editable ? 'disabled' : ''}><span class="gap-body"><span class="gap-title"><strong>${esc(g.label)}</strong><span class="gap-count" title="Occurrences found">${g.count}</span></span><span class="gap-where">${esc(g.original_name)} · ${esc(g.locations.slice(0,6).join('; '))}${g.locations.length > 6 ? ` and ${g.locations.length - 6} more` : ''}</span>${r ? `<span class="gap-resolution">${icon('check')}Confirmed irrelevant by ${esc(r.reviewer)} · ${esc(new Date(r.at).toLocaleString('en-GB'))}<br>${esc(r.reason)}</span>` : `<span class="gap-action">${esc(g.required_action)}</span>`}</span></label>`;
 }).join('');
 const limits = (c.limitations || []).length ? `<details class="gap-limits"><summary>What this check cannot detect</summary><ul>${c.limitations.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></details>` : '';
 if(!open.size) return `<section class="coverage-review is-done"><div class="section-label">Source coverage check · IN001</div><h3>All flagged content was reviewed</h3><p>Each item below was confirmed irrelevant to this task. Its content was not extracted.</p><div class="gap-list">${gaps}</div>${limits}</section>`;
 return `<section class="coverage-review"><div class="section-label">Source coverage check · IN001</div><h3>Some source content may not have been read</h3><p>Text extraction can miss scanned pages, images, equations, text boxes and notes. Context compression stays locked until every item below is confirmed irrelevant to this task, or you start a new run with a readable version of the file.</p><form id="coverage-form" class="review-form"><div class="gap-list-head"><span>${open.size} of ${c.gaps.length} item${c.gaps.length === 1 ? '' : 's'} need a decision</span>${open.size > 1 && editable ? '<button type="button" class="text-button" id="select-all-gaps">Select all</button>' : ''}</div><div class="gap-list">${gaps}</div><label>Reviewer<input name="reviewer" required maxlength="100" autocomplete="name" ${!editable ? 'disabled' : ''}></label><label>Why are the selected items irrelevant to this task?<textarea name="reason" required minlength="5" maxlength="10000" placeholder="For example: the figure repeats the table on page 3; the scanned page is the cover sheet" ${!editable ? 'disabled' : ''}></textarea></label><label class="confirm-label"><input type="checkbox" name="confirmed" required ${!editable ? 'disabled' : ''}>I checked the selected items in the original files. This records that they are irrelevant to this task; it does not mean their content was extracted.</label><button class="button primary" type="submit" ${!editable || busy ? 'disabled' : ''}>Confirm selected as irrelevant</button></form><p class="help-note">If an item matters, create a new blank run and upload a readable version instead, for example typed equations, table values or checked OCR text.</p>${limits}</section>`;
}
function bindCoverageGaps() {
 const form = $('#coverage-form');
 if(!form) return;
 if($('#select-all-gaps')) $('#select-all-gaps').onclick = () => form.querySelectorAll('input[name="gap_ids"]:not(:disabled)').forEach(x=>{x.checked = true;});
 form.onsubmit = e => {
  e.preventDefault();
  const f = new FormData(form), ids = f.getAll('gap_ids');
  if(!ids.length) {toast('Select at least one item.'); return;}
  mutate(`${sessionPath()}/nodes/intake/coverage-resolutions`,{gap_ids:ids,decision:'IRRELEVANT_TO_TASK',reviewer:f.get('reviewer'),reason:f.get('reason'),confirmed:f.get('confirmed') === 'on'},`${ids.length} item${ids.length === 1 ? '' : 's'} recorded as irrelevant.`);
 };
}
