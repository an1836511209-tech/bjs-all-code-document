/** Theme integration regression against the real app. Start the app before running. */
import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import { chromium } from '@playwright/test';

const baseUrl = process.env.AI_CHAT_BASE_URL ?? 'http://localhost:3000';
const output = 'coverage/ai-chat-themes';
await mkdir(output, { recursive: true });
// Use the maintained registry rather than maintaining a second list of themes.
const registry = await readFile('src/components/themes/theme.config.ts', 'utf8');
const themes = [...registry.matchAll(/name:\s*'([^']+)'\s*,\s*value:\s*'([^']+)'/g)]
  .map(([, name, value]) => ({ name, value }));
assert.ok(themes.length > 0, 'Theme registry must be discoverable');
const markdown = '# 主题检查\n\n正文、**重点**、[链接](https://example.com) 和 `inline code`。\n\n| 指标 | 值 |\n| --- | --- |\n| 营收 | 100 |\n\n```json\n{ "preview": true }\n```';
const previews = [
  { kind: 'document', renderer: 'document', data: { markdown } },
  { kind: 'spreadsheet', renderer: 'spreadsheet', data: { sheets: [{ name: '营收', columns: ['指标', '数值'], rows: [['收入', 100], ['变化', -10]] }] } },
  { kind: 'presentation', renderer: 'presentation', data: { slides: [{ id: 's1', title: '经营汇报', bullets: ['收入增长', '持续跟踪客户留存'] }] } },
  { kind: 'custom', renderer: 'bi-dashboard', data: { title: '经营看板', period: '本月', kpis: [{ label: '营收', value: '100' }], series: [{ label: '增长', value: 100 }, { label: '减少', value: -10 }], highlights: ['检查正负数据颜色'] } }
];
const artifacts = previews.map((item, index) => ({ schemaVersion: 1, id: `theme-artifact-${index}`, revision: 1, status: 'ready', kind: item.kind, title: item.renderer, preview: { renderer: item.renderer, version: 1, data: item.data } }));
const attachment = { id: 'cbbd92b9-6364-4d68-af8e-2900d5a79f4b', filename: '主题附件.txt', mediaType: 'text/plain', size: 100, url: '/api/ai-chat/attachments/cbbd92b9-6364-4d68-af8e-2900d5a79f4b', expiresAt: '2036-01-01T00:00:00.000Z' };
const conversation = {
  id: 'theme-conversation', title: '主题适配检查', titleSource: 'manual',
  createdAt: '2026-01-01T00:00:00.000Z', updatedAt: '2026-01-01T00:00:00.000Z', draft: '可发送的草稿', scenario: 'document',
  draftAttachments: [attachment],
  artifacts: Object.fromEntries(artifacts.map((item) => [item.id, item])),
  messages: [
    { id: 'theme-user', role: 'user', parts: [{ type: 'text', text: '检查主题配色与可读性' }, { type: 'file', filename: attachment.filename, mediaType: attachment.mediaType, url: attachment.url }] },
    { id: 'theme-assistant', role: 'assistant', parts: [
      { type: 'reasoning', state: 'done', text: '主题应统一使用语义 token。\n'.repeat(10) },
      { type: 'tool-createArtifact', toolCallId: 'theme-tool', state: 'output-available', input: { kind: 'document', source: 'fixture', format: 'structured-preview' }, output: { artifactId: artifacts[0].id, status: 'ready', previewOnly: true } },
      { type: 'text', text: markdown },
      ...artifacts.map((data) => ({ type: 'data-artifact', id: data.id, data }))
    ] }
  ]
};
const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1600, height: 1000 }, reducedMotion: 'reduce' });
await context.addInitScript((history) => {
  localStorage.setItem('ai-chat:history:v1', JSON.stringify(history));
  if (!localStorage.getItem('theme')) localStorage.setItem('theme', 'light');
}, { schemaVersion: 1, activeId: conversation.id, conversations: [conversation] });
const page = await context.newPage();
page.setDefaultTimeout(15_000);
const report = { checks: [], samples: [], errors: [], passed: false };
page.on('pageerror', (error) => report.errors.push(error.message));
let label = '';
function check(name, value, details) {
  assert.ok(value, `${label}: ${name}: ${JSON.stringify(details)}`);
  report.checks.push(`${label}: ${name}`);
}
async function token(locator, property, variable) {
  const sample = await locator.first().evaluate((element, { property, variable }) => {
    const probe = document.createElement('span');
    probe.style.setProperty(property, `var(${variable})`);
    document.body.append(probe);
    const actual = getComputedStyle(element).getPropertyValue(property);
    const expected = getComputedStyle(probe).getPropertyValue(property);
    probe.remove();
    // Canvas normalizes CSS Color 4 output (lab/oklch/color-mix) to sRGB RGBA.
    const context = document.createElement('canvas').getContext('2d');
    const rgba = (color) => {
      context.clearRect(0, 0, 1, 1); context.fillStyle = color; context.fillRect(0, 0, 1, 1);
      return [...context.getImageData(0, 0, 1, 1).data];
    };
    return { actual: rgba(actual), expected: rgba(expected), variable, property, defined: getComputedStyle(document.documentElement).getPropertyValue(variable).trim().length > 0 };
  }, { property, variable });
  check(`${property} resolves ${variable}`, sample.defined && sample.actual.every((channel, index) => Math.abs(channel - sample.expected[index]) <= 1), sample);
  return sample.actual;
}
async function pair(locator, background, foreground) {
  const bg = await token(locator, 'background-color', background);
  const fg = await token(locator, 'color', foreground);
  return { bg, fg };
}
function contrast({ bg, fg }) {
  const luminance = (rgb) => rgb.slice(0, 3).map((value) => {
    const s = value / 255; return s <= 0.04045 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
  }).reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
  const a = luminance(bg), b = luminance(fg);
  return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
}
async function closePreview() {
  await page.getByTestId('artifact-close').click();
  await page.getByTestId('artifact-panel').waitFor({ state: 'detached' });
}
try {
  await page.goto(`${baseUrl}/dashboard/ai-chat`, { waitUntil: 'domcontentloaded', timeout: 60_000 });
  await page.getByTestId('conversation-history').waitFor();
  for (const mode of ['light', 'dark']) {
    if (mode === 'dark') await page.getByRole('button', { name: 'Toggle theme', exact: true }).click();
    await page.waitForFunction((dark) => document.documentElement.classList.contains('dark') === dark, mode === 'dark');
    for (const theme of themes) {
      label = `${theme.value}/${mode}`;
      await page.locator('#theme-selector').click();
      await page.getByRole('option', { name: theme.name, exact: true }).click();
      await page.waitForFunction((value) => document.documentElement.dataset.theme === value, theme.value);
      // Shared buttons transition colors; test the settled selected palette.
      await page.waitForTimeout(250);
      await pair(page.locator('body'), '--background', '--foreground');
      await pair(page.locator('aside[aria-label="历史会话"]'), '--sidebar', '--sidebar-foreground');
      const selected = await pair(page.locator('[data-testid="select-conversation"][aria-current]'), '--sidebar-accent', '--sidebar-accent-foreground');
      check('Selected conversation text meets 4.5:1 contrast', contrast(selected) >= 4.5, selected);
      await page.getByTestId('new-conversation').hover();
      await page.waitForTimeout(250);
      await pair(page.getByTestId('new-conversation'), '--sidebar-accent', '--sidebar-accent-foreground');
      await pair(page.locator('[data-align="end"] [data-slot="bubble-content"]'), '--secondary', '--secondary-foreground');
      await pair(page.getByTestId('send-message'), '--primary', '--primary-foreground');
      await pair(page.getByTestId('draft-attachment'), '--card', '--card-foreground');
      await pair(page.getByTestId('message-attachment'), '--card', '--card-foreground');
      await token(page.getByTestId('draft-attachment').locator('[data-slot="attachment-description"]'), 'color', '--muted-foreground');
      await token(page.locator('[data-testid="assistant-response-text"] a'), 'color', '--primary');
      await token(page.locator('[data-testid="reasoning-viewport"] p'), 'color', '--muted-foreground');
      const font = await page.evaluate(() => ({ alias: getComputedStyle(document.documentElement).getPropertyValue('--font-sans'), body: getComputedStyle(document.body).fontFamily, loaded: getComputedStyle(document.documentElement).getPropertyValue('--font-geist-sans') }));
      check('Theme font alias is resolved at html', font.alias.trim().length > 0 && font.loaded.includes('Geist'), font);
      if (theme.value === 'vercel') check('Local Geist font is used', font.body.includes('GeistSans'), font);
      for (const [index, preview] of previews.entries()) {
        await page.getByTestId('artifact-card').nth(index).click();
        const panel = page.getByTestId('artifact-panel');
        await pair(panel, '--background', '--foreground');
        const view = page.getByTestId(`${preview.kind === 'custom' ? 'dashboard' : preview.renderer}-preview`);
        await view.waitFor();
        if (preview.kind === 'document') await pair(view.locator('article'), '--card', '--card-foreground');
        if (preview.kind === 'presentation') await pair(view.locator('section').first(), '--card', '--card-foreground');
        if (preview.kind === 'spreadsheet') {
          const header = await pair(page.getByTestId('spreadsheet-column-header'), '--secondary', '--secondary-foreground');
          check('Spreadsheet column text meets 4.5:1 contrast', contrast(header) >= 4.5, header);
          if (['claude', 'discord', 'astro-vista'].includes(theme.value)) await page.screenshot({ path: `${output}/${theme.value}-${mode}-spreadsheet.png`, animations: 'disabled' });
        }
        if (preview.kind === 'custom') {
          await token(page.locator('[data-testid="dashboard-series-bar"][data-negative="false"]'), 'background-color', '--chart-1');
          await token(page.locator('[data-testid="dashboard-series-bar"][data-negative="true"]'), 'background-color', '--destructive');
        }
        await closePreview();
      }
      const row = page.getByTestId('conversation-row');
      await row.hover();
      await row.getByRole('button', { name: /^会话操作：/ }).click();
      await pair(page.getByRole('menu'), '--popover', '--popover-foreground');
      await page.getByRole('menuitem', { name: '重命名', exact: true }).click();
      await pair(page.getByRole('dialog', { name: '重命名会话', exact: true }), '--popover', '--popover-foreground');
      await page.getByRole('button', { name: '取消', exact: true }).click();
      await page.setViewportSize({ width: 390, height: 844 });
      await page.getByRole('button', { name: '打开历史会话', exact: true }).click();
      await pair(page.getByRole('dialog', { name: '历史会话', exact: true }), '--sidebar', '--sidebar-foreground');
      await page.keyboard.press('Escape');
      await page.getByRole('dialog', { name: '历史会话', exact: true }).waitFor({ state: 'detached' });
      await page.getByTestId('artifact-card').nth(1).click();
      await pair(page.getByTestId('artifact-panel'), '--background', '--foreground');
      await pair(page.getByTestId('spreadsheet-column-header'), '--secondary', '--secondary-foreground');
      check('Mobile has no horizontal overflow', await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth));
      await closePreview();
      await page.setViewportSize({ width: 1600, height: 1000 });
      report.samples.push({ theme: theme.value, mode, selectedContrast: contrast(selected), font: font.body });
      console.log(`PASS ${label}: desktop/mobile, four previews, popovers and fonts`);
    }
  }
  await page.reload({ waitUntil: 'domcontentloaded', timeout: 60_000 });
  await page.getByTestId('conversation-history').waitFor();
  check('Theme selection persists after reload', await page.locator('html').getAttribute('data-theme') === themes.at(-1).value);
  check('Dark mode persists after reload', await page.locator('html').evaluate((element) => element.classList.contains('dark')));
  check('No browser runtime errors', report.errors.length === 0, report.errors);
  report.passed = true;
} catch (error) {
  report.failure = error.stack ?? String(error); process.exitCode = 1;
  await page.screenshot({ path: `${output}/failure.png`, animations: 'disabled' }).catch(() => {});
  console.error(report.failure);
} finally {
  await writeFile(`${output}/report.json`, JSON.stringify(report, null, 2));
  await browser.close();
}
