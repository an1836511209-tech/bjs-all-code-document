'use client';

import Image from 'next/image';
import { useCallback, useState } from 'react';
import type { FileUIPart } from 'ai';
import { Icons } from '@/components/icons';
import {
  Attachment,
  AttachmentMedia,
  AttachmentContent,
  AttachmentTitle,
  AttachmentDescription,
  AttachmentActions,
  AttachmentAction,
  AttachmentTrigger
} from '@/components/ui/attachment';
import { isSafeFilePart } from '../attachments/types';
import type { DraftAttachment } from '../attachments/use-attachments';

interface AttachmentThumbnailProps {
  src: string;
  alt: string;
}

function AttachmentThumbnail({ src, alt }: AttachmentThumbnailProps) {
  const [failed, setFailed] = useState(false);
  // Next Image includes onError in its ref dependencies; an inline callback
  // reattaches the ref and assigns img.src again on every streaming render.
  const handleError = useCallback(() => setFailed(true), []);
  return failed ? (
    <Icons.media aria-label='图片不可用' />
  ) : (
    <Image src={src} alt={alt} width={80} height={80} unoptimized onError={handleError} />
  );
}

interface DraftAttachmentCardProps {
  item: DraftAttachment;
  disabled: boolean;
  onRemove: () => void;
  onRetry: () => void;
}

export function DraftAttachmentCard({
  item,
  disabled,
  onRemove,
  onRetry
}: DraftAttachmentCardProps) {
  const image =
    item.preview ?? (item.uploaded?.mediaType.startsWith('image/') ? item.uploaded.url : undefined);
  return (
    <Attachment state={item.state} className='max-w-64' data-testid='draft-attachment'>
      <AttachmentMedia variant={image ? 'image' : 'icon'}>
        {image ? (
          <AttachmentThumbnail key={image} src={image} alt={item.filename} />
        ) : (
          <Icons.page />
        )}
      </AttachmentMedia>
      <AttachmentContent>
        <AttachmentTitle title={item.filename}>{item.filename}</AttachmentTitle>
        <AttachmentDescription aria-live='polite'>
          {item.state === 'uploading'
            ? '正在上传…'
            : item.state === 'error'
              ? '上传失败'
              : `${item.size < 1024 ? `${item.size} B` : `${(item.size / 1024).toFixed(1)} KB`} · 已上传`}
        </AttachmentDescription>
      </AttachmentContent>
      <AttachmentActions>
        {item.state === 'error' && (
          <AttachmentAction
            type='button'
            disabled={disabled}
            aria-label={`重试上传 ${item.filename}`}
            onClick={onRetry}
          >
            <Icons.upload />
          </AttachmentAction>
        )}
        <AttachmentAction
          type='button'
          disabled={disabled}
          aria-label={`移除附件 ${item.filename}`}
          onClick={onRemove}
        >
          <Icons.close />
        </AttachmentAction>
      </AttachmentActions>
    </Attachment>
  );
}

interface MessageAttachmentProps {
  part: FileUIPart;
}

export function MessageAttachment({ part }: MessageAttachmentProps) {
  const safe = isSafeFilePart(part);
  const image = safe && part.mediaType.startsWith('image/');
  return (
    <Attachment
      state={safe ? 'done' : 'error'}
      className='max-w-72'
      data-testid='message-attachment'
    >
      <AttachmentMedia variant={image ? 'image' : 'icon'}>
        {image ? (
          <AttachmentThumbnail key={part.url} src={part.url} alt={part.filename ?? '图片附件'} />
        ) : (
          <Icons.page />
        )}
      </AttachmentMedia>
      <AttachmentContent>
        <AttachmentTitle>{part.filename ?? '附件'}</AttachmentTitle>
        <AttachmentDescription>
          {safe ? (image ? '图片 · 点击查看' : '附件 · 点击下载') : '附件地址无效，请重新上传'}
        </AttachmentDescription>
      </AttachmentContent>
      {safe && (
        <AttachmentTrigger
          render={
            <a
              href={part.url}
              target='_blank'
              rel='noopener noreferrer'
              aria-label={`查看附件 ${part.filename ?? ''}`}
            />
          }
          aria-label={`查看附件 ${part.filename ?? ''}`}
        />
      )}
    </Attachment>
  );
}
