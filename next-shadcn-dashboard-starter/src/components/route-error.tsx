'use client';

import { useEffect, useTransition } from 'react';
import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { useQueryErrorResetBoundary } from '@tanstack/react-query';
import * as Sentry from '@sentry/nextjs';
import { FeedbackNotice } from '@/components/feedback-notice';
import { Button } from '@/components/ui/button';
import { Icons } from '@/components/icons';
import { getQueryClient } from '@/lib/query-client';

interface RouteErrorProps {
  error: Error & { digest?: string };
  reset: () => void;
  title?: string;
  description?: string;
  homeLink?: boolean;
}

/** Reset both the query failure latch and the Next.js segment. */
export function RouteError({
  error,
  reset,
  title = 'Unable to load this page',
  description = 'Please try again. If the problem continues, contact your administrator.',
  homeLink = false
}: RouteErrorProps) {
  const router = useRouter();
  const queryBoundary = useQueryErrorResetBoundary();
  const [pending, startTransition] = useTransition();
  useEffect(() => {
    Sentry.captureException(error);
  }, [error]);
  return (
    <FeedbackNotice
      severity='error'
      title={title}
      className='m-4 sm:m-6'
      actions={
        <>
          <Button
            variant='outline'
            size='sm'
            disabled={pending}
            onClick={() => {
              startTransition(() => {
                queryBoundary.reset();
                void getQueryClient().resetQueries({
                  predicate: (query) => query.state.status === 'error'
                });
                router.refresh();
                reset();
              });
            }}
          >
            {pending && (
              <Icons.spinner className='size-4 motion-safe:animate-spin' aria-hidden='true' />
            )}
            {pending ? 'Retrying…' : 'Try again'}
          </Button>
          {homeLink && (
            <Button
              variant='ghost'
              size='sm'
              render={<Link href='/dashboard/overview' aria-label='Back to overview' />}
            >
              Back to overview
            </Button>
          )}
        </>
      }
    >
      <p>{description}</p>
      {error.digest && <p className='mt-1 text-xs'>Reference: {error.digest}</p>}
    </FeedbackNotice>
  );
}
