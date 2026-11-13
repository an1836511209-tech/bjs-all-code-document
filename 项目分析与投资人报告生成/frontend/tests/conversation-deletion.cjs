const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({channel:'chrome',headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[]; page.on('pageerror',error=>errors.push(error.message));
    const base='http://127.0.0.1:8027';
    await page.goto(`${base}/console/`);
    const [deleted,kept]=await (await page.request.get(`${base}/test/tasks`)).json();
    const deleteButton=page.getByRole('button',{name:'删除会话：待删除会话',exact:true});
    await deleteButton.waitFor();
    const staleState=await page.evaluate(()=>localStorage.getItem('bjs-console-v2'));
    page.once('dialog',dialog=>dialog.dismiss());
    await deleteButton.click();
    assert(await deleteButton.isVisible());
    assert.equal((await (await page.request.get(`${base}/api/conversations`)).json()).items.length,2);
    // A failed DELETE must retain the entry and allow retry.
    await page.route('**/api/conversations/'+deleted,route=>route.fulfill({status:503,json:{detail:'删除暂不可用'}}));
    const alert=page.waitForEvent('dialog',d=>d.type()==='alert');
    page.once('dialog',dialog=>dialog.accept());
    await deleteButton.click();
    const failure=await alert; await failure.accept();
    await page.unroute('**/api/conversations/'+deleted);
    assert(await deleteButton.isVisible());
    page.once('dialog',dialog=>dialog.accept());
    await deleteButton.click();
    await deleteButton.waitFor({state:'detached'});
    assert.equal((await (await page.request.get(`${base}/api/conversations`)).json()).items[0].task_id,kept);
    // Simulate a second browser tab retaining the old local list.
    await page.evaluate(value=>localStorage.setItem('bjs-console-v2',value),staleState);
    await page.reload();
    await page.getByRole('button',{name:'删除会话：保留会话',exact:true}).waitFor();
    assert.equal(await deleteButton.count(),0);
    await page.evaluate(()=>localStorage.clear());
    await page.reload();
    await page.getByRole('button',{name:'删除会话：保留会话',exact:true}).waitFor();
    assert.equal(await deleteButton.count(),0);
    // Delete the selected last real conversation: switch to a usable empty chat.
    await page.locator('.convo').filter({hasText:'保留会话'}).click();
    page.once('dialog',dialog=>dialog.accept());
    await page.getByRole('button',{name:'删除会话：保留会话',exact:true}).click();
    await page.locator('#chatTitle').filter({hasText:'新对话'}).waitFor();
    assert(await page.locator('#input').isEnabled());
    // Local unsent conversations also support deletion.
    await page.locator('[data-add="ws-default"]').click();
    const localDeletes=page.getByRole('button',{name:'删除会话：新对话',exact:true});
    assert.equal(await localDeletes.count(),2);
    page.once('dialog',dialog=>dialog.accept());
    await localDeletes.first().click();
    assert.equal(await localDeletes.count(),1);
    // Running conversations cannot be deleted; the stop button remains available.
    await page.locator('#input').fill('持续运行');
    await page.locator('#sendBtn').click();
    await page.locator('#runStatus').filter({hasText:'执行中'}).waitFor();
    await page.waitForFunction(()=>document.querySelector('.convo.on')?.closest('.convo-row').querySelector('.convo-delete').disabled);
    await page.screenshot({path:'.runtime/diagnostics/conversation-delete.png',fullPage:true,animations:'disabled'});
    await page.locator('#attachBtn').click();
    await page.locator('#runStatus').filter({hasText:'执行中'}).waitFor({state:'hidden'});
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({passed:true,cancel:true,failureRetained:true,reload:true,clearCache:true,active:true,local:true,runningProtected:true}));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
