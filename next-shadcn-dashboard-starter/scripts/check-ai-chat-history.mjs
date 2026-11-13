/** Session regression using deterministic SSE fixtures; start the app first. */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import { chromium } from '@playwright/test';

const baseUrl = process.env.AI_CHAT_BASE_URL ?? 'http://localhost:3000';
const output = 'coverage/ai-chat-history';
await mkdir(output, { recursive: true });
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
const page = await context.newPage();
const report = { checks: [], errors: [] };
page.on('pageerror', (error) => report.errors.push(error.message));
let requestBody;
let turn = 0;
let delay = 0;
function check(name, condition) { assert.ok(condition, name); report.checks.push(name); console.log(`PASS ${name}`); }
async function until(test, timeout = 15_000) {
  const deadline = Date.now() + timeout;
  while (Date.now() < deadline) { if (await test()) return; await page.waitForTimeout(40); }
  throw new Error('Timed out waiting for history state');
}
const status = () => page.getByTestId('chat-status').getAttribute('data-status');
async function send(text) {
  await page.getByTestId('chat-composer').fill(text);
  await page.getByTestId('send-message').click();
  await until(async () => (await status()) === 'ready' && (await page.getByTestId('assistant-response-text').count()) > 0);
}
async function openHistory() {
  await page.getByRole('button', { name: '打开历史会话', exact: true }).click();
  await page.getByTestId('conversation-history').waitFor();
}
const rows = () => page.getByTestId('conversation-row');
async function openAction(row, name) {
  await row.hover();
  await row.getByRole('button', { name: /^会话操作：/ }).click();
  await page.getByRole('menuitem', { name, exact: true }).click();
}
const firstArtifact = { schemaVersion: 1, id: 'same-artifact-id', kind: 'document', revision: 2, status: 'ready', title: '历史报告', autoOpen: true, preview: { renderer: 'document', version: 1, data: { markdown: '# 会话独立报告\n\n完整历史成果' } } };
await page.route('**/api/ai-chat', async (route) => {
  requestBody = route.request().postDataJSON();
  const current = ++turn;
  if (delay) await new Promise((resolve) => setTimeout(resolve, delay));
  const frames = [
    { type: 'start', messageId: `assistant-${current}` },
    { type: 'tool-input-available', toolCallId: `tool-${current}`, toolName: 'createArtifact', input: { kind: 'document', source: 'fixture', format: 'structured-preview' } },
    { type: 'tool-output-available', toolCallId: `tool-${current}`, output: { artifactId: firstArtifact.id, status: 'ready', previewOnly: true } },
    { type: 'data-artifact', id: firstArtifact.id, data: firstArtifact },
    { type: 'text-start', id: 'answer' },
    { type: 'text-delta', id: 'answer', delta: `完整会话回复 ${current} 👨‍👩‍👧‍👦` },
    { type: 'text-end', id: 'answer' },
    { type: 'finish', finishReason: 'stop' }
  ];
  await route.fulfill({ contentType: 'text/event-stream', headers: { 'x-vercel-ai-ui-message-stream': 'v1' }, body: frames.map((frame) => `data: ${JSON.stringify(frame)}\n\n`).join('') + 'data: [DONE]\n\n' });
});

