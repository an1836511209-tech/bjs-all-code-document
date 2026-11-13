import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import type { DemoUIMessage } from '../chat';
import {
  advancePresentation,
  preparePresentation,
  presentMessage,
  textBoundaries
} from '../streaming/presentation';

describe('streaming presentation', () => {
  it('reveals complete Chinese, combining characters and joined emoji', () => {
    const text = '你e\u0301👨‍👩‍👧‍👦👍🏽好';
    const ends = textBoundaries(text);
    assert.equal(ends.length, 5);
    assert.deepEqual(
      ends.map((end, index) => text.slice(index ? ends[index - 1] : 0, end)),
      ['你', 'e\u0301', '👨‍👩‍👧‍👦', '👍🏽', '好']
    );
  });
  it('keeps fractional time credit and adapts to bursts without overshooting', () => {
    let count = 0;
    let credit = 0;
    for (let frame = 0; frame < 10; frame++) {
      const next = advancePresentation(100 - count, 1, credit);
      count += next.count;
      credit = next.credit;
    }
    assert.ok(count > 0 && count < 10);
    assert.ok(advancePresentation(1000, 16, 0).count > advancePresentation(10, 16, 0).count);
    assert.deepEqual(advancePresentation(2, 10_000, 0), { count: 2, credit: 0 });
    assert.equal(advancePresentation(20, 0, 0).count, 0);
  });
  it('preserves the canonical transcript and reveals parts in order', () => {
    const source: DemoUIMessage = {
      id: 'reply',
      role: 'assistant',
      parts: [
        { type: 'reasoning', text: '核对数据', state: 'done' },
        {
          type: 'tool-getRevenue',
          toolCallId: 'tool',
          state: 'input-available',
          input: { period: 'x', currency: 'CNY', groupBy: 'week' }
        },
        { type: 'text', text: '**结论**\n\n增长良好。', state: 'done' }
      ]
    };
    const canonical = JSON.stringify(source);
    const prepared = preparePresentation(source);
    const partial = presentMessage(prepared, 2);
    assert.equal(partial.parts.length, 1);
    assert.equal((partial.parts[0] as { text: string }).text, '核对');
    assert.equal(presentMessage(prepared, 4).parts[1].type, 'tool-getRevenue');
    assert.deepEqual(presentMessage(prepared, prepared.length), source);
    assert.equal(JSON.stringify(source), canonical);
  });
  it('withholds a split surrogate until the rest arrives without changing source data', () => {
    const message: DemoUIMessage = {
      id: 'unicode',
      role: 'assistant',
      parts: [{ type: 'text', text: '好\ud83d', state: 'streaming' }]
    };
    const partial = preparePresentation(message);
    assert.equal((presentMessage(partial, partial.length).parts[0] as { text: string }).text, '');
    message.parts = [{ type: 'text', text: '好😀', state: 'done' }];
    const completed = preparePresentation(message);
    assert.equal(
      (presentMessage(completed, completed.length).parts[0] as { text: string }).text,
      '好😀'
    );
  });
  it('releases English words together and holds an unfinished transport word', () => {
    const source: DemoUIMessage = {
      id: 'words',
      role: 'assistant',
      parts: [{ type: 'text', text: '中文 visibility artifact ', state: 'streaming' }]
    };
    const prepared = preparePresentation(source);
    for (let count = 0; count <= prepared.length; count++) {
      const text = (presentMessage(prepared, count).parts[0] as { text: string }).text;
      assert.ok(
        !/ (?:v|vi|vis|visi|visib|visibi|visibil|visibili|a|ar|art|arti|artif|artifa|artifac)$/.test(
          text
        ),
        text
      );
    }
    const open = preparePresentation({
      ...source,
      parts: [{ type: 'text', text: '中文 visibility', state: 'streaming' }]
    });
    assert.equal((presentMessage(open, open.length).parts[0] as { text: string }).text, '中文 ');
    const done = preparePresentation({
      ...source,
      parts: [{ type: 'text', text: '中文 visibility', state: 'done' }]
    });
    assert.equal(
      (presentMessage(done, done.length).parts[0] as { text: string }).text,
      '中文 visibility'
    );
  });
  it('does not reveal punctuation that would push the preceding character onto a new line', () => {
    const source: DemoUIMessage = {
      id: 'punctuation',
      role: 'assistant',
      parts: [{ type: 'text', text: '中文，测试（内容）结束。', state: 'done' }]
    };
    const prepared = preparePresentation(source);
    for (let count = 0; count < prepared.length; count++) {
      const text = (presentMessage(prepared, count).parts[0] as { text: string }).text;
      assert.ok(
        !text.endsWith('文') &&
          !text.endsWith('容') &&
          !text.endsWith('（') &&
          !text.endsWith('束'),
        text
      );
    }
  });
});
