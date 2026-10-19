'use strict';
// All mutations go through the existing API and its version-bound review gates.
const Live = {
  session: new URLSearchParams(location.search).get('flow') || localStorage.getItem('pkpd-live-session') || '',
  timer: null,
  progress(value) {
    const label=value.stage_label||value.stage||'Current operation';
    const phase=({AWAITING_MODEL_OUTPUT:'Waiting for model response',MODEL_OUTPUT_RECEIVED:'Model response received',RETURNED:'Response returned'})[value.phase]||value.phase||value.status;
    return `<p>${esc(label)} · ${esc(phase)}${Number.isFinite(value.elapsed_seconds)?' · '+Math.round(value.elapsed_seconds)+' s':''}</p><details><summary>Execution details</summary><pre>${esc(JSON.stringify(value,null,2))}</pre></details>`;
  },
  nodeMap: {intake:'intake', context_bundle:'context', data_bundle:'adequacy'},
  checkpoint(node, session) {
    if(node.id==='intake')return '';
    const n=node.state, review=n.review, automatic=review?.reviewer==='USER_AUTHORIZED_DEMO_ACCEPTANCE';
    const title=({context:'Human gate · Context compression & Rules',adequacy:'Human gate · Data scope',prepare:'Human gate · Completed Data'})[node.id];
    const status=review?(automatic?'Automatically approved for this demo':review.decision):n.can_review?'Awaiting human review':n.approved?'Technical validation recorded':'Waiting for completed outputs';
    return `<section class="live-checkpoint ${n.approved?'approved':''}"><div class="live-panel-heading"><h3>${esc(title)}</h3><span class="live-status">${esc(status)}</span></div><p>${esc(({context:'Inspect the compressed objective, source evidence and extracted key Rules before starting Data.',adequacy:'Confirm the assessed data scope and unresolved findings before preparation.',prepare:'Inspect cleaned tables, QC findings, omissions and the Data handoff before any later analysis.'})[node.id])}</p>${review?`<p><strong>Reviewer:</strong> ${esc(review.reviewer)} · ${esc(review.at)}</p><p>${esc(review.rationale)}</p><details><summary>Version-bound decision record</summary><pre>${esc(JSON.stringify(review,null,2))}</pre></details>`:''}${n.output_signature?`<p class="preview-help">Output signature: <code>${esc(n.output_signature.slice(0,16))}…</code></p>`:''}<div class="preview-actions"><button class="primary" data-review-node="${node.id}" ${n.can_review?'':'disabled'}>Review & record decision</button><a href="/workbench?flow=${encodeURIComponent(session)}#node=${node.id}&tab=review">Detailed review ↗</a></div></section>`;
  },
  reviewDialog(node, session, stage) {
    clearTimeout(Live.timer);
    const objective=node.state.objective_review?.objective;
    modal('Record human checkpoint',`<p>Review the current outputs. This decision applies to this exact step and output signature.</p>${objective?`<h3>Compressed objective</h3><p>${esc(typeof objective==='string'?objective:JSON.stringify(objective))}</p>`:''}<form id="checkpoint-form"><label class="preview-field">Reviewer<input name="reviewer" required maxlength="100"></label><label class="preview-field">Decision<select name="decision"><option value="APPROVE">Approve this step</option><option value="REQUEST_CHANGES">Request changes</option><option value="REJECT">Reject</option></select></label>${node.id==='context'?'<label class="preview-field">Compressed objective assessment<select name="objective_decision"><option value="CONFIRMED">Correct and in scope</option><option value="INCORRECT">Incorrect</option><option value="OFF_SCOPE">Off scope</option><option value="MISSING">Missing</option></select></label>':''}<label class="preview-field">Rationale<textarea name="rationale" required minlength="5"></textarea></label><label class="live-check"><input name="confirmed" type="checkbox" required> I reviewed these version-bound outputs.</label><button class="primary" type="submit">Save checkpoint decision</button><p id="checkpoint-result" role="status"></p></form>`,'HUMAN REVIEW');
    $('#checkpoint-form').onsubmit=async e=>{
      e.preventDefault();const values=Object.fromEntries(new FormData(e.target));
      await Live.action(e.target.querySelector('button'),async()=>{
        await json(`/ui-api/workflow/sessions/${encodeURIComponent(session)}/nodes/${node.id}/review`,{method:'POST',body:JSON.stringify({...values,confirmed:true,output_signature:node.state.output_signature})});
        $('#checkpoint-result').textContent='Decision saved against the exact output signature.';
        e.target.querySelector('button').hidden=true;
        await Live.refresh(stage);
      });
    };
  },
  async settings() {
    const value = await json('/workspace-api/capabilities');
    modal('Connected services', `<p>Live workflow execution ends at Data. Model calls use your local provider configuration.</p><pre>${esc(JSON.stringify(value,null,2))}</pre>`, 'BACKEND CAPABILITIES');
  },
  selectSession(id) {
    Live.session = id;
    localStorage.setItem('pkpd-live-session', id);
  },
  async latestRevision(id) {
    const visited=new Set();
    while(id && !visited.has(id) && visited.size<20) {
      visited.add(id);
      const run=await json('/ui-api/workflow/sessions/'+encodeURIComponent(id));
      if(!run.context_revision_child){Live.selectSession(id);previewNavigate();return;}
      id=run.context_revision_child;
    }
    throw Error('Revision history could not be resolved. Inspect the detailed workflow controls.');
  },
  async action(button, work) {
    button.disabled = true;
    const text = button.textContent;
    button.textContent = 'Working…';
    try { await work(); } catch(e) { toast(e.message); }
    finally { if(button.isConnected) { button.disabled=false; button.textContent=text; } }
  },
  async stage(id, part, active) {
    clearTimeout(Live.timer);
    if(active==='context' && ['context_bundle','data_bundle'].includes(id)) {
      const panel=$('.preview-tabs + .preview-panel');
      if(panel)panel.innerHTML='<h2>Agent-to-agent context</h2><p>Read the exact saved requests, model inputs, responses and source bindings for this run. This inspection never starts a model call.</p><div id="handoff-browser"></div>';
    }
    if(['intake','context_bundle','data_bundle'].includes(id))$('.preview-label').textContent='Live execution available · current status below';
    if(id==='data_bundle' && !part && active==='overview') {
      const grid=$('.preview-node-grid', $('#list-panel'));
      grid.insertAdjacentHTML('beforebegin','<div class="preview-note"><strong>Lightweight Data demo</strong><p>Inventory + requirements → source access → labels → technical input checks → Human scope gate → source-preserving preparation + program QC → completed-Data Human gate.</p><p>Requirements and scientific gaps remain visible for later EDA / PK review. This run does not establish model readiness.</p></div>');
    }
    if(id==='intake') {
      const contextTab=$('.preview-tabs a[href$="tab=context"]');
      if(contextTab)contextTab.textContent='File provenance';
      $$('.preview-actions a[href*="section=builder"]',$('#list-panel')).forEach(a=>a.remove());
      if(active==='context') {
        const panel=$('.preview-tabs + .preview-panel');
        if(panel)panel.innerHTML='<h2>File provenance</h2><p>File intake runs directly: register files → unpack → check readability and extraction coverage → bind source hashes. ContextBuilder, RAG, model calls and the scientific scheduler are not used.</p><p>The next Context stage consumes these exact registered files.</p>';
      }
      if(active==='inputs')$('.preview-tabs + .preview-grid').innerHTML='<div class="preview-panel"><h2>Original source files</h2><p>Import a proposal and source data ZIP. Keep the original filenames, document locations and source values.</p></div><div class="preview-panel"><h2>Registration & extraction</h2><p>Store the originals, verify readability and extraction coverage, and bind each file to its SHA-256. Scientific context is built in the next stage.</p></div>';
    }
    if(active==='outputs' && id!=='data_bundle') {
      const panel=$('.preview-tabs + .preview-panel');
      if(panel) {
        if(id==='intake')panel.innerHTML='<h2>File inventory & provenance</h2><p>The current run produces a file manifest, extraction coverage and immutable source bindings. Open its artifacts in the live panel above.</p>';
        else if(id==='context_bundle')panel.innerHTML='<h2>Context & Project Rules artifacts</h2><p>The current run retains compressed context, project Rules, review findings and request provenance. Open the version-bound artifacts in the live panel above.</p><a class="inline-link" href="/recorded/evidence/upstream_human_review/artifacts/main.json" target="_blank">Inspect the historical context snapshot ↗</a>';
        else if(['eda','pk'].includes(id)) {
          panel.innerHTML=`<h2>${id==='eda'?'Recorded EDA subset test':'Recorded PK diagnostic preview'}</h2><p>${id==='eda'?'These three figures belong to a previous EP / EC / EV subset test. EI and ER were not completed.':'These five figures are diagnostic demonstrations. They do not establish an accepted PK model.'} This demo does not execute this stage.</p><div class="recorded-gallery" id="recorded-gallery"></div>`;
          const figures=await json('/demo-api/gallery');
          if(!panel.isConnected)return;
          $('#recorded-gallery').innerHTML=figures.filter(f=>(f.kind==='EDA_TEST_VISUAL_FINDINGS')===(id==='eda')).map(f=>`<figure><a href="${esc(f.url)}" target="_blank"><img loading="lazy" src="${esc(f.url)}" alt="${esc(f.title)}"></a><figcaption>${esc(f.title)}</figcaption></figure>`).join('');
        } else panel.innerHTML='<h2>Planned output</h2><p>No current execution or accepted result is available for this stage. The workflow describes the intended process.</p>';
      }
    }
    if(active==='review' && id!=='data_bundle') {
      const panel=$('.preview-tabs + .preview-panel');
      if(panel)panel.innerHTML=`<h2>${id==='intake'?'Source coverage review':'Stage review'}</h2><p>${id==='intake'?'Check that the expected files are registered, readable and completely extracted. This technical checkpoint does not establish scientific adequacy.':id==='context_bundle'?'Review the compressed objective, source evidence, contradictions and project Rules before Data assessment. The live controls record a decision against the exact output signature.':'This stage has no live review action in the demo. Review criteria describe the intended workflow.'}</p>`;
    }
    if(!['intake','context_bundle','data_bundle'].includes(id)) {
      $('#list-panel').insertAdjacentHTML('afterbegin', '<div class="preview-note">Execution is not enabled for this stage in the current demo. Workflow steps describe the intended process; existing figures are recorded results.</div>');
      return;
    }
    const host=document.createElement('section');
    host.className='preview-panel live-panel'; host.id='live-run-panel';
    $('.preview-tabs', $('#list-panel')).after(host);
    host.innerHTML='<h2>Live workflow</h2><p>Loading backend status…</p>';
    const imports=(await json('/workspace-api/imports')).sort((a,b)=>b.created_at.localeCompare(a.created_at));
    Live.importIds=new Set(imports.map(item=>item.id));
    const revisions=await json('/workspace-api/workflow-runs');
    for(const run of revisions)if(!Live.importIds.has(run.id))imports.push({id:run.id,filename:'Workflow revision'});
    if(!host.isConnected) return;
    if(!Live.session && imports.length) Live.selectSession(imports[0].id);
    host.innerHTML=`<div class="live-panel-heading"><div><span class="preview-kicker">CURRENT EXECUTION</span><h2>Live workflow</h2></div><span class="live-status">Backend connected</span></div><label class="preview-field">Current run<select id="live-session"><option value="">Select an imported run</option>${imports.map(r=>`<option value="${esc(r.id)}" ${r.id===Live.session?'selected':''}>${esc(r.filename)} · ${esc(r.id.slice(-8))}</option>`).join('')}</select></label><div id="live-status-body"></div>${id==='intake'?'<div id="live-inputs"></div>':''}`;
    $('#live-session').onchange=async()=>{Live.selectSession($('#live-session').value);await Live.refresh(id);if(id==='intake')await Live.sourceTools();if($('#handoff-browser'))await Live.handoffs(id);};
    await Live.refresh(id);
    if($('#handoff-browser'))await Live.handoffs(id);
    if(id==='intake' && $('#live-inputs')) await Live.inputs();
    if(id==='data_bundle' && active==='review' && $('#live-review')) await Live.reviews();
  },
  async handoffs(stage) {
    const host=$('#handoff-browser');
    if(!host)return;
    if(!Live.session){host.innerHTML='<p>Select an imported run first.</p>';return;}
    const session=Live.session;
    host.innerHTML='<p>Loading recorded handoffs…</p>';
    const result=await json('/workspace-api/workflow/'+encodeURIComponent(session)+'/handoffs');
    if(!host.isConnected || session!==Live.session)return;
    const calls=result.calls.filter(c=>stage==='data_bundle'?['DR','DR-access','DC-label','DC-review','DP','DH-handoff'].includes(c.stage):!['DR','DR-access','DC-label','DC-review','DP','DH-handoff'].includes(c.stage));
    host.innerHTML=`<div class="handoff-controls"><label>Stage <select id="handoff-stage"><option value="">All stages</option>${[...new Set(calls.map(c=>c.stage))].map(s=>`<option>${esc(s)}</option>`).join('')}</select></label><label><input type="checkbox" id="handoff-history"> Include earlier attempts</label><button id="handoff-refresh">Refresh records</button></div><p class="preview-help">A recorded response is not scientific approval. Reused responses retain their original model identity. Current and earlier attempts remain separate.</p><div id="handoff-list"></div>`;
    const draw=()=>{
      const selected=$('#handoff-stage').value,history=$('#handoff-history').checked;
      const visible=calls.filter(c=>(!selected||c.stage===selected)&&(history||c.current_job));
      $('#handoff-list').innerHTML=visible.map(c=>`<details class="handoff-call"><summary><strong>${esc(c.stage)}</strong> · ${esc(c.receiver)} <span>${esc(c.status)}</span></summary><p>${esc(c.sender)} → ${esc(c.receiver)}</p><p>${esc(c.purpose)}</p><p class="preview-help">${esc(c.job_id)} · ${esc(c.requested_model||'See original receipt')}${c.elapsed_seconds!=null?' · '+c.elapsed_seconds+' s':''}</p><p class="preview-help">Request SHA-256: ${esc(c.request_sha256||'Recorded in request artifact')}</p><div class="preview-actions">${c.files.map(f=>`<a target="_blank" rel="noopener" href="${esc(f.url)}">${esc(f.name)} · ${(f.bytes/1024).toFixed(1)} KB ↗</a>`).join('')}</div></details>`).join('')||'<p>No model handoff was recorded in this selected scope. Deterministic steps use the stage output artifacts; enable earlier attempts to inspect retained model evidence.</p>';
    };
    $('#handoff-stage').onchange=draw;$('#handoff-history').onchange=draw;
    $('#handoff-refresh').onclick=()=>Live.handoffs(stage);draw();
  },
  async refresh(stage) {
    clearTimeout(Live.timer);
    const host=$('#live-status-body');
    if(!host) return;
    if(!Live.session) { host.innerHTML='<p>Import an example in File intake to create a new, source-bound run.</p>'; return; }
    try {
      const s=await json('/ui-api/workflow/sessions/'+encodeURIComponent(Live.session));
      if(!host.isConnected) return;
      const ids=stage==='data_bundle'?['adequacy','prepare']:[Live.nodeMap[stage]];
      const nodes=s.nodes.filter(n=>ids.includes(n.id));
      host.innerHTML=nodes.map(n=>`<div class="live-node"><div class="live-panel-heading"><h3>${esc(({intake:'File intake',context:'Context & Project Rules',adequacy:'Data assessment',prepare:'Data preparation & handoff'})[n.id])}</h3><span class="live-status">${esc(n.state.approved?'Approved for this step':n.state.execution)}</span></div><p>${esc(englishMessage(n.state.error||n.state.reason||''))}</p>${n.state.execution==='RUNNING'&&n.state.model_progress?Live.progress(n.state.model_progress):''}<div class="preview-actions">${n.state.can_run?`<button class="primary" data-start-node="${n.id}">Run ${n.id==='prepare'?'Data preparation':n.id}</button>`:''}<a href="/workbench?flow=${encodeURIComponent(s.session_id)}#node=${n.id}&tab=${n.state.can_review?'review':'files'}">${n.state.can_review?'Review this checkpoint':'Open detailed controls'} ↗</a></div>${n.state.artifacts?.length?'<details><summary>Current artifacts · '+n.state.artifacts.length+'</summary><ul>'+n.state.artifacts.map(a=>`<li><a target="_blank" class="inline-link" href="/ui-api/workflow/sessions/${encodeURIComponent(s.session_id)}/nodes/${n.id}/artifacts/${encodeURIComponent(a.name)}">${esc(a.name)}</a></li>`).join('')+'</ul></details>':''}</div>`).join('');
      $$('[data-start-node]',host).forEach(button=>button.onclick=()=>Live.action(button,async()=>{
        await json(`/ui-api/workflow/sessions/${encodeURIComponent(Live.session)}/nodes/${button.dataset.startNode}/start`,{method:'POST',body:'{}'});
        await Live.refresh(stage);
      }));
      for(const node of nodes) {
        const row=host.querySelectorAll('.live-node')[nodes.indexOf(node)];
        row.insertAdjacentHTML('beforeend',Live.checkpoint(node,s.session_id));
      }
      $$('[data-review-node]',host).forEach(button=>button.onclick=()=>Live.reviewDialog(nodes.find(n=>n.id===button.dataset.reviewNode),s.session_id,stage));
      if(s.context_revision_child) {
        host.insertAdjacentHTML('afterbegin','<div class="preview-note">A source-preserving revision follows this attempt. <button class="button secondary" id="open-latest-revision">Open latest revision →</button></div>');
        $('#open-latest-revision').onclick=e=>Live.action(e.target,()=>Live.latestRevision(s.context_revision_child));
      }
      if(s.nodes.some(n=>n.state.execution==='RUNNING')) Live.timer=setTimeout(()=>Live.refresh(stage),5000);
    } catch(e) { if(host.isConnected) host.innerHTML=`<p class="preview-note">${esc(e.message)}</p>`; }
  },
  async inputs() {
    const examples=await json('/workspace-api/examples'),host=$('#live-inputs');
    if(!host)return;
    host.innerHTML=`<h3>Start from the actual project inputs</h3><p>Each ZIP contains the proposal, source workbook and original AGENT_README. Import registers immutable originals and creates a workflow run.</p><div class="preview-node-grid">${examples.map(e=>`<div class="preview-node"><h3>${esc(e.title)}</h3><p>3 source files · ${(e.bytes/1024).toFixed(0)} KB</p><div class="preview-actions"><button data-import="${e.id}">Import example</button><a href="${e.url}" download>ZIP ↓</a></div></div>`).join('')}</div><form id="live-upload"><label class="preview-field">Or upload your own proposal + data ZIP<input type="file" accept=".zip" id="live-zip" required></label><button class="button secondary" type="submit">Upload & register</button></form><div class="preview-actions"><a href="/examples/acceptance/index.html" target="_blank">Accepted example runs ↗</a><a href="/examples/inputs/manifest.json" target="_blank">Package provenance & checksums ↗</a></div><div id="live-source-tools"></div>`;
    const imported=async value=>{Live.selectSession(value.id);previewNavigate();toast('Package registered. Run File intake to start the original workflow.');};
    $$('[data-import]',host).forEach(b=>b.onclick=()=>Live.action(b,async()=>imported(await json('/workspace-api/examples/'+b.dataset.import+'/import',{method:'POST',body:'{}'}))));
    $('#live-upload').onsubmit=async e=>{e.preventDefault();const form=new FormData();form.append('file',$('#live-zip').files[0]);await Live.action(e.target.querySelector('button'),async()=>imported(await json('/workspace-api/imports',{method:'POST',body:form})));};
    await Live.sourceTools();
  },
  async sourceTools() {
    const host=$('#live-source-tools');
    if(!host)return;
    if(!Live.session){host.innerHTML='';return;}
    if(!Live.importIds?.has(Live.session)){host.innerHTML='<p>This source-preserving revision reuses the registered originals. Inspect its current file artifacts in the live controls above.</p>';return;}
    const receipt=await json('/workspace-api/imports/'+encodeURIComponent(Live.session));
    if(!host.isConnected)return;
    host.innerHTML=`<details><summary>Source inspection tools · no model calls</summary><p>Inspect all registered files, then organize source tables. These tools preserve file identities and never grant data readiness.</p><div class="preview-actions"><button id="inspect-source">Inspect package</button>${receipt.manifest?'<button id="organize-source">Organize source tables</button>':''}</div>${receipt.manifest?`<p>${receipt.manifest.files.length} files · ${esc(receipt.status)} · scientific QC not run</p>`:''}${receipt.source_preparation?`<p>${receipt.source_preparation.tables.length} tables · ${esc(receipt.source_preparation.status)}</p><details><summary>Source preparation receipt</summary><pre>${esc(JSON.stringify(receipt.source_preparation,null,2))}</pre></details>`:''}</details>`;
    $('#inspect-source').onclick=e=>Live.action(e.target,async()=>{await json('/workspace-api/imports/'+Live.session+'/inspect',{method:'POST',body:'{}'});await Live.sourceTools();});
    if($('#organize-source'))$('#organize-source').onclick=e=>Live.action(e.target,async()=>{await json('/workspace-api/imports/'+Live.session+'/organize',{method:'POST',body:'{}'});await Live.sourceTools();});
  },
  async reviews() {
    const result=await json('/demo-api/findings'),notes=await json('/demo-api/reviews');
    const host=$('#live-review'); if(!host)return;
    host.innerHTML=`<h3>Recorded Data findings · add a review note</h3><p>Notes persist locally and bind to this report's SHA-256. Workflow gate decisions are recorded separately in the live controls above.</p><form id="review-form"><label class="preview-field">Finding<select id="review-finding">${result.findings.map((f,i)=>`<option value="${i}">${esc(f.code+' · '+f.affected_id+' · '+f.severity)}</option>`).join('')}</select></label><div id="finding-detail"></div><div class="preview-grid"><label class="preview-field">Reviewer<input id="reviewer" required maxlength="100"></label><label class="preview-field">Decision<select id="review-decision"><option value="NEEDS_SOURCE">Needs source evidence</option><option value="REQUEST_REVISION">Request revision</option><option value="ACKNOWLEDGE_LIMITATION">Acknowledge limitation</option></select></label></div><label class="preview-field">Rationale<textarea id="review-rationale" required minlength="5" maxlength="5000"></textarea></label><button class="button primary">Save review note</button></form><div class="preview-actions"><a href="/demo-api/reviews/export" download>Export notes ↓</a></div><p id="saved-note-count">${notes.length} saved notes</p>`;
    const detail=()=>$('#finding-detail').innerHTML='<pre>'+esc(JSON.stringify(result.findings[Number($('#review-finding').value)],null,2))+'</pre>';
    $('#review-finding').onchange=detail;detail();
    $('#review-form').onsubmit=e=>{e.preventDefault();Live.action(e.target.querySelector('button'),async()=>{const f=result.findings[Number($('#review-finding').value)];await json('/demo-api/reviews',{method:'POST',body:JSON.stringify({code:f.code,affected_id:f.affected_id,report_sha256:result.report_sha256,reviewer:$('#reviewer').value,decision:$('#review-decision').value,rationale:$('#review-rationale').value})});$('#review-rationale').value='';$('#saved-note-count').textContent=(await json('/demo-api/reviews')).length+' saved notes';toast('Review note saved. Workflow permissions are unchanged.');});};
  }
};
