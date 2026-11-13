/** Real upload/download + deterministic chat fixtures. Start the app before running. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium } from '@playwright/test';
import sharp from 'sharp';

const baseUrl = process.env.AI_CHAT_BASE_URL ?? 'http://localhost:3000';
const output = 'coverage/ai-chat-attachments';
await mkdir(output, { recursive: true });
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce', permissions: ['clipboard-read', 'clipboard-write'] });
const page = await context.newPage();
const report = { checks: [], errors: [] };
page.on('pageerror', (error) => report.errors.push(error.message));
function check(name, condition) { assert.ok(condition, name); report.checks.push(name); console.log(`PASS ${name}`); }
const png = await sharp({ create: { width: 100, height: 80, channels: 3, background: '#678' } }).png().toBuffer();
const image = { name: '截图.png', mimeType: 'image/png', buffer: png };
const text = { name: '客户资料.txt', mimeType: 'text/plain', buffer: Buffer.from('客户资料 UTF-8') };
const drafts = () => page.getByTestId('draft-attachment');
const picker = () => page.getByLabel('选择图片或附件', { exact: true });
async function until(test) {
  const deadline = Date.now() + 25_000;
  while (Date.now() < deadline) { if (await test()) return; await page.waitForTimeout(60); }
  throw new Error('Timed out waiting for attachment state');
}
async function ready(count) { await until(async () => await drafts().count() === count && await page.getByText('正在上传附件…', { exact: true }).count() === 0); }
let body;
await page.route('**/api/ai-chat', async (route) => {
  body = route.request().postDataJSON();
  const frames = [ { type: 'start', messageId: crypto.randomUUID() }, { type: 'text-start', id: 't' }, { type: 'text-delta', id: 't', delta: '附件传输测试完成。' }, { type: 'text-end', id: 't' }, { type: 'finish', finishReason: 'stop' } ];
  await route.fulfill({ contentType: 'text/event-stream', headers: { 'x-vercel-ai-ui-message-stream': 'v1' }, body: frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join('') + 'data: [DONE]\n\n' });
});

