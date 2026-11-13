'use client';

import { Component, type ReactNode } from 'react';
import { Icons } from '@/components/icons';
import { Button, buttonVariants } from '@/components/ui/button';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { cn, formatBytes } from '@/lib/utils';
import { getArtifactRenderer } from '../registry';
import { isSafeDownloadUrl } from '../schemas';
import type { Artifact } from '../types';
import { artifactKindIcons, artifactKindLabels } from './artifact-card';

interface ArtifactPanelProps {
  artifacts: Artifact[];
  activeArtifactId: string;
  onSelect: (id: string) => void;
  onClose: () => void;
  expanded?: boolean;
  onToggleExpand?: () => void;
  className?: string;
}

interface PreviewNoticeProps {
  title: string;
  description: string;
  loading?: boolean;
}

function PreviewNotice({
  title,
  description,
  loading = false
}: PreviewNoticeProps): React.JSX.Element {
  const NoticeIcon = loading ? Icons.spinner : Icons.page;
  return (
    <div
      className='flex min-h-80 flex-col items-center justify-center px-8 py-14 text-center'
      role='status'
    >
      <span className='mb-5 flex size-14 items-center justify-center rounded-2xl border bg-background'>
        <NoticeIcon
          className={cn('size-6 text-muted-foreground', loading && 'animate-spin')}
          aria-hidden='true'
        />
      </span>
      <h3 className='text-sm font-medium'>{title}</h3>
      <p className='mt-2 max-w-xs text-xs leading-relaxed text-muted-foreground'>{description}</p>
    </div>
  );
}

class PreviewErrorBoundary extends Component<{ children: ReactNode }, { hasError: boolean }> {
  state = { hasError: false };

  static getDerivedStateFromError(): { hasError: boolean } {
    return { hasError: true };
  }

  render(): ReactNode {
    if (this.state.hasError) {
      return (
        <PreviewNotice
          title='暂时无法显示预览'
          description='成果内容仍然保留。请稍后重新打开；如已提供文件，也可以直接下载。'
        />
      );
    }
    return this.props.children;
  }
}

function ArtifactPreview({ artifact }: { artifact: Artifact }): React.JSX.Element {
  if (artifact.status === 'error') {
    return (
      <PreviewNotice
        title='成果生成未完成'
        description={artifact.error || '生成时遇到问题，可以在对话中重试。'}
      />
    );
  }

  if (!artifact.preview) {
    return artifact.status === 'generating' ? (
      <PreviewNotice
        title='正在准备成果'
        description='内容准备好后将自动显示，你可以继续阅读左侧对话。'
        loading
      />
    ) : (
      <PreviewNotice
        title='文件已就绪'
        description='此成果暂无在线预览，可以通过右上角下载文件。'
      />
    );
  }

  const renderer = getArtifactRenderer(artifact.preview.renderer, artifact.preview.version);
  if (!renderer) {
    return (
      <PreviewNotice
        title='暂不支持此成果的在线预览'
        description={
          artifact.file
            ? '文件已保留，可以通过右上角下载。'
            : '成果已保留。此工作区尚未启用对应的预览方式。'
        }
      />
    );
  }

  const rendered = renderer.render(artifact);
  if (!rendered.success) {
    return artifact.status === 'generating' ? (
      <PreviewNotice title='正在整理预览内容' description='内容准备好后会自动显示。' loading />
    ) : (
      <PreviewNotice
        title='暂时无法显示预览'
        description='成果内容格式不完整，请在对话中重新生成。'
      />
    );
  }
  return <>{rendered.content}</>;
}

