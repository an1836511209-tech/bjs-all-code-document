import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { z } from 'zod';
import { createDemoArtifact } from '../artifacts/demo-data';
import { builtinPreviewValidators, isSafeDownloadUrl, parseArtifact } from '../artifacts/schemas';
import { collectArtifacts, reduceArtifact } from '../artifacts/state';
import type { ArtifactState } from '../artifacts/types';
import type { DemoUIMessage } from '../chat';

describe('artifact contract validation', () => {
  it('accepts all four preview types without claiming native office files exist', () => {
    for (const scenario of ['document', 'spreadsheet', 'presentation', 'dashboard'] as const) {
      const artifact = createDemoArtifact(scenario, scenario, 'ready');
      assert.deepEqual(parseArtifact(artifact), artifact);
      assert.equal(artifact.file, undefined);
    }
  });

  it('requires usable content for ready and a message for error', () => {
    const generating = createDemoArtifact('document', 'report', 'generating');
    assert.equal(parseArtifact({ ...generating, status: 'ready' }), null);
    assert.equal(parseArtifact({ ...generating, status: 'error' }), null);
    assert.ok(parseArtifact({ ...generating, status: 'error', error: '文件生成失败' }));
    assert.ok(
      parseArtifact({
        ...generating,
        status: 'ready',
        file: {
          url: '/api/files/report.docx',
          name: '报告.docx',
          mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        }
      })
    );
  });

  it('rejects malformed known previews, future protocol envelopes and invalid revisions', () => {
    const artifact = createDemoArtifact('spreadsheet', 'table', 'ready');
    assert.equal(parseArtifact({ ...artifact, schemaVersion: 2 }), null);
    assert.equal(parseArtifact({ ...artifact, revision: 0 }), null);
    assert.equal(parseArtifact({ ...artifact, revision: 1.5 }), null);
    assert.equal(
      parseArtifact({
        ...artifact,
        preview: {
          renderer: 'spreadsheet',
          version: 1,
          data: { sheets: [{ name: 'Sheet', columns: ['A', 'B'], rows: [[1]] }] }
        }
      }),
      null
    );
  });

  it('preserves unknown renderer and renderer version payloads for the safe fallback', () => {
    const artifact = createDemoArtifact('dashboard', 'custom', 'ready');
    const unknown = {
      ...artifact,
      preview: { renderer: 'company.capacity', version: 7, data: { free: 42 } }
    };
    assert.deepEqual(parseArtifact(unknown), unknown);
    const future = {
      ...artifact,
      preview: { renderer: 'document', version: 2, data: { blocks: [] } }
    };
    assert.deepEqual(parseArtifact(future), future);
  });

  it('allows a plugin validator to reject invalid custom payloads', () => {
    const validators = {
      ...builtinPreviewValidators,
      'company.capacity:1': z.object({ free: z.number().nonnegative() })
    };
    const artifact = {
      ...createDemoArtifact('dashboard', 'custom', 'ready'),
      preview: { renderer: 'company.capacity', version: 1, data: { free: -1 } }
    };
    assert.equal(parseArtifact(artifact, validators), null);
    assert.ok(
      parseArtifact(
        { ...artifact, preview: { ...artifact.preview, data: { free: 3 } } },
        validators
      )
    );
  });

  it('rejects executable, credentialed and protocol-relative download URLs', () => {
    for (const value of [
      'javascript:alert(1)',
      'data:text/html,test',
      'file:///C:/private',
      '//evil.test/file',
      '/\\evil.test/file',
      'https://user:pass@example.com/file',
      'https://example.com/a\nb'
    ]) {
      assert.equal(isSafeDownloadUrl(value), false, value);
    }
    assert.equal(isSafeDownloadUrl('/api/artifacts/report/download'), true);
    assert.equal(isSafeDownloadUrl('https://files.example.com/report.docx?signature=test'), true);
    const artifact = createDemoArtifact('document', 'report', 'ready');
    assert.equal(
      parseArtifact({
        ...artifact,
        file: { url: 'javascript:alert(1)', name: 'bad', mimeType: 'text/html' }
      }),
      null
    );
  });
});

describe('artifact stream reconciliation', () => {
  it('upgrades generating to ready without mutating the previous state', () => {
    const generating = createDemoArtifact('document', 'report', 'generating');
    const ready = createDemoArtifact('document', 'report', 'ready');
    const initial: ArtifactState = {};
    const pending = reduceArtifact(initial, generating);
    const complete = reduceArtifact(pending, ready);
    assert.deepEqual(initial, {});
    assert.equal(pending.report.status, 'generating');
    assert.equal(complete.report.status, 'ready');
  });

  it('ignores duplicate revisions and delayed generating snapshots', () => {
    const ready = createDemoArtifact('document', 'report', 'ready');
    const state = reduceArtifact({}, ready);
    assert.equal(reduceArtifact(state, ready), state);
    assert.equal(reduceArtifact(state, { ...ready, title: 'Duplicate overwrite' }), state);
    assert.equal(
      reduceArtifact(state, createDemoArtifact('document', 'report', 'generating')),
      state
    );
  });

  it('keeps identity stable across revisions and rejects malformed updates', () => {
    const ready = createDemoArtifact('document', 'report', 'ready');
    const state = reduceArtifact({}, ready);
    assert.equal(reduceArtifact(state, { ...ready, revision: 3, kind: 'spreadsheet' }), state);
    assert.equal(
      reduceArtifact(state, {
        ...ready,
        revision: 3,
        preview: { renderer: 'document', version: 1, data: { markdown: 1 } }
      }),
      state
    );
    assert.equal(reduceArtifact(state, null), state);
  });

  it('lets a newer complete snapshot update a title or retry a failed generation', () => {
    const generating = createDemoArtifact('document', 'report', 'generating');
    const failed = reduceArtifact(
      {},
      { ...generating, revision: 2, status: 'error', error: 'Generation failed' }
    );
    const ready = {
      ...createDemoArtifact('document', 'report', 'ready'),
      revision: 3,
      title: 'Updated report'
    };
    assert.deepEqual(reduceArtifact(failed, ready).report, ready);
  });

  it('hydrates highest revision from assistant data parts and ignores text/user spoofing', () => {
    const ready = createDemoArtifact('document', 'report', 'ready');
    const generating = createDemoArtifact('document', 'report', 'generating');
    const messages: DemoUIMessage[] = [
      {
        id: 'u1',
        role: 'user',
        parts: [{ type: 'data-artifact', data: { ...ready, id: 'spoofed' } }]
      },
      {
        id: 'a1',
        role: 'assistant',
        parts: [
          { type: 'text', text: 'I created artifact fake.docx' },
          { type: 'data-artifact', data: ready }
        ]
      },
      { id: 'a2', role: 'assistant', parts: [{ type: 'data-artifact', data: generating }] }
    ];
    assert.deepEqual(collectArtifacts(messages), { report: ready });
  });

  it('treats reserved JavaScript property names as ordinary stable identifiers', () => {
    const artifact = createDemoArtifact('document', '__proto__', 'ready');
    const state = reduceArtifact({}, artifact);
    assert.equal(Object.getPrototypeOf(state), Object.prototype);
    assert.equal(state['__proto__'].id, '__proto__');
    assert.equal(Object.prototype.hasOwnProperty.call(state, '__proto__'), true);
  });
});
