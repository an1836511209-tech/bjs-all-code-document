/** Deterministic large-chunk UI regression; start the development server first. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium } from '@playwright/test';

const output = 'coverage/ai-chat-typewriter';
await mkdir(output, { recursive: true });
const browser = await chromium.launch();
const page = await browser.newPage({ reducedMotion: 'no-preference', viewport: { width: 1440, height: 1000 } });
const report = { checks: [], errors: [], samples: [] };
page.on('pageerror', (error) => report.errors.push(error.message));
const text = '逐字显示中文，保留完整字符👨‍👩‍👧‍👦。'.repeat(24);
let requestBody;
let responseText = text;
let deliverArtifact = false;
function check(name, condition) { assert.ok(condition, name); report.checks.push(name); console.log(`PASS ${name}`); }
async function until(test, timeout = 5000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { if (await test()) return; await page.waitForTimeout(16); }
  throw new Error('Timed out waiting for presentation state');
}
await page.route('**/api/ai-chat', async (route) => {
  requestBody = route.request().postDataJSON();
  const frames = [{ type: 'start', messageId: `burst-${crypto.randomUUID()}` },
    ...(deliverArtifact ? [{ type: 'data-artifact', id: 'wrap-document', data: {
      schemaVersion: 1, id: 'wrap-document', revision: 1, status: 'ready',
      kind: 'document', title: '换行回归文档', autoOpen: true,
      preview: { renderer: 'document', version: 1, data: { markdown: '# 成果预览\n\n保持成果物打开，验证左侧正文。' } }
    } }] : []),
    { type: 'text-start', id: 'answer' }, { type: 'text-delta', id: 'answer', delta: responseText },
    { type: 'text-end', id: 'answer' }, { type: 'finish', finishReason: 'stop' }];
  await route.fulfill({ contentType: 'text/event-stream', headers: { 'x-vercel-ai-ui-message-stream': 'v1' }, body: frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join('') + 'data: [DONE]\n\n' });
});
const visible = () => page.getByTestId('assistant-response-text').last().innerText();
async function send() {
  await page.getByTestId('chat-composer').fill('演示分块输出');
  // Keyboard submission also works on narrow screens with the devtools badge.
  await page.getByTestId('chat-composer').press('Enter');
}
try {
  await page.goto(`${process.env.AI_CHAT_BASE_URL ?? 'http://localhost:3000'}/dashboard/ai-chat`);
  await page.evaluate(() => {
    window.__fadeObserved = false;
    const deadline = performance.now() + 5000;
    function sampleFade() {
      window.__fadeObserved ||= [...document.querySelectorAll('[data-sd-animate]')].slice(-8).some((node) => {
        const style = getComputedStyle(node);
        return style.animationName === 'sd-fadeIn' && style.animationDuration === '0.12s' && Number(style.opacity) < 1;
      });
      if (!window.__fadeObserved && performance.now() < deadline) requestAnimationFrame(sampleFade);
    }
    requestAnimationFrame(sampleFade);
  });
  await send();
  await until(async () => (await page.getByTestId('assistant-response-text').count()) > 0 && (await visible()).length > 0 && (await visible()).length < text.length);
  const first = await visible();
  await until(async () => page.evaluate(() => window.__fadeObserved));
  check('Streamdown fades newly revealed characters', await page.evaluate(() => window.__fadeObserved));
  report.samples.push(first.length);
  check('A single large delta appears progressively', first.length > 0 && first.length < text.length);
  await page.waitForTimeout(100);
  const second = await visible();
  report.samples.push(second.length);
  check('Display advances independently after network completion', second.length > first.length);
  await until(async () => (await visible()) === text);
  check('Completed content is exact, including joined emoji', (await visible()) === text);
  check('No show-all control is introduced', await page.getByTestId('show-full-response').count() === 0);
  await page.screenshot({ path: `${output}/completed.png` });

  await page.emulateMedia({ reducedMotion: 'reduce' });
  await send();
  await until(async () => (await page.getByTestId('assistant-response-text').count()) === 2 && (await visible()) === text);
  check('Reduced-motion mode renders full received text', (await visible()) === text);
  check('Reduced-motion mode disables character animations', await page.locator('[data-sd-animate]').evaluateAll((nodes) => nodes.every((node) => getComputedStyle(node).animationName === 'none')));
  check('The next request contains full canonical assistant text', requestBody.messages.some((message) => message.role === 'assistant' && message.parts.some((part) => part.text === text)));

  await page.emulateMedia({ reducedMotion: 'no-preference' });
  responseText = text.repeat(8);
  await send();
  await until(async () => (await page.getByTestId('assistant-response-text').count()) === 3 && (await visible()).length > 0 && (await visible()).length < responseText.length);
  await page.getByTestId('stop-stream').press('Enter');
  await until(async () => (await visible()) === responseText);
  const stopped = await visible();
  await page.waitForTimeout(120);
  check('Stopping flushes received content and cancels the display queue', (await visible()) === stopped);
  await page.getByTestId('restart-chat').click();
  await page.waitForTimeout(120);
  check('Restart leaves no stale animated text', await page.getByTestId('assistant-response-text').count() === 0);

  // Track already-painted glyphs, relative to the paragraph so scroll-follow
  // movement is excluded. This catches the line-end jump that screenshots miss.
  responseText = '中文内容保持平稳，检查 visibility artifact streaming developer experience。'.repeat(35);
  for (const { width, artifact } of [
    { width: 1440, artifact: false }, { width: 390, artifact: false },
    { width: 1100, artifact: true }, { width: 1440, artifact: true },
    { width: 1920, artifact: true }
  ]) {
    deliverArtifact = artifact;
    await page.setViewportSize({ width, height: 1000 });
    await page.evaluate(() => {
      window.__wrapResult = { frames: 0, moved: [] };
      window.__wrapSampling = true;
      let previous = [];
      function sample() {
        const host = document.querySelector('[data-testid="assistant-response-text"] p');
        if (host) {
          const origin = host.getBoundingClientRect();
          const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT);
          const current = [];
          while (walker.nextNode()) {
            const node = walker.currentNode;
            for (let index = 0; index < node.length; index++) {
              const range = document.createRange();
              range.setStart(node, index); range.setEnd(node, index + 1);
              const rect = range.getBoundingClientRect();
              current.push({ char: node.textContent[index], x: rect.x - origin.x, y: rect.y - origin.y });
            }
          }
          for (let index = 0; index < Math.min(previous.length, current.length); index++) {
            const before = previous[index], after = current[index];
            if (before.char === after.char && after.char.trim() &&
              (Math.abs(before.x - after.x) > 2 || Math.abs(before.y - after.y) > 2)) {
              window.__wrapResult.moved.push({ index, before, after });
            }
          }
          previous = current;
          window.__wrapResult.frames++;
        }
        if (window.__wrapSampling) requestAnimationFrame(sample);
      }
      requestAnimationFrame(sample);
    });
    await send();
    await until(async () => (await visible()) === responseText);
    await page.waitForTimeout(80);
    const geometry = await page.evaluate(() => { window.__wrapSampling = false; return window.__wrapResult; });
    report.samples.push({ width, ...geometry });
    check(`Line-end glyphs stay in place while streaming at ${width}px${artifact ? ' with artifact open' : ''}`, geometry.frames > 3 && geometry.moved.length === 0);
    if (artifact) {
      const panelBox = await page.getByTestId('artifact-panel').boundingBox();
      const chatBox = await page.getByTestId('chat-viewport').boundingBox();
      check(`Artifact regression actually uses split view at ${width}px`, panelBox && chatBox && chatBox.x + chatBox.width <= panelBox.x + 1);
    }
    await page.screenshot({ path: `${output}/wrap-${width}.png` });
    await page.getByTestId('restart-chat').click();
  }
  deliverArtifact = false;

  await page.setViewportSize({ width: 1440, height: 1000 });
  responseText = '## 标题\n\n**稳定粗体内容（重点）。**与[文档](https://example.com)。\n\n| 项目 | 结果 |\n| --- | --- |\n| 流式 | 正常 |\n\n```js\nconst result = 1;\n```\n\n' + '末尾内容继续增长。'.repeat(100);
  await send();
  const response = page.getByTestId('assistant-response-text').last();
  await until(async () => await response.locator('table').count() > 0);
  const table = await response.locator('table').elementHandle();
  await until(async () => (await page.getByTestId('chat-status').getAttribute('data-status')) === 'ready');
  check('Settled Markdown table keeps its DOM identity through completion', await table.evaluate((node) => node.isConnected));
  const markdownCounts = { heading: await response.locator('h2').count(), strong: await response.locator('strong').count(), code: await response.locator('pre code').count() };
  check(`Streamdown renders headings, strong, tables and code: ${JSON.stringify(markdownCounts)}`, markdownCounts.heading === 1 && markdownCounts.strong === 1 && markdownCounts.code === 1);
  check('Completed responses release character animation DOM', await response.locator('[data-sd-animate]').count() === 0);
  await page.getByTestId('restart-chat').click();
  await page.emulateMedia({ reducedMotion: 'reduce' });
  responseText = '<script>window.__unsafeChat = 1</script>\n\n<iframe src="https://example.com"></iframe>\n\n<button>RAW_HTML_TEST</button>\n\n[unsafe](javascript:alert(1)) ![remote](https://example.com/tracker.png)';
  let remoteRequests = 0;
  await page.route('https://example.com/**', async (route) => { remoteRequests++; await route.abort(); });
  await send();
  await until(async () => await response.innerText().then((text) => text.includes('remote')));
  check('Model HTML and executable URLs remain inert', await response.locator('script,iframe,button,a[href^="javascript:"]').count() === 0 && await page.evaluate(() => !window.__unsafeChat));
  check('Markdown images never fetch remote resources', remoteRequests === 0 && await response.locator('img').count() === 0);
  check('No runtime errors', report.errors.length === 0);
  report.passed = true;
} catch (error) {
  report.passed = false;
  report.failure = error.stack;
  await page.screenshot({ path: `${output}/failure.png` });
  process.exitCode = 1;
  console.error(error);
} finally {
  await writeFile(`${output}/report.json`, JSON.stringify(report, null, 2));
  await browser.close();
}
