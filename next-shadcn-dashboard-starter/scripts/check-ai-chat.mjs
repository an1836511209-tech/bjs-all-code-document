/**
 * Browser regression checks against the real local demo transport.
 * Start the app first, then run `npm run test:ai-chat:browser`.
 * AI_CHAT_BASE_URL and AI_CHAT_OUTPUT_DIR optionally override the defaults.
 */
import assert from 'node:assert/strict';
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const { chromium } = process.env.PLAYWRIGHT_MODULE_PATH
  ? await import(pathToFileURL(path.join(process.env.PLAYWRIGHT_MODULE_PATH, 'index.mjs')).href)
  : await import('@playwright/test');

const baseUrl = process.env.AI_CHAT_BASE_URL ?? 'http://localhost:3000';
const outputDir = path.resolve(process.env.AI_CHAT_OUTPUT_DIR ?? 'coverage/ai-chat');
await mkdir(outputDir, { recursive: true });
const report = { baseUrl, startedAt: new Date().toISOString(), checks: [], samples: [], errors: [] };
const browser = await chromium.launch({ headless: true });
report.browserVersion = browser.version();
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
const page = await context.newPage();
page.setDefaultTimeout(15_000);
page.on('pageerror', (error) => report.errors.push(error.message));

function check(name, condition, details) {
  assert.ok(condition, `${name}: ${JSON.stringify(details)}`);
  report.checks.push({ name, details });
  console.log(`PASS ${name}`);
}

async function until(name, test, timeout = 30_000) {
  const deadline = Date.now() + timeout;
  let last;
  while (Date.now() < deadline) {
    last = await test();
    if (last) return last;
    await page.waitForTimeout(80);
  }
  throw new Error(`Timed out waiting for ${name}; last value: ${JSON.stringify(last)}`);
}

async function metrics(locator, label) {
  const value = await locator.evaluate((element) => ({
    top: Math.round(element.scrollTop),
    height: element.clientHeight,
    total: element.scrollHeight,
    bottom: Math.round(element.scrollHeight - element.clientHeight - element.scrollTop),
    textLength: element.textContent.length,
    width: Math.round(element.getBoundingClientRect().width)
  }));
  if (label) report.samples.push({ label, at: new Date().toISOString(), ...value });
  return value;
}

async function status() {
  return page.getByTestId('chat-status').getAttribute('data-status');
}

async function ready() {
  await until('stream to complete', async () => (await status()) === 'ready', 90_000);
}

async function pointerInside(locator) {
  const box = await locator.boundingBox();
  assert.ok(box, 'Scroll viewport has a visible bounding box');
  // Keep the pointer away from nested thinking/tool scroll areas at the top.
  await page.mouse.move(box.x + box.width - 26, box.y + box.height - 34);
}

async function verifyStreamScroll(locator, name, { keyboard = false } = {}) {
  await until(`${name} overflows while streaming`, async () => {
    const value = await metrics(locator);
    return value.total > value.height + 100 && (await status()) === 'streaming';
  });
  // Assert the snapshot that satisfied the condition, not a second read after
  // another streamed line may have been appended but not yet followed.
  const following = await until(`${name} catches up with rendering`, async () => {
    const sample = await metrics(locator);
    return sample.bottom <= 12 ? sample : null;
  }, 5_000);
  report.samples.push({ label: `${name}: following`, at: new Date().toISOString(), ...following });
  check(`${name}: follows new stream content`, following.bottom <= 12, following);

  await pointerInside(locator);
  await page.mouse.wheel(0, -240);
  await page.waitForTimeout(200);
  const paused = await metrics(locator, `${name}: wheel paused`);
  await page.waitForTimeout(900);
  const held = await metrics(locator, `${name}: paused during new content`);
  check(`${name}: wheel moves up`, paused.bottom > 50, paused);
  check(`${name}: continues receiving content while paused`, held.textLength > paused.textLength, {
    paused,
    held,
    status: await status()
  });
  check(`${name}: does not pull reader down`, Math.abs(held.top - paused.top) <= 8, {
    paused,
    held
  });

  if (keyboard) {
    await locator.focus();
    await page.keyboard.press('End');
  } else {
    await pointerInside(locator);
    await page.mouse.wheel(0, 50_000);
  }
  await until(`${name} returns to bottom`, async () => (await metrics(locator)).bottom <= 12);
  const resumed = await metrics(locator, `${name}: resumed`);
  await page.waitForTimeout(900);
  // Assert the exact sample that satisfied the condition. Reading geometry again
  // after an awaited round-trip can observe the next streamed line before its follow frame.
  const resumedLater = await until(`${name} follows resumed rendering`, async () => {
    const sample = await metrics(locator);
    return sample.bottom <= 12 && sample.textLength > resumed.textLength ? sample : null;
  }, 5_000);
  report.samples.push({ label: `${name}: following resumed content`, ...resumedLater });
  check(`${name}: resumes following at bottom`, resumedLater.bottom <= 12, resumedLater);
  check(`${name}: resume verified during stream growth`, resumedLater.textLength > resumed.textLength, {
    resumed,
    resumedLater
  });

  const thumb = locator.locator('..').locator(':scope > [data-slot="chat-scrollbar"] > [data-slot="chat-scrollbar-thumb"]');
  const box = await thumb.boundingBox();
  assert.ok(box, `${name} has a draggable thumb`);
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  check(`${name}: dragging disables thumb animation`, await thumb.evaluate((element) => getComputedStyle(element).transitionDuration === '0s'));
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2 - 45, { steps: 8 });
  await page.mouse.up();
  await page.waitForTimeout(200);
  const dragged = await metrics(locator);
  await page.waitForTimeout(600);
  const dragHeld = await metrics(locator);
  check(`${name}: thumb drag moves up and holds reading position`,
    dragged.bottom > 30 && Math.abs(dragHeld.top - dragged.top) <= 8,
    { dragged, dragHeld });
  await locator.focus();
  await page.keyboard.press('End');
  await until(`${name} follows after dragging`, async () => (await metrics(locator)).bottom <= 12);
}

