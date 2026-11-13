#!/usr/bin/env node
/**
 * 产物预览回归（纯 CDP，零 npm 依赖）：
 *
 *   1. 生成 Word 产物时，侧栏走 preview.pdf + pdf.js（不再抽文本框纯文本）
 *   2. 预览面板带原件 docx 下载入口
 *   3. Excel 产物不嵌 PDF（走工作簿预览）
 *
 * 用法：node frontend/tests/artifact-preview.cjs [url]
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
const PORT = 9339;

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
  assert.ok(fs.existsSync(CHROME), `找不到浏览器: ${CHROME}`);
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'bp-preview-'));
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
        errors.push(data.params.exceptionDetails.text);
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
        const d = result.exceptionDetails;
        throw new Error((d.exception && d.exception.description) || d.text);
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
      const ready = await evaluate("Boolean(window.BP && BP.document && BP.state.currentConversation && BP.state.currentConversation())");
      if (ready) { booted = true; break; }
      await sleep(150);
    }
    assert.ok(booted, '控制台没有启动出可用会话');

    // 1) Word 产物：侧栏走 preview.pdf，下载仍是原件 /content。
    // 用 office.render stub 锁接线（不依赖 Gotenberg / 真 PDF 字节）。
    const docx = await evaluate(`(async () => {
      const artifactId = 'artifact_' + 'a'.repeat(32);
      const downloadUrl = BP.files.artifactDownloadUrl(artifactId);
      const previewUrl = BP.files.artifactPreviewUrl(artifactId);
      const renderOriginal = BP.office.render;
      let renderArgs = null;
      BP.office.render = async (container, args) => {
        renderArgs = args;
        container.innerHTML = '';
        const host = document.createElement('div');
        host.className = 'office-pdf';
        container.appendChild(host);
      };
      try {
        BP.document.addLiveDoc({ artifact_id: artifactId, filename: '测试报告.docx', size_bytes: 2048 });
        for (let i = 0; i < 40 && !document.querySelector('#paper .office-pdf'); i += 1) {
          await new Promise(resolve => setTimeout(resolve, 50));
        }
      } finally {
        BP.office.render = renderOriginal;
      }
      const doc = BP.state.state.doc;
      const frame = document.querySelector('#preview iframe.file-frame, .preview iframe.file-frame');
      const pdfHost = document.querySelector('#preview .office-pdf, #paper .office-pdf');
      const textHost = document.querySelector('#preview .office-docx-content');
      const toolbar = document.querySelector('.preview-toolbar');
      return {
        hasFrame: Boolean(frame),
        hasToolbar: Boolean(toolbar),
        download: toolbar?.querySelector('.dl-btn')?.href === downloadUrl,
        previewUrl: doc?.renderUrl === previewUrl,
        renderName: doc?.renderName || '',
        renderCalledWith: renderArgs,
        hasPdfHost: Boolean(pdfHost),
        hasTextFallback: Boolean(textHost),
        sub: doc?.sub || '',
      };
    })()`);

    assert.equal(docx.hasFrame, false, 'Word 产物预览不得使用 iframe');
    assert.equal(docx.hasToolbar, true, '预览应有工具栏');
    assert.equal(docx.download, true, '工具栏里要有原件下载入口');
    assert.equal(docx.previewUrl, true, 'renderUrl 应指向 preview.pdf');
    assert.equal(docx.renderName, '测试报告.pdf', 'renderName 应为 .pdf 以走 pdf.js');
    assert.equal(docx.renderCalledWith?.url?.includes('/preview.pdf'), true, 'office.render 应请求 preview.pdf');
    assert.equal(docx.renderCalledWith?.name, '测试报告.pdf', 'office.render 应用 .pdf 名');
    assert.equal(docx.hasPdfHost, true, '侧栏应渲染 PDF 画布容器');
    assert.equal(docx.hasTextFallback, false, '不应再走文本框纯文本降级');
    assert.match(docx.sub, /PDF 预览/, '副标题应标明 PDF 预览');

    // 2) Excel 产物：不嵌 PDF
    const excel = await evaluate(`(() => {
      BP.document.openPreview({
        title: '投资人清单.xlsx',
        sub: 'Excel 匹配表',
        artifactId: 'artifact_xlsx',
        html: '<h1>投资人清单.xlsx</h1>'
      });
      const frame = document.querySelector('.preview iframe.file-frame');
      return { hasFrame: Boolean(frame) };
    })()`);
    assert.equal(excel.hasFrame, false, 'Excel 不应嵌 iframe');

    // 3) 无 renderUrl 时回退到 html 渲染
    const plain = await evaluate(`(() => {
      BP.document.openPreview({ title: '纯文本', sub: '', html: '<p id="plain-body">内容</p>' });
      return Boolean(document.querySelector('#plain-body'));
    })()`);
    assert.equal(plain, true, '没有 renderUrl 时应回退渲染 html');

    // 4) 上下文占用环：按比例画弧、按阈值变色
    const ring = await evaluate(`(() => {
      BP.dom.renderContextUsage({ tokens: 98304, window: 131072, trigger_tokens: 98304, compressed: false });
      const el = document.getElementById('ctxRing');
      const fill = document.getElementById('ctxRingFill');
      const label = document.getElementById('ctxRingLabel');
      const danger = el.classList.contains('is-danger');
      const off = parseFloat(fill.style.strokeDashoffset || '0');
      const high = { label: label.textContent, title: el.title, hidden: el.hidden };
      BP.dom.renderContextUsage({ tokens: 1000, window: 131072, trigger_tokens: 98304 });
      return { ...high, danger, off, afterLow: document.getElementById('ctxRingLabel').textContent };
    })()`);
    assert.equal(ring.hidden, false, '有数据时环形应显示');
    assert.equal(ring.label, '75%', `75% 占用应显示 75%，实际 ${ring.label}`);
    assert.ok(ring.off > 0 && ring.off < 94.25, `弧长应随比例变化，实际 offset=${ring.off}`);
    assert.equal(ring.afterLow, '1%', '低占用应回落到小百分比');
    assert.ok(ring.title.includes('131,072'), 'title 应给出窗口大小');

    // 5) 上下文环的导出面（file:// 下无法 fetch 源码，这里只锁 API 形状；
    //    「10-run.js 少了别名」那次回归靠真机联调发现，见提交说明）
    const ringApi = await evaluate(`({
      render: typeof BP.dom.renderContextUsage,
      clear: typeof BP.dom.clearContextUsage,
    })`);
    assert.equal(ringApi.render, 'function', 'BP.dom.renderContextUsage 未导出');
    assert.equal(ringApi.clear, 'function', 'BP.dom.clearContextUsage 未导出');

    assert.deepEqual(errors, [], '页面有异常');
    console.log(JSON.stringify({ docx, excel, plain }, null, 2));
    console.log('\n✅ 文档预览（侧栏内嵌）测试通过');
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
