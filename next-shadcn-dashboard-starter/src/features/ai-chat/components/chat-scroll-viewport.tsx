'use client';

import type { ComponentProps } from 'react';
import { ScrollArea } from '@base-ui/react/scroll-area';
import { MessageScrollerViewport, useMessageScroller } from '@/components/ui/message-scroller';
import { cn } from '@/lib/utils';
import styles from './chat-scroll-viewport.module.css';

function releaseFollowing(scrollbar: HTMLElement): void {
  const viewport = scrollbar.parentElement?.querySelector<HTMLElement>(
    '[data-slot="message-scroller-viewport"]'
  );
  viewport?.dispatchEvent(new WheelEvent('wheel', { bubbles: true, deltaY: 0 }));
}

/** Keep End at the live edge instead of the browser's soon-outdated scroll target. */
export function ChatScrollViewport({
  onKeyDown,
  children,
  className,
  style,
  ...props
}: ComponentProps<typeof MessageScrollerViewport>) {
  const { scrollToEnd } = useMessageScroller();
  return (
    <ScrollArea.Root className={styles.root}>
      {/* One DOM viewport: MessageScroller owns following; Base UI owns thumb geometry/dragging. */}
      <ScrollArea.Viewport
        render={<MessageScrollerViewport />}
        {...props}
        className={cn(styles.viewport, className)}
        style={style}
        onKeyDown={(event) => {
          onKeyDown?.(event);
          if (
            event.key === 'End' &&
            event.target === event.currentTarget &&
            !event.defaultPrevented
          ) {
            event.preventDefault();
            scrollToEnd({ behavior: 'auto' });
          }
        }}
      >
        <ScrollArea.Content className={styles.content}>{children}</ScrollArea.Content>
      </ScrollArea.Viewport>
      <ScrollArea.Scrollbar
        className={styles.scrollbar}
        data-slot='chat-scrollbar'
        onPointerDownCapture={(event) => {
          // The sibling thumb bypasses MessageScroller's wheel/touch/key intent
          // handlers. Normalize this real pointer gesture to a zero-delta wheel
          // event so its existing state machine releases following before drag.
          // Synthetic wheel events have no browser scrolling default action.
          releaseFollowing(event.currentTarget);
        }}
        onPointerMoveCapture={(event) => {
          if (event.buttons) releaseFollowing(event.currentTarget);
        }}
        onPointerUpCapture={(event) => releaseFollowing(event.currentTarget)}
      >
        <ScrollArea.Thumb className={styles.thumb} data-slot='chat-scrollbar-thumb' />
      </ScrollArea.Scrollbar>
    </ScrollArea.Root>
  );
}
