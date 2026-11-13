const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');

(async () => {
  const browser = await chromium.launch({ channel:'chrome', headless:true });
  try {
    const page = await browser.newPage({ viewport:{ width:1280, height:950 } });
    const errors = [];
    const submissions = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('request', request => {
      if (request.method() === 'POST' && request.url().endsWith('/api/runs')) submissions.push(request);
    });
    let feature = { enabled:false, worker_online:false };
    let unavailable = false;
    await page.route('**/api/features', route => unavailable
      ? route.fulfill({ status:503, json:{ detail:'unavailable' } })
      : route.fulfill({ json:{ institution_workbook:feature } }));
    await page.goto('http://127.0.0.1:8024/console/');
    await page.locator('#workbookStatus').filter({ hasText:'当前服务未启用' }).waitFor();
    assert.equal(await page.locator('#institutionWorkbook').isDisabled(), true);
    assert.equal(await page.locator('#urlBtn').isVisible(), false);
    assert.equal(await page.locator('#attachBtn').isVisible(), true);

    // A stopped worker does not prevent selecting the preference. Retrying capabilities
    // after a backend restart must work without reloading or starting a report.
    feature = { enabled:true, worker_online:false };
    await page.locator('[data-workbook="status"]').click();
    await page.locator('#institutionWorkbook:not(:disabled)').waitFor();
    await page.locator('#workbookStatus').filter({ hasText:'附件生成服务未启动' }).waitFor();
    await page.locator('#institutionWorkbook').check();
    await page.locator('#workbookStatus').filter({ hasText:'已选择附带匹配表' }).waitFor();
    const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('bjs-console-v2')));
    const active = saved.workspaces.flatMap(w => w.conversations).find(c => c.id === saved.activeConversation);
    assert.equal(active.institutionWorkbook, true);

    unavailable = true;
    await page.locator('[data-workbook="status"]').click();
    await page.locator('#workbookStatus').filter({ hasText:'暂时无法读取附件功能状态' }).waitFor();
    assert.equal(await page.locator('#institutionWorkbook').isDisabled(), true);
    unavailable = false;
    feature = { enabled:true, worker_online:true };
    await page.locator('[data-workbook="status"]').click();
    await page.locator('#institutionWorkbook:not(:disabled)').waitFor();
    assert.equal(await page.locator('#institutionWorkbook').isChecked(), true);
    assert.equal((await page.locator('#workbookStatus').textContent()).trim(), '已选择附带匹配表，报告完成后独立生成。');
    assert.equal(submissions.length, 0);
    assert.deepEqual(errors, []);
    await page.screenshot({ path:'.runtime/diagnostics/workbook-controls.png', fullPage:true });
    console.log(JSON.stringify({ passed:true, disabledReasonVisible:true, workerOfflineSelectable:true,
      recoversWithoutReload:true, urlHidden:true, reportSubmissions:submissions.length }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
