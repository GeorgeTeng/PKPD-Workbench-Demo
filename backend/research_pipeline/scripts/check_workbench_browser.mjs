import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
const require=createRequire('C:/Users/georg/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright/package.json');
const {chromium}=require('playwright');
const out=path.resolve('outputs/Workbench_Browser_Check_02');await mkdir(out,{recursive:true});
const browser=await chromium.launch({channel:'msedge',headless:true});
const context=await browser.newContext({viewport:{width:1512,height:1080},acceptDownloads:true,reducedMotion:'reduce'});
const page=await context.newPage();const errors=[];const results=[];
page.on('pageerror',e=>errors.push(e.message));
page.on('response',r=>{if(r.status()>=400)errors.push(`${r.status()} ${r.url()}`)});
try{
 await page.goto('http://127.0.0.1:8767');await page.getByRole('heading',{name:'研究工作台',exact:true}).waitFor();
 await page.screenshot({path:path.join(out,'overview-desktop.png'),fullPage:true});
 results.push('Overview loaded from actual run');
 for(const [id,heading] of [['proposal','研究任务'],['data','数据准备'],['pk','动物 PK 建模'],['index','最佳 index 筛选'],['library','模型与文献库'],['review','人工审核']]){
  await page.locator(`nav a[href="#${id}"]`).click();await page.getByRole('heading',{name:heading,exact:true}).waitFor();results.push(id+' view rendered');
 }
 await page.locator('nav a[href="#data"]').click();await page.locator('#dataset-search').fill('rat_plasma_IV');
 if(await page.locator('#dataset-table tbody tr').count()!==1)throw Error('Dataset search did not isolate rat table');
 await page.getByRole('button',{name:'预览数据 ↗'}).click();await page.locator('#next-page').waitFor();
 await page.locator('#next-page').click();await page.getByText('31–60 / 110',{exact:true}).waitFor();
 await page.screenshot({path:path.join(out,'dataset-preview.png'),fullPage:true});
 const downloadPromise=page.waitForEvent('download');await page.getByRole('button',{name:'导出完整 CSV'}).click();
 const download=await downloadPromise;if(download.suggestedFilename()!=='rat_plasma_IV.csv')throw Error('Wrong download');
 await page.locator('#close-modal').click();results.push('Dataset filter, pagination and CSV download');
 await page.locator('nav a[href="#pk"]').click();await page.locator('img.diagnostic').waitFor();
 await page.waitForFunction(()=>document.querySelector('img.diagnostic')?.naturalWidth>0);
 await page.screenshot({path:path.join(out,'pk-desktop.png'),fullPage:true});
 for(const species of ['rat_individual','mouse','rabbit','elf','rat']){await page.locator(`[data-species="${species}"]`).click();}
 results.push('All species tabs and diagnostic image');
 await page.locator('nav a[href="#library"]').click();await page.locator('#model-search').fill('PK_SYS_2C_LIN');
 if(await page.locator('.model-card').count()!==1)throw Error('Model filter failed');
 await page.locator('[data-library="papers"]').click();await page.locator('#paper-query').fill('clearance');
 await page.locator('#paper-search button[type="submit"]').click();await page.getByRole('heading',{name:'没有检索到结果'}).waitFor();
 results.push('Local model search and empty literature search');
 await page.locator('nav a[href="#review"]').click();await page.locator('#reviewer').fill('');
 if(await page.locator('#review-form').evaluate(el=>el.checkValidity()))throw Error('Review form should require human input');
 results.push('Review form requires actual inputs; no real scientific review submitted');
 await page.setViewportSize({width:390,height:844});await page.goto('http://127.0.0.1:8767/#overview');
 await page.getByRole('heading',{name:'研究工作台',exact:true}).waitFor();
 await page.screenshot({path:path.join(out,'overview-mobile.png'),fullPage:true});
 if(await page.locator('#sidebar').isVisible())throw Error('Closed mobile sidebar must be hidden');
 if(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+2))throw Error('Mobile horizontal overflow');
 await page.locator('#menu').click();await page.locator('nav a[href="#pk"]').click();
 await page.getByRole('heading',{name:'动物 PK 建模',exact:true}).waitFor();
 results.push('390 px layout and mobile navigation');
 await page.setViewportSize({width:1512,height:1080});
 await page.locator('#new-run').click();await page.locator('#package-file').setInputFiles('C:/Users/georg/Documents/Transitioanl PKPD Context Engineering/PMB_Translational_PKPD_Project/FINAL_DELIVERY/PMB_Agent_Ready_Package.zip');
 await page.locator('#stop-after').selectOption('intake');
 const submitted=page.waitForResponse(r=>r.url().endsWith('/ui-api/jobs')&&r.request().method()==='POST');
 await page.locator('#new-run-form button[type="submit"]').click();
 const submission=await submitted;
 if(submission.status()!==202)throw Error('Job submission failed: '+await submission.text());
 const job=await submission.json();
 await page.locator('#job-banner').waitFor({state:'visible'});
 results.push('Fresh ZIP uploaded without baseline; Prefect job accepted: '+job.id);
 if(errors.length)throw Error(errors.join('\n'));
 await writeFile(path.join(out,'browser-check.json'),JSON.stringify({status:'PASSED',checks:results,page_errors:errors,started_job:job.id},null,2));
 console.log(JSON.stringify({status:'PASSED',checks:results,started_job:job.id}));
}catch(e){await page.screenshot({path:path.join(out,'failure.png'),fullPage:true});await writeFile(path.join(out,'browser-check.json'),JSON.stringify({status:'FAILED',checks:results,errors:[e.message,...errors]},null,2));throw e}
finally{await browser.close()}
