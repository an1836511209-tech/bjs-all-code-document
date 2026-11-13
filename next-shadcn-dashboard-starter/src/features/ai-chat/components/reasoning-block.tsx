'use client';

import { Icons } from '@/components/icons';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import {
  MessageScroller,
  MessageScrollerButton,
  MessageScrollerContent,
  MessageScrollerItem,
  MessageScrollerProvider
} from '@/components/ui/message-scroller';
import { ChatScrollViewport } from './chat-scroll-viewport';

export function ReasoningBlock({
  text,
  streaming,
  interrupted
}: {
  text: string;
  streaming: boolean;
  interrupted: boolean;
}) {
  return (
    <Collapsible defaultOpen className='min-w-0'>
      <CollapsibleTrigger className='group flex items-center gap-2 rounded-md py-2 text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring'>
        {streaming ? (
          <Icons.spinner className='size-3.5 motion-safe:animate-spin' />
        ) : (
          <Icons.check className='size-3.5' />
        )}
        <span>{streaming ? '正在思考' : interrupted ? '思考已中止' : '思考过程'}</span>
        <Icons.chevronDown className='size-3.5 transition-transform group-aria-expanded:rotate-180' />
      </CollapsibleTrigger>
      <CollapsibleContent>
        {/* Nested scroll intent must not reach the conversation's scroller. */}
        {/* oxlint-disable-next-line jsx-a11y/no-noninteractive-element-interactions -- contains an accessible keyboard scroll viewport; these handlers only isolate nested scroll intent */}
        <div
          role='region'
          aria-label='思考过程'
          onWheel={(event) => event.stopPropagation()}
          onTouchMove={(event) => event.stopPropagation()}
          onKeyDown={(event) => event.stopPropagation()}
          className='my-2 border-l-2 pl-4'
        >
          <MessageScrollerProvider autoScroll defaultScrollPosition='end' scrollEdgeThreshold={8}>
            <MessageScroller className='h-40'>
              <ChatScrollViewport
                data-testid='reasoning-viewport'
                data-streaming={streaming}
                aria-label='思考内容，可独立滚动'
                className='pr-3'
              >
                <MessageScrollerContent className='min-h-0'>
                  <MessageScrollerItem
                    messageId='reasoning'
                    className='[content-visibility:visible]'
                  >
                    <p className='text-sm leading-6 whitespace-pre-wrap text-muted-foreground'>
                      {text}
                    </p>
                  </MessageScrollerItem>
                </MessageScrollerContent>
              </ChatScrollViewport>
              <MessageScrollerButton aria-label='回到最新思考' className='bottom-1' />
            </MessageScroller>
          </MessageScrollerProvider>
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
