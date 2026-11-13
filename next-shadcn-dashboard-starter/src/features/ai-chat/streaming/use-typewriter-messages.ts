'use client';

import { useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import type { DemoUIMessage } from '../chat';
import {
  advancePresentation,
  preparePresentation,
  presentMessage,
  TYPEWRITER_CONFIG
} from './presentation';

function subscribePreferences(callback: () => void) {
  const media = window.matchMedia('(prefers-reduced-motion: reduce)');
  media.addEventListener('change', callback);
  document.addEventListener('visibilitychange', callback);
  return () => {
    media.removeEventListener('change', callback);
    document.removeEventListener('visibilitychange', callback);
  };
}
const instantSnapshot = () =>
  document.hidden || window.matchMedia('(prefers-reduced-motion: reduce)').matches;
const serverSnapshot = () => true;

/** One RAF queue for the active response; transport and artifact events remain untouched. */
export function useTypewriterMessages(messages: DemoUIMessage[], status: string) {
  const instant = useSyncExternalStore(subscribePreferences, instantSnapshot, serverSnapshot);
  const last = messages.at(-1);
  const prepared = useMemo(
    () => (last?.role === 'assistant' ? preparePresentation(last) : null),
    [last]
  );
  const [cursor, setCursor] = useState({ id: '', count: 0 });
  const [skippedId, setSkippedId] = useState('');
  const knownIds = useRef(new Set(messages.map((message) => message.id)));
  const timing = useRef({ id: '', previous: 0, credit: 0, completedAt: 0 });
  const eligible =
    !!prepared &&
    (status === 'streaming' ||
      cursor.id === prepared.message.id ||
      !knownIds.current.has(prepared.message.id));
  const animated = eligible && !instant && status !== 'error' && skippedId !== prepared?.message.id;
  const count = animated
    ? cursor.id === prepared?.message.id
      ? cursor.count
      : 0
    : (prepared?.length ?? 0);
  const pending = !!prepared && animated && count < prepared.length;

  useLayoutEffect(() => {
    for (const message of messages) knownIds.current.add(message.id);
    if (!prepared || !eligible) return;
    const id = prepared.message.id;
    if (cursor.id !== id && animated) setCursor({ id, count: 0 });
    if (!animated) {
      timing.current = { id, previous: 0, credit: 0, completedAt: 0 };
      setCursor((current) =>
        current.id === id && current.count === prepared.length
          ? current
          : { id, count: prepared.length }
      );
      return;
    }
    if (timing.current.id !== id) {
      timing.current = { id, previous: 0, credit: 0, completedAt: 0 };
    }
    const clock = timing.current;
    if (status === 'ready' && !clock.completedAt) clock.completedAt = performance.now();
    let visible = cursor.id === id ? Math.min(cursor.count, prepared.length) : 0;
    let frame = 0;
    function tick(now: number) {
      const elapsed = clock.previous ? now - clock.previous : 0;
      clock.previous = now;
      if (clock.completedAt && now - clock.completedAt >= TYPEWRITER_CONFIG.maxTailMs) {
        visible = prepared!.length;
      } else {
        const next = advancePresentation(prepared!.length - visible, elapsed, clock.credit);
        clock.credit = next.credit;
        visible += next.count;
      }
      setCursor((current) =>
        current.id === id && current.count === visible ? current : { id, count: visible }
      );
      if (visible < prepared!.length) frame = requestAnimationFrame(tick);
      else {
        clock.previous = 0;
        clock.credit = 0;
      }
    }
    if (visible < prepared.length) frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
    // Cursor updates are produced by this queue, not a reason to restart it.
    // oxlint-disable-next-line react-hooks/exhaustive-deps
  }, [prepared, eligible, animated, status]);

  const displayMessages = useMemo(() => {
    if (!prepared || !animated) return messages;
    return [...messages.slice(0, -1), presentMessage(prepared, count)];
  }, [messages, prepared, animated, count]);

  return {
    displayMessages,
    pending,
    flush: () => {
      if (prepared) setSkippedId(prepared.message.id);
    }
  };
}
