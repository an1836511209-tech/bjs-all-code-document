#!/usr/bin/env node
/**
 * 已完成任务的事件回放回归测试（纯 CDP，零 npm 依赖）：
 *
 *   控制台只在 run 运行时订阅 SSE，所以"浏览器没看过的 run"（评测脚本、
 *   别的浏览器、清过 localStorage）只剩一个 artifact 卡片，工具调用一行不显。
 *   服务端其实存着完整事件（tool.started / tool.completed / plan.updated）。
 *
 *   本测试注入一个「有 taskId/lastRunId、但 events 为空」的会话，重载后断言：
 *     1. 前端从服务端补齐了工具事件（≥ 10 条 tool.started）
 *     2. 补齐结果落了 localStorage（第二次重载不会再发请求）
 *     3. 期间没有异常
 *
 * 用法：node frontend/tests/tool-trace-backfill.cjs [url]
 *   需要 report-agent 服务在 127.0.0.1:8000 上跑着（用于事件回放）。
 *   环境变量：CHROME_PATH、TASK_ID、RUN_ID
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
const PORT = 9336;
const API = process.env.REPORT_AGENT_API || 'http://127.0.0.1:8000';
const TASK_ID = process.env.TASK_ID || 'task_eaec7469a1a54b13a1aa7bb03440fc3c';
const RUN_ID = process.env.RUN_ID || 'run_db3044c82991451ea3c70456959c161f';

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

function seedState() {
  return {
    workspaces: [{
      id: 'ws-default', name: '我的项目', demo: false, collapsed: false,
      conversations: [{
        id: 'conv-backfill',
        title: '请阅读材料，生成投资人匹配报告',
        titleAttempted: true,
        mode: 'live',
        createdAt: Date.now(),
        messages: [
          { role: 'user', text: '请阅读材料，生成投资人匹配报告', runId: RUN_ID },
          { role: 'assistant', text: '报告已发布。', runId: RUN_ID },
        ],
        // 关键：没有 events —— 模拟"浏览器没看过这个 run"
        events: [],
        taskId: TASK_ID,
        lastRunId: RUN_ID,
        requestedSkill: 'investment-report',
        activeSkill: 'investment-report',
        lastSeq: 0,
        draft: { text: '', urls: '' },
      }],
    }],
    activeConversation: 'conv-backfill',
  };
}

(async () => {
  assert.ok(fs.existsSync(CHROME), `找不到浏览器: ${CHROME}`);

  // 先确认服务端确实有这个 run 的事件，否则测试没有意义
  const probe = await fetch(`${API}/api/runs/${RUN_ID}/events?after_seq=0`);
  assert.equal(probe.status, 200, `服务端事件接口不可用（${probe.status}）`);
  const body = await probe.text();
  const serverTools = (body.match(/"type"\s*:\s*"tool\.started"/g) || []).length;
  assert.ok(serverTools >= 10, `服务端只有 ${serverTools} 条 tool.started，先确认服务在跑`);

  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'bp-backfill-'));
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

    const { WebSocket } = globalThis;
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

    await evaluate(`localStorage.setItem('bjs-console-v2', ${JSON.stringify(JSON.stringify(seedState()))}); 'seeded'`);
    await send('Page.reload', { ignoreCache: true });

    // 等回放：SSE 一次性把整段事件推完，116 条大约需要 1-3 秒
    let toolStarted = 0;
    let persisted = 0;
    for (let attempt = 0; attempt < 60; attempt += 1) {
      await sleep(250);
      toolStarted = await evaluate(`(() => {
        const c = window.BP.state.currentConversation();
        return (c.events || []).filter(e => e.type === 'tool.started').length;
      })()`);
      if (toolStarted >= serverTools) break;
    }

    // 落盘检查：第二次重载不应再依赖服务端
    persisted = await evaluate(`(() => {
      const raw = localStorage.getItem('bjs-console-v2');
      if (!raw) return 0;
      const state = JSON.parse(raw);
      const conv = (state.workspaces?.[0]?.conversations || [])[0] || {};
      return (conv.events || []).filter(e => e.type === 'tool.started').length;
    })()`);

    const planUpdated = await evaluate(`(() => {
      const c = window.BP.state.currentConversation();
      return (c.events || []).filter(e => e.type === 'plan.updated').length;
    })()`);

    console.log(JSON.stringify({
      serverTools, toolStarted, persisted, planUpdated, errors,
    }, null, 2));

    assert.equal(toolStarted, serverTools, `事件没补齐：${toolStarted}/${serverTools}`);
    assert.ok(persisted >= serverTools, `事件没落 localStorage：${persisted}/${serverTools}`);
    assert.ok(planUpdated >= 1, '执行计划事件没回放');
    assert.deepEqual(errors, [], '页面有异常');

    console.log('\n✅ 已完成任务的工具调用回放测试通过');
  } finally {
    if (ws) { try { ws.close(); } catch { /* ignore */ } }
    browser.kill();
    // Windows keeps the profile directory locked for a moment after the kill;
    // a leftover temp dir must not turn a passing test into a failure.
    await sleep(600);
    try { fs.rmSync(profile, { recursive: true, force: true }); } catch { /* locked */ }
  }
})().catch((err) => {
  console.error('\n❌ 测试失败:', err.message);
  process.exit(1);
});
