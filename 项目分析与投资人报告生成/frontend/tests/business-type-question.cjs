const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
(async()=>{
  const browser=await chromium.launch({channel:'chrome',headless:true});
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[]; page.on('pageerror',error=>errors.push(error.message));
    const base='http://127.0.0.1:8020';
    const active=async()=>await page.evaluate(()=>{
      const state=JSON.parse(localStorage.getItem('bjs-console-v2'));
      return state.workspaces.flatMap(w=>w.conversations).find(c=>c.id===state.activeConversation);
    });
    await page.goto(`${base}/console/`);
    for(const [value,label] of [['增资','增资扩股'],['产权','股权转让（产权）']]) {
      await page.locator('[data-add="ws-default"]').click();
      await page.locator('#input').fill('请生成一页纸BP');
      await page.locator('#sendBtn').click();
      await page.locator('.approval-q').filter({hasText:'当前材料无法确定业务类型'}).waitFor();
      const first=await active();
      assert.equal(await page.locator('.approval-opt').count(),2);
      assert.equal(await page.getByText('确认无误',{exact:true}).count(),0);
      assert.equal(await page.getByText('有些出入',{exact:true}).count(),0);
      assert.equal(await page.getByText('跳过此步骤',{exact:true}).count(),0);
      await page.locator('.approval textarea').fill('请保留业务团队的介绍');
      await page.locator('.approval-send').click();
      assert((await page.locator('.approval-error').textContent()).includes('请先选择'));
      await page.getByText(label,{exact:true}).click();
      await page.reload();
      await page.locator('.approval-opt.selected').waitFor();
      assert.equal(await page.locator('.approval-opt.selected').getAttribute('data-value'),value);
      assert.equal(await page.locator('.approval textarea').inputValue(),'请保留业务团队的介绍');
      await page.screenshot({path:`.runtime/diagnostics/business-type-${value}.png`,fullPage:true});
      await page.locator('.approval-send').click();
      await page.locator('#runStatus').filter({hasText:'已完成'}).waitFor();
      assert.equal((await active()).taskId,first.taskId);
      const state=await (await page.request.get(`${base}/api/tasks/${first.taskId}/state`)).json();
      assert.equal(state.business_type_selection.value,value);
      assert.equal(state.business_type_selection.source,'user');
      assert.equal(state.pending_question,null);
      assert(state.turns.some(t=>t.role==='user' && t.text.includes('请保留业务团队的介绍')));
      assert((await page.locator('.doc-card').last().textContent()).includes(`${value}_一页纸.docx`));
    }
    // Recreate the reported stuck card in both persisted task state and browser event cache.
    const seeded=await (await page.request.post(`${base}/test/legacy-question`)).json();
    await page.evaluate(seed=>{
      const state=JSON.parse(localStorage.getItem('bjs-console-v2'));
      const workspace=state.workspaces.find(w=>w.id==='ws-default');
      const conversation={id:'legacy-screenshot',title:'旧空白业务卡片',mode:'live',messages:[{
        role:'user',text:'__legacy_empty_business_card__',runId:seed.run_id}],
        taskId:seed.task_id,lastRunId:seed.run_id,lastSeq:1,pendingQuestion:seed.pending,events:[seed.event]};
      workspace.conversations.unshift(conversation);
      state.activeConversation=conversation.id;
      localStorage.setItem('bjs-console-v2',JSON.stringify(state));
    },seeded);
    await page.reload();
    await page.locator('.approval-opt').first().waitFor();
    const restored=await (await page.request.get(`${base}/api/tasks/${seeded.task_id}/state`)).json();
    assert.equal(restored.pending_question.kind,'business_type');
    assert.equal(restored.pending_question.question_id,seeded.pending.question_id);
    assert.equal(await page.locator('.approval-opt').count(),2);
    assert(await page.locator('.approval textarea').isVisible());
    await page.screenshot({path:'.runtime/diagnostics/business-type-legacy-repaired.png',fullPage:true});
    await page.getByText('增资扩股',{exact:true}).click();
    await page.locator('.approval-send').click();
    await page.locator('#runStatus').filter({hasText:'已完成'}).waitFor();
    assert.equal((await active()).taskId,seeded.task_id);
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({passed:true,automaticCard:true,bothTypes:true,sameTask:true,legacyEmptyCardRepaired:true,refreshRestored:true,errors}));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
