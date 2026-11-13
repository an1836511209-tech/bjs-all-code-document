'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { uploadAttachment } from './service';
import {
  MAX_ATTACHMENTS,
  MAX_TOTAL_BYTES,
  validateAttachment,
  type UploadedAttachment
} from './types';

export interface DraftAttachment {
  key: string;
  filename: string;
  mediaType: string;
  size: number;
  file?: File;
  preview?: string;
  uploaded?: UploadedAttachment;
  state: 'uploading' | 'error' | 'done';
}

export interface AttachmentController {
  items: DraftAttachment[];
  ready: UploadedAttachment[];
  error: string | null;
  uploading: boolean;
  blocked: boolean;
  dismissError: () => void;
  add: (files: File[]) => void;
  remove: (key: string) => void;
  retry: (key: string) => void;
  clear: () => void;
}

export function useAttachments(initial: UploadedAttachment[] = []): AttachmentController {
  const [items, setItems] = useState<DraftAttachment[]>(() =>
    initial.map((uploaded) => ({
      key: uploaded.id,
      filename: uploaded.filename,
      mediaType: uploaded.mediaType,
      size: uploaded.size,
      uploaded,
      state: 'done'
    }))
  );
  const itemsRef = useRef(items);
  const controllers = useRef(new Map<string, AbortController>());
  const previews = useRef(new Set<string>());
  const [error, setError] = useState<string | null>(null);
  function update(next: DraftAttachment[]) {
    itemsRef.current = next;
    setItems(next);
  }

  useEffect(() => {
    const pending = controllers.current;
    const urls = previews.current;
    return () => {
      for (const controller of pending.values()) controller.abort();
      pending.clear();
      for (const url of urls) URL.revokeObjectURL(url);
      urls.clear();
    };
  }, []);

  async function upload(item: DraftAttachment) {
    if (!item.file) return;
    const controller = new AbortController();
    controllers.current.set(item.key, controller);
    try {
      const uploaded = await uploadAttachment(item.file, controller.signal);
      if (!controller.signal.aborted)
        update(
          itemsRef.current.map((entry) =>
            entry.key === item.key ? { ...entry, uploaded, state: 'done' } : entry
          )
        );
    } catch {
      if (!controller.signal.aborted) {
        update(
          itemsRef.current.map((entry) =>
            entry.key === item.key ? { ...entry, state: 'error' } : entry
          )
        );
        setError('附件上传失败。请检查网络与文件内容，重试或移除失败附件后发送。');
      }
    } finally {
      if (controllers.current.get(item.key) === controller) controllers.current.delete(item.key);
    }
  }

  function add(files: File[]) {
    setError(null);
    const next = [...itemsRef.current];
    const additions: DraftAttachment[] = [];
    for (const file of files) {
      const invalid = validateAttachment(file);
      if (invalid) {
        setError(`${file.name}：${invalid}`);
        continue;
      }
      if (
        next.some(
          (entry) =>
            entry.filename === file.name &&
            entry.size === file.size &&
            entry.file?.lastModified === file.lastModified
        )
      )
        continue;
      if (next.length >= MAX_ATTACHMENTS) {
        setError('每条消息最多添加 5 个附件。');
        break;
      }
      if (next.reduce((sum, entry) => sum + entry.size, file.size) > MAX_TOTAL_BYTES) {
        setError('每条消息附件总大小不能超过 20 MB。');
        continue;
      }
      const preview = file.type.startsWith('image/') ? URL.createObjectURL(file) : undefined;
      if (preview) previews.current.add(preview);
      const item: DraftAttachment = {
        key: crypto.randomUUID(),
        filename: file.name,
        mediaType: file.type,
        size: file.size,
        file,
        preview,
        state: 'uploading'
      };
      next.push(item);
      additions.push(item);
    }
    update(next);
    for (const item of additions) void upload(item);
  }

  function remove(key: string) {
    controllers.current.get(key)?.abort();
    controllers.current.delete(key);
    const item = itemsRef.current.find((entry) => entry.key === key);
    if (item?.preview) {
      URL.revokeObjectURL(item.preview);
      previews.current.delete(item.preview);
    }
    update(itemsRef.current.filter((entry) => entry.key !== key));
  }

  const ready = useMemo(
    () => items.flatMap((item) => (item.uploaded ? [item.uploaded] : [])),
    [items]
  );
  return {
    items,
    ready,
    error,
    dismissError: () => setError(null),
    add,
    remove,
    uploading: items.some((item) => item.state === 'uploading'),
    blocked: items.some((item) => item.state !== 'done'),
    retry: (key: string) => {
      const item = itemsRef.current.find((entry) => entry.key === key);
      if (!item || item.state !== 'error') return;
      setError(null);
      update(
        itemsRef.current.map((entry) =>
          entry.key === key ? { ...entry, state: 'uploading' } : entry
        )
      );
      void upload(item);
    },
    clear: () => {
      for (const item of itemsRef.current) remove(item.key);
      setError(null);
    }
  };
}
