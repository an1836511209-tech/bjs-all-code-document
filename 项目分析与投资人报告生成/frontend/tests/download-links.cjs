const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({channel:'chrome', headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[]; page.on('pageerror', error=>errors.push(error.message));
    const base='http://127.0.0.1:8018';
    await page.goto(`${base}/console/`);
    const suffix=Date.now().toString().slice(-5);
    const companyA=`海康智联${suffix}`, companyB=`北京中科${suffix}`;
    async function publish(text, newChat) {
      if (newChat) await page.locator('[data-add="ws-default"]').click();
      await page.locator('#input').fill(text);
      await page.locator('#sendBtn').click();
      await page.locator('#runStatus').filter({hasText:'已完成'}).waitFor();
      return await page.evaluate(()=>{
        const state=JSON.parse(localStorage.getItem('bjs-console-v2'));
        return state.workspaces.flatMap(w=>w.conversations).find(c=>c.id===state.activeConversation);
      });
    }
    async function checkLinks(cardIndex=-1) {
      const card=page.locator('.doc-card').nth(cardIndex);
      await card.click();
      const preview=await page.locator('#paper a').getAttribute('href');
      const bodyLinks=await page.locator('.ai-text a').evaluateAll(links=>links.map(a=>a.href));
      assert(bodyLinks.includes(preview), `preview is absent from published reply: ${preview}`);
      assert(!preview.includes('X-Amz-'));
      assert(preview.startsWith(`${base}/api/artifacts/`));
      const response=await page.request.get(preview);
      assert.equal(response.status(),200);
      const artifactId=preview.split('/').at(-2);
      assert((await response.text()).includes(artifactId));
      return preview;
    }
    const a=await publish(companyA,true);
    const firstA=await checkLinks();
    const b=await publish(companyB,true);
    const firstB=await checkLinks();
    assert.notEqual(firstA,firstB);
    await page.locator('#closePreview').click();
    await page.locator('#previewToggle').click();
    assert.equal(await page.locator('#previewTitle').textContent(),'文件预览');
    assert(!(await page.locator('#paper').textContent()).includes(companyA));
    await page.locator('#previewToggle').click();
    assert(!await page.locator('#shell').evaluate(el=>el.classList.contains('has-preview')));
    await page.locator('.convo').filter({hasText:companyA}).click();
    assert.equal(await checkLinks(), firstA);
    await publish(`${companyA}版本二`,false);
    const secondA=await checkLinks();
    assert.notEqual(firstA,secondA);
    assert.equal(await checkLinks(0),firstA);
    // Simulate an old cache with a truncated URL, stale name, and foreign artifact.
    await page.evaluate(({aId,bId})=>{
      const state=JSON.parse(localStorage.getItem('bjs-console-v2'));
      const conversations=state.workspaces.flatMap(w=>w.conversations);
      const a=conversations.find(c=>c.id===aId), b=conversations.find(c=>c.id===bId);
      const own=a.events.find(e=>e.type==='artifact.created');
      own.payload.download_url='http://unused.test/truncated%E2%80%A6';
      own.payload.filename='串用的旧标题.docx';
      const foreign=JSON.parse(JSON.stringify(b.events.find(e=>e.type==='artifact.created')));
      foreign.run_id=a.lastRunId;
      a.events.push(foreign);
      for(const event of a.events.filter(e=>e.type==='run.completed')) {
        event.payload.assistant_text=event.payload.assistant_text.replace(/下载链接：[^\n]+/,'下载链接：http://unused.test/truncated…');
      }
      localStorage.setItem('bjs-console-v2',JSON.stringify(state));
    },{aId:a.id,bId:b.id});
    const restored=page.waitForResponse(r=>r.url().includes(`/api/tasks/${a.taskId}/state`));
    await page.reload(); await restored;
    await page.locator('.doc-card').filter({hasText:companyA}).first().waitFor();
    assert.equal(await page.locator('.doc-card').filter({hasText:companyB}).count(),0);
    assert.equal(await checkLinks(0),firstA);
    assert.equal(await checkLinks(),secondA);
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({passed:true,twoTasks:true,multipleVersions:true,legacyCacheRepaired:true,errors}));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
