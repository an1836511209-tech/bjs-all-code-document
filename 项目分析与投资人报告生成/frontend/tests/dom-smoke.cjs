#!/usr/bin/env node
/**
 * 纯 CDP 冒烟测试（零 npm 依赖，Node 24 内置 WebSocket）：
 * 打开 console 页面，检查
 *   1. 没有未捕获异常 / console.error
 *   2. #skillSelect 始终落在真实选项上（P0-1）
 *   3. 窄屏下 #convosToggle 可见，点击能拉开侧栏（P0-2）
 *   4. 焦点环样式生效（P0-3）
 *
 * 用法：node frontend/tests/dom-smoke.cjs [url]
 *   默认 url = http://127.0.0.1:8000/console/
 * 环境变量：CHROME_PATH 指定浏览器，缺省用系统 Chrome。
 */
'use strict';

const { spawn } = require('node:child_process');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const URL_ARG = process.argv[2] || 'http://127.0.0.1:8000/console/';
const CHROME = process.env.CHROME_PATH
  || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PORT = 9333;

function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function waitForJson(url, attempts = 40) {
  for (let i = 0; i < attempts; i += 1) {
    try {
      const res = await fetch(url);
      if (res.ok) return await res.json();
    } catch { /* 浏览器还没起来 */ }
    await sleep(250);
  }
  throw new Error(`devtools 未就绪: ${url}`);
}

