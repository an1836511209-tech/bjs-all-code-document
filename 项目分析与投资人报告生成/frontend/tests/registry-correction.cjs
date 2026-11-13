const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({channel:'chrome',headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[]; page.on('pageerror',error=>errors.push(error.message));
    const base='http://127.0.0.1:8019';
    await page.goto(`${base}/console/`);
    const getCalls=async()=>await (await page.request.get(`${base}/test/registry_calls`)).json();
    const active=async()=>await page.evaluate(()=>{
      const state=JSON.parse(localStorage.getItem('bjs-console-v2'));
      return state.workspaces.flatMap(w=>w.conversations).find(c=>c.id===state.activeConversation);
    });
    async function start(){
      await page.locator('[data-add="ws-default"]').click();
      await page.locator('#input').fill('生成一页纸BP');
      await page.locator('#sendBtn').click();
      await page.locator('.approval-q').filter({hasText:'当前公司名称无法获取企查查数据，请提供精确名称。'}).waitFor();
      return await active();
    }
    const first=await start();
    assert.equal(await page.locator('.approval-opt').count(),2);
    assert(!await page.locator('.approval textarea').isVisible());
    await page.getByText('填写精确名称',{exact:true}).click();
    assert(await page.locator('.approval textarea').isVisible());
    await page.locator('.approval-send').click();
    assert((await page.locator('.approval-error').textContent()).includes('请输入精确名称'));
    await page.locator('.approval textarea').fill('精确登记名称科技有限公司');
    await page.reload();
    await page.locator('.approval textarea').waitFor({state:'visible'});
    assert.equal(await page.locator('.approval textarea').inputValue(),'精确登记名称科技有限公司');
    await page.screenshot({path:'.runtime/diagnostics/registry-name-card.png',fullPage:true});
    await page.locator('.approval-send').click();
    await page.locator('#runStatus').filter({hasText:'已完成'}).waitFor();
    assert.equal((await active()).taskId,first.taskId);
    assert.equal((await getCalls()).at(-1),'精确登记名称科技有限公司');
    const second=await start();
    const before=(await getCalls()).length;
    await page.getByText('跳过此步骤',{exact:true}).click();
    await page.locator('.approval-send').click();
    await page.locator('#runStatus').filter({hasText:'已完成'}).waitFor();
    assert.equal((await active()).taskId,second.taskId);
    assert.equal((await getCalls()).length,before);
    const snapshot=await (await page.request.get(`${base}/api/tasks/${second.taskId}/state`)).json();
    assert.equal(snapshot.registry_lookup.status,'skipped');
    assert(snapshot.turns.some(t=>t.role==='user' && t.text.includes('跳过企查查')));
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({passed:true,retryUsesExactName:true,skipMakesNoCall:true,sameTask:true,errors}));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
