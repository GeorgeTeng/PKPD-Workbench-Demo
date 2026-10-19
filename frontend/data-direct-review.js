'use strict';
const reviewId=location.pathname.split('/').filter(Boolean).pop();
const api='/ui-api/data-reviews/'+encodeURIComponent(reviewId);
const $=s=>document.querySelector(s);
let current,originalText='',generation=0;
const labels={INTERRUPTED:'Awaiting your review',APPROVED:'Assessment accepted',REVISION_REQUIRED:'Changes requested or assessment rejected',STALE:'Files changed — this review is no longer current',SUPERSEDED:'Replaced by a corrected assessment'};
async function request(url,options){const r=await fetch(url,options);if(!r.ok){const b=await r.json().catch(()=>({detail:r.statusText}));throw new Error(typeof b.detail==='string'?b.detail:JSON.stringify(b.detail));}return r;}
function node(tag,text,parent){const e=document.createElement(tag);if(text)e.textContent=text;if(parent)parent.append(e);return e;}
function list(parent,title,items,empty){node('h3',title,parent);if(!items.length){node('p',empty||'None stated.',parent);return;}const ul=node('ul','',parent);items.forEach(x=>node('li',x,ul));}
function renderShortSummary(result){
 const root=$('#executive');root.replaceChildren();const s=result.summary;
 node('span','Overall recommendation: '+s.decision.replaceAll('_',' '),root).className='badge';
 node('h2',s.headline,root);
 const table=node('table','',root);table.className='decisions';
 const tr=node('tr','',node('thead','',table));['Analysis / source scope','Data recommendation','Specific problem and impact','Next action'].forEach(x=>node('th',x,tr));
 const tbody=node('tbody','',table);
 const names={MODEL_BASED_ANIMAL_PK:'Animal PK · model-based',PD_INDEX_COMPARISON:'PD index comparison',PD_TARGET_ESTIMATION:'PD target estimation',NCA:'NCA (optional)',PTA:'PTA (later)'};
 const states={READY:'Inputs supported',CONDITIONAL:'Proceed with limits',NOT_READY:'Hold',NOT_ESTABLISHED:'Input support unresolved',LATER:'Later'};
 for(const [key,row] of Object.entries(s.rows)){const line=node('tr','',tbody);const label=node('th',names[key],line);node('p',result.action_decisions[key].source_scope,label).className='muted';node('td',states[row.readiness]||row.readiness,line);node('td',row.finding,line);node('td',row.next_step,line);}
 node('p',s.later_and_optional,root).className='muted';
 const details=node('details','',root);node('summary','Detailed Necessity opinions and scope',details);
 for(const [key,value] of Object.entries(result.action_decisions)){node('h3',names[key],details);node('p',value.readiness+' — '+value.source_scope,details);if(value.scope_readiness)list(details,'Source decisions',value.scope_readiness.map(r=>r.scope_id+': '+(states[r.readiness]||r.readiness)));node('p',value.finding,details);node('p','Next: '+value.next_step,details);}
}
function renderSummary(result){
 if(result.version==='DATA_HUMAN_SUMMARY_3.0'){renderShortSummary(result);return;}

 const root=$('#executive');root.replaceChildren();const s=result.summary,a=result.assessment;
 node('span',s.decision.replaceAll('_',' '),root).className='badge';
 node('h2',s.headline,root);node('p',s.overview,root);
 node('p','Scope: '+a.scope,root).className='muted';
 const reasons=node('details','',root);node('summary','Necessity’s opinion and reasons',reasons);
 node('p',a.opinion,reasons);list(reasons,'Reasons to proceed',a.reasons_to_proceed);list(reasons,'Reasons not to proceed',a.reasons_not_to_proceed);list(reasons,'Conditions',a.conditions);
 const columns=node('div','',root);columns.className='columns';
 list(node('div','',columns),'Can proceed now',s.can_proceed_now);
 list(node('div','',columns),'Must wait',s.must_wait);
 node('h2','Current issues and their effect',root);
 for(const issue of s.issues){const card=node('article','',root);node('h3',issue.title,card);node('p',issue.problem,card);node('p','Effect: '+issue.effect_on_progress,card);node('p','Advice: '+issue.advice,card);const trace=node('details','',card);node('summary','Assessment references',trace);node('small',issue.analysis_ids.join(', '),trace);}
 list(root,'Optional improvements',s.optional_improvements,'No optional improvements are identified in this assessment.');
 list(root,'Recommended next steps',s.recommended_next_steps);
 node('p','Recommendation only. No human approval has been inferred.',root).className='muted';
}
async function loadArtifact(){const epoch=++generation,name=$('#artifact').value;$('#raw').textContent='Loading original file…';const text=await(await request(api+'/artifacts/'+encodeURIComponent(name))).text();if(epoch!==generation)return;originalText=text;$('#raw').textContent=text;$('#download').href=api+'/artifacts/'+encodeURIComponent(name)+'?download=true';$('#hash').textContent='SHA-256 · '+current.artifacts.find(a=>a.name===name).sha256;}
async function renderPreparationHistory(){const root=$('#previous-preparations');root.replaceChildren();const value=await(await request('/ui-api/direct-preparations')).json();const matches=value.jobs.filter(job=>job.review_id===reviewId);if(!matches.length)return;node('h4','Recorded technical-preparation runs',root);for(const job of matches){const row=node('p','',root);node('span',`${job.status||'Status unavailable'}${job.stage?' · '+job.stage:''} · Technical processing: ${job.technical_processing_complete===true?'complete':job.technical_processing_complete===false?'incomplete':'not reported'}`,row);if(job.report_url){node('br','',row);const link=node('a','Open bound preparation report JSON',row);link.href=job.report_url;}}}
async function refresh(){
 current=await(await request(api)).json();$('#status').textContent=labels[current.status]||current.status;$('#controls').disabled=true;$('#signature').textContent=current.output_signature;
 $('#record').textContent=current.review?'Reviewer: '+current.review.reviewer+'\nDecision: '+current.review.decision+'\n'+current.review.rationale:'No human decision submitted.';
 if(current.status==='SUPERSEDED'){$('#executive').replaceChildren();node('p','This assessment has been replaced. Its original files remain available as evidence.',$('#executive'));if(/^data_[a-f0-9]+$/.test(current.superseded_by)){const link=node('a','Open the current assessment',$('#executive'));link.href='/data-review/'+current.superseded_by;}return;}
 if(current.status==='STALE'){$('#executive').textContent='This review is stale. Its files or inputs have changed.';return;}
 if(!$('#artifact').options.length){for(const a of current.artifacts){const o=node('option',a.name,$('#artifact'));o.value=a.name;}$('#artifact').value=current.effective_assessment_name||'necessity.json';}
 $('#preparation').hidden=!(current.approved || current.can_review);
 try{await renderPreparationHistory();}catch(e){$('#previous-preparations').textContent=e.message;}
 if(current.artifacts.some(a=>a.name==='summary.json'))renderSummary(await(await request(api+'/artifacts/summary.json')).json());
 else $('#executive').textContent='This historical assessment predates the English summary. Its original results remain available below.';
 if(current.effective_assessment_name==='necessity.reviewed.json'){
  const effective=await(await request(api+'/artifacts/necessity.reviewed.json')).json();
  const detail=node('details','',$('#executive'));node('summary','Effective reviewed actions and conditions',detail);
  node('p','These recorded corrections are part of this review. The original model response remains available as evidence.',detail);
  for(const row of effective.analyses){node('h3',row.id,detail);node('p',row.next_action,detail);list(detail,'Conditions',row.conditions_to_verify);}
 }
 $('#controls').disabled=!current.can_review;
}
function error(e){$('#message').className='error';$('#message').textContent=e.message;}
$('#evidence').ontoggle=()=>{if($('#evidence').open&&!originalText)loadArtifact().catch(error);};
$('#artifact').onchange=()=>loadArtifact().catch(error);
$('#copy').onclick=()=>navigator.clipboard.writeText(originalText).then(()=>{$('#message').textContent='Original JSON copied.';}).catch(error);
$('#review').elements.decision.onchange=()=>{const f=$('#review').elements.rationale,required=['REQUEST_CHANGES','REJECT'].includes($('#review').elements.decision.value);f.required=required;if(required)f.minLength=5;else f.removeAttribute('minlength');};
$('#review').onsubmit=async event=>{event.preventDefault();const f=$('#review').elements;const payload={decision:f.decision.value,reviewer:f.reviewer.value,rationale:f.rationale.value,confirmed:f.confirmed.checked,output_signature:current.output_signature};$('#controls').disabled=true;try{await request(api+'/review',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});$('#message').className='';$('#message').textContent='Review decision saved.';await refresh();}catch(e){error(e);await refresh().catch(error);}};
$('#start-preparation').onclick=async()=>{const button=$('#start-preparation');button.disabled=true;$('#preparation-status').textContent='Starting…';try{const response=await request(api+'/preparation',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({confirmed_user_authorization:true,auto_approve_human_gates:true})});const job=await response.json();$('#preparation-status').textContent='Job '+job.id+' · '+job.status+'. Automatic approval is recorded as USER_AUTHORIZED_AUTOMATION; no human reviewer is claimed.';const link=$('#preparation-report');link.href='/ui-api/jobs/'+encodeURIComponent(job.id)+'/artifacts/data_report';link.hidden=false;link.textContent='Open preparation report when available';const poll=async()=>{try{const status=await(await request('/ui-api/jobs/'+encodeURIComponent(job.id))).json();$('#preparation-status').textContent='Job '+job.id+' · '+status.status+(status.error?' · '+status.error:'');if(status.artifacts?.includes('data_report')){link.hidden=false;link.textContent='Open preparation report JSON';}if(['QUEUED','RUNNING'].includes(status.status))setTimeout(poll,5000);}catch(e){$('#preparation-status').textContent=e.message;}};setTimeout(poll,1000);}catch(e){$('#preparation-status').textContent=e.message;button.disabled=false;}};
refresh().catch(error);
