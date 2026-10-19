// Real local stack + browser checks. All inputs and review attestations are synthetic.
import {createRequire} from 'node:module';
import {mkdir,writeFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const require=createRequire('C:/Users/georg/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json');
const {chromium}=require('playwright');
const base=process.env.CANVAS_URL || 'http://127.0.0.1:8772';
const out='outputs/Supplemental_Branch_Check'; await mkdir(out,{recursive:true});
const browser=await chromium.launch({channel:'msedge',headless:true});
const page=await browser.newPage({viewport:{width:1512,height:1080}});
const errors=[], checks=[]; page.on('pageerror',e=>errors.push(e.message));
let session,branch;
async function waitBranch(id) {
 for(let i=0;i<120;i++) {
  const value=await (await page.request.get(`${base}/ui-api/workflow/sessions/${session}/supplements/${id}`)).json();
  if(['WAITING_FOR_REVIEW','BLOCKED','FAILED','STALE'].includes(value.status)) return value;
  await new Promise(r=>setTimeout(r,1000));
 }
 throw Error('Supplemental execution did not finish within the test deadline');
}
try {
 await page.goto(base); await page.locator('#node-intake').waitFor();
 await page.locator('[data-page="supplements"]').click();
 assert(await page.locator('#supplement-form button[type=submit]').isDisabled());
 await page.locator('#create-flow').click();
 await page.waitForURL(/flow=/); session=new URL(page.url()).searchParams.get('flow');
 await page.locator('[data-page="supplements"]').click();
 const form=page.locator('#supplement-form');
 await form.locator('[name="label"]').fill('SYNTHETIC ENGINEERING TEST — supplemental rat PK');
 await form.locator('[name="target_pk"]').check();
 const values={drug:'PMB',species:'rat',route:'IV',matrix:'plasma',concentration_basis:'total',record_level:'individual',sampling_design:'serial',time_unit:'h',concentration_unit:'mg/L',dose_unit:'mg'};
 for(const [name,value] of Object.entries(values)) await form.locator(`[name="${name}"]`).fill(value);
 const rows='subject_id,time_h,concentration_mg_L\n'+Array.from({length:6},(_,i)=>`SYNTHETIC_R1,${i},${10*Math.exp(-i/2)}\n`).join('');
 await form.locator('[name="files"]').setInputFiles({name:'synthetic_supplement.csv',mimeType:'text/csv',buffer:Buffer.from(rows)});
 await form.locator('summary').click();
 await form.locator('[name="config"]').fill(JSON.stringify({column_map:{},metadata:{formulation:'synthetic solution',parameter_definition:'Synthetic concentration'},analysis_options:{mode:'individual',doses:[{time_h:0,duration_h:0,dose_mg:1}]},evidence_locators:[{type:'SYNTHETIC_TEST_ONLY'}]},null,2));
 const registered=page.waitForResponse(r=>r.url().endsWith('/supplements')&&r.request().method()==='POST');
 await form.locator('button[type=submit]').click(); const response=await registered; assert.equal(response.status(),201); branch=(await response.json()).id;
 await page.locator(`[data-supp-action="start"][data-branch="${branch}"]`).click();
 const result=await waitBranch(branch); assert.equal(result.status,'WAITING_FOR_REVIEW',JSON.stringify(result));
 assert.equal(result.runtime.control.controller,'LangGraph');
 assert.equal(result.runtime.control.scheduler,'Prefect'); assert.equal(result.runtime.control.file_executor,'Snakemake');
 assert.equal(result.artifacts.filter(a=>a.kind==='figure').length,3);
 checks.push('Real LangGraph -> Prefect -> Snakemake preparation and EDA; three generated PNGs and one metadata sidecar');
 await page.reload(); await page.locator('[data-page="supplements"]').click();
 await page.locator(`[data-supp-review="${branch}"]`).click();
 const review=page.locator('#supp-review-form');
 assert.equal(await review.locator('[name="decision"]').inputValue(),'APPROVE');
 assert.equal(await review.locator('[name="rationale"]').getAttribute('required'),null);
 await review.locator('[name="reviewer"]').fill('AUTOMATED SYNTHETIC FIXTURE ONLY'); await review.locator('[name="confirmed"]').check();
 const reviewed=page.waitForResponse(r=>r.url().endsWith(`/${branch}/review`)&&r.request().method()==='POST');
 await review.locator('button').click(); assert.equal((await reviewed).status(),200);
 await page.locator('[data-supp-file="handoff_pk.json"]').waitFor();
 await page.screenshot({path:`${out}/supplemental-desktop.png`,fullPage:true});
 const handoff=await (await page.request.get(`${base}/ui-api/workflow/sessions/${session}/nodes/pk/supplements`)).json();
 assert.equal(handoff.inputs.length,1); assert.equal(handoff.replaces_main_prerequisites,false);
 checks.push('One combined review, optional approval comment, scoped PK handoff and retained main gates');
 await page.locator('[data-supp-file$="_linear.png"]').click();
 await page.locator('.supplement-figure').waitFor();
 await page.screenshot({path:`${out}/eda-preview.png`,fullPage:true}); await page.locator('#close-modal').click();
 // A second synthetic input deliberately omits units to test missing-material feedback.
 const uploaded=await (await page.request.post(`${base}/pipeline/v1/attachments`,{multipart:{file:{name:'synthetic_missing_units.csv',mimeType:'text/csv',buffer:Buffer.from(rows)}}})).json();
 const invalid={label:'SYNTHETIC — missing units',targets:['pk'],datasets:[{id:'missing_units',upload_id:uploaded.upload_id,metadata:{role:'pk_observations',drug:'PMB',analyte:'PMB',species:'rat',route:'IV',matrix:'plasma',concentration_basis:'total',record_level:'individual'},analysis_options:{}}]};
 const invalidBranch=await (await page.request.post(`${base}/ui-api/workflow/sessions/${session}/supplements`,{data:invalid})).json();
 assert.equal((await page.request.post(`${base}/ui-api/workflow/sessions/${session}/supplements/${invalidBranch.id}/start`)).status(),202);
 const blocked=await waitBranch(invalidBranch.id); assert.equal(blocked.status,'BLOCKED');
 assert(blocked.feedback.missing_materials.length);
 await page.reload(); await page.locator('[data-page="supplements"]').click();
 await page.getByRole('heading',{name:'Why this cannot pass',exact:true}).waitFor();
 await page.getByRole('heading',{name:'Missing data or materials',exact:true}).waitFor();
 await page.screenshot({path:`${out}/missing-materials.png`,fullPage:true});
 assert.equal((await page.request.get(`${base}/ui-api/workflow/sessions/${session}/nodes/pk/supplements`)).status(),409);
 checks.push('Missing units produce explicit reasons/materials and prevent downstream delivery');
 await page.setViewportSize({width:390,height:844});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await page.screenshot({path:`${out}/supplemental-mobile.png`,fullPage:true});
 assert.deepEqual(errors,[]);
 await writeFile(`${out}/browser-report.json`,JSON.stringify({passed:true,test_only:true,scientific_release:false,base,session,branch,checks,errors},null,2));
 console.log(JSON.stringify({passed:true,session,checks,errors}));
} finally {await browser.close();}
