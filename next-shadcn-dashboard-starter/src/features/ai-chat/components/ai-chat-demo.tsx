'use client';

import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react';
import { AttachmentGroup } from '@/components/ui/attachment';
import { DraftAttachmentCard, MessageAttachment } from './chat-attachment';
import { useAttachments } from '../attachments/use-attachments';
import { ATTACHMENT_ACCEPT, toFilePart } from '../attachments/types';
import { useChat } from '@ai-sdk/react';
import { isToolUIPart } from 'ai';
import { FeedbackNotice } from '@/components/feedback-notice';
import { Button } from '@/components/ui/button';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider
} from '@/components/ui/message-scroller';
import { Message, MessageContent } from '@/components/ui/message';
import { Bubble, BubbleContent } from '@/components/ui/bubble';
import { InputGroup, InputGroupAddon, InputGroupTextarea } from '@/components/ui/input-group';
import { Sheet, SheetContent, SheetTitle } from '@/components/ui/sheet';
import { chatTransport, DEMO_SCENARIOS, type DemoUIMessage } from '../chat';
import { collectArtifacts, reduceArtifact } from '../artifacts/state';
import { ConversationHistory as ConversationHistoryPanel } from './conversation-history';
import { createConversation, MAX_CONVERSATIONS, removeConversation } from '../history/state';
import type { Conversation, ConversationHistory, ConversationSnapshot } from '../history/types';
import { toast } from 'sonner';
import { parseArtifact } from '../artifacts/schemas';
import type { ArtifactState } from '../artifacts/types';
import { ArtifactCard } from '../artifacts/components/artifact-card';
import { ArtifactPanel } from '../artifacts/components/artifact-panel';
import { ChatMarkdown } from './chat-markdown';
import { ChatScrollViewport } from './chat-scroll-viewport';
import { ReasoningBlock } from './reasoning-block';
import { ToolCall } from './tool-call';
import { useTypewriterMessages } from '../streaming/use-typewriter-messages';

function subscribeLayout(callback: () => void) {
  const media = window.matchMedia('(min-width: 1024px)');
  media.addEventListener('change', callback);
  return () => media.removeEventListener('change', callback);
}
const getDesktop = () => window.matchMedia('(min-width: 1024px)').matches;
const getServerDesktop = () => false;
const scenarioIcons = [
  Icons.fileTypeDoc,
  Icons.fileTypeXls,
  Icons.galleryVerticalEnd,
  Icons.dashboard
];

interface AiChatSessionProps {
  conversation: Conversation;
  history: ConversationHistory;
  onHistoryChange: (history: ConversationHistory) => void;
  onSnapshot: (id: string, snapshot: ConversationSnapshot) => void;
}