(async () => {
  assert.ok(fs.existsSync(CHROME), `找不到浏览器: ${CHROME}`);
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'bp-smoke-'));
  const browser = spawn(CHROME, [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`,
    '--no-first-run',
    '--disable-gpu',
    'about:blank',
  ], { stdio: 'ignore' });

  try {
    // 必须连到「页面」这个 target；/json/version 给的是浏览器级 WS，没有 Page/Runtime 域。
    let pageTarget = null;
    for (let attempt = 0; attempt < 40 && !pageTarget; attempt += 1) {
      try {
        const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
        pageTarget = list.find((t) => t.type === 'page' && t.webSocketDebuggerUrl);
      } catch { /* 还没起来 */ }
      if (!pageTarget) await sleep(250);
    }
    if (!pageTarget) throw new Error('找不到可调试的页面 target');
    const { webSocketDebuggerUrl } = pageTarget;
    const ws = new WebSocket(webSocketDebuggerUrl);
    let id = 0;
    const pending = new Map();
    const errors = [];

    const send = (method, params = {}) => new Promise((resolve, reject) => {
      const msgId = ++id;
      pending.set(msgId, { resolve, reject });
      ws.send(JSON.stringify({ id: msgId, method, params }));
    });

    await new Promise((resolve, reject) => {
      ws.addEventListener('open', resolve, { once: true });
      ws.addEventListener('error', reject, { once: true });
    });

    ws.addEventListener('message', (event) => {
      const data = JSON.parse(event.data);
      if (data.id && pending.has(data.id)) {
        const { resolve, reject } = pending.get(data.id);
        pending.delete(data.id);
        if (data.error) reject(new Error(data.error.message));
        else resolve(data.result);
        return;
      }
      if (data.method === 'Runtime.exceptionThrown') {
        errors.push(data.params.exceptionDetails.text
          + (data.params.exceptionDetails.exception?.description || ''));
      }
      if (data.method === 'Runtime.consoleAPICalled' && data.params.type === 'error') {
        errors.push(data.params.args.map((a) => a.value ?? a.description).join(' '));
      }
    });

    await send('Runtime.enable');
    await send('Page.enable');
    await send('Emulation.setDeviceMetricsOverride', {
      width: 1440, height: 900, deviceScaleFactor: 1, mobile: false,
    });
    await send('Page.navigate', { url: URL_ARG });
    await sleep(2500);
    // 16 个模块 + 15 个样式表是并行加载的，机器忙时 getComputedStyle 会先读到
    // 浏览器默认值（例如 button 的 inline-block），偶发假红。等样式表就绪再断言。
    for (let attempt = 0; attempt < 40; attempt += 1) {
      const ready = await send('Runtime.evaluate', {
        expression: "document.readyState === 'complete' && document.styleSheets.length >= 15",
        returnByValue: true,
      });
      if (ready.result && ready.result.value) break;
      await sleep(150);
    }

    const evaluate = async (expression) => {
      const result = await send('Runtime.evaluate', {
        expression, returnByValue: true, awaitPromise: true,
      });      if (result.exceptionDetails) {
        throw new Error(result.exceptionDetails.text + JSON.stringify(result.exceptionDetails));
      }
      return result.result.value;
    };

    // 1) skillSelect 非空
    const skill = await evaluate(`(() => {
      const select = document.querySelector('#skillSelect');
      if (!select) return 'MISSING';
      return select.value || 'EMPTY';
    })()`);
    console.log('skillSelect =', JSON.stringify(skill));
    assert.notEqual(skill, 'MISSING', '缺少 #skillSelect');
    assert.notEqual(skill, 'EMPTY', '#skillSelect 值为空（P0-1 未修好）');

    // 1b) 旧会话（requestedSkill 为空串）也不能把下拉框变空白
    await evaluate(`(() => {
      const state = {
        workspaces: [{
          id: 'ws-legacy', name: 'legacy', demo: false, collapsed: false,
          conversations: [{
            id: 'conv-legacy', title: '旧会话', mode: 'live',
            createdAt: Date.now(), messages: [], events: [],
            taskId: '', lastRunId: '', requestedSkill: '', activeSkill: '',
          }],
        }],
        activeConversation: 'conv-legacy',
      };
      localStorage.setItem('bjs-console-v2', JSON.stringify(state));
      return true;
    })()`);
    await send('Page.reload', { ignoreCache: true });
    await sleep(1500);
    const legacySkill = await evaluate(`(() => {
      const select = document.querySelector('#skillSelect');
      return select ? (select.value || 'EMPTY') : 'MISSING';
    })()`);
    console.log('旧会话 skillSelect =', JSON.stringify(legacySkill));
    assert.notEqual(legacySkill, 'EMPTY', '旧会话（requestedSkill 为空）下拉框仍空白（P0-1 未修好）');

    // 2) 宽屏下折叠按钮隐藏
    const wideToggle = await evaluate(`(() => {
      const btn = document.querySelector('#convosToggle');
      return btn ? getComputedStyle(btn).display : 'MISSING';
    })()`);
    console.log('宽屏 convosToggle display =', wideToggle);
    assert.equal(wideToggle, 'none', '宽屏下不应显示侧栏开关');

    // 3) 窄屏：按钮可见、点击后侧栏 .open、遮罩可见
    await send('Emulation.setDeviceMetricsOverride', {
      width: 900, height: 900, deviceScaleFactor: 1, mobile: false,
    });
    await sleep(400);
    const narrow = await evaluate(`(() => {
      const btn = document.querySelector('#convosToggle');
      const convos = document.querySelector('#convos');
      const scrim = document.querySelector('#scrim');
      const visible = btn && getComputedStyle(btn).display !== 'none';
      btn && btn.click();
      const opened = convos && convos.classList.contains('open');
      const scrimShown = scrim && !scrim.hidden;
      scrim && scrim.click();
      const closed = convos && !convos.classList.contains('open');
      return { visible, opened, scrimShown, closed };
    })()`);
    console.log('窄屏侧栏 =', JSON.stringify(narrow));
    assert.equal(narrow.visible, true, '窄屏下侧栏开关不可见');
    assert.equal(narrow.opened, true, '点击后侧栏未打开');
    assert.equal(narrow.scrimShown, true, '遮罩未显示');
    assert.equal(narrow.closed, true, '点击遮罩后侧栏未关闭');

    // 4) 焦点环规则存在
    const focusRing = await evaluate(`(() => {
      for (const sheet of document.styleSheets) {
        let rules;
        try { rules = sheet.cssRules; } catch { continue; }
        for (const rule of rules) {
          if (rule.selectorText && rule.selectorText.includes(':focus-visible')
              && /outline/.test(rule.cssText)) return true;
        }
      }
      return false;
    })()`);
    console.log('存在 :focus-visible 轮廓规则 =', focusRing);
    assert.equal(focusRing, true, '缺少 :focus-visible 轮廓规则（P0-3）');

    // 5) 演示对话能驱动 mock 播放：计划面板 + 工具组都要出现
    await send('Emulation.setDeviceMetricsOverride', {
      width: 1440, height: 900, deviceScaleFactor: 1, mobile: false,
    });
    await evaluate("localStorage.removeItem('bjs-console-v2'); 'cleared'");
    await send('Page.reload', { ignoreCache: true });
    await sleep(1800);
    const mockExpr = "(async () => {"
      + "const tag = document.querySelector('.demo-tag');"
      + "const demo = tag ? tag.closest('[data-convo]') : document.querySelector('[data-convo]');"
      + "if (!demo) return {found:false};"
      + "demo.click();"
      + "await new Promise((r) => setTimeout(r, 3000));"
      + "return {found:true,"
      + " planSteps: document.querySelectorAll('#taskBody .plan-step').length,"
      + " toolGroup: document.querySelectorAll('.tool-group').length};"
      + "})()";
    const mock = await evaluate(mockExpr);
    console.log('mock 播放 =', JSON.stringify(mock));
    assert.equal(mock.found, true, '找不到演示对话');
    assert.ok(mock.planSteps > 0, '演示对话没有渲染出执行计划');
    assert.ok(mock.toolGroup > 0, '演示对话没有渲染出工具组');

    if (errors.length) {
      console.log('页面错误:', errors);
      throw new Error(`页面有 ${errors.length} 条错误`);
    }
    console.log('\n✅ 冒烟测试通过');
    ws.close();
  } finally {
    browser.kill();
    // Chrome 退出后仍会短暂占用 profile 目录，清理失败不应掩盖测试结果。
    await sleep(600);
    try {
      fs.rmSync(profile, { recursive: true, force: true, maxRetries: 3, retryDelay: 150 });
    } catch { /* 临时目录清理失败可忽略 */ }
  }
})().catch((err) => {
  console.error('❌', err.message);
  process.exit(1);
});
