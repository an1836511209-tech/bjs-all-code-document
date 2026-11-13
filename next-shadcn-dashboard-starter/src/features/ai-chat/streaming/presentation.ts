import type { DemoUIMessage } from '../chat';

export const TYPEWRITER_CONFIG = {
  charactersPerSecond: 90,
  catchUpSeconds: 0.35,
  maxTailMs: 800
};

const segmenter =
  typeof Intl.Segmenter === 'function'
    ? new Intl.Segmenter(undefined, { granularity: 'grapheme' })
    : null;

const wordSegmenter =
  typeof Intl.Segmenter === 'function'
    ? new Intl.Segmenter(undefined, { granularity: 'word' })
    : null;
const cjkOnly =
  /^[\p{Script=Han}\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Hangul}\p{Mark}]+$/u;
const closingPunctuation = /^[\p{Pe}\p{Pf}.,!?;:%，。！？；：、…]/u;
const openingPunctuation = /[\p{Ps}\p{Pi}]$/u;

/** Keep a growing word or punctuation pair from rewrapping after it is visible. */
function revealBoundaries(text: string, boundaries: number[], streaming: boolean): number[] {
  const words = wordSegmenter
    ? Array.from(wordSegmenter.segment(text)).filter(
        (word) => word.isWordLike && !cjkOnly.test(word.segment)
      )
    : [];
  let wordIndex = 0;
  return boundaries.filter((end, index) => {
    while (
      wordIndex < words.length &&
      words[wordIndex].index + words[wordIndex].segment.length < end
    )
      wordIndex++;
    const word = words[wordIndex];
    if (
      word &&
      end > word.index &&
      (end < word.index + word.segment.length || (streaming && end === text.length))
    )
      return false;
    if (streaming && index === boundaries.length - 1) return false;
    return (
      !closingPunctuation.test(text.slice(end)) && !openingPunctuation.test(text.slice(0, end))
    );
  });
}

function lastBoundaryAtOrBefore(boundaries: number[], end: number): number {
  let low = 0;
  let high = boundaries.length;
  while (low < high) {
    const middle = (low + high) >>> 1;
    if (boundaries[middle] <= end) low = middle + 1;
    else high = middle;
  }
  return low ? boundaries[low - 1] : 0;
}

/** UTF-16 boundaries for user-perceived characters, including joined emoji. */
export function textBoundaries(text: string): number[] {
  if (!segmenter) return text ? [text.length] : [];
  return Array.from(segmenter.segment(text), ({ index, segment }) => index + segment.length);
}

export function preparePresentation(message: DemoUIMessage) {
  const safeMessage = {
    ...message,
    parts: message.parts.map((part) =>
      (part.type === 'text' || part.type === 'reasoning') && part.state === 'streaming'
        ? { ...part, text: part.text.replace(/[\uD800-\uDBFF]$/, '') }
        : part
    )
  };
  const boundaries = safeMessage.parts.map((part) =>
    part.type === 'text' || part.type === 'reasoning' ? textBoundaries(part.text) : []
  );
  return {
    message: safeMessage,
    boundaries,
    revealBoundaries: safeMessage.parts.map((part, index) =>
      part.type === 'text' || part.type === 'reasoning'
        ? revealBoundaries(part.text, boundaries[index], part.state === 'streaming')
        : []
    ),
    length: boundaries.reduce((sum, item) => sum + item.length, 0)
  };
}

export type PreparedPresentation = ReturnType<typeof preparePresentation>;

/** Display-only projection. Never write these truncated parts back into useChat. */
export function presentMessage(prepared: PreparedPresentation, count: number): DemoUIMessage {
  let remaining = Math.max(0, count);
  const parts: DemoUIMessage['parts'] = [];
  for (const [index, part] of prepared.message.parts.entries()) {
    if (part.type !== 'text' && part.type !== 'reasoning') {
      parts.push(part);
      continue;
    }
    const boundaries = prepared.boundaries[index];
    const shown = Math.min(remaining, boundaries.length);
    const budgetEnd = shown ? boundaries[shown - 1] : 0;
    const end =
      part.state !== 'streaming' && shown === boundaries.length
        ? part.text.length
        : lastBoundaryAtOrBefore(prepared.revealBoundaries[index], budgetEnd);
    parts.push({ ...part, text: part.text.slice(0, end) });
    remaining -= shown;
    // Later prose/cards must not overtake this still-revealing text part.
    if (end < part.text.length) break;
  }
  return { ...prepared.message, parts };
}

export function advancePresentation(remaining: number, elapsedMs: number, credit: number) {
  const rate = Math.max(
    TYPEWRITER_CONFIG.charactersPerSecond,
    remaining / TYPEWRITER_CONFIG.catchUpSeconds
  );
  const available = credit + (rate * Math.min(Math.max(elapsedMs, 0), 50)) / 1000;
  const count = Math.min(remaining, Math.floor(available));
  return { count, credit: count === remaining ? 0 : available - count };
}