async function screenshot(name) {
  // Observe streaming as rendered; disabling animations would fast-forward thumb transitions.
  await page.screenshot({ path: path.join(outputDir, `${name}.png`), fullPage: true });
}

async function clickToolDisclosure(tool) {
  if ((await tool.getAttribute('aria-expanded')) != null) await tool.click();
  else await tool.locator('button').first().click();
}

try {
  await page.goto(`${baseUrl}/dashboard/ai-chat`, { waitUntil: 'networkidle', timeout: 90_000 });
  await page.getByTestId('scenario-document').waitFor();
  const chat = page.getByTestId('chat-viewport');
  const originalChat = await metrics(chat, 'initial chat');
  check('Immersive conversation has no message avatars', (await page.locator('[data-slot="message-avatar"]').count()) === 0);
  await screenshot('01-empty-desktop');
  await page.evaluate(() => {
    window.__chatScrollbarSamples = { 'chat-viewport': [], 'reasoning-viewport': [] };
    const identities = new WeakMap();
    let nextIdentity = 0;
    window.__sampleChatScrollbars = true;
    function sample(now) {
      for (const viewport of document.querySelectorAll('[data-testid="chat-viewport"], [data-testid="reasoning-viewport"]')) {
        if (viewport.scrollHeight <= viewport.clientHeight + 2) continue;
        const track = viewport.nextElementSibling;
        const thumb = track?.querySelector('[data-slot="chat-scrollbar-thumb"]');
        if (!thumb) continue;
        if (!identities.has(thumb)) identities.set(thumb, ++nextIdentity);
        const style = getComputedStyle(thumb);
        const viewportStyle = getComputedStyle(viewport);
        const rect = thumb.getBoundingClientRect();
        const samples = window.__chatScrollbarSamples[viewport.dataset.testid];
        if (samples.length < 10_000) samples.push({
          now, id: identities.get(thumb), height: rect.height, y: rect.y,
          viewportHeight: viewport.clientHeight, width: viewport.clientWidth,
          total: viewport.scrollHeight, top: viewport.scrollTop,
          following: viewport.getAttribute('data-scrollable') === 'start',
          dragging: track.matches(':active'),
          position: style.position,
          lowerEdgeGap: track.getBoundingClientRect().bottom - rect.bottom,
          visible: style.visibility, opacity: style.opacity,
          mask: viewportStyle.maskImage, native: viewportStyle.scrollbarWidth,
          targetHeight: parseFloat(getComputedStyle(track).getPropertyValue('--scroll-area-thumb-height'))
        });
      }
      if (window.__sampleChatScrollbars) requestAnimationFrame(sample);
    }
    requestAnimationFrame(sample);
  });
  await page.getByTestId('scenario-document').click();
  await until('document stream begins', async () => (await status()) === 'streaming');
  const reasoning = page.getByTestId('reasoning-viewport').last();
  await reasoning.waitFor();
  await verifyStreamScroll(reasoning, 'Reasoning');
  check('Reasoning has a bounded scroll window', (await metrics(reasoning)).height <= 220);
  await screenshot('02-reasoning-stream');
  await verifyStreamScroll(chat, 'Conversation', { keyboard: true });
  await screenshot('03-long-response-stream');
  await ready();

  const scrollbarSamples = await page.evaluate(() => {
    window.__sampleChatScrollbars = false;
    return window.__chatScrollbarSamples;
  });
  await writeFile(path.join(outputDir, 'scrollbar-frames.json'), JSON.stringify(scrollbarSamples));
  for (const [name, samples] of Object.entries(scrollbarSamples)) {
    // Base UI measures before revealing a newly mounted scrollbar. Check every
    // subsequent frame, rather than treating that initial measurement as a blink.
    const measured = samples.slice(2);
    check(`${name}: actual thumb stays mounted and visible throughout overflow`,
      samples.length > 100 && new Set(samples.map((s) => s.id)).size === 1 &&
      measured.every((s) => s.visible === 'visible' && Number(s.opacity) > 0 && s.height >= 16),
      { frames: samples.length });
    check(`${name}: one viewport without native scrollbar or scroll-linked mask`,
      samples.every((s) => s.native === 'none' && s.mask === 'none'));
    const growing = samples.filter((s, index) => {
      const previous = samples[index - 1];
      return previous && s.now - previous.now < 50 && s.width === previous.width &&
        s.viewportHeight === previous.viewportHeight && s.total >= previous.total &&
        s.total - previous.total <= 48;
    });
    const interpolated = growing.filter((s) => Math.abs(s.height - s.targetHeight) > 0.2);
    check(`${name}: line growth interpolates thumb size across animation frames`,
      interpolated.length > 5, { interpolatedFrames: interpolated.length });
    const following = measured.filter((s) => s.following && !s.dragging);
    check(`${name}: following thumb lower edge stays pinned without upward jumps`,
      following.length > 100 && following.every((s) => s.position === 'absolute' && Math.abs(s.lowerEdgeGap - 2) < 0.5),
      { frames: following.length, minGap: Math.min(...following.map((s) => s.lowerEdgeGap)), maxGap: Math.max(...following.map((s) => s.lowerEdgeGap)) });
  }

  await page.waitForTimeout(180);
  check('Thumbs settle to measured content proportions', await page.locator('[data-slot="chat-scrollbar-thumb"]').evaluateAll((elements) => elements.length >= 2 && elements.every((element) => Math.abs(element.getBoundingClientRect().height - parseFloat(getComputedStyle(element.parentElement).getPropertyValue('--scroll-area-thumb-height'))) < 1)));

  await page.emulateMedia({ reducedMotion: 'reduce' });
  check('Reduced motion disables both thumb transitions', await page.locator('[data-slot="chat-scrollbar-thumb"]').evaluateAll((elements) => elements.length >= 2 && elements.every((element) => getComputedStyle(element).transitionDuration === '0s')));
  await page.emulateMedia({ reducedMotion: 'no-preference', forcedColors: 'active' });
  check('Forced colors keeps thumbs opaque', await page.locator('[data-slot="chat-scrollbar-thumb"]').evaluateAll((elements) => elements.length >= 2 && elements.every((element) => getComputedStyle(element).opacity === '1')));
  await page.emulateMedia({ forcedColors: 'none' });

  const firstTool = page.getByTestId('tool-call').first();
  await firstTool.scrollIntoViewIfNeeded();
  check('Tool request starts collapsed', !(await page.getByTestId('tool-input').first().isVisible()));
  check('Tool response starts collapsed', !(await page.getByTestId('tool-output').first().isVisible()));
  await clickToolDisclosure(firstTool);
  await page.getByTestId('tool-input').first().waitFor();
  await page.getByTestId('tool-output').first().waitFor();
  const request = await page.getByTestId('tool-input').first().innerText();
  const response = await page.getByTestId('tool-output').first().innerText();
  check('Tool expands both request and result', request.length > 10 && response.length > 10, { request, response });
  await screenshot('04-tool-details');
  await clickToolDisclosure(firstTool);

  const panel = page.getByTestId('artifact-panel');
  await panel.waitFor();
  const splitChat = await metrics(chat, 'chat beside artifact');
  const chatBox = await chat.boundingBox();
  const panelBox = await panel.boundingBox();
  check('Desktop chat narrows for artifact', splitChat.width < originalChat.width * 0.8, { originalChat, splitChat });
  check('Desktop artifact sits to the right', panelBox.x >= chatBox.x + chatBox.width - 4, { chatBox, panelBox });
  await page.getByTestId('document-preview').waitFor();
  check('Document preview contains readable content', (await page.getByTestId('document-preview').innerText()).length > 100);
  await screenshot('05-document-artifact');
  const download = page.getByTestId('artifact-download');
  if (await download.isVisible()) {
    const [file] = await Promise.all([page.waitForEvent('download'), download.click()]);
    check('Artifact download has a filename', Boolean(file.suggestedFilename()), { filename: file.suggestedFilename() });
  } else {
    report.checks.push({ name: 'Download not exercised', details: 'Demo publishes preview data without a downloadable Office file.' });
  }
  await page.getByTestId('artifact-close').click();
  await until('artifact closes', async () => !(await panel.isVisible()));
  await until('chat width restores', async () => (await metrics(chat)).width >= originalChat.width - 4);
  check('Closing artifact restores chat width', (await metrics(chat)).width >= originalChat.width - 4);
  await page.getByTestId('artifact-card').first().click();
  await panel.waitFor();
  check('Artifact can reopen from transcript', await panel.isVisible());

  for (const kind of ['spreadsheet', 'presentation', 'dashboard']) {
    await page.getByTestId('artifact-close').click();
    await page.getByTestId('restart-chat').click();
    await page.getByTestId(`scenario-${kind}`).click();
    await until(`${kind} stream begins`, async () => (await status()) === 'streaming');
    await ready();
    await page.getByTestId(`${kind}-preview`).waitFor();
    if (kind === 'spreadsheet') {
      const preview = page.getByTestId('spreadsheet-preview');
      check('Spreadsheet displays data rows', (await preview.locator('tbody tr').count()) > 1);
      const tabs = preview.getByRole('tab');
      if ((await tabs.count()) > 1) {
        await tabs.nth(1).click();
        check('Spreadsheet changes worksheets', (await tabs.nth(1).getAttribute('aria-selected')) === 'true');
      }
    }
    if (kind === 'presentation') {
      const before = await page.getByTestId('presentation-preview').innerText();
      await page.getByTestId('presentation-next').click();
      check('Presentation advances slides', (await page.getByTestId('presentation-preview').innerText()) !== before);
    }
    if (kind === 'dashboard') {
      const preview = page.getByTestId('dashboard-preview');
      check('Custom dashboard displays metrics and chart', (await preview.locator('article').count()) > 1 && (await preview.getByRole('img').getAttribute('aria-label')).length > 10);
    }
    check(`${kind} renderer displays artifact`, await page.getByTestId(`${kind}-preview`).isVisible());
    await screenshot(`06-${kind}-artifact`);
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await page.waitForTimeout(350);
  const mobilePanel = await panel.boundingBox();
  check('Mobile artifact fits viewport', mobilePanel.x >= -1 && mobilePanel.x + mobilePanel.width <= 391, mobilePanel);
  check('Mobile page has no horizontal overflow', await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
  check('Mobile artifact has dialog semantics', await page.getByRole('dialog').isVisible());
  await page.keyboard.press('Tab');
  await page.keyboard.press('Tab');
  // Base UI briefly focuses a portal guard before wrapping to a dialog control.
  await until('mobile dialog focus settles', async () => page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"]'))));
  check('Mobile dialog contains keyboard focus', await page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"]'))));
  await screenshot('07-mobile-artifact');
  await page.keyboard.press('Escape');
  await until('Escape closes mobile artifact', async () => !(await panel.isVisible()));
  check('Mobile artifact closes with Escape', !(await panel.isVisible()));
  await page.getByTestId('artifact-card').first().click();
  await panel.waitFor();
  await page.getByTestId('artifact-close').click();
  await until('mobile artifact closes', async () => !(await panel.isVisible()));
  await until('mobile focus returns to card', async () => page.evaluate(() => document.activeElement?.getAttribute('data-testid') === 'artifact-card'));
  check('Mobile closing restores card focus', await page.evaluate(() => document.activeElement?.getAttribute('data-testid') === 'artifact-card'));
  await screenshot('08-mobile-chat');
  check('Mobile composer remains accessible', await page.getByTestId('chat-composer').isVisible());

  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByTestId('restart-chat').click();
  await page.getByTestId('scenario-document').click();
  await until('cancellable stream begins', async () => (await status()) === 'streaming');
  await page.waitForTimeout(700);
  await page.getByTestId('stop-stream').click();
  await ready();
  const stopped = await chat.innerText();
  await page.waitForTimeout(700);
  check('Stopping stream prevents late content', (await chat.innerText()) === stopped);
  await page.getByTestId('restart-chat').click();
  await page.waitForTimeout(700);
  check('Restart clears artifact and tool state', (await page.getByTestId('artifact-card').count()) === 0 && (await page.getByTestId('tool-call').count()) === 0);

  // Deterministic contract fixtures complement (and do not replace) the real-stream checks above.
  let fixtureTurn = 0;
  const artifactBase = { schemaVersion: 1, id: 'fixture-report', kind: 'document', title: '契约测试报告', autoOpen: true };
  await page.route('**/api/ai-chat', async (route) => {
    fixtureTurn++;
    let snapshots;
    if (fixtureTurn === 1) {
      snapshots = [{ ...artifactBase, revision: 1, status: 'generating' }];
    } else if (fixtureTurn === 2) {
      snapshots = [
        { ...artifactBase, revision: 2, status: 'ready', title: '已更新报告', preview: { renderer: 'document', version: 1, data: { markdown: '# 已更新\n\n有效正文' } } },
        { ...artifactBase, revision: 1, status: 'generating' },
        null
      ];
    } else if (fixtureTurn === 3) {
      snapshots = [{ ...artifactBase, id: 'unknown-preview', kind: 'custom', revision: 1, status: 'ready', preview: { renderer: 'company.unregistered', version: 1, data: { sample: true } } }];
    } else {
      snapshots = [{ ...artifactBase, id: 'failed-preview', revision: 1, status: 'error', error: '测试服务返回：生成失败，请重试。' }];
    }
    const frames = [
      { type: 'start', messageId: `fixture-message-${fixtureTurn}` },
      ...snapshots.map((data, index) => ({ type: 'data-artifact', id: data?.id ?? `invalid-${index}`, data })),
      { type: 'text-start', id: 'fixture-text' },
      { type: 'text-delta', id: 'fixture-text', delta: '契约测试响应。' },
      { type: 'text-end', id: 'fixture-text' },
      { type: 'finish', finishReason: 'stop' }
    ];
    await route.fulfill({ status: 200, contentType: 'text/event-stream', headers: { 'x-vercel-ai-ui-message-stream': 'v1' }, body: frames.map((event) => `data: ${JSON.stringify(event)}\n\n`).join('') + 'data: [DONE]\n\n' });
  });
  async function sendFixture() {
    await page.getByTestId('chat-composer').fill(`契约测试 ${fixtureTurn + 1}`);
    const request = page.waitForResponse((response) => response.url().endsWith('/api/ai-chat'));
    await page.getByTestId('send-message').click();
    await request;
    await ready();
  }
  await sendFixture();
  await panel.waitFor();
  check('Incomplete stream does not leave artifact spinning', (await panel.innerText()).includes('回复已结束，但未收到成果完成状态'));
  await page.getByTestId('artifact-close').click();
  await sendFixture();
  check('Newer revision does not reopen closed artifact', !(await panel.isVisible()));
  await page.getByTestId('artifact-card').first().click();
  await page.getByTestId('document-preview').waitFor();
  check('Stale and malformed snapshots preserve latest valid preview', (await page.getByTestId('document-preview').innerText()).includes('有效正文') && (await panel.innerText()).includes('版本 2'));
  await page.getByTestId('artifact-close').click();
  await sendFixture();
  await panel.waitFor();
  check('Unknown custom renderer displays safe fallback', (await panel.innerText()).includes('暂不支持此成果的在线预览'));
  await page.getByTestId('artifact-close').click();
  await sendFixture();
  await panel.waitFor();
  check('Artifact error displays readable failure', (await panel.innerText()).includes('测试服务返回：生成失败，请重试。'));
  await screenshot('09-contract-fallbacks');
  await page.unroute('**/api/ai-chat');
  check('No browser runtime errors', report.errors.length === 0, report.errors);
  report.passed = true;
} catch (error) {
  report.passed = false;
  report.failure = error.stack ?? String(error);
  await screenshot('failure').catch(() => {});
  console.error(report.failure);
  process.exitCode = 1;
} finally {
  report.finishedAt = new Date().toISOString();
  await writeFile(path.join(outputDir, 'report.json'), JSON.stringify(report, null, 2));
  await browser.close();
  console.log(`Browser evidence: ${outputDir}`);
}
