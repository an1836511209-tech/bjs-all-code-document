import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import { createDemoArtifact } from '../artifacts/demo-data';
import { collectArtifacts } from '../artifacts/state';
import {
  createConversation,
  createHistory,
  removeConversation,
  updateConversation
} from '../history/state';
import { decodeHistory, MAX_HISTORY_BYTES } from '../history/service';
import type { DemoUIMessage } from '../chat';

describe('conversation history', () => {
  it('restores empty, draft-only and mixed histories without treating valid sessions as corrupt', async () => {
    const history = createHistory();
    assert.deepEqual(await decodeHistory(JSON.stringify(history)), history);
    history.conversations[0].draft = '未发送的草稿';
    assert.deepEqual(await decodeHistory(JSON.stringify(history)), history);
    history.conversations.push({
      ...createConversation(),
      messages: [{ id: 'u1', role: 'user', parts: [{ type: 'text', text: '报告' }] }]
    });
    assert.deepEqual(await decodeHistory(JSON.stringify(history)), history);
  });

  it('generates stable independent identities and derives a title from the first user message', () => {
    const history = createHistory();
    const first = history.conversations[0];
    assert.notEqual(first.id, createConversation().id);
    const messages: DemoUIMessage[] = [
      { id: 'u1', role: 'user', parts: [{ type: 'text', text: '经营分析报告' }] }
    ];
    const updated = updateConversation(history, first.id, { ...first, messages });
    assert.equal(updated.conversations[0].title, '经营分析报告');
    assert.equal(history.conversations[0].messages.length, 0);
    assert.equal(updateConversation(updated, first.id, updated.conversations[0]), updated);
    assert.equal(updateConversation(updated, 'deleted', first), updated);
    const manual = {
      ...updated,
      conversations: [
        { ...updated.conversations[0], title: '我的报告', titleSource: 'manual' as const }
      ]
    };
    assert.equal(
      updateConversation(manual, first.id, { ...first, messages: [...messages] }).conversations[0]
        .title,
      '我的报告'
    );
  });

  it('deletes inactive and active conversations without leaving a dangling selection', () => {
    const history = createHistory();
    const second = createConversation();
    history.conversations.push(second);
    assert.equal(removeConversation(history, second.id).activeId, history.activeId);
    assert.equal(removeConversation(history, history.activeId).activeId, second.id);
    const empty = removeConversation(removeConversation(history, second.id), history.activeId);
    assert.equal(empty.conversations.length, 1);
    assert.equal(empty.conversations[0].messages.length, 0);
    assert.equal(empty.activeId, empty.conversations[0].id);
  });

  it('round-trips canonical messages, tools, drafts, scenario and authoritative artifacts', async () => {
    const history = createHistory();
    const first = history.conversations[0];
    const artifact = createDemoArtifact('document', 'report', 'ready');
    first.draft = '下一步计划';
    first.scenario = 'spreadsheet';
    first.messages = [
      {
        id: 'a1',
        role: 'assistant',
        parts: [
          { type: 'reasoning', text: '完整思考', state: 'done' },
          { type: 'text', text: '完整正文👨‍👩‍👧‍👦', state: 'done' },
          {
            type: 'tool-createArtifact',
            toolCallId: 'call1',
            state: 'output-available',
            input: { kind: 'document', source: 'demo', format: 'structured-preview' },
            output: { artifactId: 'report', status: 'ready', previewOnly: true }
          },
          { type: 'data-artifact', id: 'report', data: artifact }
        ]
      }
    ];
    first.artifacts = { report: artifact };
    const restored = await decodeHistory(JSON.stringify(history));
    assert.deepEqual(restored, history);
    assert.deepEqual(collectArtifacts(restored.conversations[0].messages), first.artifacts);
  });

  it('rejects corrupt, oversized, incompatible and ambiguous persisted state before rendering', async () => {
    const history = createHistory();
    const first = history.conversations[0];
    for (const invalid of [
      { ...history, schemaVersion: 2 },
      { ...history, activeId: 'missing' },
      { ...history, conversations: [first, first] },
      {
        ...history,
        conversations: [
          { ...first, messages: [{ id: 'u', role: 'user', parts: [{ type: 'text', text: 123 }] }] }
        ]
      },
      { ...history, conversations: [{ ...first, artifacts: { broken: { invalid: true } } }] }
    ]) {
      await assert.rejects(decodeHistory(JSON.stringify(invalid)));
    }
    await assert.rejects(decodeHistory('{broken'));
    await assert.rejects(decodeHistory(' '.repeat(MAX_HISTORY_BYTES + 1)));
  });
});
