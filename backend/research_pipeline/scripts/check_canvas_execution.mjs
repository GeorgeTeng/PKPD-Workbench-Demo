// Isolated engineering fixture only: real upload + intake, no LLM or scientific fit.
import {createRequire} from 'node:module';
import {mkdir, writeFile} from 'node:fs/promises';
import path from 'node:path';
import assert from 'node:assert/strict';
const require = createRequire('C:/Users/georg/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json');
const {chromium} = require('playwright');
const base = process.env.CANVAS_URL || 'http://127.0.0.1:8771';
const out = path.resolve('outputs/Workflow_Canvas_Browser_Check');
await mkdir(out,{recursive:true});
const browser = await chromium.launch({channel:'msedge',headless:true});
const context = await browser.newContext({viewport:{width:1512,height:1080}});
const page = await context.newPage();
const errors = [], requests = [];
page.on('pageerror',e => errors.push(e.message));
page.on('response',r => {if(r.status() >= 400) errors.push(`${r.status()} ${r.url()}`);});
page.on('request',r => requests.push({method:r.method(),url:r.url()}));
try {
 await page.goto(base);
 await page.locator('#node-intake').waitFor();
 await page.locator('#create-flow').click();
 await page.waitForURL(/flow=flow_/);
 const session = new URL(page.url()).searchParams.get('flow');
 await page.locator('#pause-flow').click();
 await page.locator('#pause-flow').filter({hasText:'Resume'}).waitFor();
 assert(await page.locator('#run-step').isDisabled());
 await page.locator('#pause-flow').click();
 await page.locator('#pause-flow').filter({hasText:'Pause'}).waitFor();
 await page.locator('#flow-files').setInputFiles([
  {name:'synthetic_proposal.txt',mimeType:'text/plain',buffer:Buffer.from('Synthetic engineering check only. Polymyxin B PK research input registration; no scientific fitting or clinical conclusion.')},
  {name:'synthetic_pk.csv',mimeType:'text/csv',buffer:Buffer.from('subject_id,time_h,concentration_mg_L\nfixture_1,0,0\nfixture_1,1,2\n')}
 ]);
 await page.waitForFunction(() => document.querySelector('#run-step')?.disabled === false);
 await page.locator('#run-step').click();
 await page.waitForFunction(() => document.querySelector('#run-clock').textContent !== '00:00:00',{},{timeout:30000});
 await page.locator('[data-tab="review"]').click();
 await page.locator('#review-form').waitFor({timeout:60000});
 const response = await (await context.request.get(`${base}/ui-api/workflow/sessions/${session}`)).json();
 const intake = response.nodes.find(n=>n.id==='intake').state;
 assert.equal(intake.execution,'COMPLETED');
 assert.equal(intake.langgraph_review.status,'INTERRUPTED');
 assert(intake.timing.elapsed_seconds > 0);
 assert(intake.artifacts.some(a=>a.name.endsWith('.csv')));
 assert(intake.artifacts.some(a=>a.name.endsWith('.json')));
 assert.equal(response.nodes.find(n=>n.id==='context').state.can_run,false);
 const elapsed = await page.locator('#run-clock').textContent();
 await page.locator('[data-tab="files"]').click();
 await page.locator('[data-artifact="manifest.json"]').waitFor();
 await page.locator('[data-artifact="manifest.json"]').click();
 await page.locator('#modal[open]').waitFor();
 assert((await page.locator('#modal-body').textContent()).includes('synthetic'));
 await page.locator('#close-modal').click();
 await page.screenshot({path:path.join(out,'intake-real-execution.png'),fullPage:true});
 await page.reload();
 await page.locator('[data-artifact="manifest.json"]').waitFor();
 assert.equal(await page.locator('#run-clock').textContent(),elapsed);
 await page.locator('#node-context').click();
 await page.locator('#inspector h2').filter({hasText:'Context compression'}).waitFor();
 assert(await page.locator('#run-step').isDisabled());
 // Return to the default empty framework; no historical session is auto-selected.
 await page.goto(base);
 await page.locator('#node-intake').waitFor();
 assert.equal(await page.locator('#file-count').textContent(),'0 attachments');
 assert(!requests.some(r=>/\/model\/test|\/nodes\/context\/start/.test(r.url)));
 assert.deepEqual(errors,[]);
 const report={base,session,test_only:true,passed:true,errors,elapsed_seconds:intake.timing.elapsed_seconds,
  checks:['empty session pause/resume','actual synthetic attachment upload','real intake worker and elapsed clock',
   'actual JSON plus CSV downloads','LangGraph persistent review interrupt','unapproved context remains locked',
   'reload preserves outputs and stopped clock','default homepage stays empty'],llm_calls:0,requests};
 await writeFile(path.join(out,'execution-report.json'),JSON.stringify(report,null,2));
 console.log(JSON.stringify({...report,requests:undefined},null,2));
} finally {await browser.close();}
