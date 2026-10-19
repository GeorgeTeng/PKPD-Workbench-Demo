// Read-only UI verification. No upload, run, model call, or human review is submitted.
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
const context = await browser.newContext({viewport:{width:1512,height:1080},acceptDownloads:true});
const page = await context.newPage();
const errors = [], requests = [], passed = [];
page.on('pageerror',e => errors.push(e.message));
page.on('response',r => {if(r.status() >= 400) errors.push(`${r.status()} ${r.url()}`);});
page.on('request',r => requests.push({method:r.method(),url:r.url()}));
try {
 await page.goto(base);
 await page.locator('.flow-node').first().waitFor();
 assert.equal(await page.locator('.flow-node').count(),10);
 assert.equal(await page.locator('.edge-link').count(),12);
 assert.equal(await page.locator('#file-count').textContent(),'0 attachments');
 assert.equal(await page.locator('#completion-count').textContent(),'0 / 10 steps cleared');
 assert(await page.locator('#run-step').isDisabled());
 assert(await page.locator('#add-files').isDisabled());
 assert(await page.locator('#pause-flow').isDisabled());
 assert.equal(await page.locator('#run-clock').textContent(),'00:00:00');
 assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),false);
 await page.screenshot({path:path.join(out,'canvas-desktop.png'),fullPage:true});
 passed.push('Empty homepage: ten clickable steps, twelve handoff/feedback links, no prefilled attachments or results');

 await page.locator('#node-context').click();
 await page.locator('[data-tab="context"]').click();
 await page.getByText('No actual context yet',{exact:true}).waitFor();
 for(const key of ['"version": "3.0"','"objective"','"study"','"rules"','"uncertainties"']) {
  assert((await page.locator('.json-preview').textContent()).includes(key));
 }
 await page.locator('[data-template="context"]').click();
 await page.locator('#modal[open]').waitFor();
 const templateDownload = page.waitForEvent('download');
 await page.locator('#download-template').click();
 assert.equal((await templateDownload).suggestedFilename(),'context.template.json');
 await page.locator('#close-modal').click();
 await page.screenshot({path:path.join(out,'context-template.png'),fullPage:true});
 passed.push('B1 3.0 template preview and labeled JSON template download');

 await page.locator('[data-edge="dispatch-pk"]').click();
 await page.locator('#inspector h2').filter({hasText:'Clinical questions & routing'}).waitFor();
 assert((await page.locator('.detail-body').textContent()).includes('pk_context.json'));
 assert((await page.locator('.detail-body').textContent()).includes('index_context.json'));
 await page.screenshot({path:path.join(out,'context-routing.png'),fullPage:true});
 passed.push('Branch handoff links show separate PK/index JSON contracts and receiving steps');

 await page.locator('[data-tab="clinical"]').click();
 await page.locator('#clinical-form').waitFor();
 assert.equal(await page.locator('#clinical-form textarea').count(),12);
 assert(await page.locator('#clinical-form button').isDisabled());
 await page.locator('#node-eda').click();
 await page.locator('[data-tab="eda"]').click();
 await page.locator('.eda-card').first().waitFor();
 assert.equal(await page.locator('.eda-card').count(),5);
 assert((await page.locator('.detail-body').textContent()).includes('flip-flop'));
 const edaDownload = page.waitForEvent('download');
 await page.locator('#download-eda').click();
 assert.equal((await edaDownload).suggestedFilename(),'eda_protocol.json');
 await page.screenshot({path:path.join(out,'eda-protocol.png'),fullPage:true});
 passed.push('Five verified EDA panels, scientific caveats, downloadable protocol and twelve clinical definitions');

 await page.locator('#node-results').click();
 await page.locator('#inspector h2').filter({hasText:'Model results'}).waitFor();
 await page.locator('[data-tab="review"]').click();
 await page.getByText('Automatic technical checks',{exact:true}).waitFor();
 assert(await page.locator('#run-step').isDisabled());
 assert.equal(await page.locator('#review-form').count(),0);
 assert((await page.locator('.detail-body').textContent()).includes('No separate human signature'));
 await page.reload();
 await page.locator('#inspector h2').filter({hasText:'Model results'}).waitFor();
 assert(await page.locator('#run-step').isDisabled());
 passed.push('Deep links survive reload; locked final join cannot run or submit a review');

 await page.locator('.rail-button[data-page="contracts"]').click();
 assert.equal(await page.locator('.contract-row').count(),10);
 assert((await page.locator('#list-panel').textContent()).includes('normalized/pk_observations.csv'));
 await page.locator('.rail-button[data-page="architecture"]').click();
 assert.equal(await page.locator('.architecture-stack>div').count(),3);
 await page.locator('.rail-button[data-page="rules"]').click();
 await page.locator('.rule-card').first().waitFor();
 assert.equal(await page.locator('.rule-card').count(),12);
 assert((await page.locator('.draft-banner').textContent()).includes('All disabled'));
 passed.push('Actual-data handoff contracts, three orchestration layers and twelve disabled rules for review');
 await page.locator('.rail-button[data-page="events"]').click();
 await page.getByText('No activity yet',{exact:true}).waitFor();
 await page.locator('.rail-button[data-page="canvas"]').click();
 const beforeZoom = await page.locator('#zoom-value').textContent();
 await page.locator('#zoom-in').click();
 assert.notEqual(await page.locator('#zoom-value').textContent(),beforeZoom);
 await page.locator('#fit').click();
 const definitionDownload = page.waitForEvent('download');
 await page.locator('#export-plan').click();
 assert.equal((await definitionDownload).suggestedFilename(),'research_workflow.definition.json');
 passed.push('Contracts, empty activity, zoom/fit and workflow definition export');

 await page.setViewportSize({width:390,height:844});
 await page.goto(base);
 await page.locator('.flow-node').first().waitFor();
 assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth),false);
 assert(await page.locator('#pause-flow').isVisible());
 assert(await page.locator('#run-clock').isVisible());
 await page.screenshot({path:path.join(out,'canvas-mobile.png'),fullPage:true});
 await page.locator('#node-context').click();
 await page.locator('[data-tab="context"]').click();
 assert(await page.locator('#run-step').isDisabled());
 passed.push('Mobile layout: local canvas scrolling, clickable nodes, no page overflow');

 assert.equal(requests.filter(r => r.method !== 'GET').length,0);
 assert.equal(requests.filter(r => /\/ui-api\/(runs|jobs|model)|\/pipeline\//.test(r.url)).length,0);
 assert.deepEqual(errors,[]);
 passed.push('Network audit: no uploads, execution, models, historical runs or hidden mutations');
 await writeFile(path.join(out,'report.json'),JSON.stringify({base,passed,errors,requests},null,2));
 console.log(JSON.stringify({base,passed,errors},null,2));
} finally {await browser.close();}
