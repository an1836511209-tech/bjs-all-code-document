#!/usr/bin/env node
/**
 * 技能路由回归测试（纯 CDP，零 npm 依赖）：
 *   1. 快捷语点击后，下拉框与对话记录必须同时变成该快捷语对应的技能
 *   2. 切换对话时，技能不得从上一个对话串过来
 *   3. 下拉框的值必须始终是某个真实选项
 *
 * 用法：node frontend/tests/skill-routing.cjs [url]
 *   默认打开同目录的 frontend/index.html（file://），不需要起服务。
 *   环境变量：CHROME_PATH 指定浏览器，缺省用系统 Chrome。
 */
'use strict';

const { spawn } = require('node:child_process');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const DEFAULT_URL = 'file:///' + path.resolve(__dirname, '..', 'index.html').replace(/\\/g, '/');
const URL_ARG = process.argv[2] || DEFAULT_URL;
const CHROME = process.env.CHROME_PATH
  || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PORT = 9334;

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
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'bp-routing-'));
  const browser = spawn(CHROME, [
    '--headless=new',
    `--remote-debugging-port=${PORT}`,
    `--user-data-dir=${profile}`,
    '--no-first-run',
    '--disable-gpu',
    'about:blank',
  ], { stdio: 'ignore' });

  let ws;
  try {
    const list = await waitForJson(`http://127.0.0.1:${PORT}/json/list`);
    const target = list.find((t) => t.type === 'page');
    assert.ok(target, '找不到 page target');

    const { WebSocket } = require('node:worker_threads') && globalThis.WebSocket
      ? globalThis : require('node:ws');
    ws = new WebSocket(target.webSocketDebuggerUrl);
    await new Promise((resolve, reject) => {
      ws.addEventListener('open', resolve, { once: true });
      ws.addEventListener('error', reject, { once: true });
    });

    let id = 0;
    const pending = new Map();
    const errors = [];
    ws.addEventListener('message', (event) => {
      const data = JSON.parse(event.data);
      if (data.id && pending.has(data.id)) {
        const { resolve, reject } = pending.get(data.id);
        pending.delete(data.id);
        if (data.error) reject(new Error(data.error.message));
        else resolve(data.result);
      }
      if (data.method === 'Runtime.exceptionThrown') {
        errors.push(data.params.exceptionDetails.text
          + (data.params.exceptionDetails.exception?.description || ''));
      }
      if (data.method === 'Runtime.consoleAPICalled' && data.params.type === 'error') {
        errors.push(data.params.args.map((a) => a.value ?? a.description).join(' '));
      }
    });
    const send = (method, params = {}) => new Promise((resolve, reject) => {
      id += 1;
      pending.set(id, { resolve, reject });
      ws.send(JSON.stringify({ id, method, params }));
    });
    const evaluate = async (expression) => {
      const result = await send('Runtime.evaluate', {
        expression, returnByValue: true, awaitPromise: true,
      });
      if (result.exceptionDetails) {
        throw new Error(result.exceptionDetails.text + JSON.stringify(result.exceptionDetails));
      }
      return result.result.value;
    };

    await send('Runtime.enable');
    await send('Page.enable');
    await send('Page.navigate', { url: URL_ARG });
    await sleep(1200);
    await evaluate("localStorage.removeItem('bjs-console-v2'); 'cleared'");
    await send('Page.reload', { ignoreCache: true });
    // Wait for boot instead of sleeping: a skill can only be attached to a
    // conversation that already exists, and a fixed wait races the boot.
    let booted = false;
    for (let attempt = 0; attempt < 80; attempt += 1) {
      const ready = await evaluate(
        "(!!window.BP && !!window.BP.state && !!window.BP.state.currentConversation())"
      );
      if (ready) { booted = true; break; }
      await sleep(150);
    }
    assert.equal(booted, true, '控制台没有启动出可用会话');

    // 页面内取当前对话记录里的技能
    const HELPERS = `
      window.__probe = {
        selectValue: () => document.querySelector('#skillSelect').value,
        optionValues: () => Array.from(document.querySelector('#skillSelect').options).map(o => o.value),
        activeRequestedSkill: () => {
          const ui = window.BP.state.ui;
          for (const ws of ui.workspaces) {
            const c = ws.conversations.find(c => c.id === ui.activeConversation);
            if (c) return c.requestedSkill || '';
          }
          return '';
        },
        activeConversationId: () => window.BP.state.ui.activeConversation,
        conversationIds: () => {
          const ids = [];
          for (const ws of window.BP.state.ui.workspaces) {
            for (const c of ws.conversations) ids.push(c.id);
          }
          return ids;
        },
        openConversation: (id) => window.BP.sidebar.openConversation(id),
      };
      'ready';
    `;
    await evaluate(HELPERS);

    // 1) 快捷语点击 → 下拉框 + 对话记录同步
    const chip = await evaluate(`(() => {
      const el = document.querySelector('.chip[data-skill="investment-report"]');
      if (!el) return { found: false };
      el.click();
      return {
        found: true,
        select: window.__probe.selectValue(),
        stored: window.__probe.activeRequestedSkill(),
      };
    })()`);
    console.log('快捷语「生成投资报告」 =', JSON.stringify(chip));
    assert.equal(chip.found, true, '缺少 data-skill 的快捷语');
    assert.equal(chip.select, 'investment-report', '快捷语没有切换下拉框');
    assert.equal(chip.stored, 'investment-report', '快捷语没有写回对话记录');

    // 2) 切换对话不得串技能
    const switchResult = await evaluate(`(() => {
      const before = window.__probe.activeConversationId();
      const ids = window.__probe.conversationIds();
      // 造第二个对话
      window.BP.sidebar.createConversation(window.BP.state.ui.workspaces[0].id);
      const second = window.__probe.activeConversationId();
      const secondSelect = window.__probe.selectValue();
      const secondStored = window.__probe.activeRequestedSkill();
      // 切回第一个
      window.__probe.openConversation(before);
      const backSelect = window.__probe.selectValue();
      const backStored = window.__probe.activeRequestedSkill();
      return { before, second, secondSelect, secondStored, backSelect, backStored };
    })()`);
    console.log('切换对话 =', JSON.stringify(switchResult));
    assert.notEqual(switchResult.second, switchResult.before, '没有创建出第二个对话');
    assert.equal(
      switchResult.secondSelect, 'one-pager',
      '新对话继承上一个对话的技能（跨会话污染）',
    );
    assert.equal(
      switchResult.secondStored, 'one-pager',
      '新对话的记录里被写入了上一个对话的技能',
    );
    assert.equal(switchResult.backSelect, 'investment-report', '切回原对话后技能丢失');
    assert.equal(switchResult.backStored, 'investment-report', '切回原对话后记录不一致');

    // 3) 下拉框的值必须始终是真实选项
    const valid = await evaluate(`(() => {
      const values = window.__probe.optionValues();
      return { current: window.__probe.selectValue(), values };
    })()`);
    console.log('下拉框当前值 =', JSON.stringify(valid));
    assert.ok(
      valid.values.includes(valid.current),
      `下拉框值 ${valid.current} 不在选项 ${JSON.stringify(valid.values)} 中`,
    );

    if (errors.length) {
      console.log('页面错误:', errors);
      throw new Error(`页面有 ${errors.length} 条错误`);
    }
    console.log('\n✅ 技能路由测试通过');
    ws.close();
  } finally {
    browser.kill();
    await sleep(600);
    try {
      fs.rmSync(profile, { recursive: true, force: true, maxRetries: 3, retryDelay: 150 });
    } catch { /* 临时目录清理失败可忽略 */ }
  }
})().catch((err) => {
  console.error('❌', err.message);
  process.exit(1);
});
