import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';
import type { DashboardPreview } from '../types';

interface DashboardPreviewProps {
  data: DashboardPreview;
}

export function DashboardArtifactPreview({ data }: DashboardPreviewProps): React.JSX.Element {
  const minValue = Math.min(0, ...data.series.map((point) => point.value));
  const maxValue = Math.max(0, ...data.series.map((point) => point.value));
  const range = maxValue - minValue || 1;
  const zeroPosition = (-minValue / range) * 100;
  const numberFormat = new Intl.NumberFormat('zh-CN');

  return (
    <div className='flex flex-col gap-5 p-4 sm:p-6' data-testid='dashboard-preview'>
      <header className='flex items-start justify-between gap-4'>
        <div>
          <p className='text-[10px] font-medium tracking-[0.16em] text-muted-foreground uppercase'>
            业务洞察
          </p>
          <h3 className='mt-2 text-xl font-semibold tracking-tight'>{data.title}</h3>
        </div>
        <span className='shrink-0 rounded-lg border bg-background px-2.5 py-1.5 text-xs text-muted-foreground'>
          {data.period}
        </span>
      </header>
      <div className='grid grid-cols-2 gap-3'>
        {data.kpis.map((kpi, index) => (
          <article key={index} className='rounded-xl border bg-background p-4'>
            <h4 className='text-xs text-muted-foreground'>{kpi.label}</h4>
            <p className='mt-3 text-2xl font-semibold tracking-tight tabular-nums'>{kpi.value}</p>
            {kpi.change && <p className='mt-2 text-xs text-muted-foreground'>{kpi.change}</p>}
          </article>
        ))}
      </div>
      <section className='rounded-xl border bg-background p-5'>
        <div className='mb-6 flex items-center justify-between gap-2'>
          <h4 className='text-sm font-medium'>趋势概览</h4>
          <span className='flex items-center gap-1.5 text-[11px] text-muted-foreground'>
            <span className='size-2 rounded-sm bg-chart-1' />
            {data.period}
          </span>
        </div>
        <div
          className='flex flex-col gap-4'
          role='img'
          aria-label={data.series
            .map((point) => `${point.label}：${numberFormat.format(point.value)}`)
            .join('；')}
        >
          {data.series.map((point, index) => (
            <div
              key={index}
              className='grid grid-cols-[3.5rem_1fr_4.5rem] items-center gap-3 text-xs'
              aria-hidden='true'
            >
              <span className='truncate text-muted-foreground' title={point.label}>
                {point.label}
              </span>
              <div className='relative h-7 overflow-hidden rounded bg-muted/50'>
                {minValue < 0 && (
                  <span
                    className='absolute inset-y-0 z-10 w-px bg-foreground/20'
                    style={{ left: `${zeroPosition}%` }}
                  />
                )}
                <div
                  data-testid='dashboard-series-bar'
                  data-negative={point.value < 0}
                  className={cn(
                    'absolute h-full min-w-0 rounded transition-[width] duration-500 motion-reduce:transition-none',
                    point.value < 0 ? 'bg-destructive' : 'bg-chart-1'
                  )}
                  style={{
                    left: `${((Math.min(0, point.value) - minValue) / range) * 100}%`,
                    width: `${(Math.abs(point.value) / range) * 100}%`
                  }}
                />
              </div>
              <span className='text-right font-medium tabular-nums'>
                {numberFormat.format(point.value)}
              </span>
            </div>
          ))}
        </div>
      </section>
      <section className='rounded-xl border bg-background p-5'>
        <h4 className='flex items-center gap-2 text-sm font-medium'>
          <Icons.sparkles className='size-4 text-muted-foreground' aria-hidden='true' />
          关键发现
        </h4>
        <ul className='mt-4 flex flex-col gap-3'>
          {data.highlights.map((highlight, index) => (
            <li key={index} className='flex gap-3 text-sm leading-relaxed text-muted-foreground'>
              <span
                className='mt-2 size-1.5 shrink-0 rounded-full bg-primary/60'
                aria-hidden='true'
              />
              {highlight}
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
