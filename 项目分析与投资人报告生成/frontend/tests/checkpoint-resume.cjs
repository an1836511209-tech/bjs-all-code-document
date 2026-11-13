const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[]; page.on('pageerror',err=>errors.push(err.message));
    const base='http://127.0.0.1:8023';
    const active=()=>page.evaluate(()=>{
      const state=JSON.parse(localStorage.getItem('bjs-console-v2'));
      return state.workspaces.flatMap(w=>w.conversations).find(c=>c.id===state.activeConversation);
    });
    await page.goto(`${base}/console/`);
    await page.locator('[data-add="ws-default"]').click();
    await page.locator('#skillSelect').selectOption('one-pager');
    await page.locator('#input').fill('请生成一页纸BP');
    await page.locator('#sendBtn').click();
    await page.locator('.approval-q').filter({hasText:'业务类型'}).waitFor();
    let conversation=await active();
    const taskId=conversation.taskId;
    const first=await (await page.request.get(`${base}/api/tasks/${taskId}/state`)).json();
    assert.equal(first.pending_question.checkpointed,true);
    assert.deepEqual(first.execution.plan.slice(0,2).map(x=>x.status),['completed','completed']);
    await page.reload();
    await page.locator('.approval-q').filter({hasText:'业务类型'}).waitFor();
    assert.equal(await page.locator('.card.plan').last().locator('.plan-step.done').count(),2);
    await page.locator('.approval-opt').filter({hasText:'增资扩股'}).click();
    await page.locator('.approval textarea').fill('融资5000万元，请保留现有团队');
    await page.locator('.approval-send').click();
    await page.locator('.approval-q').filter({hasText:'北交互联'}).waitFor();
    assert.equal((await active()).taskId,taskId);
    assert.equal(await page.locator('.card.plan').last().locator('.plan-step.done').count(),2);
    const second=await (await page.request.get(`${base}/api/tasks/${taskId}/state`)).json();
    assert(second.turns.some(t=>t.text.includes('5000万元')));
    assert.notEqual(first.pending_question.question_id,second.pending_question.question_id);
    assert.deepEqual(await (await page.request.get(`${base}/api/testing/counts`)).json(),{parse:1,detect:1,labels:1});
    await page.reload();
    await page.locator('.approval-q').filter({hasText:'北交互联'}).waitFor();
    assert.equal(await page.locator('.approval-opt').count(),3);
    await page.locator('.approval-opt').filter({hasText:'不是'}).click();
    await page.locator('.approval-send').click();
    await page.locator('#runStatus').filter({hasText:'已完成'}).waitFor();
    assert.deepEqual(await (await page.request.get(`${base}/api/testing/counts`)).json(),{parse:1,detect:1,labels:1});
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({passed:true,taskId,parse:1,labels:1,browserErrors:errors}));
  } finally { await browser.close(); }
})().catch(err=>{console.error(err);process.exitCode=1;});
