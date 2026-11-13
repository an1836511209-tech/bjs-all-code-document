'use client';

import { useId, type ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { Alert, AlertTitle, AlertDescription } from '@/components/ui/alert';
import { cn } from '@/lib/utils';

interface FeedbackNoticeProps {
  title: string;
  children: ReactNode;
  actions?: ReactNode;
  severity?: 'warning' | 'error';
  className?: string;
}

/** Persistent feedback composed from the template's Alert. Keep diagnostics in monitoring. */
export function FeedbackNotice({
  title,
  children,
  actions,
  severity = 'warning',
  className
}: FeedbackNoticeProps) {
  const titleId = useId();
  const descriptionId = useId();
  const Icon = severity === 'error' ? Icons.alertCircle : Icons.info;
  return (
    <Alert
      variant={severity === 'error' ? 'destructive' : 'default'}
      role={severity === 'error' ? 'alert' : 'status'}
      aria-labelledby={titleId}
      aria-describedby={descriptionId}
      className={cn('min-w-0 gap-3 p-4 sm:grid-cols-[auto_minmax(0,1fr)_auto]', className)}
    >
      <Icon aria-hidden='true' />
      <div className='flex min-w-0 flex-col gap-1'>
        <AlertTitle id={titleId}>
          <h2>{title}</h2>
        </AlertTitle>
        <AlertDescription id={descriptionId} className='break-words'>
          {children}
        </AlertDescription>
      </div>
      {actions && (
        <div className='col-span-full flex flex-wrap items-center gap-2 sm:col-span-1 sm:col-start-3 sm:row-start-1'>
          {actions}
        </div>
      )}
    </Alert>
  );
}