export function AiChatSession({
  conversation,
  history,
  onHistoryChange,
  onSnapshot
}: AiChatSessionProps) {
  const attachments = useAttachments(conversation.draftAttachments);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const submittingRef = useRef(false);
  const [draft, setDraft] = useState(conversation.draft);
  const [scenario, setScenario] = useState(conversation.scenario);
  const [historyOpen, setHistoryOpen] = useState(true);
  const [mobileHistoryOpen, setMobileHistoryOpen] = useState(false);
  const [artifacts, setArtifacts] = useState<ArtifactState>(() => {
    let restored = collectArtifacts(conversation.messages);
    for (const artifact of Object.values(conversation.artifacts))
      restored = reduceArtifact(restored, artifact);
    return restored;
  });
  const [activeId, setActiveId] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [incompleteArtifacts, setIncompleteArtifacts] = useState<
    Record<string, { revision: number; message: string }>
  >({});
  const artifactsRef = useRef<ArtifactState>(artifacts);
  const seenArtifactIds = useRef(new Set(Object.keys(artifacts)));
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const sheetReturnFocus = useRef<HTMLElement | null>(null);
  const isDesktop = useSyncExternalStore(subscribeLayout, getDesktop, getServerDesktop);

  function markIncompleteArtifacts(message: string) {
    const pending = Object.values(artifactsRef.current).filter(
      (artifact) => artifact.status === 'generating'
    );
    if (!pending.length) return;
    setIncompleteArtifacts((current) => {
      const next = { ...current };
      for (const artifact of pending) {
        if (next[artifact.id]?.revision !== artifact.revision) {
          next[artifact.id] = { revision: artifact.revision, message };
        }
      }
      return next;
    });
  }

  function openArtifact(id: string) {
    if (!isDesktop && activeId === null) {
      sheetReturnFocus.current =
        document.activeElement instanceof HTMLElement && document.activeElement.tabIndex >= 0
          ? document.activeElement
          : null;
    }
    setActiveId(id);
  }

  const closeArtifact = useCallback(() => {
    setActiveId(null);
    setExpanded(false);
  }, []);

  const { messages, sendMessage, status, stop, error, clearError } = useChat<DemoUIMessage>({
    id: conversation.id,
    messages: conversation.messages,
    transport: chatTransport,
    onData: (part) => {
      if (part.type !== 'data-artifact') return;
      const artifact = parseArtifact(part.data);
      if (!artifact) return;
      // Only an accepted newer snapshot may change either data or panel visibility.
      const next = reduceArtifact(artifactsRef.current, artifact);
      if (next === artifactsRef.current) return;
      artifactsRef.current = next;
      setArtifacts(next);
      const isFirstSnapshot = !seenArtifactIds.current.has(artifact.id);
      seenArtifactIds.current.add(artifact.id);
      if (isFirstSnapshot && artifact.autoOpen) openArtifact(artifact.id);
    },
    onError: () =>
      markIncompleteArtifacts('连接中断，尚未收到成果完成状态。当前内容仅为未完成预览。'),
    onFinish: ({ isAbort, isDisconnect, isError }) =>
      markIncompleteArtifacts(
        isAbort
          ? '生成已中止，当前内容仅为未完成预览。'
          : isDisconnect || isError
            ? '连接中断，尚未收到成果完成状态。当前内容仅为未完成预览。'
            : '回复已结束，但未收到成果完成状态。当前内容仅为未完成预览。'
      )
  });
  const {
    displayMessages,
    pending: presentationPending,
    flush: flushPresentation
  } = useTypewriterMessages(messages, status);
  const transportBusy = status === 'submitted' || status === 'streaming';
  const isBusy = transportBusy || presentationPending;
  const sessionBusy = isBusy || attachments.uploading;
  useEffect(() => {
    if (!isBusy) submittingRef.current = false;
  }, [isBusy]);
  useEffect(() => {
    if (transportBusy && status !== 'submitted') return;
    onSnapshot(conversation.id, {
      messages,
      artifacts,
      draft,
      scenario,
      draftAttachments: attachments.ready
    });
  }, [
    conversation.id,
    messages,
    artifacts,
    draft,
    scenario,
    transportBusy,
    status,
    onSnapshot,
    attachments.ready
  ]);
  const artifactList = useMemo(
    () =>
      Object.values(artifacts).map((artifact) =>
        artifact.status === 'generating' &&
        (incompleteArtifacts[artifact.id]?.revision === artifact.revision || !transportBusy)
          ? {
              ...artifact,
              status: 'error' as const,
              error:
                incompleteArtifacts[artifact.id]?.message ??
                '会话已恢复，未收到成果完成状态。当前内容仅为未完成预览。'
            }
          : artifact
      ),
    [artifacts, incompleteArtifacts, transportBusy]
  );
  const panelOpen = activeId !== null && artifactList.some((item) => item.id === activeId);

  function submit(text: string, selectedScenario = scenario) {
    if (
      isBusy ||
      submittingRef.current ||
      attachments.blocked ||
      (!text.trim() && !attachments.ready.length)
    )
      return;
    if (attachments.ready.some((file) => Date.parse(file.expiresAt) <= Date.now())) {
      toast.error('附件已过期，请移除后重新上传。');
      return;
    }
    if (messages.length >= 198) {
      toast.error('当前演示会话已达消息上限，请新建对话。');
      return;
    }
    submittingRef.current = true;
    clearError();
    const files = attachments.ready.map(toFilePart);
    attachments.clear();
    setDraft('');
    setScenario(selectedScenario);
    void sendMessage(
      { text: text.trim(), files },
      { body: { scenario: selectedScenario, conversationId: conversation.id } }
    )
      .catch(() => toast.error('消息未发送，请检查网络后重试。'))
      .finally(() => {
        submittingRef.current = false;
      });
  }

  function newConversation() {
    if (sessionBusy) return;
    if (!messages.length && !draft.trim() && !attachments.items.length) {
      setMobileHistoryOpen(false);
      return;
    }
    if (history.conversations.length >= MAX_CONVERSATIONS) {
      toast.error(`最多保留 ${MAX_CONVERSATIONS} 个本地会话，请先删除不需要的会话。`);
      return;
    }
    const next = createConversation();
    onHistoryChange({
      ...history,
      activeId: next.id,
      conversations: [next, ...history.conversations]
    });
  }

  const historyPanel = (
    <ConversationHistoryPanel
      conversations={history.conversations}
      activeId={conversation.id}
      busy={sessionBusy}
      onCreate={newConversation}
      onSelect={(id) => {
        if (!sessionBusy) {
          onHistoryChange({ ...history, activeId: id });
          setMobileHistoryOpen(false);
        }
      }}
      onRename={(id, title) => {
        if (!sessionBusy)
          onHistoryChange({
            ...history,
            conversations: history.conversations.map((item) =>
              item.id === id ? { ...item, title, titleSource: 'manual' } : item
            )
          });
      }}
      onDelete={(id) => {
        if (!sessionBusy) onHistoryChange(removeConversation(history, id));
      }}
      onClose={() => {
        setHistoryOpen(false);
        setMobileHistoryOpen(false);
      }}
    />
  );

  function stopGeneration() {
    flushPresentation();
    markIncompleteArtifacts('生成已中止，当前内容仅为未完成预览。');
    void stop();
  }

  const panel = useMemo(
    () =>
      panelOpen && activeId ? (
        <ArtifactPanel
          artifacts={artifactList}
          activeArtifactId={activeId}
          onSelect={setActiveId}
          onClose={closeArtifact}
          expanded={expanded}
          onToggleExpand={isDesktop ? () => setExpanded((value) => !value) : undefined}
        />
      ) : null,
    [panelOpen, activeId, artifactList, closeArtifact, expanded, isDesktop]
  );

  return (
    <div className='relative min-h-0 w-full flex-1' data-testid='ai-chat-workspace'>
      <div className='absolute inset-0 flex min-w-0 gap-4'>
        {isDesktop && historyOpen && !panelOpen && (
          <aside
            aria-label='历史会话'
            className='h-full w-64 shrink-0 border-r border-sidebar-border bg-sidebar pr-2 text-sidebar-foreground xl:w-72'
          >
            {historyPanel}
          </aside>
        )}
        <section aria-label='AI 对话' className='flex min-w-0 flex-1 flex-col'>
          <div className='flex h-14 shrink-0 items-center justify-between gap-2 px-2 pb-2'>
            <div className='flex min-w-0 items-center gap-3'>
              {(!isDesktop || !historyOpen || panelOpen) && (
                <Button
                  variant='ghost'
                  size='icon-sm'
                  aria-label='打开历史会话'
                  aria-expanded={isDesktop ? historyOpen && !panelOpen : mobileHistoryOpen}
                  onClick={() => {
                    if (isDesktop) {
                      closeArtifact();
                      setHistoryOpen((value) => !value || panelOpen);
                    } else setMobileHistoryOpen(true);
                  }}
                >
                  <Icons.panelLeft />
                </Button>
              )}
              <span className='truncate text-sm font-medium' title={conversation.title}>
                {conversation.title}
              </span>
            </div>
            <div className='flex shrink-0 items-center gap-1'>
              <span
                data-testid='chat-status'
                data-status={status === 'ready' && presentationPending ? 'typing' : status}
                role='status'
                className='mr-2 shrink-0 text-xs whitespace-nowrap text-muted-foreground'
              >
                {transportBusy
                  ? '正在生成…'
                  : presentationPending
                    ? '正在显示…'
                    : error
                      ? '连接失败'
                      : null}
              </span>
              {artifactList.length > 0 && (
                <Button
                  variant='ghost'
                  size='sm'
                  onClick={() => openArtifact(activeId ?? artifactList.at(-1)!.id)}
                >
                  <Icons.panelLeft data-icon='inline-start' />
                  成果物 <span className='tabular-nums'>{artifactList.length}</span>
                </Button>
              )}
              <Button
                data-testid='restart-chat'
                variant='ghost'
                size='icon-sm'
                aria-label='新建对话'
                disabled={sessionBusy}
                onClick={newConversation}
              >
                <Icons.add />
              </Button>
            </div>
          </div>
          <MessageScrollerProvider autoScroll defaultScrollPosition='end' scrollEdgeThreshold={8}>
            <MessageScroller className='min-h-0 flex-1'>
              <ChatScrollViewport data-testid='chat-viewport' aria-label='对话消息'>
                <MessageScrollerContent className='mx-auto w-full max-w-3xl gap-8 px-2 pt-6 pb-12 sm:px-6'>
                  {messages.length === 0 ? (
                    <MessageScrollerItem
                      messageId='welcome'
                      className='flex flex-1 items-center [content-visibility:visible]'
                    >
                      <div className='mx-auto flex w-full max-w-3xl flex-col items-start gap-5 py-8 sm:py-16'>
                        <span className='flex items-center gap-2 text-xs font-medium tracking-[0.18em] text-muted-foreground'>
                          <Icons.sparkles className='size-4' />
                          从想法，到成果
                        </span>
                        <h1 className='text-3xl leading-tight font-medium tracking-tight sm:text-4xl'>
                          一起把工作向前推进。
                        </h1>
                        <p className='max-w-xl text-sm leading-7 text-muted-foreground'>
                          分析一个问题，整理一份报告，或搭建一个看板。
                        </p>
                        <div className='mt-4 grid w-full grid-cols-1 gap-3 sm:grid-cols-2'>
                          {DEMO_SCENARIOS.map((item, index) => {
                            const Icon = scenarioIcons[index];
                            return (
                              <Button
                                key={item.id}
                                data-testid={`scenario-${item.id}`}
                                variant='outline'
                                className='h-auto justify-start gap-3 rounded-xl p-4 text-left whitespace-normal'
                                onClick={() => submit(item.prompt, item.id)}
                              >
                                <Icon className='size-5 shrink-0' />
                                <span className='flex flex-col gap-1'>
                                  <span>{item.label}</span>
                                  <span className='text-xs leading-5 font-normal text-muted-foreground'>
                                    {item.description}
                                  </span>
                                </span>
                                <Icons.arrowRight className='ml-auto shrink-0' />
                              </Button>
                            );
                          })}
                        </div>
                      </div>
                    </MessageScrollerItem>
                  ) : (
                    displayMessages.map((message) => {
                      const isUser = message.role === 'user';
                      const isCurrentResponse =
                        status === 'streaming' && !isUser && message.id === messages.at(-1)?.id;
                      return (
                        <MessageScrollerItem
                          key={message.id}
                          messageId={message.id}
                          className='[content-visibility:visible]'
                        >
                          <Message align={isUser ? 'end' : 'start'}>
                            <MessageContent className='gap-3'>
                              {message.parts.map((part, index) => {
                                const key = `${message.id}-${index}`;
                                if (part.type === 'text' && !part.text) return null;
                                if (part.type === 'text')
                                  return isUser ? (
                                    <Bubble
                                      key={key}
                                      variant='secondary'
                                      align='end'
                                      className='max-w-[90%]'
                                    >
                                      <BubbleContent className='px-5 py-3 text-[15px] leading-7 whitespace-pre-wrap'>
                                        {part.text}
                                      </BubbleContent>
                                    </Bubble>
                                  ) : (
                                    <Bubble key={key} variant='ghost' className='w-full'>
                                      <BubbleContent
                                        className='w-full'
                                        data-testid='assistant-response-text'
                                      >
                                        <ChatMarkdown
                                          content={part.text}
                                          streaming={
                                            isCurrentResponse ||
                                            (presentationPending &&
                                              message.id === messages.at(-1)?.id)
                                          }
                                        />
                                      </BubbleContent>
                                    </Bubble>
                                  );
                                if (part.type === 'file')
                                  return <MessageAttachment key={key} part={part} />;
                                if (part.type === 'reasoning')
                                  return (
                                    <ReasoningBlock
                                      key={key}
                                      text={part.text}
                                      streaming={part.state === 'streaming' && isCurrentResponse}
                                      interrupted={part.state === 'streaming' && !isCurrentResponse}
                                    />
                                  );
                                if (isToolUIPart(part))
                                  return (
                                    <ToolCall
                                      key={part.toolCallId}
                                      part={part}
                                      busy={isCurrentResponse}
                                    />
                                  );
                                if (part.type === 'data-artifact') {
                                  const snapshot = parseArtifact(part.data);
                                  const artifact =
                                    snapshot &&
                                    artifactList.find((item) => item.id === snapshot.id);
                                  return artifact ? (
                                    <ArtifactCard
                                      key={part.id ?? key}
                                      artifact={artifact}
                                      isActive={activeId === artifact.id}
                                      onOpen={openArtifact}
                                    />
                                  ) : null;
                                }
                                return null;
                              })}
                            </MessageContent>
                          </Message>
                        </MessageScrollerItem>
                      );
                    })
                  )}
                  {status === 'submitted' && (
                    <MessageScrollerItem messageId='pending'>
                      <div className='flex items-center gap-2 text-sm text-muted-foreground'>
                        <Icons.spinner className='size-4 motion-safe:animate-spin' />
                        正在整理思路…
                      </div>
                    </MessageScrollerItem>
                  )}
                  {error && (
                    <MessageScrollerItem messageId='error'>
                      <FeedbackNotice
                        severity='error'
                        title='回复未完成'
                        actions={
                          <Button
                            variant='outline'
                            size='sm'
                            onClick={() => {
                              clearError();
                              composerRef.current?.focus();
                            }}
                          >
                            继续对话
                          </Button>
                        }
                      >
                        连接可能暂时不可用，已收到的内容仍然保留。请检查网络及附件是否仍可用，再重新输入消息。
                      </FeedbackNotice>
                    </MessageScrollerItem>
                  )}
                </MessageScrollerContent>
              </ChatScrollViewport>
              <MessageScrollerButton
                aria-label='回到最新'
                size='sm'
                className='gap-1.5 rounded-full px-3 shadow-sm'
              >
                <Icons.chevronsDown />
                回到最新
              </MessageScrollerButton>
            </MessageScroller>
          </MessageScrollerProvider>
          <div className='mx-auto w-full max-w-3xl shrink-0 px-2 pt-3 sm:px-6'>
            {messages.length > 0 && (
              <div className='mb-3 flex gap-1.5 overflow-x-auto'>
                {DEMO_SCENARIOS.map((item) => (
                  <Button
                    key={item.id}
                    data-testid={`scenario-${item.id}`}
                    variant={scenario === item.id ? 'secondary' : 'ghost'}
                    size='sm'
                    disabled={sessionBusy}
                    onClick={() => {
                      setScenario(item.id);
                      setDraft(item.prompt);
                    }}
                  >
                    {item.label}
                  </Button>
                ))}
              </div>
            )}
            <form
              onDragOver={(event) => {
                if (event.dataTransfer.types.includes('Files')) event.preventDefault();
              }}
              onDrop={(event) => {
                if (!event.dataTransfer.types.includes('Files')) return;
                event.preventDefault();
                if (!isBusy) attachments.add(Array.from(event.dataTransfer.files));
              }}
              onSubmit={(event) => {
                event.preventDefault();
                submit(draft);
              }}
            >
              <input
                ref={fileInputRef}
                type='file'
                multiple
                accept={ATTACHMENT_ACCEPT}
                className='sr-only'
                tabIndex={-1}
                aria-label='选择图片或附件'
                aria-invalid={Boolean(attachments.error)}
                aria-describedby={attachments.error ? 'attachment-error' : undefined}
                disabled={isBusy}
                onChange={(event) => {
                  attachments.add(Array.from(event.target.files ?? []));
                  event.target.value = '';
                }}
              />
              {attachments.error && (
                <div id='attachment-error'>
                  <FeedbackNotice
                    severity='error'
                    title='附件未就绪'
                    actions={
                      <Button
                        type='button'
                        variant='outline'
                        size='sm'
                        onClick={attachments.dismissError}
                      >
                        关闭提示
                      </Button>
                    }
                  >
                    {attachments.error}
                  </FeedbackNotice>
                </div>
              )}
              <InputGroup className='rounded-2xl bg-background shadow-xs'>
                {attachments.items.length > 0 && (
                  <InputGroupAddon align='block-start' className='min-w-0 px-3 pt-3'>
                    <AttachmentGroup aria-label='待发送附件' className='w-full'>
                      {attachments.items.map((item) => (
                        <DraftAttachmentCard
                          key={item.key}
                          item={item}
                          disabled={isBusy}
                          onRemove={() => attachments.remove(item.key)}
                          onRetry={() => attachments.retry(item.key)}
                        />
                      ))}
                    </AttachmentGroup>
                  </InputGroupAddon>
                )}
                <InputGroupTextarea
                  ref={composerRef}
                  data-testid='chat-composer'
                  aria-label='发送消息'
                  maxLength={100_000}
                  onPaste={(event) => {
                    const files = Array.from(event.clipboardData.items)
                      .filter((item) => item.kind === 'file')
                      .flatMap((item) => {
                        const file = item.getAsFile();
                        return file ? [file] : [];
                      });
                    if (!files.length) return;
                    // Preserve mixed clipboard text through the textarea's normal paste behavior.
                    if (!event.clipboardData.getData('text/plain')) event.preventDefault();
                    if (!isBusy) attachments.add(files);
                  }}
                  placeholder='描述你想完成的工作，或粘贴图片…'
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  className='max-h-40 min-h-16 px-4 pt-4'
                  onKeyDown={(event) => {
                    if (
                      event.key === 'Enter' &&
                      !event.shiftKey &&
                      !event.nativeEvent.isComposing
                    ) {
                      event.preventDefault();
                      submit(draft);
                    }
                  }}
                />
                <InputGroupAddon align='block-end' className='justify-between px-3 pb-3'>
                  <div className='flex min-w-0 items-center gap-2'>
                    <Button
                      type='button'
                      variant='ghost'
                      size='icon-sm'
                      aria-label='添加图片或附件'
                      disabled={isBusy}
                      onClick={() => fileInputRef.current?.click()}
                    >
                      <Icons.add />
                    </Button>
                    <span className='truncate text-xs text-muted-foreground' aria-live='polite'>
                      {attachments.uploading ? '正在上传附件…' : '最多 5 个 · 单个 10 MB'}
                    </span>
                  </div>
                  {isBusy ? (
                    <Button
                      type='button'
                      data-testid='stop-stream'
                      variant='secondary'
                      size='sm'
                      onClick={stopGeneration}
                    >
                      <Icons.close data-icon='inline-start' />
                      停止生成
                    </Button>
                  ) : (
                    <Button
                      type='submit'
                      data-testid='send-message'
                      size='icon'
                      aria-label='发送消息'
                      disabled={attachments.blocked || (!draft.trim() && !attachments.ready.length)}
                    >
                      <Icons.send />
                    </Button>
                  )}
                </InputGroupAddon>
              </InputGroup>
            </form>
          </div>
        </section>
        {isDesktop && panelOpen && (
          <div
            className={cn(
              'h-full min-w-0 shrink-0 motion-safe:transition-[width] motion-safe:duration-300',
              expanded ? 'w-[68%]' : 'w-[55%]'
            )}
          >
            {panel}
          </div>
        )}
      </div>
      <Sheet open={!isDesktop && mobileHistoryOpen} onOpenChange={setMobileHistoryOpen}>
        <SheetContent
          side='left'
          showCloseButton={false}
          className='gap-0 border-sidebar-border bg-sidebar text-sidebar-foreground'
        >
          <SheetTitle className='sr-only'>历史会话</SheetTitle>
          {!isDesktop && historyPanel}
        </SheetContent>
      </Sheet>
      <Sheet
        open={!isDesktop && panelOpen}
        onOpenChange={(open) => {
          if (!open) closeArtifact();
        }}
      >
        <SheetContent
          showCloseButton={false}
          finalFocus={() =>
            sheetReturnFocus.current?.isConnected && !sheetReturnFocus.current.matches(':disabled')
              ? sheetReturnFocus.current
              : composerRef.current
          }
          className='w-full gap-0 data-[side=right]:w-full data-[side=right]:sm:max-w-none'
        >
          <SheetTitle className='sr-only'>成果物预览</SheetTitle>
          {!isDesktop && panel}
        </SheetContent>
      </Sheet>
    </div>
  );
}
