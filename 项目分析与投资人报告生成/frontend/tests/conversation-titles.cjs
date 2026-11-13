// Test the actual title helpers without accessing a user's browser or the model.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('frontend/assets/modules/14-session.js','utf8');
function extract(name) {
  const sync=source.indexOf(`  function ${name}(`);
  const async=source.indexOf(`  async function ${name}(`);
  const start=sync>=0?sync:async;
  assert(start>=0);
  return source.slice(start,source.indexOf('\n  }',start)+4);
}
function fixture() {
  let resolve, calls=0;
  const conversation={id:'a',title:'新对话'};
  const context={AbortController,setTimeout,clearTimeout,
    ui:{activeConversation:'a'},el:{chatTitle:{textContent:''}},
    currentConversation:()=>conversation,getApiBase:()=>'',saveState(){},renderProjects(){},
    fetch:()=>{calls++;return new Promise(r=>{resolve=r;});}};
  vm.createContext(context);
  vm.runInContext(extract('fallbackTitle')+'\n'+extract('maybeAutoTitle'),context);
  return {context,conversation,calls:()=>calls,finish:title=>resolve({ok:true,json:async()=>({title})})};
}
(async()=>{
  {
    const f=fixture();
    const first=f.context.maybeAutoTitle('帮我生成一页纸BP',f.conversation);
    assert.equal(f.conversation.title,'帮我生成一页纸BP');
    assert.equal(f.context.el.chatTitle.textContent,'帮我生成一页纸BP');
    await f.context.maybeAutoTitle('用户正在补充消息',f.conversation);
    assert.equal(f.calls(),1);
    f.finish('智能标题');await first;
    assert.equal(f.conversation.title,'智能标题');
  }
  {
    const f=fixture();
    const first=f.context.maybeAutoTitle('新对话',f.conversation);
    f.finish('');await first;
    assert.equal(f.conversation.title,'新对话');
    await f.context.maybeAutoTitle('补充消息',f.conversation);
    assert.equal(f.calls(),1); // Persisted attempted flag matters even if fallback is literally 新对话.
  }
  {
    const f=fixture();
    const first=f.context.maybeAutoTitle('第一条消息',f.conversation);
    f.conversation.title='用户手动设置的标题';
    f.finish('迟到的智能标题');await first;
    assert.equal(f.conversation.title,'用户手动设置的标题');
  }
  console.log('3 title interaction regressions passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
