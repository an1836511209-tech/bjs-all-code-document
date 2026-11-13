'use client';

import { RouteError } from '@/components/route-error';

export default function OverviewError(props: { error: Error & { digest?: string }; reset: () => void }) {
  return <RouteError {...props} title='Unable to load statistics' description='This section is temporarily unavailable. Please try again.' />;
}
