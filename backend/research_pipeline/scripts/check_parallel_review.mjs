// Read-only live page plus browser-local telemetry fixtures. Never posts reviews or starts jobs.
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/georg/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json');
const {chromium}=require('playwright');
const base=process.env.CANVAS_URL,sid=process.env.CONTEXT_SESSION,out=process.env.CONTEXT_CHECK_OUT;
if(!base||!sid||!out) throw Error('Explicit URL, session and output directory required');
await mkdir(out,{recursive:true});
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:1512,height:1080}}); const errors=[];
page.on('pageerror',e=>errors.push(e.message));
try {
 await page.goto(`${base}/?flow=${sid}#node=adequacy&tab=input`);
 await page.locator('.adapter-missing').waitFor();
 const gap=await page.locator('.adapter-missing').innerText();
 assert(gap.includes('approval is saved')&&gap.includes('Repetition')===false&&gap.includes('Repeating Context compression will not resolve it'));
 assert(await page.locator('#run-step').isDisabled());
 await page.screenshot({path:`${out}/live-adequacy-connection-gap.png`,fullPage:true});
 await page.route(`${base}/ui-api/workflow/sessions/${sid}`,async route=>{
  const response=await route.fetch(), value=await response.json(), n=value.nodes.find(n=>n.id==='context');
  const now=new Date().toISOString();
  const common={status:'RUNNING',monitor_current:true,process_alive:true,elapsed_seconds:90,timeout_seconds:null,
   started_at:now,last_checked_at:now,model_event_count:3,last_model_event_at:now,last_event_type:'item.completed',
   first_response_at:now,model_output_completed_at:now,model_turn_completed_at:null,cli_process_exited_at:null};
  const a={...common,stage:'context_faithfulness',stage_label:'Context faithfulness review',call_id:'synthetic:faith',phase:'MODEL_OUTPUT_RECEIVED_WAITING_TURN_END'};
  const b={...common,stage:'context_completeness',stage_label:'Context completeness review',call_id:'synthetic:complete',phase:'MODEL_TURN_COMPLETE_WAITING_CLI_EXIT',model_turn_completed_at:now,last_event_type:'turn.completed'};
  n.state={...n.state,execution:'RUNNING',approved:false,can_run:false,can_review:false,model_progress:{...a,parallel_calls:[a,b]}};
  await route.fulfill({response,json:value});
 });
 await page.goto(`${base}/?flow=${sid}#node=context&tab=context`);
 await page.locator('.model-progress').waitFor();
 assert.equal(await page.locator('.model-call').count(),2);
 const status=await page.locator('.model-progress').innerText();
 for(const term of ['Context faithfulness review','Context completeness review','waiting for turn completion','waiting for CLI exit','First assistant response','CLI process exited','Forced deadline: None']) assert(status.includes(term),term);
 await page.screenshot({path:`${out}/synthetic-parallel-progress.png`,fullPage:true});
 await page.setViewportSize({width:390,height:844});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 assert.deepEqual(errors,[]);
 await writeFile(`${out}/browser-report.json`,JSON.stringify({passed:true,live_read_only:true,telemetry_fixture:'browser interception only',errors},null,2));
 console.log('PASS: live adapter-gap explanation; parallel review telemetry; mobile layout; no JS errors.');
} finally {await browser.close();}
