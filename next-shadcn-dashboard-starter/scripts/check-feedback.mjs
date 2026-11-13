/** Fault injection against a running app; evidence stays in ignored coverage/. */
import assert from 'node:assert/strict';
import { existsSync } from 'node:fs';
import { mkdir, writeFile, readFile } from 'node:fs/promises';
import { chromium, expect } from '@playwright/test';

const baseUrl = process.env.AI_CHAT_BASE_URL ?? 'http://localhost:3000';
const output = 'coverage/feedback';
await mkdir(output, { recursive: true });
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
const page = await context.newPage();
const report = { checks: [], errors: [] };
page.on('pageerror', (error) => report.errors.push(error.message));
function check(name, value) { assert.ok(value, name); report.checks.push(name); console.log(`PASS ${name}`); }
const secret = 'INTERNAL_DATABASE_PASSWORD_MUST_NOT_APPEAR';
try {
  if (existsSync('src/features/ai-chat')) {
  await page.route('**/api/ai-chat', (route) => route.fulfill({ status: 503, body: secret }));
  await page.goto(`${baseUrl}/dashboard/ai-chat`);
  await page.getByTestId('chat-composer').fill('故障测试');
  await page.getByTestId('send-message').click();
  const alert = page.getByRole('alert').filter({ hasText: '回复未完成' });
  await expect(alert).toBeVisible();
  check('Chat uses actionable feedback without leaking server details', !(await page.locator('body').innerText()).includes(secret));
  check('Failed request preserves the user message', (await page.locator('body').innerText()).includes('故障测试'));
  await page.screenshot({ path: `${output}/chat-error-desktop.png` });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(alert.getByRole('button', { name: '继续对话' })).toBeVisible();
  check('Mobile error does not overflow', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  await page.screenshot({ path: `${output}/chat-error-mobile.png` });
  await alert.getByRole('button', { name: '继续对话' }).click();
  await expect(page.getByTestId('chat-composer')).toBeFocused();
  await expect(alert).toHaveCount(0);
  check('Continue clears the error and focuses the composer', true);
  await page.unroute('**/api/ai-chat');

  const storageContext = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  await storageContext.addInitScript(() => { Storage.prototype.getItem = function(key) {
    if (key === 'ai-chat:history:v1') throw new DOMException('Denied', 'SecurityError');
    return null;
  }; });
  const storage = await storageContext.newPage();
  await storage.goto(`${baseUrl}/dashboard/ai-chat`);
  const notice = storage.getByRole('status').filter({ hasText: '临时会话模式' });
  await expect(notice).toBeVisible();
  check('Denied reads show a polite notice and keep chat usable', await storage.getByTestId('chat-composer').isVisible());
  await expect(notice).toContainText('站点存储权限');
  for (const dark of [false, true]) {
    await storage.evaluate((dark) => document.documentElement.classList.toggle('dark', dark), dark);
    await storage.screenshot({ path: `${output}/storage-${dark ? 'dark' : 'light'}.png` });
  }
  await storage.setViewportSize({ width: 390, height: 844 });
  await expect(notice.getByRole('button', { name: '导出当前会话' })).toBeVisible();
  check('Mobile storage notice wraps without horizontal overflow', await storage.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
  const downloadEvent = storage.waitForEvent('download');
  await notice.getByRole('button', { name: '导出当前会话' }).click();
  const download = await downloadEvent;
  const backup = JSON.parse(await readFile(await download.path(), 'utf8'));
  check('Unsaved conversation exports a complete JSON envelope', download.suggestedFilename() === 'ai-chat-history.json' && backup.schemaVersion === 1 && backup.conversations.length === 1);
  await storage.screenshot({ path: `${output}/storage-mobile.png` });
  await storageContext.close();
  const corruptContext = await browser.newContext();
  await corruptContext.addInitScript(() => localStorage.setItem('ai-chat:history:v1', '{broken'));
  const corrupt = await corruptContext.newPage();
  await corrupt.goto(`${baseUrl}/dashboard/ai-chat`);
  await expect(corrupt.getByRole('status').filter({ hasText: '临时会话模式' })).toBeVisible();
  check('Invalid records remain intact with a distinct recovery explanation', await corrupt.evaluate(() => localStorage.getItem('ai-chat:history:v1')) === '{broken' && (await corrupt.locator('body').innerText()).includes('格式不兼容'));
  await corrupt.screenshot({ path: `${output}/corrupt-history.png` });
  await corruptContext.close();
  }

  if (existsSync('src/features/react-query-demo')) {
  await page.setViewportSize({ width: 1440, height: 1000 });
  let failQuery = true;
  const pokemon = (id) => ({ id, name: 'feedback-fixture', sprites: { front_shiny: '', front_default: '' }, types: [], stats: [], height: 4, weight: 60 });
  await page.route('https://pokeapi.co/api/v2/pokemon/**', (route) => {
    const id = Number(route.request().url().split('/').pop());
    return failQuery && id === 1
      ? route.fulfill({ status: 503, body: secret })
      : route.fulfill({ json: pokemon(id) });
  });
  await page.goto(`${baseUrl}/dashboard/react-query`);
  // Server prefetch may fail offline. Its error boundary must recover through the client query.
  const picker = page.getByRole('button', { name: '#1', exact: true });
  await Promise.race([picker.waitFor({ timeout: 60000 }), page.getByRole('button', { name: 'Try again', exact: true }).waitFor({ timeout: 60000 })]);
  if (!(await picker.isVisible())) await page.getByRole('button', { name: 'Try again', exact: true }).click();
  await expect(picker).toBeVisible({ timeout: 60000 });
  await picker.click();
  const routeError = page.getByRole('alert').filter({ hasText: 'Unable to load this page' });
  await expect(routeError).toBeVisible({ timeout: 45000 });
  check('Query failure keeps the dashboard shell and safe copy', await page.locator('#main-content').isVisible() && !(await routeError.innerText()).includes(secret));
  await page.screenshot({ path: `${output}/route-error.png` });
  failQuery = false;
  await routeError.getByRole('button', { name: 'Try again', exact: true }).click();
  await expect(picker).toBeVisible({ timeout: 30000 });
  await picker.click();
  await expect(page.getByText('feedback-fixture', { exact: true })).toBeVisible({ timeout: 30000 });
  check('Query recovery can revisit the previously failed key', true);
  }
  const routes = [
    '/dashboard/overview', '/dashboard/product', '/dashboard/product/new',
    '/dashboard/product/1', '/dashboard/users', '/dashboard/chat',
    '/dashboard/kanban', '/dashboard/notifications', '/dashboard/forms',
    '/dashboard/forms/basic', '/dashboard/forms/advanced', '/dashboard/forms/multi-step',
    '/dashboard/forms/sheet-form', '/dashboard/elements/icons', '/dashboard/ai-chat'
  ];
  for (const route of routes) {
    // Skip optional feature routes after cleanup; source tree is the template's capability map.
    if (!existsSync(`src/app${route}/page.tsx`) && !existsSync(`src/app${route}/layout.tsx`) && !route.startsWith('/dashboard/product/')) continue;
    const response = await page.goto(`${baseUrl}${route}`);
    await page.waitForLoadState('networkidle');
    check(`Route smoke: ${route}`, response.status() === 200 && await page.getByText('Unable to load this page', { exact: true }).count() === 0);
  }
  const missing = await page.goto(`${baseUrl}/missing-feedback-fixture`);
  check('Unknown routes have a usable not-found page', missing.status() === 404 && (await page.locator('body').innerText()).length > 20);
  if (existsSync('src/features/notifications')) {
    const clockContext = await browser.newContext();
    await clockContext.addInitScript(() => { const now = Date.now; Date.now = () => now() + 120000; });
    const clockPage = await clockContext.newPage();
    const clockErrors = [];
    clockPage.on('pageerror', (error) => clockErrors.push(error.message));
    await clockPage.goto(`${baseUrl}/dashboard/notifications`);
    await expect(clockPage.getByText('New team member joined', { exact: true })).toBeVisible();
    await clockPage.waitForTimeout(500);
    check('Notification timestamps hydrate safely with a different browser clock', clockErrors.length === 0);
    await clockContext.close();
  }
  check('No unexpected chat runtime errors', report.errors.every((message) => message.includes('Failed to fetch pokemon') || message.includes('dehydrated as pending')));
  report.passed = true;
} catch (error) {
  report.passed = false; report.failure = error.stack ?? String(error); process.exitCode = 1;
  await page.screenshot({ path: `${output}/failure.png` }).catch(() => {});
  console.error(report.failure);
} finally {
  await writeFile(`${output}/report.json`, JSON.stringify(report, null, 2));
  await browser.close();
}
