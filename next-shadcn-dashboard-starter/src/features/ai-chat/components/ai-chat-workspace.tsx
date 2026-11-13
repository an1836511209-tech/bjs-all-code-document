'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { FeedbackNotice } from '@/components/feedback-notice';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { createHistory, updateConversation } from '../history/state';
import {
  classifyStorageError,
  loadHistory,
  saveHistory,
  type HistoryStorageError
} from '../history/service';
import type { ConversationHistory, ConversationSnapshot } from '../history/types';
import { AiChatSession } from './ai-chat-demo';

export function AiChatWorkspace() {
  const [history, setHistory] = useState<ConversationHistory | null>(null);
  const [warning, setWarning] = useState<HistoryStorageError['code'] | null>(null);
  const [canPersist, setCanPersist] = useState(false);
  const latestHistory = useRef(history);
  latestHistory.current = history;

  useEffect(() => {
    let cancelled = false;
    void loadHistory()
      .then((saved) => {
        if (cancelled) return;
        setHistory(saved ?? createHistory());
        setCanPersist(true);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        setHistory(createHistory());
        setWarning(classifyStorageError(error).code);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!history || !canPersist) return;
    // Coalesce draft edits. Streaming updates never trigger browser storage writes.
    const timer = setTimeout(() => {
      try {
        saveHistory(history);
        setWarning(null);
      } catch (error) {
        setWarning(classifyStorageError(error).code);
      }
    }, 300);
    return () => clearTimeout(timer);
  }, [history, canPersist]);

  useEffect(() => {
    if (!canPersist) return;
    const flush = () => {
      if (!latestHistory.current) return;
      try {
        saveHistory(latestHistory.current);
      } catch {
        /* The visible save warning handles quota failures. */
      }
    };
    window.addEventListener('pagehide', flush);
    return () => {
      window.removeEventListener('pagehide', flush);
      flush();
    };
  }, [canPersist]);

  const onSnapshot = useCallback((id: string, snapshot: ConversationSnapshot) => {
    setHistory((current) => (current ? updateConversation(current, id, snapshot) : current));
  }, []);
  if (!history)
    return <Skeleton className='h-[calc(100dvh-5.5rem)] w-full' aria-label='正在加载历史会话' />;
  const active = history.conversations.find((item) => item.id === history.activeId)!;
  return (
    <div className='flex h-[calc(100dvh-5.5rem)] min-h-0 flex-col gap-2'>
      {warning && (
        <FeedbackNotice
          className='shrink-0'
          title={canPersist ? '会话尚未保存' : '临时会话模式'}
          actions={
            <>
              <Button
                variant='outline'
                size='sm'
                onClick={() => {
                  const url = URL.createObjectURL(
                    new Blob([JSON.stringify(latestHistory.current, null, 2)], {
                      type: 'application/json'
                    })
                  );
                  const link = document.createElement('a');
                  link.href = url;
                  link.download = 'ai-chat-history.json';
                  link.click();
                  setTimeout(() => URL.revokeObjectURL(url), 1000);
                }}
              >
                导出当前会话
              </Button>
              {canPersist && (
                <Button
                  variant='outline'
                  size='sm'
                  onClick={() => setHistory((current) => (current ? { ...current } : current))}
                >
                  重试保存
                </Button>
              )}
            </>
          }
        >
          {warning === 'invalid'
            ? '原有记录格式不兼容或已损坏，尚未被覆盖。本次对话仅在当前页面保留，离开前请导出；请联系维护者协助恢复原记录。'
            : warning === 'unavailable'
              ? '浏览器暂不允许访问本地存储。本次对话仍可继续，离开前请导出，并检查浏览器的站点存储权限。'
              : '存储空间不足或会话超过本地保存上限，最新修改尚未保存。请先导出会话，再删除不需要的历史或释放空间后重试。'}
        </FeedbackNotice>
      )}
      <AiChatSession
        key={active.id}
        conversation={active}
        history={history}
        onHistoryChange={setHistory}
        onSnapshot={onSnapshot}
      />
    </div>
  );
}
