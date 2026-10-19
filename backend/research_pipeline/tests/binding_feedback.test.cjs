const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const esc = v => String(v ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
const env = vm.createContext({esc});
vm.runInContext(fs.readFileSync(path.join(__dirname,'../../../frontend/execution-feedback.js'),'utf8'),env);
env.report={code:'MODEL_BINDING_INVALID',validation_details:{check_scope:'Source contract only.',issues:[{
 item_id:'I001',field:'units',proposed_value:'<script>alert(1)</script>',reason:'VALUE_NOT_IN_SINGLE_QUOTE',
 evidence:[{source_id:'S1',unit_id:'U1',quote:'4 L/h',source_verified:true}],
 what_to_change:'Copy a continuous excerpt; summarize in statement.',path:'/requirements/items/0/science/bindings/0/value'
}]}};
const html=vm.runInContext('renderBindingCorrections(report)',env);
assert.match(html,/Binding corrections \(1\)/);
assert.match(html,/I001 · units/);
assert.match(html,/4 L\/h/);
assert.match(html,/&lt;script&gt;/);
assert.doesNotMatch(html,/<script>|<details[^>]*open/);
assert.equal(vm.runInContext('renderBindingCorrections({code:"MODEL_TIMEOUT"})',env),'');
console.log('Binding feedback: actionable, collapsed, HTML-escaped.');

env.flow = {};
env.failureNode = {id:'context',state:{execution:'FAILED',can_retry_context:true,
 failure:{code:'LOCAL_FILE_REPLACE_BLOCKED',title:'A local log file could not be updated',
 stage_label:'Check retrieved supporting evidence',summary:'Windows refused replacement.',
 known_facts:['File: progress.json'],uncertainty:'Occupying process is unknown.',
 suggested_actions:['Retry with the updated writer.'],materials_note:'No proposal change requested.'}}};
const localHtml = vm.runInContext('renderExecutionFeedback(failureNode)',env);
assert.match(localHtml,/A local log file could not be updated/);
assert.match(localHtml,/id="retry-context"/);
assert.match(localHtml,/id="download-execution-feedback"/);
assert.doesNotMatch(localHtml,/Check model connection/);
console.log('Local I/O feedback: retry and diagnosis available; no irrelevant connection action.');

env.readinessReport={preparation_policy:'DATASET_ACTION_V1',technical_processing_complete:true,
 handoff_review_complete:false,cleaning_complete:false,fit_ready:false,scientific_release:false,
 findings:[{affected_id:'D1',code:'DOSE_BASIS',reason:'Dose basis needs source evidence',needed_material:'Dose record',required_by:'BEFORE_MODELING'}],
 dataset_action_readiness:[{dataset_id:'D1',source_item_id:'F1:S1:T1',actions:{
  SOURCE_INSPECTION:{status:'READY',reasons:[]},DESCRIPTIVE_EDA:{status:'RESTRICTED',reasons:['Time mapping remains unresolved. <retain raw>']},
  PK_MODELING:{status:'RESTRICTED',reasons:['Fit readiness is not established.']}}}]};
const readinessHtml=vm.runInContext('renderDatasetActionReadiness(readinessReport)',env);
assert.match(readinessHtml,/D1 · F1:S1:T1/);
assert.match(readinessHtml,/Source inspection/);
assert.match(readinessHtml,/Restricted/);
assert.match(readinessHtml,/&lt;retain raw&gt;/);
assert.match(readinessHtml,/Related scoped findings/);
assert.match(readinessHtml,/Dose basis needs source evidence/);
assert.match(readinessHtml,/BEFORE_MODELING/);
assert.doesNotMatch(readinessHtml,/<retain raw>/);
env.legacyPreparationNode={id:'prepare',state:{execution:'COMPLETED',preparation_report:{
 status:'WAITING_FOR_HUMAN_REVIEW',cleaning_complete:false,scientific_release:false,
 findings:[],sample_size_status:'NOT_CALCULABLE'},can_retry_preparation:false}};
const legacyPreparationHtml=vm.runInContext('renderExecutionState(legacyPreparationNode)',env);
assert.match(legacyPreparationHtml,/Legacy report schema/);
assert.match(legacyPreparationHtml,/Technical processing incomplete/);
assert.doesNotMatch(legacyPreparationHtml,/Ready for scoped action/);
console.log('Preparation readiness: action-scoped new schema and legacy report flags remain distinct.');
env.preEdaNode={id:'context',state:{pre_eda_source_job_id:'source_job',pre_eda_rules_available:true}};
const preEdaHtml=vm.runInContext('renderExecutionState(preEdaNode)',env);
assert.match(preEdaHtml,/Build formal handoff and prepare data/);
assert.match(preEdaHtml,/Project Rules already bound to this approved Context/);
assert.match(preEdaHtml,/Authorize this run and start/);
assert.match(preEdaHtml,/stops before EDA and fitting/);
console.log('Pre-EDA UI requires a verified First Part v4 handoff and stops before EDA.');

env.duration = s => String(s);
const evidenceCalls = ['file_0001','file_0002','file_0003'].map((id,i)=>({stage:'attachment_evidence--'+id,
 stage_label:'Attachment evidence · '+id,status:i<2?'RUNNING':'RETURNED',started_at:String(i),phase:'AWAITING_MODEL_OUTPUT'}));
env.evidenceNode = {id:'context',depends_on:[],state:{execution:'RUNNING',locked_by:[],
 model_progress:{...evidenceCalls[1],parallel_calls:evidenceCalls}}};
const evidenceHtml = vm.runInContext('renderExecutionState(evidenceNode)',env);
assert.equal((evidenceHtml.match(/class="field-card model-call"/g) || []).length,2);
assert.match(evidenceHtml,/Attachment evidence · file_0001/);
assert.match(evidenceHtml,/1 returned · 2 running/);
console.log('Attachment evidence: every running call is shown with a returned/running count.');

const reviewCalls = ['context_faithfulness--part_1','context_faithfulness--part_2','context_completeness'].map((stage,i)=>({stage,
 stage_label:stage,status:'RUNNING',started_at:String(i),phase:'AWAITING_MODEL_OUTPUT'}));
env.reviewNode = {id:'context',depends_on:[],state:{execution:'RUNNING',locked_by:[],model_progress:{...reviewCalls[0],parallel_calls:reviewCalls}}};
const reviewHtml = vm.runInContext('renderExecutionState(reviewNode)',env);
assert.equal((reviewHtml.match(/class="field-card model-call"/g) || []).length,3);
assert.match(reviewHtml,/runs in parts alongside the completeness review/);
console.log('Split faithfulness review: every part and the completeness review are shown.');

const concurrentCalls = ['context_faithfulness--part_1','context_faithfulness--part_2','context_completeness','context_conflicts'].map(stage=>({stage,
 stage_label:stage,status:'RUNNING',started_at:'2026-10-08T07:00:00Z',phase:'AWAITING_MODEL_OUTPUT'}));
env.concurrentNode = {id:'context',depends_on:[],state:{execution:'RUNNING',locked_by:[],
 model_progress:{...concurrentCalls[0],context_review_mode:'parallel_v3',parallel_calls:concurrentCalls}}};
const concurrentHtml = vm.runInContext('renderExecutionState(concurrentNode)',env);
assert.equal((concurrentHtml.match(/class="field-card model-call"/g) || []).length,4);
assert.match(concurrentHtml,/alongside the completeness and global conflict reviews/);
// A resumed v3 run reuses the accepted completeness review, so it has no call and no start time.
const resumedCalls = concurrentCalls.filter(x=>x.stage!=='context_completeness').map(x=>x.stage==='context_conflicts' ? {...x,started_at:'2026-10-08T07:09:00Z'} : x);
env.resumedNode = {id:'context',depends_on:[],state:{execution:'RUNNING',locked_by:[],
 model_progress:{...resumedCalls[0],context_review_mode:'parallel_v3',parallel_calls:resumedCalls}}};
assert.match(vm.runInContext('renderExecutionState(resumedNode)',env),/alongside the completeness and global conflict reviews/);
// parallel_v2: conflicts wait for the branches even when the last branch returns seconds before.
const laterConflicts = concurrentCalls.map(x=>x.stage==='context_conflicts' ? {...x,started_at:'2026-10-08T07:00:30Z'} : {...x,status:'RETURNED'});
env.laterNode = {id:'context',depends_on:[],state:{execution:'RUNNING',locked_by:[],
 model_progress:{...laterConflicts[3],context_review_mode:'parallel_v2',parallel_calls:laterConflicts}}};
const laterHtml = vm.runInContext('renderExecutionState(laterNode)',env);
assert.match(laterHtml,/Global conflict review starts after all of them/);
assert.doesNotMatch(laterHtml,/alongside the completeness and global conflict reviews/);
env.v1Node = {id:'context',depends_on:[],state:{execution:'RUNNING',locked_by:[],
 model_progress:{stage:'context_completeness',stage_label:'context_completeness',status:'RUNNING',phase:'AWAITING_MODEL_OUTPUT',context_review_mode:'parallel_v1'}}};
assert.match(vm.runInContext('renderExecutionState(v1Node)',env),/Global conflict review starts after both return valid reviews/);
console.log('Context review order: taken from the run\'s frozen review mode, including resumed runs.');

// Operation-specific restrictions remain visible alongside scoped display readiness.
env.operationReport = {preparation_policy:'DATASET_ACTION_V1',findings:[],dataset_action_readiness:[{
 dataset_id:'T0049',source_item_id:'F1:T49',actions:{SOURCE_INSPECTION:{status:'READY'},
 DESCRIPTIVE_EDA:{status:'READY'},PK_MODELING:{status:'RESTRICTED'}},
 operation_restrictions:[{operation:'TIME_AXIS_SELECTION',reasons:['Nominal and pixel times differ.']}]}]};
const operationHtml=vm.runInContext('renderDatasetActionReadiness(operationReport)',env);
assert.match(operationHtml,/Restricted operations/);
assert.match(operationHtml,/TIME AXIS SELECTION/);
assert.match(operationHtml,/Nominal and pixel times differ/);
assert.match(operationHtml,/Ready for scoped action/);
