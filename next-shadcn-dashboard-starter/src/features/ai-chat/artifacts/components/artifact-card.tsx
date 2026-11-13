'use client';

import { Icons, type Icon } from '@/components/icons';
import { cn } from '@/lib/utils';
import type { Artifact } from '../types';

export const artifactKindLabels: Record<Artifact['kind'], string> = {
  document: '文档',
  spreadsheet: '表格',
  presentation: '演示文稿',
  custom: '交互成果'
};

export const artifactKindIcons: Record<Artifact['kind'], Icon> = {
  document: Icons.fileTypeDoc,
  spreadsheet: Icons.fileTypeXls,
  presentation: Icons.galleryVerticalEnd,
  custom: Icons.dashboard
};

interface ArtifactCardProps {
  artifact: Artifact;
  isActive?: boolean;
  onOpen: (id: string) => void;
}

export function ArtifactCard({
  artifact,
  isActive = false,
  onOpen
}: ArtifactCardProps): React.JSX.Element {
  const KindIcon = artifactKindIcons[artifact.kind];

  return (
    <button
      type='button'
      data-testid='artifact-card'
      data-artifact-id={artifact.id}
      data-artifact-kind={artifact.kind}
      aria-label={`查看成果：${artifact.title}`}
      aria-pressed={isActive}
      onClick={() => onOpen(artifact.id)}
      className={cn(
        'group flex w-full max-w-xl items-center gap-4 rounded-2xl border bg-background p-4 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring',
        isActive && 'border-primary/35 bg-muted/40'
      )}
    >
      <span className='flex size-12 shrink-0 items-center justify-center rounded-xl border bg-muted/40 text-muted-foreground'>
        <KindIcon className='size-6' aria-hidden='true' />
      </span>
      <span className='min-w-0 flex-1'>
        <span className='block truncate text-sm font-medium'>{artifact.title}</span>
        <span className='mt-1 flex items-center gap-1.5 text-xs text-muted-foreground'>
          {artifactKindLabels[artifact.kind]}
          <span aria-hidden='true'>·</span>
          {artifact.status === 'generating' ? (
            <>
              <Icons.spinner className='size-3 animate-spin' aria-hidden='true' />
              正在生成
            </>
          ) : artifact.status === 'error' ? (
            '生成失败'
          ) : (
            `版本 ${artifact.revision}`
          )}
        </span>
      </span>
      <span className='flex shrink-0 items-center gap-1 text-xs text-muted-foreground group-hover:text-foreground'>
        {isActive ? '已打开' : '查看'}
        <Icons.chevronRight className='size-3.5' aria-hidden='true' />
      </span>
    </button>
  );
}
