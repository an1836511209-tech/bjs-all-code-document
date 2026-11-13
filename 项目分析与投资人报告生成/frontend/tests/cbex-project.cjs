const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
(async () => {
  const browser = await chromium.launch({channel:'chrome',headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[]; page.on('pageerror',error=>errors.push(error.message));
    const base='http://127.0.0.1:8026';
    const name='某某科技有限公司100%股权转让';
    const getCalls=async()=>await (await page.request.get(`${base}/test/cbex_calls`)).json();
    await page.goto(`${base}/console/`);
    await page.locator('#input').fill('生成一页纸BP');
    await page.locator('#sendBtn').click();
    await page.locator('.cbex-listing').waitFor();
    assert(!await page.locator('.approval textarea').isVisible());
    await page.getByText('是，正在北交互联披露',{exact:true}).click();
    const input=page.getByRole('textbox',{name:'北交互联正在挂牌的项目全称'});
    assert.equal(await input.getAttribute('placeholder'),'输入北交互联正在挂牌的项目全称');
    assert.equal(await input.inputValue(),'');
    const inputBox=await input.boundingBox();
    const optionBox=await page.locator('.approval-opt').first().boundingBox();
    assert(inputBox.x>optionBox.x+optionBox.width);
    await page.locator('.approval-send').click();
    assert((await page.locator('.approval-error').textContent()).includes('项目全称'));
    assert.equal((await getCalls()).length,0);
    await input.fill(name);
    await page.reload();
    await input.waitFor();
    assert.equal(await input.inputValue(),name);
    await page.getByText('不是',{exact:true}).click();
    assert(!await input.isVisible());
    await page.getByText('是，正在北交互联披露',{exact:true}).click();
    assert.equal(await input.inputValue(),name);
    await page.screenshot({path:'.runtime/diagnostics/cbex-project-name.png',fullPage:true,animations:'disabled'});
    await page.locator('.approval-send').click();
    await page.getByText('请选择挂牌项目',{exact:true}).waitFor();
    assert.deepEqual(await getCalls(),[{project_name:name}]);
    assert.equal(await page.locator('.approval-opt').count(),2);
    assert((await page.locator('.approval-opt').first().textContent()).includes('2026-12-31'));
    assert((await page.locator('.approval-opt').last().textContent()).includes('信息披露截止日期：未披露'));
    assert.equal(await page.locator('.approval textarea').count(),0);
    await page.locator('.approval-opt').last().click();
    await page.reload();
    await page.locator('.approval-opt.selected').waitFor();
    await page.screenshot({path:'.runtime/diagnostics/cbex-project-candidates.png',fullPage:true,animations:'disabled'});
    await page.locator('.approval-send').click();
    await page.locator('#runStatus').filter({hasText:'已完成'}).waitFor();
    assert.deepEqual((await getCalls()).at(-1),{
      project_name:name+'（二次挂牌）',detail_url:'https://otc.cbex.com/cgq/detail/1002.html'});
    // No and unknown skip both the project-name requirement and MCP calls.
    for (const label of ['不是','不确定，按材料继续']) {
      await page.locator('[data-add="ws-default"]').click();
      await page.locator('#input').fill('生成一页纸BP');
      await page.locator('#sendBtn').click();
      await page.getByText(label,{exact:true}).click();
      await page.locator('.approval-send').click();
      await page.locator('#runStatus').filter({hasText:'已完成'}).waitFor();
    }
    assert.equal((await getCalls()).length,2);
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({passed:true,nameRequired:true,exactName:true,candidateUrl:true,draftRestore:true,skip:true}));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
