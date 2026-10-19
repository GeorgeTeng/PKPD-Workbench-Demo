const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const nodes = Object.fromEntries(['context','adequacy','prepare'].map(id => [id, {
 id, state:{approved:false, execution:'NOT_STARTED'}
}]));
const env = vm.createContext({URLSearchParams, getNode:id=>nodes[id], stateLabel:n=>n.state.approved?'Approved':n.state.execution});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../../../frontend/workbench-ui.js'),'utf8'),env);
const evaluate = code => vm.runInContext(code,env);
assert.equal(evaluate("moduleStatus('data_bundle')"),'NOT_STARTED');
nodes.adequacy.state.approved=true;
assert.equal(evaluate("moduleStatus('data_bundle')"),'NOT_STARTED');
nodes.prepare.state.execution='COMPLETED';
assert.equal(evaluate("moduleStatus('data_bundle')"),'COMPLETED');
nodes.prepare.state.approved=true;
assert.equal(evaluate("moduleStatus('data_bundle')"),'Cleared');
nodes.prepare.state.approved=false;
nodes.prepare.state.execution='STALE';
assert.equal(evaluate("moduleStatus('data_bundle')"),'STALE');
nodes.context.state.approved=true;
assert.equal(evaluate("moduleStatus('prc')"),'Within context'); // No fabricated internal completion.
assert.equal(evaluate("moduleRoute('data_bundle')"),'#view=module&module=data_bundle');
assert.equal(evaluate("stageParent('prepare')"),'data_bundle');
for(const id of ['translation','targets','pta']){
 assert.equal(evaluate(`moduleStatus('${id}')`),'Planned');
 assert.equal(evaluate(`moduleViews['${id}'].owner`),undefined);
}
console.log('Grouped state, routes and planned-module boundaries passed.');

// Animal PK: agent design for one species, repeated per species, owned by the existing pk step.
assert.equal(evaluate("moduleViews.pk.owner"),'pk');
assert.equal(evaluate("moduleViews.pk.perSpecies"),true);
assert.equal(evaluate("moduleViews.pk.planned"),undefined);
assert.deepEqual(JSON.parse(evaluate("JSON.stringify(moduleParts(moduleViews.pk).map(x=>x[0]))")),
 ['evidence','candidates','library','plan','fit','diagnostics','comparison','review','support','handoff']);
assert.equal(evaluate("moduleParts(moduleViews.pk).filter(x=>x[2]?.role==='human').length"),2);
assert.deepEqual(JSON.parse(evaluate("JSON.stringify(moduleViews.pk.loops)")),[{from:'review',to:'plan',label:'Targeted revision'}]);
assert.equal(evaluate("moduleViews.pk.next.module"),'translation');
const reviewRelations = JSON.parse(evaluate("JSON.stringify(agentRelations(moduleViews.pk,'review'))"));
assert.deepEqual(reviewRelations,[['Receives from','Model Comparison Agent'],['Advice from','PK Support Agent'],
 ['Hands off to','Report & PK/PD Handoff Agent'],['Targeted revision to','Model Plan Approval Agent']]);
assert.deepEqual(JSON.parse(evaluate("JSON.stringify(agentRelations(moduleViews.pk,'library'))")),[['Feeds','Candidate Specification Agent']]);
assert.equal(evaluate("moduleViews.translation.title"),'PK translation');
// PK translation: five agents, revision returns to extrapolation, input from all species.
assert.deepEqual(JSON.parse(evaluate("JSON.stringify(moduleParts(moduleViews.translation).map(x=>x[0]))")),
 ['extrapolation','compare','validate','review','handoff']);
assert.deepEqual(JSON.parse(evaluate("JSON.stringify(moduleViews.translation.loops)")),[{from:'review',to:'extrapolation',label:'Targeted revision'}]);
assert.equal(evaluate("moduleViews.translation.previous.module"),'pk');
console.log('Animal PK (per species) and PK translation agent structures passed.');
// Data: four agents, DR and DC inside the adequacy step, DP and DH inside the prepare step.
assert.deepEqual(JSON.parse(evaluate("JSON.stringify(moduleViews.data_bundle.children.map(id=>[moduleViews[id].agent,moduleViews[id].owner]))")),
 [['DR','adequacy'],['DC','adequacy'],['DP','prepare'],['DH','prepare']]);
assert.equal(evaluate("moduleAlias('data_adequacy')"),'data_coverage');
assert.equal(evaluate("moduleAlias('data_metadata')"),'data_handoff');
// Each agent page lists its own outputs and every audited call it made; DC-label and DC-review are both DC.
const dataFiles = ['requirements.json','data_labels.json','data_agents__method_context.json','data_agents__audit__DR__a1__request.json',
 'data_agents__audit__DC-label__b2__request.json','data_agents__audit__DC-review__c3__response.json','data_agents__audit__DH-metadata__d4__request.json'];
const shown = id => JSON.parse(evaluate(`JSON.stringify(moduleArtifacts('${id}',{state:{artifacts:${JSON.stringify(dataFiles.map(name=>({name})))}}}).map(a=>a.name))`));
assert.deepEqual(shown('data_requirements'),['requirements.json','data_agents__method_context.json','data_agents__audit__DR__a1__request.json']);
assert.deepEqual(shown('data_coverage'),['data_labels.json','data_agents__audit__DC-label__b2__request.json','data_agents__audit__DC-review__c3__response.json']);
assert.deepEqual(shown('data_preparation'),[]);
assert.deepEqual(shown('data_handoff'),['data_agents__audit__DH-metadata__d4__request.json']);

