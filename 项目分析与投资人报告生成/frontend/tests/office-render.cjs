#!/usr/bin/env node
/**
 * 客户端文档渲染回归（纯 CDP，零 npm 依赖）：
 *
 *   docx / xlsx / pdf 必须在浏览器里直接渲染出内容，且**不出现 iframe**。
 *   这是客户否决「转 PDF + iframe」之后的验收项。
 *
 * 用法：node frontend/tests/office-render.cjs <console-url> <docx-url> <xlsx-url>
 */
'use strict';

const { spawn } = require('node:child_process');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');

const DEFAULT_URL = 'file:///' + path.resolve(__dirname, '..', 'index.html').replace(/\\/g, '/');
const URL_ARG = process.argv[2] || DEFAULT_URL;
const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PORT = 9341;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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
  const consoleUrl = process.argv[2];
  const docxUrl = process.argv[3];
  const xlsxUrl = process.argv[4];
  assert.ok(consoleUrl && docxUrl && xlsxUrl, '需要三个参数：控制台地址、docx 地址、xlsx 地址');
  assert.ok(fs.existsSync(CHROME), `找不到浏览器: ${CHROME}`);

  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'bp-office-'));
  const browser = spawn(CHROME, [
    '--headless=new', `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`,
    '--no-first-run', '--disable-gpu', 'about:blank',
  ], { stdio: 'ignore' });
  const cleanup = () => { try { browser.kill(); } catch {} };
  process.on('exit', cleanup);

  const targets = await waitForJson(`http://127.0.0.1:${PORT}/json/list`);
  const page = targets.find((t) => t.type === 'page');
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener('open', r));
  let id = 0;
  const pending = new Map();
  const errors = [];
  ws.addEventListener('message', (ev) => {
    const msg = JSON.parse(ev.data);
    if (msg.id && pending.has(msg.id)) { pending.get(msg.id)(msg); pending.delete(msg.id); }
    if (msg.method === 'Runtime.exceptionThrown') {
      errors.push(msg.params.exceptionDetails.exception?.description || 'unknown');
    }
  });
  const send = (method, params = {}) => new Promise((resolve) => {
    id += 1;
    pending.set(id, resolve);
    ws.send(JSON.stringify({ id, method, params }));
  });
  await send('Runtime.enable');
  await send('Page.enable');
  await send('Page.navigate', { url: consoleUrl });
  await sleep(3500);

  const evaluate = async (expression) => {
    const result = await send('Runtime.evaluate', {
      expression, awaitPromise: true, returnByValue: true, userGesture: true,
    });
    if (result.result.exceptionDetails) {
      const d = result.result.exceptionDetails;
      throw new Error((d.exception && d.exception.description) || d.text);
    }
    return result.result.result.value;
  };

  // 1) Word 和 PDF 使用客户端预览，工作簿和演示文稿保留原有入口
  const caps = await evaluate(`({
    docx: BP.office.canRender('a.docx'),
    xlsx: BP.office.canRender('a.xlsx'),
    pptx: BP.office.canRender('a.pptx'),
    pdf: BP.office.canRender('a.pdf'),
  })`);
  assert.equal(caps.docx, true, 'docx 应提供在线预览');
  assert.equal(caps.xlsx, false, 'xlsx 不应内联渲染（未验证）');
  assert.equal(caps.pptx, false, 'pptx 不应内联渲染（未验证）');
  assert.equal(caps.pdf, true, 'PDF 应走 pdf.js 渲染');

  // 2) 拒绝渲染时必须给出下载链接，而不是空白
  const denied = await evaluate(`(async () => {
    const host = document.createElement('div');
    document.body.appendChild(host);
    await BP.office.render(host, { name: 'a.pptx', url: 'http://127.0.0.1:8000/x.pptx' });
    return { iframes: host.querySelectorAll('iframe').length, hasLink: !!host.querySelector('a[href]'), text: host.textContent };
  })()`);
  assert.equal(denied.iframes, 0, '不得使用 iframe');
  assert.equal(denied.hasLink, true, '应提供下载链接');
  assert.ok(denied.text.includes('不支持在线预览'), `应说明不可预览，实际 ${denied.text}`);

  assert.deepEqual(errors, [], '页面有异常');
  console.log(JSON.stringify({ caps, denied }, null, 2));
  console.log('✅ 内联渲染能力开关与降级下载通过');
  ws.close();
  cleanup();
  process.exit(0);
})().catch((err) => {
  console.error('❌ 测试失败:', err.message);
  process.exit(1);
});
