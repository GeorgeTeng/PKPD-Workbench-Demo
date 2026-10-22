/* Read-only, lazily expanded metadata folders. Original values and files stay intact. */
(() => {
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const instances=new Map(),expanded=new Set();let sequence=0;
 const groups={
  'Data provenance':['source','source_table','source_files','source_id','source_ids','provenance','citation','doi','path','sha256'],
  'Study and sampling':['drug','species','matrix','route','dose','dosing','sampling','record_level','independent_animal_count','endpoint_window','animal_id','subject_id'],
  'Units and exposure':['units','time_unit','concentration_unit','dose_unit','exposure_basis','free_fraction','normalized_fields','column_map'],
  'Execution and review':['role','classification_status','permission','status','review','audit','run_id','created_at','updated_at']
 };
 window.metadataTree=function(value,label='JSON fields'){
  value=value===undefined?null:value;
  const serialized=JSON.stringify(value);let hash=2166136261;for(let i=0;i<serialized.length;i++)hash=Math.imul(hash^serialized.charCodeAt(i),16777619);
  const prefix=String(hash>>>0),id='json_tree_'+(++sequence),pending=new Map();let next=0;instances.set(id,pending);
  function folder(name,count,path,build){
   const key=prefix+path,token=String(++next),open=expanded.has(key);if(!open)pending.set(token,build);
   return `<details class="metadata-folder" data-metadata-key="${esc(key)}" ${open?'open':`data-metadata-lazy="${token}"`}><summary><span class="metadata-folder-icon" aria-hidden="true">▱</span><span class="metadata-name" title="${esc(name)}">${esc(name)}</span><small>${esc(count)}</small></summary><div class="metadata-children">${open?build():''}</div></details>`;
  }
  function grouped(v,path,depth){
   const used=new Set(),folders=[];
   for(const [label,keys] of Object.entries(groups)){
    const entries=keys.filter(k=>Object.hasOwn(v,k)).map(k=>{used.add(k);return [k,v[k]];});
    if(entries.length)folders.push([label,entries]);
   }
   const other=Object.entries(v).filter(([k])=>!used.has(k));if(other.length)folders.push(['Other metadata',other]);
   return folders.map(([name,entries])=>folder(name,entries.length+' fields',path+'/group:'+name,()=>entries.map(([k,x])=>row(k,x,path+'/'+k,depth+1)).join(''))).join('');
  }
  function row(key,v,path,depth=0){
   if(v!==null&&typeof v==='object'&&depth<40){
    const entries=Object.entries(v),count=entries.length+(Array.isArray(v)?' items':' fields');
    return folder(key,count,path,()=>key==='metadata'&&!Array.isArray(v)?grouped(v,path,depth):entries.map(([k,x])=>row(Array.isArray(v)?'['+k+']':k,x,path+'/'+k,depth+1)).join('')||'<p class="metadata-empty">Empty</p>');
   }
   const raw=typeof v==='string'?v:JSON.stringify(v),text=esc(raw);
   return `<div class="metadata-value"><span class="metadata-name" title="${esc(key)}">${esc(key)}</span>${raw.length>160?`<details class="metadata-long"><summary title="${text}">${esc(raw.slice(0,160))}…</summary><div>${text}</div></details>`:`<span class="metadata-scalar">${text}</span>`}</div>`;
  }
  const fields=value!==null&&typeof value==='object'?Object.entries(value).map(([k,v])=>row(k,v,'/'+k)).join(''):row('value',value,'/value');
  const raw=folder('Complete JSON text','Full content','/raw',()=>`<pre>${esc(JSON.stringify(value,null,2))}</pre>`);
  return `<section class="metadata-tree" data-metadata-tree="${id}" aria-label="${esc(label)}"><p class="metadata-note">Expand folders to inspect fields. Original keys and values are preserved.</p>${fields}${raw}</section>`;
 };
 document.addEventListener('toggle',event=>{
  const el=event.target,key=el.dataset?.metadataKey;if(!key)return;
  if(el.open){expanded.add(key);const token=el.dataset.metadataLazy;if(token){const instance=instances.get(el.closest('[data-metadata-tree]')?.dataset.metadataTree),build=instance?.get(token);if(build){el.querySelector(':scope > .metadata-children').innerHTML=build();instance.delete(token);delete el.dataset.metadataLazy;}}}else expanded.delete(key);
 },true);
 // Discard detached previews without retaining their potentially large JSON payloads.
 setInterval(()=>{const visible=new Set([...document.querySelectorAll('[data-metadata-tree]')].map(e=>e.dataset.metadataTree));for(const id of instances.keys())if(!visible.has(id))instances.delete(id);},30000);
})();
