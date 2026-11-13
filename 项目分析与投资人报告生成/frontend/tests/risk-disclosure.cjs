const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[]; page.on('pageerror',e=>errors.push(e.message));
    const base='http://127.0.0.1:8028';
    await page.goto(base+'/console/');
    const results=async()=>await (await page.request.get(base+'/test/results')).json();
    for(const [choice,label,title] of [['show','展示','风险提示'],['hide','不展示','项目布局']]) {
      await page.locator('[data-add="ws-default"]').click();
      await page.locator('#input').fill('生成一页纸BP');
      await page.locator('#sendBtn').click();
      await page.locator('.approval-q').filter({hasText:'非优质项目信息'}).waitFor();
      assert.equal(await page.locator('.approval-opt').count(),2);
      assert((await page.locator('.approval-q').textContent()).includes('关联方担保'));
      assert((await page.locator('.approval-q').textContent()).includes('未决诉讼'));
      const before=(await results()).length;
      await page.locator('.approval textarea').fill('请按原文处理');
      await page.locator('.approval-send').click();
      assert((await page.locator('.approval-error').textContent()).includes('请选择展示或不展示'));
      assert.equal((await results()).length,before);
      await page.getByText(label,{exact:true}).click();
      await page.reload();
      await page.locator('.approval-opt.selected').waitFor();
      assert.equal(await page.locator('.approval-opt.selected').textContent().then(s=>s.trim()),label);
      assert.equal(await page.locator('.approval textarea').inputValue(),'请按原文处理');
      await page.screenshot({path:`.runtime/diagnostics/risk-disclosure-${choice}.png`,fullPage:true,animations:'disabled'});
      await page.locator('.approval-send').click();
      await page.locator('#runStatus').filter({hasText:'已完成'}).waitFor();
      const last=(await results()).at(-1);
      assert.equal(last.choice.value,choice);
      assert.equal(last.choice.supplement,'请按原文处理');
      assert.equal(last.result.intro_titles[2],title);
      assert.deepEqual(last.choice.risk_items,['关联方担保','未决诉讼']);
    }
    await page.locator('[data-add="ws-default"]').click();
    await page.locator('#input').fill('无风险');
    await page.locator('#sendBtn').click();
    await page.locator('#runStatus').filter({hasText:'已完成'}).waitFor();
    assert.equal(await page.locator('.approval').count(),0);
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({passed:true,show:true,hide:true,noRiskSkips:true,required:true,draftRestored:true}));
  } finally { await browser.close(); }
})().catch(e=>{console.error(e);process.exitCode=1;});
