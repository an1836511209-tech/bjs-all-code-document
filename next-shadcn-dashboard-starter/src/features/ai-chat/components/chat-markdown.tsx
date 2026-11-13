'use client';

import { Streamdown, defaultRehypePlugins, type Components } from 'streamdown';
import { memo } from 'react';
import { cjk } from '@streamdown/cjk';
import 'streamdown/styles.css';

// Retain Streamdown's sanitization/hardening without interpreting model HTML.
const rehypePlugins = [defaultRehypePlugins.sanitize, defaultRehypePlugins.harden];
const remend = { linkMode: 'text-only' as const };
const plugins = { cjk };
// The display queue owns pacing; Streamdown only fades newly revealed text.
const animation = { animation: 'fadeIn', duration: 120, sep: 'char', stagger: 0 } as const;
const linkClassName = 'text-primary underline underline-offset-4';
// Stable component identities preserve links/tables across streaming updates.
const components: Components = {
  strong: ({ children }) => <strong>{children}</strong>,
  a: ({ children, href }) =>
    href ? (
      <a href={href} target='_blank' rel='noopener noreferrer' className={linkClassName}>
        {children}
      </a>
    ) : (
      <span className={linkClassName}>{children}</span>
    ),
  table: ({ children }) => (
    <div className='my-4 max-w-full overflow-x-auto rounded-lg border'>
      <table className='w-full text-sm'>{children}</table>
    </div>
  ),
  pre: ({ children }) => <pre>{children}</pre>,
  code: ({ children }) => <code>{children}</code>,
  img: ({ alt }) => <span className='text-muted-foreground'>[图片：{alt ?? '未命名'}]</span>
};

/** Model HTML is never interpreted as executable markup. */
export const ChatMarkdown = memo(function ChatMarkdown({
  content,
  streaming = false
}: {
  content: string;
  streaming?: boolean;
}) {
  return (
    <div className='min-w-0 [text-wrap:stable] text-[15px] leading-7 wrap-break-word [&>*:first-child]:mt-0 [&>*:last-child]:mb-0 [&_blockquote]:border-l-2 [&_blockquote]:pl-4 [&_blockquote]:text-muted-foreground [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:font-mono [&_code]:text-[0.85em] [&_h1]:mt-7 [&_h1]:mb-4 [&_h1]:text-2xl [&_h1]:font-semibold [&_h2]:mt-7 [&_h2]:mb-3 [&_h2]:text-xl [&_h2]:font-semibold [&_h3]:mt-5 [&_h3]:mb-2 [&_h3]:text-base [&_h3]:font-semibold [&_li]:my-1 [&_ol]:my-3 [&_ol]:list-decimal [&_ol]:pl-6 [&_p]:my-3 [&_pre]:my-4 [&_pre]:overflow-x-auto [&_pre]:rounded-xl [&_pre]:bg-muted [&_pre]:p-4 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_strong]:font-semibold [&_th]:bg-muted [&_th]:text-left [&_th]:font-medium [&_th]:p-3 [&_td]:border-t [&_td]:p-3 [&_ul]:my-3 [&_ul]:list-disc [&_ul]:pl-6'>
      <Streamdown
        mode='streaming'
        isAnimating={streaming}
        parseIncompleteMarkdown={streaming}
        animated={animation}
        className='motion-reduce:[&_[data-sd-animate]]:animate-none motion-reduce:[&_[data-sd-animate-marker]::marker]:animate-none'
        controls={false}
        skipHtml
        rehypePlugins={rehypePlugins}
        components={components}
        plugins={plugins}
        remend={remend}
      >
        {content}
      </Streamdown>
    </div>
  );
});