try {
  await page.goto(`${baseUrl}/dashboard/ai-chat`);
  await page.getByTestId('conversation-history').waitFor();
  check('Initial history has one empty conversation', await rows().count() === 1);
  await page.getByTestId('chat-composer').fill('空会话草稿');
  await page.waitForTimeout(450);
  await page.reload();
  await page.getByTestId('conversation-history').waitFor();
  check('Empty draft-only session survives reload without a storage warning', await page.getByTestId('chat-composer').inputValue() === '空会话草稿' && await page.getByText(/^(历史会话存储提示|临时会话模式)$/).count() === 0);

  await send('第一份报告');
  const firstId = requestBody.conversationId;
  check('Transport uses the selected stable conversation identity', requestBody.id === firstId && firstId.length > 0);
  await page.getByTestId('artifact-close').click();
  await openAction(rows().first(), '重命名');
  await page.getByRole('textbox', { name: /^会话标题/ }).fill('季度复盘');
  await page.getByRole('button', { name: '保存标题' }).click();
  await until(async () => (await rows().first().innerText()).includes('季度复盘'));
  await page.getByTestId('chat-composer').fill('待发送的草稿');
  await page.getByTestId('new-conversation').click();
  check('New conversation preserves the previous session', await rows().count() === 2 && await page.getByTestId('assistant-response-text').count() === 0);
  await send('第二份报告');
  check('Another session receives a distinct identity and isolated message list', requestBody.conversationId !== firstId && requestBody.messages.length === 1);
  await page.getByTestId('artifact-close').click();
  check('A new session derives its own title', requestBody.messages[0].parts.some((part) => part.text === '第二份报告') && (await rows().filter({ hasText: '第二份报告' }).count()) === 1);
  await page.getByLabel('搜索历史会话').fill('不存在');
  await page.getByText('没有匹配的会话').waitFor();
  await page.getByLabel('搜索历史会话').fill('季度');
  check('Title search filters history', await rows().count() === 1);
  await page.getByTestId('select-conversation').click();
  check('Switch restores the draft and original canonical content', await page.getByTestId('chat-composer').inputValue() === '待发送的草稿' && (await page.getByTestId('assistant-response-text').innerText()).includes('回复 1'));
  check('Switch does not auto-open historical artifacts', await page.getByTestId('artifact-panel').count() === 0);
  await page.getByTestId('artifact-card').click();
  check('Historical artifact preview is reconstructed', (await page.getByTestId('document-preview').innerText()).includes('完整历史成果'));
  await page.getByTestId('artifact-close').click();
  await page.waitForTimeout(450);
  await page.reload();
  await page.getByTestId('conversation-history').waitFor();
  check('Reload restores selected session, draft, title and messages', await page.getByTestId('chat-composer').inputValue() === '待发送的草稿' && await rows().count() === 2 && (await page.getByTestId('assistant-response-text').innerText()).includes('回复 1'));
  await page.screenshot({ animations: 'disabled', path: `${output}/desktop.png` });
  await page.getByRole('button', { name: '收起历史会话', exact: true }).click();
  await until(async () => await page.getByTestId('conversation-history').count() === 0);
  await openHistory();
  check('Desktop history can collapse and reopen', await rows().count() === 2);
  const selectedRow = rows().filter({ has: page.locator('[aria-current="page"]') });
  await selectedRow.getByTestId('select-conversation').focus();
  const moreButton = selectedRow.getByRole('button', { name: /^会话操作：/ });
  await until(async () => await moreButton.evaluate((element) => getComputedStyle(element).opacity === '1'));
  check('Keyboard focus reveals the row menu', await moreButton.evaluate((element) => getComputedStyle(element).opacity === '1'));
  await moreButton.focus();
  await page.keyboard.press('Enter');
  await page.getByRole('menuitem', { name: '重命名', exact: true }).waitFor();
  check('More menu opens from the keyboard', await page.getByRole('menuitem', { name: '删除会话', exact: true }).isVisible());
  await page.keyboard.press('Escape');

  delay = 1200;
  await page.getByTestId('chat-composer').fill('继续');
  await page.getByTestId('send-message').click();
  await until(async () => (await status()) === 'submitted');
  check('Session-changing actions are disabled while a request is active', await page.getByTestId('new-conversation').isDisabled() && await page.getByTestId('select-conversation').first().isDisabled() && await rows().first().getByRole('button', { name: /^会话操作：/ }).isDisabled());
  await until(async () => (await status()) === 'ready');
  delay = 0;
  if (await page.getByTestId('artifact-close').isVisible()) await page.getByTestId('artifact-close').click();
  check('Manual title survives subsequent turns', (await rows().first().innerText()).includes('季度复盘'));
  await page.getByTestId('chat-composer').fill('');
  await page.getByTestId('new-conversation').click();
  await openAction(rows().filter({ has: page.locator('[aria-current="page"]') }), '删除会话');
  await page.getByRole('button', { name: '取消', exact: true }).click();
  check('Cancel deletion preserves history', await rows().count() === 3);
  await openAction(rows().filter({ has: page.locator('[aria-current="page"]') }), '删除会话');
  await page.getByRole('button', { name: '确认删除', exact: true }).click();
  check('Deleting active conversation selects a remaining conversation', await rows().count() === 2 && await page.getByTestId('assistant-response-text').count() > 0);

  await page.setViewportSize({ width: 390, height: 844 });
  await openHistory();
  check('Mobile history uses an accessible dialog', await page.getByRole('dialog', { name: '历史会话', exact: true }).isVisible());
  await page.screenshot({ animations: 'disabled', path: `${output}/mobile-history.png` });
  await page.getByTestId('select-conversation').filter({ hasText: '第二份报告' }).click();
  await until(async () => await page.getByRole('dialog', { name: '历史会话', exact: true }).count() === 0);
  check('Mobile selection closes history and restores matching content', await page.getByRole('dialog', { name: '历史会话', exact: true }).count() === 0 && (await page.getByTestId('assistant-response-text').innerText()).includes('回复 2'));
  await openHistory();
  await page.keyboard.press('Escape');
  await until(async () => await page.getByRole('dialog', { name: '历史会话', exact: true }).count() === 0);
  check('Mobile history restores focus to its trigger', await page.getByRole('button', { name: '打开历史会话', exact: true }).evaluate((element) => document.activeElement === element));
  check('Mobile workspace does not overflow horizontally', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ animations: 'disabled', path: `${output}/mobile-chat.png` });

  await page.setViewportSize({ width: 1440, height: 1000 });
  while (await page.getByTestId('assistant-response-text').count()) {
    await openAction(rows().filter({ has: page.locator('[aria-current="page"]') }), '删除会话');
    await page.getByRole('button', { name: '确认删除', exact: true }).click();
  }
  check('Deleting the last session leaves a valid empty conversation', await rows().count() === 1);
  // Preserve corrupt storage instead of replacing it with an empty initial state.
  const corruptContext = await browser.newContext();
  await corruptContext.addInitScript(() => localStorage.setItem('ai-chat:history:v1', '{broken'));
  const corrupt = await corruptContext.newPage();
  await corrupt.goto(`${baseUrl}/dashboard/ai-chat`);
  await corrupt.getByText(/^(历史会话存储提示|临时会话模式)$/).waitFor();
  check('Corrupt history falls back visibly without overwriting original storage', await corrupt.evaluate(() => localStorage.getItem('ai-chat:history:v1')) === '{broken');
  await corruptContext.close();

  const blockedContext = await browser.newContext();
  await blockedContext.addInitScript(() => { window.__nativeSetItem = Storage.prototype.setItem;
    Storage.prototype.setItem = () => { throw new DOMException('Quota exceeded', 'QuotaExceededError'); }; });
  const blocked = await blockedContext.newPage();
  await blocked.goto(`${baseUrl}/dashboard/ai-chat`);
  await blocked.getByText(/^(历史会话存储提示|会话尚未保存)$/).waitFor();
  check('Storage quota failure leaves the conversation usable and offers retry', await blocked.getByTestId('chat-composer').isVisible() && await blocked.getByRole('button', { name: '重试保存' }).isVisible());
  await blocked.evaluate(() => { Storage.prototype.setItem = window.__nativeSetItem; });
  await blocked.getByRole('button', { name: '重试保存' }).click();
  await until(async () => await blocked.getByRole('button', { name: '重试保存' }).count() === 0);
  check('Retry saves the current session and clears the warning', await blocked.evaluate(() => localStorage.getItem('ai-chat:history:v1') !== null));
  await blockedContext.close();
  const touchContext = await browser.newContext({ viewport: { width: 390, height: 844 }, hasTouch: true });
  const touchPage = await touchContext.newPage();
  await touchPage.goto(`${baseUrl}/dashboard/ai-chat`);
  await touchPage.getByRole('button', { name: '打开历史会话', exact: true }).click();
  const touchMenu = touchPage.getByRole('button', { name: /^会话操作：/ });
  await until(async () => await touchMenu.evaluate((element) => getComputedStyle(element).opacity === '1'));
  await touchMenu.tap();
  await touchPage.getByRole('menuitem', { name: '重命名', exact: true }).waitFor();
  check('Touch users can discover and open the more menu without hover', await touchPage.getByRole('menuitem', { name: '删除会话', exact: true }).isVisible());
  await touchContext.close();
  check('No browser runtime errors', report.errors.length === 0);
  report.passed = true;
} catch (error) {
  report.passed = false; report.failure = error.stack ?? String(error); process.exitCode = 1;
  await page.screenshot({ animations: 'disabled', path: `${output}/failure.png` }).catch(() => {});
  console.error(report.failure);
} finally {
  await writeFile(`${output}/report.json`, JSON.stringify(report, null, 2));
  await browser.close();
}