try {
  await page.goto(`${baseUrl}/dashboard/ai-chat`);
  await page.getByTestId('chat-composer').waitFor();
  const fileChooser = page.waitForEvent('filechooser');
  await page.getByRole('button', { name: '添加图片或附件', exact: true }).click();
  await (await fileChooser).setFiles([image, text]);
  await ready(2);
  check('Picker uploads image and UTF-8 file with thumbnails and ready state', await drafts().filter({ hasText: '已上传' }).count() === 2 && await drafts().locator('img').count() === 1);
  check('Attachment-only message can be sent', await page.getByTestId('send-message').isEnabled());
  await page.waitForTimeout(550);
  await page.reload();
  await ready(2);
  check('Uploaded draft references survive refresh', await drafts().filter({ hasText: '客户资料.txt' }).count() === 1);
  await until(async () => await drafts().locator('img').evaluateAll((images) => images.every((image) => image.complete && image.naturalWidth > 0)));
  await page.screenshot({ path: `${output}/desktop.png` });
  await page.getByTestId('send-message').click();
  await page.getByTestId('assistant-response-text').waitFor();
  const parts = body.messages.at(-1).parts.filter((part) => part.type === 'file');
  check('Canonical request carries two standard file parts without embedded data', parts.length === 2 && parts.every((part) => /^\/api\/ai-chat\/attachments\//.test(part.url)) && !JSON.stringify(body).includes('base64'));
  check('Attachment-only message has no empty text bubble', await page.locator('[data-align="end"] [data-slot="bubble-content"]').count() === 0);
  check('Sent attachments remain visible and composer clears', await page.getByTestId('message-attachment').count() === 2 && await drafts().count() === 0);
  const download = await context.request.get(`${baseUrl}${parts.find((part) => part.filename === '客户资料.txt').url}`);
  check('Real uploaded file downloads with original bytes', download.ok() && await download.text() === '客户资料 UTF-8');
  await page.waitForTimeout(550);
  await page.reload();
  await page.getByTestId('chat-composer').waitFor();
  check('Sent file parts restore from history', await page.getByTestId('message-attachment').count() === 2);

  await page.evaluate(async (bytes) => {
    await navigator.clipboard.write([new ClipboardItem({ 'image/png': new Blob([new Uint8Array(bytes)], { type: 'image/png' }) })]);
  }, [...png]);
  await page.getByTestId('chat-composer').focus();
  await page.keyboard.press('Control+V');
  await ready(1);
  check('Native clipboard paste uploads an image', await drafts().locator('img').count() === 1);
  await page.getByRole('button', { name: /^移除附件/ }).click();
  await page.evaluate(async () => navigator.clipboard.writeText('普通文本粘贴'));
  await page.getByTestId('chat-composer').focus();
  await page.keyboard.press('Control+V');
  check('Plain clipboard text still pastes normally', await page.getByTestId('chat-composer').inputValue() === '普通文本粘贴');
  await picker().setInputFiles({ name: 'bad.exe', mimeType: 'application/octet-stream', buffer: Buffer.from('x') });
  check('Unsupported type shows accessible feedback and retains text', await page.getByRole('alert').filter({ hasText: '不支持此文件类型' }).count() === 1 && await page.getByTestId('chat-composer').inputValue() === '普通文本粘贴');
  await picker().setInputFiles({ name: 'large.txt', mimeType: 'text/plain', buffer: Buffer.alloc(10 * 1024 * 1024 + 1, 65) });
  check('Oversize file is rejected before upload', await page.getByRole('alert').filter({ hasText: '单个文件不能超过' }).count() === 1);

  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  const delayUpload = async (route) => { await gate; await route.continue().catch(() => {}); };
  await page.route('**/api/ai-chat/attachments', delayUpload);
  await picker().setInputFiles(text);
  await until(async () => await page.getByText('正在上传附件…', { exact: true }).count() === 1);
  check('Pending upload blocks send and session switch', await page.getByTestId('send-message').isDisabled() && await page.getByTestId('new-conversation').isDisabled());
  await page.getByRole('button', { name: /^移除附件/ }).click();
  release();
  await page.unroute('**/api/ai-chat/attachments', delayUpload);
  await page.waitForTimeout(350);
  check('Removing a pending upload cancels it without late resurrection', await drafts().count() === 0);

  await page.getByTestId('chat-composer').fill('');
  await page.route('**/api/ai-chat/attachments', (route) => route.fulfill({ status: 503, json: { error: 'private server detail' } }), { times: 1 });
  await picker().setInputFiles(text);
  await until(async () => await drafts().filter({ hasText: '上传失败' }).count() === 1);
  check('Upload error is recoverable and does not leak server details', await page.getByTestId('send-message').isDisabled() && !(await page.locator('body').innerText()).includes('private server detail'));
  await page.getByRole('button', { name: /^重试上传/ }).click();
  await ready(1);
  check('Retry uses real upload and keeps the selected file', await drafts().filter({ hasText: '已上传' }).count() === 1);
  await page.getByRole('button', { name: /^移除附件/ }).click();

  const data = await page.evaluateHandle(() => { const transfer = new DataTransfer(); transfer.items.add(new File(['dragged'], '拖入.txt', { type: 'text/plain' })); return transfer; });
  await page.locator('form').last().dispatchEvent('drop', { dataTransfer: data });
  await ready(1);
  check('Drag and drop uploads files', await drafts().filter({ hasText: '拖入.txt' }).count() === 1);
  await picker().setInputFiles(Array.from({ length: 5 }, (_, i) => ({ name: `file-${i}.txt`, mimeType: 'text/plain', buffer: Buffer.from('ok') })));
  await ready(5);
  check('Per-message file count limit is enforced', await page.getByRole('alert').filter({ hasText: '最多添加 5 个' }).count() === 1);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: `${output}/mobile.png` });
  check('Mobile attachment row stays inside the viewport', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  // Exercise the real SSE transport with animation enabled, not just instant fixtures.
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.emulateMedia({ reducedMotion: 'no-preference' });
  while (await drafts().count()) await page.getByRole('button', { name: /^移除附件/ }).first().click();
  await picker().setInputFiles(image);
  await ready(1);
  await page.unroute('**/api/ai-chat');
  await page.getByTestId('send-message').click();
  await until(async () => await page.getByTestId('chat-status').getAttribute('data-status') === 'streaming');
  const thumbnail = page.getByTestId('message-attachment').locator('img').last();
  await until(async () => await thumbnail.evaluate((image) => image.complete && image.naturalWidth > 0));
  let imageRequests = 0;
  const observedUrl = await thumbnail.getAttribute('src');
  const countRequest = (request) => { if (new URL(request.url()).pathname === observedUrl) imageRequests++; };
  page.on('request', countRequest);
  await thumbnail.evaluate((image) => {
    window.__attachmentSample = { image, changes: 0, frames: 0, unloaded: 0, replaced: 0, text: document.querySelector('[data-testid="reasoning-viewport"]')?.textContent.length ?? 0 };
    const sample = window.__attachmentSample;
    sample.observer = new MutationObserver((records) => { sample.changes += records.length; });
    sample.observer.observe(image, { attributes: true, attributeFilter: ['src', 'srcset'] });
    const frame = () => {
      sample.frames++;
      if (!image.isConnected) sample.replaced++;
      if (!image.complete || image.naturalWidth === 0) sample.unloaded++;
      sample.raf = requestAnimationFrame(frame);
    };
    sample.raf = requestAnimationFrame(frame);
  });
  await page.waitForTimeout(2500);
  const stability = await page.evaluate(() => {
    const sample = window.__attachmentSample;
    sample.observer.disconnect(); cancelAnimationFrame(sample.raf);
    return { changes: sample.changes, frames: sample.frames, unloaded: sample.unloaded, replaced: sample.replaced, growth: (document.querySelectorAll('[data-testid="reasoning-viewport"]')[0]?.textContent.length ?? 0) - sample.text };
  });
  page.off('request', countRequest);
  console.log('Thumbnail stability', JSON.stringify({ ...stability, imageRequests }));
  check('Thumbnail stays decoded without src reassignment or reload while real SSE grows', stability.frames > 20 && stability.growth > 0 && stability.changes === 0 && stability.unloaded === 0 && stability.replaced === 0 && imageRequests === 0);
  await page.getByTestId('stop-stream').click();
  await until(async () => await page.getByTestId('chat-status').getAttribute('data-status') === 'ready');
  check('No browser runtime errors', report.errors.length === 0);
} finally {
  await writeFile(`${output}/report.json`, JSON.stringify(report, null, 2));
  await browser.close();
}