export function ArtifactPanel({
  artifacts,
  activeArtifactId,
  onSelect,
  onClose,
  expanded = false,
  onToggleExpand,
  className
}: ArtifactPanelProps): React.JSX.Element | null {
  const artifact = artifacts.find((item) => item.id === activeArtifactId);
  if (!artifact) return null;

  const KindIcon = artifactKindIcons[artifact.kind];
  const file = artifact.file && isSafeDownloadUrl(artifact.file.url) ? artifact.file : undefined;

  return (
    <aside
      data-testid='artifact-panel'
      data-artifact-id={artifact.id}
      aria-label='成果物预览'
      className={cn(
        'flex h-full min-h-0 min-w-0 flex-col overflow-hidden rounded-2xl border bg-background text-foreground shadow-sm',
        className
      )}
    >
      <header className='flex min-h-16 shrink-0 items-center gap-2 border-b px-3 py-3 sm:px-4'>
        <KindIcon
          className='mr-1 hidden size-5 shrink-0 text-muted-foreground sm:block'
          aria-hidden='true'
        />
        <div className='min-w-0 flex-1'>
          {artifacts.length > 1 ? (
            <NativeSelect
              data-testid='artifact-select'
              aria-label='选择成果物'
              value={artifact.id}
              onChange={(event) => onSelect(event.target.value)}
              className='w-full max-w-sm [&_select]:border-transparent [&_select]:pl-0 [&_select]:font-medium'
            >
              {artifacts.map((item) => (
                <NativeSelectOption key={item.id} value={item.id}>
                  {item.title}
                </NativeSelectOption>
              ))}
            </NativeSelect>
          ) : (
            <h2 className='truncate text-sm font-medium' title={artifact.title}>
              {artifact.title}
            </h2>
          )}
          <div className='mt-0.5 flex items-center gap-1.5 text-[11px] text-muted-foreground'>
            <span>{artifactKindLabels[artifact.kind]}</span>
            <span aria-hidden='true'>·</span>
            <span>版本 {artifact.revision}</span>
            {artifact.status === 'generating' && (
              <span className='flex items-center gap-1'>
                <Icons.spinner className='size-3 animate-spin' aria-hidden='true' />
                生成中
              </span>
            )}
            {artifact.status === 'error' && <span className='text-destructive'>生成失败</span>}
          </div>
        </div>
        {file && artifact.status === 'ready' && (
          <a
            data-testid='artifact-download'
            href={file.url}
            download={file.name}
            target='_blank'
            rel='noopener noreferrer'
            aria-label={`下载 ${file.name}`}
            className={cn(buttonVariants({ variant: 'outline', size: 'sm' }), 'gap-1.5')}
          >
            <Icons.download className='size-3.5' aria-hidden='true' />
            <span className='hidden sm:inline'>下载</span>
          </a>
        )}
        {onToggleExpand && (
          <Button
            variant='ghost'
            size='icon-sm'
            className='hidden lg:inline-flex'
            aria-label={expanded ? '还原成果预览宽度' : '扩大成果预览'}
            title={expanded ? '还原宽度' : '扩大预览'}
            onClick={onToggleExpand}
          >
            {expanded ? (
              <Icons.minimize aria-hidden='true' />
            ) : (
              <Icons.maximize aria-hidden='true' />
            )}
          </Button>
        )}
        <Button
          data-testid='artifact-close'
          variant='ghost'
          size='icon-sm'
          aria-label='关闭成果预览'
          title='关闭预览'
          onClick={onClose}
        >
          <Icons.close aria-hidden='true' />
        </Button>
      </header>
      <div className='min-h-0 flex-1 overflow-auto overscroll-contain bg-muted/30'>
        <PreviewErrorBoundary key={`${artifact.id}:${artifact.revision}`}>
          <ArtifactPreview artifact={artifact} />
        </PreviewErrorBoundary>
      </div>
      <footer className='flex shrink-0 items-center justify-between gap-3 border-t px-4 py-2.5 text-[10px] leading-relaxed text-muted-foreground'>
        <span>
          {file
            ? `${file.name}${file.sizeBytes !== undefined ? ` · ${formatBytes(file.sizeBytes)}` : ''}`
            : '在线预览 · 尚未提供可下载文件'}
        </span>
        <span className='shrink-0'>
          {artifact.status === 'ready'
            ? '已就绪'
            : artifact.status === 'generating'
              ? '生成中'
              : '未完成'}
        </span>
      </footer>
    </aside>
  );
}
