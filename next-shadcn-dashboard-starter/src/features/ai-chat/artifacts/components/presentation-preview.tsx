'use client';

import { useState } from 'react';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { Artifact, PresentationPreview } from '../types';

interface PresentationPreviewProps {
  data: PresentationPreview;
  artifact: Artifact;
}

export function PresentationArtifactPreview({
  data,
  artifact
}: PresentationPreviewProps): React.JSX.Element {
  const [selectedIndex, setSelectedIndex] = useState(0);
  const activeIndex = Math.min(selectedIndex, data.slides.length - 1);
  const slide = data.slides[activeIndex];

  return (
    <div className='flex flex-col gap-5 p-4 sm:p-6' data-testid='presentation-preview'>
      <div className='flex items-center justify-between gap-3'>
        <span className='truncate text-sm font-medium'>{artifact.title}</span>
        <span className='shrink-0 text-xs text-muted-foreground'>{data.slides.length} 页</span>
      </div>
      <section
        aria-label={`第 ${activeIndex + 1} 页：${slide.title}`}
        className='relative flex aspect-video min-h-80 flex-col rounded-xl border bg-card p-6 text-card-foreground shadow-sm sm:p-9'
      >
        <div className='mb-5 flex items-center gap-2 text-[10px] font-semibold tracking-[0.15em] text-muted-foreground uppercase'>
          <span className='h-1.5 w-5 rounded-full bg-primary' />
          {artifact.title}
        </div>
        <h3 className='max-w-[95%] text-xl leading-snug font-semibold tracking-tight sm:text-3xl'>
          {slide.title}
        </h3>
        {slide.subtitle && (
          <p className='mt-3 text-sm leading-relaxed text-muted-foreground'>{slide.subtitle}</p>
        )}
        <ul className='mt-6 flex flex-1 flex-col gap-3 text-sm leading-relaxed sm:gap-4'>
          {slide.bullets.map((bullet, index) => (
            <li key={index} className='flex gap-3'>
              <span
                className='mt-2 size-1.5 shrink-0 rounded-full bg-primary/60'
                aria-hidden='true'
              />
              <span>{bullet}</span>
            </li>
          ))}
        </ul>
        <div className='mt-6 flex justify-between border-t pt-3 text-[10px] text-muted-foreground'>
          <span>演示文稿</span>
          <span>
            {String(activeIndex + 1).padStart(2, '0')} /{' '}
            {String(data.slides.length).padStart(2, '0')}
          </span>
        </div>
      </section>
      <div className='flex items-center justify-center gap-3'>
        <Button
          variant='outline'
          size='icon-sm'
          aria-label='上一页幻灯片'
          data-testid='presentation-previous'
          disabled={activeIndex === 0}
          onClick={() => setSelectedIndex(activeIndex - 1)}
        >
          <Icons.chevronLeft aria-hidden='true' />
        </Button>
        <span className='min-w-16 text-center text-xs text-muted-foreground' aria-live='polite'>
          {activeIndex + 1} / {data.slides.length}
        </span>
        <Button
          variant='outline'
          size='icon-sm'
          aria-label='下一页幻灯片'
          data-testid='presentation-next'
          disabled={activeIndex === data.slides.length - 1}
          onClick={() => setSelectedIndex(activeIndex + 1)}
        >
          <Icons.chevronRight aria-hidden='true' />
        </Button>
      </div>
      <nav aria-label='幻灯片缩略图' className='flex gap-3 overflow-x-auto pb-2'>
        {data.slides.map((thumbnail, index) => (
          <button
            key={thumbnail.id}
            type='button'
            aria-label={`跳转到第 ${index + 1} 页：${thumbnail.title}`}
            aria-current={index === activeIndex ? 'page' : undefined}
            onClick={() => setSelectedIndex(index)}
            className={cn(
              'flex w-36 shrink-0 flex-col rounded-lg border bg-background p-3 text-left transition-colors hover:border-primary/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              index === activeIndex && 'border-primary bg-primary/5'
            )}
          >
            <span className='mb-2 text-[10px] text-muted-foreground'>
              {String(index + 1).padStart(2, '0')}
            </span>
            <span className='line-clamp-2 h-8 text-xs leading-4 font-medium'>
              {thumbnail.title}
            </span>
            <span className='mt-3 h-1 w-3/4 rounded bg-muted' />
            <span className='mt-1 h-1 w-1/2 rounded bg-muted' />
          </button>
        ))}
      </nav>
      {slide.note && (
        <aside className='rounded-xl border border-dashed px-4 py-3'>
          <h4 className='text-xs font-medium'>演讲者备注</h4>
          <p className='mt-2 text-xs leading-relaxed text-muted-foreground'>{slide.note}</p>
        </aside>
      )}
    </div>
  );
}
