'use client';

import { Icons } from '@/components/icons';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';

export interface ToolPart {
  type: string;
  toolCallId: string;
  toolName?: string;
  state: string;
  input?: unknown;
  output?: unknown;
  errorText?: string;
}

function JsonDetail({ label, value, testId }: { label: string; value: unknown; testId: string }) {
  return (
    <div className='min-w-0'>
      <p className='mb-2 text-xs font-medium text-muted-foreground'>{label}</p>
      <pre
        data-testid={testId}
        className='max-h-64 overflow-auto rounded-lg bg-muted/60 p-3 font-mono text-xs leading-5'
      >
        {typeof value === 'string' ? value : JSON.stringify(value, null, 2)}
      </pre>
    </div>
  );
}

export function ToolCall({ part, busy }: { part: ToolPart; busy: boolean }) {
  const name = part.toolName ?? part.type.replace(/^tool-/, '');
  const waiting = [
    'input-streaming',
    'input-available',
    'approval-requested',
    'approval-responded'
  ].includes(part.state);
  const failed = part.state === 'output-error' || part.state === 'output-denied';
  const running = waiting && busy;
  return (
    <Collapsible className='min-w-0' data-testid='tool-call'>
      <CollapsibleTrigger className='group flex max-w-full items-center gap-2 rounded-md py-2 text-left text-sm text-muted-foreground outline-none hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring'>
        {running ? (
          <Icons.spinner className='size-3.5 shrink-0 motion-safe:animate-spin' />
        ) : failed ? (
          <Icons.warning className='size-3.5 shrink-0' />
        ) : (
          <Icons.code className='size-3.5 shrink-0' />
        )}
        <span className='truncate'>
          {running ? 'Calling' : failed ? 'Failed' : waiting ? 'Stopped' : 'Called'}{' '}
          <strong className='font-medium text-foreground'>{name}</strong>
        </span>
        <Icons.chevronRight className='size-3.5 shrink-0 transition-transform group-aria-expanded:rotate-90' />
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className='my-2 flex min-w-0 flex-col gap-4 rounded-xl border p-4'>
          <JsonDetail
            label='请求参数 · Input'
            value={part.input ?? '正在接收参数…'}
            testId='tool-input'
          />
          <JsonDetail
            label='返回结果 · Output'
            value={
              failed
                ? (part.errorText ?? '工具未执行或执行失败')
                : (part.output ?? (running ? '等待工具返回…' : '本次调用已中止，未收到结果。'))
            }
            testId='tool-output'
          />
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}
