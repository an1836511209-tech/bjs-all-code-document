#!/usr/bin/env node
/**
 * 停止按钮位置回归（纯 CDP，零 npm 依赖）：
 *
 *   1. 执行中 / 等待补充时，**发送键**变成「中止」，附件键禁用
 *   2. 回到空闲时，发送键恢复成「发送」，附件键恢复可用
 *   3. 执行中点发送不会把消息塞进队列（旧行为会排队并在结束后自动发出）
 *
 * 用法：node frontend/tests/composer-stop-button.cjs [url]
 *   默认打开 frontend/index.html（file://），不需要起服务。
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
const PORT = 9338;

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
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'bp-stop-'));
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

    let booted = false;
    for (let attempt = 0; attempt < 80; attempt += 1) {
      const ready = await evaluate("Boolean(window.BP && BP.state && BP.state.currentConversation && BP.state.currentConversation() && BP.composer && BP.composer.syncComposerButton)");
      if (ready) { booted = true; break; }
      await sleep(150);
    }
    assert.ok(booted, '控制台没有启动出可用会话');

    const readComposer = () => evaluate(`(() => {
      const send = document.getElementById('sendBtn');
      const attach = document.getElementById('attachBtn');
      return {
        send: (send?.textContent || '').trim(),
        sendStop: send?.classList.contains('is-stop') || false,
        attachDisabled: Boolean(attach?.disabled),
        attach: (attach?.textContent || '').trim(),
      };
    })()`);

    // 直接驱动渲染函数读状态：后台 reconcile 会异步改写 runtime.status，
    // 隔着 sleep 断言会跟它抢。
    const withStatus = (status) => evaluate(`(() => {
      const c = BP.state.currentConversation();
      BP.state.runtimeOf(c).status = '${status}';
      BP.composer.syncComposerButton();
      const send = document.getElementById('sendBtn');
      const attach = document.getElementById('attachBtn');
      return {
        send: (send?.textContent || '').trim(),
        sendStop: send?.classList.contains('is-stop') || false,
        attachDisabled: Boolean(attach?.disabled),
        attach: (attach?.textContent || '').trim(),
        queue: BP.state.runtimeOf(c).queue.length,
      };
    })()`);

    // 空闲态
    const idle = await withStatus('idle');
    assert.ok(idle.send.includes('发送'), `空闲时发送键应是发送，实际 ${idle.send}`);
    assert.equal(idle.sendStop, false);
    assert.equal(idle.attachDisabled, false);

    // 执行中：中止在发送键的位置上，附件禁用
    const running = await withStatus('running');
    assert.ok(running.send.includes('中止'), `执行中发送键应变成中止，实际 ${running.send}`);
    assert.equal(running.sendStop, true);
    assert.equal(running.attachDisabled, true, '执行中附件键应禁用');
    assert.ok(running.attach.includes('附件'), '附件键不应再承担中止职责');

    // 中止键必须是红的：它是危险操作，不能和"发送"看起来一样
    const danger = await evaluate(`(() => {
      const send = document.getElementById('sendBtn');
      const style = getComputedStyle(send);
      return { bg: style.backgroundColor, color: style.color };
    })()`);
    // 主题色可能是 rgb() 也可能是 oklch()，两种都要认
    const isRed = (value) => {
      const text = String(value || '').trim();
      if (text.startsWith('rgb')) {
        const [r, g, b] = (text.match(/\d+/g) || []).map(Number);
        return r > 150 && r > g + 40 && r > b + 40;
      }
      if (text.startsWith('oklch')) {
        const match = text.match(/oklch\(\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)/);
        if (!match) return false;
        const [, l, c, h] = match.map(Number);
        return h <= 45 && c >= 0.08 && l >= 0.3; // 色相 0-45° 且有一定彩度
      }
      return false;
    };
    assert.ok(isRed(danger.bg), `中止键应为红色，实际背景 ${danger.bg}`);

    // 等待补充（ask_user）也算执行中：用户必须能放弃这次任务
    const waiting = await withStatus('waiting');
    assert.ok(waiting.send.includes('中止'), `等待补充时发送键应保持中止，实际 ${waiting.send}`);
    assert.equal(waiting.attachDisabled, true);

    // 执行中点发送不应排队
    const queued = await evaluate(`(() => {
      const c = BP.state.currentConversation();
      const runtime = BP.state.runtimeOf(c);
      runtime.status = 'running';
      const before = runtime.queue.length;
      const input = document.getElementById('input');
      input.value = '我刚才干了什么？';
      input.dispatchEvent(new Event('input', { bubbles: true }));
      BP.composer.send();
      return { before, after: runtime.queue.length,
               hint: (document.getElementById('chatSub')?.textContent || '') };
    })()`);
    assert.equal(queued.after, queued.before, '执行中不应把消息塞进队列');
    assert.ok(queued.hint.includes('中止'), `应提示先中止，实际 ${queued.hint}`);

    // 回到空闲
    const restored = await withStatus('idle');
    assert.ok(restored.send.includes('发送'), '空闲后应恢复发送');
    assert.equal(restored.sendStop, false);

    // 打开预览会压缩中间列。额外工具可以换行，发送和中止键保持原尺寸。
    await send('Emulation.setDeviceMetricsOverride', {
      width: 1050, height: 800, deviceScaleFactor: 1, mobile: false,
    });
    const buttonBounds = async (status) => {
      await withStatus(status);
      return evaluate(`(() => {
        const send = document.getElementById('sendBtn').getBoundingClientRect();
        const bar = document.querySelector('.composer-bar').getBoundingClientRect();
        return { width: send.width, height: send.height, inside: send.right <= bar.right };
      })()`);
    };
    await evaluate(`(() => {
      const model = document.getElementById('modelSelect');
      model.add(new Option('测试模型名称', 'test-model'));
      model.hidden = false;
      document.getElementById('thinkingSelect').hidden = false;
      document.querySelector('.workbook-toggle').hidden = false;
    })()`);
    const closedSend = await buttonBounds('idle');
    const closedStop = await buttonBounds('running');
    await evaluate("BP.document.openPreview({title:'测试报告', sub:'', html:'<p>预览内容</p>'})");
    await sleep(400);
    assert.deepEqual(await buttonBounds('idle'), closedSend);
    assert.deepEqual(await buttonBounds('running'), closedStop);
    assert.equal(closedSend.inside, true);
    assert.equal(closedStop.inside, true);

    assert.deepEqual(errors, [], '页面有异常');
    console.log(JSON.stringify({ idle, running, waiting, queued, restored }, null, 2));
    console.log('\n✅ 停止按钮位置与执行中禁发测试通过');
  } finally {
    if (ws) { try { ws.close(); } catch { /* ignore */ } }
    browser.kill();
    await sleep(600);
    try { fs.rmSync(profile, { recursive: true, force: true }); } catch { /* locked */ }
  }
})().catch((err) => {
  console.error('\n❌ 测试失败:', err.message);
  process.exit(1);
});