// The main page lists every stage once, in scientific order, grouped into three phases.
const map = JSON.parse(evaluate('JSON.stringify(workflowMap)'));
const order = map.flatMap(p=>p.stages||p.lanes.flatMap(l=>l.stages));
assert.deepEqual(order,['intake','context_bundle','data_bundle','eda','dispatch','pk','translation','index','targets','pta','results','clinical']);
assert.deepEqual(map.map(p=>p.title),['Evidence and data','Modeling','Decision']);
assert.deepEqual(map[1].lanes.map(l=>l.stages),[['pk','translation'],['index','targets']]);
assert.equal(order.filter(id=>['adequacy','prepare','prc'].includes(id)).length,0);
assert.equal(Object.keys(evaluate('stageInfo')).length,order.length);
assert.equal(evaluate("stageOf('prepare')"),'data_bundle');
assert.equal(evaluate("stageOf('context')"),'context_bundle');
assert.equal(evaluate("statusTone('Awaiting review')"),'attention');
assert.equal(evaluate("statusTone('Cleared')"),'done');
assert.equal(evaluate("stepCount('data_bundle')"),'4 steps');
assert.equal(evaluate("stepCount('data_handoff')"),'3 steps');
assert.equal(evaluate("stepCount('pk')"),'10 agents');
// Back and breadcrumbs: every level links one level up, ending at the workflow.
env.route=(id,tab='input')=>`#node=${id}&tab=${tab}`;
env.location={hash:'#view=module&module=data_preparation'};
vm.runInContext("var page='module', selected='prepare';",env);
assert.deepEqual(JSON.parse(evaluate('JSON.stringify(navTrail())')),[['Workflow','#view=workflow'],['Data Assessment & Preparation','#view=module&module=data_bundle'],['DP · Prepare & QC','#view=module&module=data_preparation']]);
env.location={hash:'#view=module&module=pk&part=fit'};
assert.deepEqual(JSON.parse(evaluate('JSON.stringify(navTrail().map(x=>x[0]))')),['Workflow','Animal PK modeling','Model Fitting Agent']);
env.location={hash:'#node=context&tab=review'};
vm.runInContext("page='step'; selected='context';",env);
assert.deepEqual(JSON.parse(evaluate('JSON.stringify(navTrail().map(x=>x[0]))')),['Workflow','Context & Project Rules','Run and review']);
console.log('Main page phases, stage order and Back trail passed.');
// The clinical outer loop is drawn on the main page, from Clinical interpretation back to File intake.
const diagram={innerHTML:'',querySelector:()=>null};
Object.assign(env,{$:s=>s==='#diagram'?diagram:null,icon:()=>'',esc:s=>String(s),duration:()=>'00:00:00',flow:{parent_cycle:{session_id:'flow_prev'}}});
env.getNode=id=>nodes[id]||{id,depends_on:[],state:{approved:false,execution:'NOT_STARTED',timing:{elapsed_seconds:0}}};
evaluate('renderWorkflowGraph()');
assert.match(diagram.innerHTML,/class="loop-foot"[\s\S]*Clinical interpretation → File intake/);
assert.match(diagram.innerHTML,/<svg class="flow-lines"/);
assert.match(diagram.innerHTML,/id="pk-branch"[\s\S]*id="pkpd-branch"/);
assert.match(diagram.innerHTML,/Two branches run in parallel[\s\S]*Both branches join here/);
assert.match(diagram.innerHTML,/href="#node=clinical&tab=clinical"/);
assert.match(diagram.innerHTML,/href="\/\?flow=flow_prev#view=workflow"/);
assert.ok(diagram.innerHTML.indexOf('id="node-intake"')<diagram.innerHTML.indexOf('id="node-clinical"'));
// The two modeling branches run in parallel: Task assignment forks into both and both join at PTA.
const edges=JSON.parse(evaluate('JSON.stringify(workflowEdges)'));
assert.deepEqual(map[1].lanes.map(l=>l.id),['pk-branch','pkpd-branch']);
assert.deepEqual(edges.filter(e=>e[0]==='dispatch').map(e=>e[1]),['pk-branch','pkpd-branch']);
assert.deepEqual(edges.filter(e=>e[1]==='pta').map(e=>e[0]),['pk-branch','pkpd-branch']);
assert.deepEqual(edges.filter(e=>['pk-branch','pkpd-branch'].includes(e[0])||['pk-branch','pkpd-branch'].includes(e[1])).map(e=>e[2]),['target','target','source','source']);
assert.equal(edges.some(e=>e[0]==='pk'&&e[1]==='index'),false); // Only drawn when the backend declares the dependency.
console.log('Clinical outer loop, parallel branches and their join passed.');

env.esc=value=>String(value||'');
env.route=(id,tab)=>`#node=${id}&tab=${tab}`;
env.flow={context_revision_child:'flow_retry'};
nodes.context.state={execution:'FAILED',failure:{title:'Input exceeded limit',summary:'Batch evidence.'}};
assert.match(evaluate('moduleControlNotice([getNode("context")])'),/flow=flow_retry/);
assert.match(evaluate('moduleControlNotice([getNode("context")])'),/Open latest retry/);
env.flow.context_revision_child=null;
assert.match(evaluate('moduleControlNotice([getNode("context")])'),/Open diagnosis & retry/);
nodes.context.state.execution='NOT_STARTED';
assert.equal(evaluate('moduleControlNotice([getNode("context")])'),'');
console.log('Grouped module exposes the current failure and correct retry route.');
