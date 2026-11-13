import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import sharp from 'sharp';
import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { POST as upload } from '@/app/api/ai-chat/attachments/route';
import { GET as download } from '@/app/api/ai-chat/attachments/[id]/route';
import { POST as chat } from '@/app/api/ai-chat/route';
import { readLimitedBody } from '../attachments/body';
import {
  attachmentSchema,
  isSafeFilePart,
  MAX_FILE_BYTES,
  toFilePart,
  validateAttachment
} from '../attachments/types';
import { createHistory, updateConversation } from '../history/state';
import { decodeHistory } from '../history/service';

function uploadRequest(file: File): Request {
  const body = new FormData();
  body.append('file', file);
  return new Request('http://localhost/api/ai-chat/attachments', { method: 'POST', body });
}
function chatRequest(parts: unknown[]): Request {
  return new Request('http://localhost/api/ai-chat', {
    method: 'POST',
    body: JSON.stringify({ messages: [{ id: 'user-1', role: 'user', parts }] })
  });
}

describe('attachment HTTP and history boundary', () => {
  it('enforces total byte limits and expired-file rules without rejecting later text-only turns', async () => {
    const response = await upload(
      uploadRequest(new File(['x'.repeat(8 * 1024 * 1024)], 'large.txt', { type: 'text/plain' }))
    );
    const file = attachmentSchema.parse((await response.json()).attachment);
    assert.equal(
      (await chat(chatRequest([toFilePart(file), toFilePart(file), toFilePart(file)]))).status,
      413
    );
    const metadataPath = join(
      tmpdir(),
      'shadcn-ai-chat',
      createHash('sha256').update(process.cwd()).digest('hex').slice(0, 16),
      `${file.id}.json`
    );
    const metadata = JSON.parse(await readFile(metadataPath, 'utf8'));
    await writeFile(
      metadataPath,
      JSON.stringify({ ...metadata, expiresAt: '2020-01-01T00:00:00.000Z' })
    );
    assert.equal((await chat(chatRequest([toFilePart(file)]))).status, 400);
    assert.equal(
      (
        await download(new Request('http://localhost'), {
          params: Promise.resolve({ id: file.id })
        })
      ).status,
      404
    );
    const controller = new AbortController();
    controller.abort();
    const stream = await chat(
      new Request('http://localhost', {
        method: 'POST',
        signal: controller.signal,
        body: JSON.stringify({
          messages: [
            { id: 'old', role: 'user', parts: [toFilePart(file)] },
            { id: 'new', role: 'user', parts: [{ type: 'text', text: '继续讨论' }] }
          ]
        })
      })
    );
    assert.equal(stream.status, 200);
    await stream.text();
    assert.ok(validateAttachment({ name: 'file.constructor', size: 1, type: '' }));
  });
  it('uploads UTF-8 files, returns stable metadata and serves safe attachment headers', async () => {
    const response = await upload(
      uploadRequest(new File(['客户资料'], '客户资料.txt', { type: 'text/plain' }))
    );
    assert.equal(response.status, 201);
    const file = attachmentSchema.parse((await response.json()).attachment);
    const received = await download(new Request(`http://localhost${file.url}`), {
      params: Promise.resolve({ id: file.id })
    });
    assert.equal(await received.text(), '客户资料');
    assert.equal(received.headers.get('x-content-type-options'), 'nosniff');
    assert.match(received.headers.get('content-disposition')!, /^attachment; filename\*=UTF-8''/);
    assert.equal(received.headers.get('cache-control'), 'private, no-store');
    const controller = new AbortController();
    controller.abort();
    const request = new Request(chatRequest([toFilePart(file)]), { signal: controller.signal });
    const stream = await chat(request);
    assert.equal(stream.status, 200);
    assert.match(await stream.text(), /本模板仅演示上传与消息传输/);
    const history = createHistory();
    const saved = updateConversation(history, history.activeId, {
      ...history.conversations[0],
      draftAttachments: [file],
      messages: [{ id: 'user-1', role: 'user', parts: [toFilePart(file)] }]
    });
    const restored = await decodeHistory(JSON.stringify(saved));
    assert.equal(restored.conversations[0].draftAttachments?.[0].id, file.id);
    assert.equal(restored.conversations[0].title, '客户资料.txt');
    assert.ok(!JSON.stringify(saved).includes('base64'));
  });

  it('accepts actual raster images and rejects forged raster, SVG, binary text and malformed Office/JSON/PDF', async () => {
    const png = await sharp({ create: { width: 2, height: 2, channels: 3, background: '#fff' } })
      .png()
      .toBuffer();
    assert.equal(
      (
        await upload(
          uploadRequest(new File([new Uint8Array(png)], 'paste.png', { type: 'image/png' }))
        )
      ).status,
      201
    );
    for (const file of [
      new File(['fake'], 'fake.png', { type: 'image/png' }),
      new File(['<svg/>'], 'test.svg', { type: 'image/svg+xml' }),
      new File([new Uint8Array([0xff, 0])], 'binary.txt', { type: 'text/plain' }),
      new File(['a'], 'file.docx'),
      new File(['broken'], 'file.pdf', { type: 'application/pdf' }),
      new File(['broken'], 'file.json', { type: 'application/json' }),
      new File([], 'empty.txt', { type: 'text/plain' })
    ])
      assert.equal((await upload(uploadRequest(file))).status, 415, file.name);
  });

  it('rejects extra multipart fields, misleading MIME and oversize streamed bodies', async () => {
    const form = new FormData();
    form.append('file', new File(['ok'], 'test.txt'));
    form.append('unexpected', 'value');
    assert.equal(
      (await upload(new Request('http://localhost', { method: 'POST', body: form }))).status,
      400
    );
    assert.ok(validateAttachment({ name: 'file.png', type: 'application/pdf', size: 1 }));
    assert.ok(
      validateAttachment({ name: 'file.txt', type: 'text/plain', size: MAX_FILE_BYTES + 1 })
    );
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new Uint8Array(11));
        controller.close();
      }
    });
    await assert.rejects(
      readLimitedBody(
        new Request('http://localhost', {
          method: 'POST',
          body: stream,
          duplex: 'half'
        } as RequestInit),
        10
      )
    );
    assert.equal(
      (
        await upload(
          new Request('http://localhost', {
            method: 'POST',
            headers: {
              'content-type': 'multipart/form-data; boundary=x',
              'content-length': String(MAX_FILE_BYTES + 100_000)
            },
            body: 'x'
          })
        )
      ).status,
      413
    );
  });

  it('rejects executable, external, embedded, unknown and spoofed references before SSE', async () => {
    for (const url of [
      'javascript:alert(1)',
      '//evil.test/a',
      'https://evil.test/a',
      'data:image/png;base64,x',
      'blob:http://localhost/a',
      '/api/ai-chat/attachments/../../etc'
    ]) {
      const part = { type: 'file' as const, filename: 'test.txt', mediaType: 'text/plain', url };
      assert.equal(isSafeFilePart(part), false);
      assert.equal((await chat(chatRequest([part]))).status, 400);
      const history = createHistory();
      history.conversations[0].messages = [{ id: 'u1', role: 'user', parts: [part] }];
      await assert.rejects(decodeHistory(JSON.stringify(history)));
    }
    const missing = {
      type: 'file' as const,
      filename: 'test.txt',
      mediaType: 'text/plain',
      url: `/api/ai-chat/attachments/${crypto.randomUUID()}`
    };
    assert.equal((await chat(chatRequest([missing]))).status, 400);
    assert.equal((await chat(chatRequest(Array.from({ length: 6 }, () => missing)))).status, 400);
    const uploaded = attachmentSchema.parse(
      (await (await upload(uploadRequest(new File(['ok'], 'file.txt')))).json()).attachment
    );
    assert.equal(
      (await chat(chatRequest([{ ...toFilePart(uploaded), filename: 'spoof.txt' }]))).status,
      400
    );
    assert.equal(
      (
        await download(new Request('http://localhost'), {
          params: Promise.resolve({ id: '../bad' })
        })
      ).status,
      404
    );
  });
});
