import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { POST } from '@/app/api/ai-chat/route';

function request(body: unknown, signal?: AbortSignal): Request {
  return new Request('http://localhost/api/ai-chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal
  });
}

const userMessage = {
  id: 'user-1',
  role: 'user',
  parts: [{ type: 'text', text: '显示经营报告' }]
};

describe('demo HTTP stream boundary', () => {
  it('rejects malformed JSON, empty history, invalid roles, parts and scenarios', async () => {
    const invalidJson = new Request('http://localhost/api/ai-chat', {
      method: 'POST',
      body: '{broken'
    });
    assert.equal((await POST(invalidJson)).status, 400);
    for (const body of [
      null,
      { messages: [] },
      { messages: [{ ...userMessage, role: 'invalid' }] },
      { messages: [{ ...userMessage, parts: [42] }] },
      { messages: [userMessage], scenario: 'unknown' }
    ]) {
      const response = await POST(request(body));
      assert.equal(response.status, 400);
      assert.equal(typeof (await response.json()).error, 'string');
    }
  });

  it('emits the AI SDK SSE headers and ends an already aborted request', async () => {
    const controller = new AbortController();
    controller.abort();
    const response = await POST(request({ messages: [userMessage] }, controller.signal));
    assert.equal(response.status, 200);
    assert.ok(response.headers.get('Content-Type')?.startsWith('text/event-stream'));
    assert.equal(response.headers.get('x-vercel-ai-ui-message-stream'), 'v1');
    const text = await response.text();
    assert.ok(text.includes('"type":"abort"'));
    assert.ok(text.endsWith('data: [DONE]\n\n'));
    assert.ok(!text.includes('reasoning-delta'));
    assert.ok(!text.includes('data-artifact'));
  });

  it('settles a pending generation timer immediately when the request is aborted', async () => {
    const controller = new AbortController();
    const response = await POST(
      request({ messages: [userMessage], scenario: 'document' }, controller.signal)
    );
    const reader = response.body!.getReader();
    const first = await reader.read();
    assert.equal(first.done, false);
    controller.abort();
    const remaining: Uint8Array[] = [];
    let timeout: ReturnType<typeof setTimeout> | undefined;
    try {
      await Promise.race([
        (async () => {
          while (true) {
            const result = await reader.read();
            if (result.done) break;
            remaining.push(result.value);
          }
        })(),
        new Promise<never>((_, reject) => {
          timeout = setTimeout(() => reject(new Error('Aborted stream did not finish')), 1_000);
        })
      ]);
    } finally {
      clearTimeout(timeout);
      reader.releaseLock();
    }
    const text = new TextDecoder().decode(Buffer.concat(remaining));
    assert.ok(text.includes('"type":"abort"'));
    assert.ok(!text.includes('tool-input-available'));
  });
});
