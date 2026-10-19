// Synthetic server by default. The optional live check never submits or uploads.
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/georg/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json');
const {chromium}=require('playwright');
const base=process.env.CANVAS_URL, sid=process.env.CONTEXT_SESSION;
if(!base || !sid) throw Error('Explicit test URL and session are required');
const out=process.env.CONTEXT_CHECK_OUT || 'outputs/Context_Revision_Check';
await mkdir(out,{recursive:true});
const live=process.argv.includes('--live-read-only');
const executionRetry=process.argv.includes('--execution-retry');
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:1512,height:1080}});
const errors=[]; page.on('pageerror',e=>errors.push(e.message));
try {
 await page.goto(`${base}/?flow=${sid}#node=context&tab=context`);
 if(executionRetry) {
  await page.locator('#retry-context').waitFor();
  assert(await page.locator('#retry-context').isEnabled());
  assert.equal(await page.locator('#revise-context').count(),0);
  const panel=await page.locator('.execution-feedback').innerText();
  assert(panel.includes('600 seconds') && panel.includes('What to do next') && panel.includes('No proposal change'));
  assert(await page.locator('#run-step').isDisabled());
  await page.screenshot({path:`${out}/execution-feedback.png`,fullPage:true});
  const submitted=page.waitForResponse(r=>r.url().endsWith('/context-retries')&&r.request().method()==='POST');
  await page.locator('#retry-context').click();
  const response=await submitted; assert.equal(response.status(),202,await response.text());
  const next=await response.json(); await page.waitForURL(url=>url.searchParams.get('flow')===next.session_id);
  assert(next.nodes.every(n=>!n.state.approved));
  await page.locator('.model-progress').waitFor({state:'attached'});
  // Context output folders are collapsed by default; inspect their contents as a user would.
  const progressFolders=page.locator('.model-progress').locator('xpath=ancestor::details');
  for(let i=0;i<await progressFolders.count();i++) {
   const folder=progressFolders.nth(i);
   if(await folder.getAttribute('open')===null) await folder.locator(':scope > summary').click();
  }
  await page.locator('.model-progress').waitFor();
  assert((await page.locator('.model-progress').innerText()).includes('Forced deadline: None'));
  assert((await page.locator('#toast').innerText()).includes('Local process alive'));
  await page.screenshot({path:`${out}/heartbeat-message.png`,fullPage:true});
  assert.deepEqual(errors,[]);
  await writeFile(`${out}/execution-browser-report.json`,JSON.stringify({passed:true,synthetic_only:true,errors},null,2));
  console.log(JSON.stringify({passed:true,execution_retry:true,errors}));
 } else {
 await page.locator('#revise-context').waitFor();
 assert(await page.locator('#revise-context').isEnabled());
 assert(await page.locator('.context-feedback').innerText().then(t=>t.includes('Why this cannot pass')&&t.includes('What to change')));
 assert(await page.locator('#run-step').isDisabled());
 await page.screenshot({path:`${out}/${live?'live':'synthetic'}-feedback.png`,fullPage:true});
 await page.locator('#revise-context').click();
 const form=page.locator('#context-revision-form');
 assert.equal(await form.locator('[name=mode]').inputValue(),'REPAIR_EXTRACTION');
 await form.locator('[name=mode]').selectOption('REPLACE_PROPOSAL');
 assert(await page.locator('#choose-revision-proposal').isVisible());
 assert.equal(await form.locator('[name=proposal]').getAttribute('required'),'');
 await form.locator('[name=mode]').selectOption('REPAIR_EXTRACTION');
 await page.screenshot({path:`${out}/${live?'live':'synthetic'}-revision-form.png`,fullPage:true});
 if(!live) {
  await form.locator('[name=guidance]').fill('Synthetic extraction repair only.');
  await form.locator('[name=submitted_by]').fill('SYNTHETIC BROWSER TEST');
  await form.locator('[name=confirmed]').check();
  const submitted=page.waitForResponse(r=>r.url().endsWith('/context-revisions')&&r.request().method()==='POST');
  await form.locator('button[type=submit]').click();
  const response=await submitted; assert.equal(response.status(),202,await response.text());
  const next=await response.json();
  await page.waitForURL(url=>url.searchParams.get('flow')===next.session_id);
  assert.notEqual(next.session_id,sid);
  assert(next.nodes.every(n=>!n.state.approved));
  assert.equal(next.nodes.find(n=>n.id==='context').state.execution,'RUNNING');
 }
 await page.setViewportSize({width:390,height:844});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 assert.deepEqual(errors,[]);
 await writeFile(`${out}/${live?'live':'synthetic'}-browser-report.json`,JSON.stringify({passed:true,live_read_only:live,base,session:sid,errors},null,2));
 console.log(JSON.stringify({passed:true,live_read_only:live,errors}));
 }
} finally {await browser.close();}
