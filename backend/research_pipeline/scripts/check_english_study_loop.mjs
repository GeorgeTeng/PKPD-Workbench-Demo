// Check every English UI panel, then open a revision from a known synthetic intake.
import {createRequire} from 'node:module';
import {readFile,writeFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/georg/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json');
const {chromium}=require('playwright');
const base=process.env.CANVAS_URL || 'http://127.0.0.1:8771';
const out='outputs/Workflow_Canvas_Browser_Check';
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:1512,height:1080}});
const errors=[],checks=[];
page.on('pageerror',e=>errors.push(e.message));
async function englishOnly(label) {
 const text=await page.locator('body').innerText();
 const attributes=await page.locator('[placeholder],[aria-label],[title]').evaluateAll(nodes=>nodes.flatMap(n=>['placeholder','aria-label','title'].map(k=>n.getAttribute(k)||'')).join('\n'));
 assert(!/[\u4e00-\u9fff]/.test(text+'\n'+attributes),`${label}: untranslated interface text`);
}
try {
 await page.goto(base); await page.locator('#node-intake').waitFor();
 assert.equal(await page.locator('html').getAttribute('lang'),'en');
 const ids=await page.locator('.flow-node').evaluateAll(nodes=>nodes.map(n=>n.dataset.node));
 for(const id of ids) {
  await page.locator(`#node-${id}`).click();
  await page.waitForFunction(id=>document.querySelector('#inspector').dataset.scope?.includes(`:${id}:`),id);
  const tabs=await page.locator('[data-tab]').evaluateAll(nodes=>nodes.map(n=>n.dataset.tab));
  for(const tab of tabs) {
   await page.locator(`[data-tab="${tab}"]`).click();
   await page.waitForFunction(tab=>document.querySelector('#inspector').dataset.scope?.endsWith(`:${tab}`),tab);
   if(tab==='eda') await page.locator('.eda-card').first().waitFor();
   await englishOnly(`${id}/${tab}`);
  }
 }
 checks.push('All ten nodes and every inspector tab use English');
 for(const name of ['contracts','architecture','rules','events']) {
  await page.locator(`.rail-button[data-page="${name}"]`).click();
  if(name==='rules') await page.locator('.rule-card').first().waitFor();
  await englishOnly(name);
 }
 checks.push('Contracts, architecture, rule guidance, activity, placeholders and accessible labels use English');
 await page.locator('.rail-button[data-page="canvas"]').click();
 await page.locator('#study-loop-link').click();
 await page.locator('#cycle-form').waitFor();
 assert.equal(await page.locator('#cycle-form [name=change_type] option').count(),10);
 assert(await page.locator('#cycle-form button').isDisabled());
 await page.screenshot({path:`${out}/english-clinical-loop.png`,fullPage:true});
 const fixture=JSON.parse(await readFile(`${out}/execution-report.json`,'utf8'));
 assert(fixture.test_only);
 const session=fixture.session;
 const before=await (await page.request.get(`${base}/ui-api/workflow/sessions/${session}`)).json();
 const intake=before.nodes.find(n=>n.id==='intake').state;
 assert.equal(intake.execution,'COMPLETED'); assert.equal(intake.approved,false);
 const manifest=await (await page.request.get(`${base}/ui-api/workflow/sessions/${session}/nodes/intake/artifacts/manifest.json`)).text();
 assert(manifest.includes('synthetic_proposal') && manifest.includes('synthetic_pk'));
 await page.goto(`${base}/?flow=${session}#node=intake&tab=review`);
 await page.locator('#review-form').waitFor();
 assert.equal(await page.locator('#review-form [name=decision]').inputValue(),'APPROVE');
 assert.equal(await page.locator('#review-form [name=rationale]').getAttribute('required'),null);
 await page.locator('#study-loop-link').click(); await page.locator('#cycle-form').waitFor();
 assert(!(await page.locator('#cycle-form button').isDisabled()));
 await page.locator('#cycle-form [name=change_type]').selectOption('REVISE_PROPOSAL');
 await page.locator('#cycle-form [name=source_node]').selectOption('intake');
 await page.locator('#cycle-form [name=reason]').fill('Synthetic fixture: the proposal lacks a defined endpoint.');
 await page.locator('#cycle-form [name=requested_changes]').fill('Synthetic fixture: revise the proposal endpoint before any modeling.');
 await page.locator('#cycle-form [name=reviewer]').fill('AUTOMATED ENGINEERING FIXTURE');
 await page.locator('#cycle-form [name=confirmed]').check();
 const responsePromise=page.waitForResponse(r=>r.url().endsWith(`/sessions/${session}/cycles`) && r.request().method()==='POST');
 await page.locator('#cycle-form button').click();
 const response=await responsePromise; assert.equal(response.status(),201);
 const result=await response.json();
 assert.equal(result.request.change_type,'REVISE_PROPOSAL');
 assert.equal(result.request.source_node,'intake');
 assert.equal(result.request.entry_stage,'intake');
 assert.equal(result.request.scientific_acceptance,false);
 assert.equal(result.new_session.stats.approved,0);
 const after=await (await page.request.get(`${base}/ui-api/workflow/sessions/${session}`)).json();
 assert.equal(after.nodes.find(n=>n.id==='intake').state.approved,false);
 assert.equal(after.can_publish,false);
 await page.locator('#modal[open]').waitFor();
 await page.locator('#modal a').filter({hasText:'Open next cycle'}).click();
 await page.locator('.cycle-note').waitFor();
 assert((await page.locator('.cycle-note').innerText()).includes('revise the proposal endpoint'));
 assert.equal(await page.locator('#file-count').textContent(),'0 attachments');
 assert.equal(new URLSearchParams(new URL(page.url()).hash.slice(1)).get('node'),'intake');
 await englishOnly('new cycle');
 checks.push('Proposal revision can start from synthetic intake before modeling; new input review is required and prior results stay unapproved');
 await page.goto(base); await page.locator('#node-intake').waitFor();
 assert.equal(await page.locator('#file-count').textContent(),'0 attachments');
 assert.deepEqual(errors,[]);
 const report={base,passed:true,checks,errors,test_only:true,new_cycle:result.new_session.session_id,scientific_release:false};
 await writeFile(`${out}/english-study-loop-report.json`,JSON.stringify(report,null,2));
 console.log(JSON.stringify(report,null,2));
} finally {await browser.close();}
