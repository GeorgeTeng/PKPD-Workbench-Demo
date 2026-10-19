/* Presentation only: folders and previews never modify the execution contract. */
const artifactViewState = new Map();
function compactContent(text, limit = 180) {
 const value = String(text ?? '');
 if(value.length <= limit) return `<p class="compact-copy">${esc(value)}</p>`;
 return `<details class="compact-disclosure"><summary><span class="compact-excerpt">${esc(value.slice(0,limit))}…</span><span class="disclosure-hint">Read more</span></summary><p class="verbatim-copy">${esc(value)}</p></details>`;
}
function artifactSize(bytes) {return bytes == null ? '' : bytes < 1024 ? `${bytes} B` : bytes < 1048576 ? `${(bytes/1024).toFixed(1)} KB` : `${(bytes/1048576).toFixed(1)} MB`;}
function artifactFolder(a) {
 const labels = {context:'Context & JSON',data:'Data',figure:'Figures',evidence:'Evidence & audit',model:'Model files',report:'Reports'};
 return labels[a.kind] || 'Other attachments';
}
function artifactBrowser(nodeId, artifacts, key = 'outputs') {
 const groups = new Map();
 for(const a of artifacts) {const folder = artifactFolder(a); if(!groups.has(folder)) groups.set(folder,[]); groups.get(folder).push(a);}
 if(!artifacts.length) return emptyBox('No generated files yet','Execution outputs will appear here when available.','folder');
 const scope = `${flow?.session_id || 'template'}:${nodeId}:${key}`;
 const state = artifactViewState.get(scope) || {query:'',open:{}};
 return `<section class="artifact-browser" data-browser-scope="${esc(scope)}"><label class="file-search-label">Find a file<input type="search" data-artifact-search placeholder="Search names or file roles" value="${esc(state.query)}" autocomplete="off"></label><div class="browser-count" data-file-count>${artifacts.length} registered file${artifacts.length===1?'':'s'}</div><div class="artifact-folders">${[...groups].map(([label,files])=>`<details class="artifact-folder" data-folder-key="${esc(label)}" ${state.open[label] ?? (groups.size === 1 && files.length <= 8) ? 'open' : ''}><summary>${icon('folder')}<span>${esc(label)}</span><span class="folder-count">${files.length}</span></summary><div class="artifact-folder-files">${files.map(a=>`<article class="artifact-file" data-file-search="${esc((a.name+' '+label).toLowerCase())}"><div class="artifact-file-main">${icon(a.kind==='figure'?'chart':/\.json$/i.test(a.name)?'code':'file')}<button class="file-title text-button" data-artifact="${esc(a.name)}" data-artifact-node="${esc(nodeId)}" title="${esc(a.name)}">${esc(a.name)}</button><span class="file-size">${artifactSize(a.bytes)}</span></div><div class="artifact-file-actions"><button class="text-button" data-artifact="${esc(a.name)}" data-artifact-node="${esc(nodeId)}">Preview</button><button class="text-button" data-artifact="${esc(a.name)}" data-artifact-node="${esc(nodeId)}" data-artifact-mode="open">Open ↗</button><button class="text-button" data-artifact="${esc(a.name)}" data-artifact-node="${esc(nodeId)}" data-artifact-mode="download">${icon('download')}Download</button><details class="file-info" data-preserve-details="file-${esc(nodeId)}-${esc(a.name)}"><summary>Details</summary><dl><dt>Full file name</dt><dd>${esc(a.name)}</dd><dt>Registered role</dt><dd>${esc(a.kind || 'Unspecified')}</dd>${a.sha256?`<dt>SHA-256</dt><dd>${esc(a.sha256)}</dd>`:''}</dl></details></div></article>`).join('')}</div></details>`).join('')}</div><p class="browser-empty" data-no-files hidden>No files match this search.</p><p class="browser-note">Display folders use registered file roles. Original files and downstream assignments are unchanged.</p></section>`;
}
function bindArtifactBrowsers(root = document) {
 for(const browser of root.querySelectorAll('[data-browser-scope]')) {
  const key = browser.dataset.browserScope;
  const state = artifactViewState.get(key) || {query:'',open:{}};
  artifactViewState.set(key,state);
  const input = browser.querySelector('[data-artifact-search]');
  const filter = () => {
   const query = input.value.trim().toLowerCase(); state.query=input.value; let visible=0;
   for(const folder of browser.querySelectorAll('[data-folder-key]')) {
    let count=0;
    for(const row of folder.querySelectorAll('[data-file-search]')) {row.hidden = !row.dataset.fileSearch.includes(query); if(!row.hidden) count++;}
    folder.hidden = count===0; visible += count;
    folder.querySelector('.folder-count').textContent=String(count);
    if(query) folder.open=count>0; else folder.open=state.open[folder.dataset.folderKey] ?? (browser.querySelectorAll('[data-folder-key]').length===1 && count<=8);
   }
   browser.querySelector('[data-file-count]').textContent=`${visible} ${query?'matching':'registered'} file${visible===1?'':'s'}`;
   browser.querySelector('[data-no-files]').hidden=visible>0;
  };
  input.oninput=filter;
  for(const folder of browser.querySelectorAll('[data-folder-key]')) folder.ontoggle=()=>{if(!input.value.trim())state.open[folder.dataset.folderKey]=folder.open;};
  filter();
 }
}
function openArtifactWindow(blob, name, target) {
 // The new tab contains escaped text or a passive image; uploaded HTML is never executed.
 return (async()=>{
  let content, childUrl=null;
  if(/\.(png|jpe?g|gif|webp|svg)$/i.test(name)) {childUrl=URL.createObjectURL(blob);content=`<img src="${childUrl}" alt="${esc(name)}">`;}
  else if(/\.pdf$/i.test(name)) {childUrl=URL.createObjectURL(blob); target.location.replace(childUrl);setTimeout(()=>URL.revokeObjectURL(childUrl),60000);return;}
  else if(/\.(jsonl?|csv|tsv|txt|md|r|py|yaml|yml|log|html|xml|smk)$/i.test(name)) {
   let value=await blob.text();if(/\.json$/i.test(name)){try{value=JSON.stringify(JSON.parse(value),null,2);}catch{/* Keep malformed JSON inspectable. */}}
   content=`<pre>${esc(value)}</pre>`;
  } else {target.close();download(blob,name);return;}
  const documentBlob=new Blob([`<!doctype html><html lang="en"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src blob: data:"><title>${esc(name)}</title><style>body{font:15px system-ui;margin:32px;color:#203b34;background:#fafcf9}h1{font-size:20px;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px/1.7 Consolas,monospace;background:white;border:1px solid #dce5d7;padding:24px;border-radius:12px}img{max-width:100%;height:auto}</style></head><body><h1>${esc(name)}</h1><p>Full file preview. JSON whitespace may be formatted; Download preserves the original bytes.</p>${content}</body></html>`],{type:'text/html;charset=utf-8'});
  const url=URL.createObjectURL(documentBlob);target.location.replace(url);setTimeout(()=>{URL.revokeObjectURL(url);if(childUrl)URL.revokeObjectURL(childUrl);},60000);
 })();
}
function showUpstreamFiles(id) {
 const n=getNode(id); if(!n)return;
 const upstream=id!==selected;
 modal(`${n.title} · registered files`,`<p>${upstream ? "Browse this upstream step's outputs. This directory is not a claim that every file is assigned to the selected downstream task." : "Inspect this step's generated files. Preview, open or download the original artifact before recording a review decision."}</p>${artifactBrowser(id,n.state.artifacts,'upstream')}`,upstream?'UPSTREAM FILES':'STEP OUTPUTS');
 bindArtifactBrowsers(document.querySelector('#modal-body'));
}
function compactInspectorFeedback(n) {
 const content=typeof renderContextFeedback==='function' ? renderContextFeedback(n) : n.state.error ? `<div class="error-box">${esc(n.state.error)}</div>` : '';
 if(!content || tab==='review' || n.state.error || n.state.context_feedback || ['FAILED','REVISION_REQUIRED','NEEDS_ATTENTION'].includes(n.state.execution))return content;
 return `<details class="feedback-disclosure" data-preserve-details="step-findings"><summary>${icon('info')}Step findings & missing materials<span>Expand</span></summary>${content}</details>`;
}
document.addEventListener('click',event=>{
 const button=event.target.closest('[data-upstream-files]');if(button){event.preventDefault();showUpstreamFiles(button.dataset.upstreamFiles);}
});
