/* Semantic revision is distinct from approving a scientific handoff. */
function renderMissingInformation(n) {
 const report = n.state.missing_information_review;
 if(n.id !== 'context' || !report) return '';
 const warnings = report.warnings || [];
 return `<section class="context-feedback"><div class="section-label">Missing-information review · ${warnings.length} unresolved</div><p>Compression may pass when missing information is reported faithfully. These findings identify what the relevant downstream task still needs.</p><button class="text-button" id="download-missing-information">Download search and warning JSON</button>${warnings.map(w=>`<article class="field-card"><strong>${esc(w.id)} · ${esc(w.field)}</strong><p>${esc(w.status)} · Needed at: ${esc(w.needed_at)}</p><h4>Why it matters</h4><p>${esc(w.importance_reason)}</p><h4>Downstream impact</h4><p>${esc(w.downstream_impact)}</p><h4>What to provide or clarify</h4><p>${esc(w.requested_information)}</p><p>${esc(w.reason)}</p><details><summary>Searched files and locations</summary><pre class="json-preview">${esc(JSON.stringify(w.search,null,2))}</pre></details></article>`).join('')}${!warnings.length ? '<p>No material gap was identified by this review. This is not proof that the data are complete or analysis-ready.</p>' : ''}</section>`;
}
function renderContextFeedback(n) {
 const f = n.state.context_feedback;
 if(!f) return typeof renderExecutionFeedback === 'function' ? renderExecutionFeedback(n) : '';
 return `<section class="context-feedback"><div class="section-label">Revision required · ${esc(f.stage)}</div><p>${esc(f.summary)}</p><div class="template-actions"><button class="button primary" id="revise-context" ${!n.state.can_revise_context || busy ? 'disabled' : ''}>Revise and rerun</button><button class="text-button" id="download-context-feedback">Download feedback JSON</button></div>${f.issues.map(issue=>`<article class="field-card"><strong>${esc(issue.id)} · ${esc(issue.title)}</strong><p>${esc(issue.requirement_ids.join(' · '))}</p><h4>Why this cannot pass</h4><p>${esc(issue.reason)}</p><h4>What to change</h4><p>${esc(issue.what_to_change)}</p>${issue.source_evidence.length ? `<details><summary>Proposal evidence (${issue.source_evidence.length} excerpts)</summary>${issue.source_evidence.map(e=>`<blockquote><p>${esc(e.quote)}</p><small>${esc(e.source_id)} · ${esc(e.unit_id)}</small></blockquote>`).join('')}</details>` : ''}</article>`).join('')}<details><summary>Affected source sections</summary><pre class="json-preview">${esc(JSON.stringify(f.source_units,null,2))}</pre></details><p class="help-note">The proposal remains the scientific source. Repair extraction to restore omissions and explicitly retain ambiguities. Upload a revised proposal to change scientific requirements. Downstream steps remain locked.</p>${flow.context_revision_child ? `<p><a href="/?flow=${encodeURIComponent(flow.context_revision_child)}#node=context&tab=context">Open the submitted revision ↗</a></p>` : ''}<details><summary>Technical log</summary><pre class="json-preview">${esc(n.state.technical_error || 'Full execution logs are retained in the job audit.')}</pre></details></section>`;
}
function bindContextRevision(n) {
 if($('#download-missing-information')) $('#download-missing-information').onclick=()=>download(n.state.missing_information_review,'missing_information_review.json');
 if($('#download-context-feedback')) $('#download-context-feedback').onclick=()=>download(n.state.context_feedback,'context_revision_feedback.json');
 if($('#revise-context')) $('#revise-context').onclick=()=>openContextRevision(n);
}
function openContextRevision(n) {
 const feedback = n.state.context_feedback, endpoint = sessionPath() + '/context-revisions';
 modal('Revise context and rerun',`<p>Earlier results are retained and nothing is approved. Repairing extraction continues this run: accepted steps, including the attachment evidence, are reused and the reviewed step is redone with the review and your guidance. A revised proposal starts a new run with the same attachments.</p><form id="context-revision-form" class="review-form"><label>Revision mode<select name="mode"><option value="REPAIR_EXTRACTION">Repair extraction from review feedback</option><option value="REPLACE_PROPOSAL">Upload a revised proposal</option></select></label><p id="revision-mode-help">Keeps the original proposal. Restores omitted requirements and retains unresolved conflicts; it does not decide scientific permissions.</p><div id="replacement-proposal" hidden><input type="file" name="proposal" class="supplement-file-input" accept=".docx,.pdf,.md,.txt"><button type="button" id="choose-revision-proposal" class="button secondary">Choose revised proposal</button><p id="revision-proposal-name">No revised proposal selected</p></div><label>Extraction guidance (optional)<textarea name="guidance" maxlength="20000" rows="5" placeholder="Explain what to restore or check. To add or change scientific requirements, put them in the revised proposal."></textarea></label><label>Submitted by<input name="submitted_by" required maxlength="100" autocomplete="name"></label><label class="confirm-label"><input type="checkbox" name="confirmed" required>I have reviewed the findings. Rerun context; keep existing results and scientific review gates.</label><div id="revision-submit-error" class="error-box" hidden></div><button class="button primary" type="submit">Submit revision and run</button></form>`,'CONTEXT REVISION');
 const form = $('#context-revision-form');
 form.elements.mode.onchange=()=>{
  const replace=form.elements.mode.value==='REPLACE_PROPOSAL';
  $('#replacement-proposal').hidden=!replace; form.elements.proposal.required=replace;
  $('#revision-mode-help').textContent=replace ? 'Revise the conflicting or missing scientific requirements in your proposal. Other attachments are carried over unchanged.' : 'Keeps the original proposal. Restores omitted requirements and retains unresolved conflicts; it does not decide scientific permissions.';
 };
 $('#choose-revision-proposal').onclick=()=>form.elements.proposal.click();
 form.elements.proposal.onchange=()=>$('#revision-proposal-name').textContent=form.elements.proposal.files[0]?.name || 'No revised proposal selected';
 form.onsubmit=async event=>{
  event.preventDefault(); if(busy) return;
  busy=true; const button=form.querySelector('[type=submit]'); button.disabled=true; $('#revision-submit-error').hidden=true;
  try {
   const data=new FormData(form), mode=data.get('mode'), previous=flow.session_id; let uploadId=null;
   if(mode==='REPLACE_PROPOSAL') {const body=new FormData(); body.append('file',form.elements.proposal.files[0]); uploadId=(await json('/pipeline/v1/attachments',{method:'POST',body})).upload_id;}
   const next=await json(endpoint,{method:'POST',body:JSON.stringify({mode,proposal_upload_id:uploadId,feedback_signature:feedback.signature,guidance:data.get('guidance'),submitted_by:data.get('submitted_by'),confirmed:data.get('confirmed')==='on'})});
   flow=next; receivedAt=performance.now(); selected='context'; tab='context';
   const url=new URL(location.href); url.searchParams.set('flow',next.session_id); url.hash=route('context','context'); history.pushState(null,'',url);
   $('#modal').close(); toast(next.session_id===previous ? 'Context continues in this run with the review and your guidance. Earlier results and review gates are retained.'
    : 'New context attempt started. Original results and review gates are retained.');
  } catch(error) {$('#revision-submit-error').textContent=error.message; $('#revision-submit-error').hidden=false;}
  finally {busy=false; button.disabled=false; render();}
 };
}
