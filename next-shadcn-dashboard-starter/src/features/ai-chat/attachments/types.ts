import { z } from 'zod';
import type { FileUIPart } from 'ai';

export const MAX_ATTACHMENTS = 5;
export const MAX_FILE_BYTES = 10 * 1024 * 1024;
export const MAX_TOTAL_BYTES = 20 * 1024 * 1024;
export const ATTACHMENT_TTL_MS = 24 * 60 * 60 * 1000;
export const FILE_TYPES = {
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  webp: 'image/webp',
  gif: 'image/gif',
  pdf: 'application/pdf',
  txt: 'text/plain',
  md: 'text/markdown',
  csv: 'text/csv',
  json: 'application/json',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
  xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
  pptx: 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
} as const;
export const ATTACHMENT_ACCEPT = Object.keys(FILE_TYPES)
  .map((ext) => `.${ext}`)
  .join(',');
export const attachmentIdSchema = z.uuid();
export const attachmentUrlSchema = z
  .string()
  .regex(/^\/api\/ai-chat\/attachments\/[0-9a-f-]{36}$/)
  .refine((url) => attachmentIdSchema.safeParse(url.split('/').at(-1)).success);
export const attachmentSchema = z
  .object({
    id: attachmentIdSchema,
    filename: z.string().min(1).max(200),
    mediaType: z.enum(Object.values(FILE_TYPES)),
    size: z.number().int().positive().max(MAX_FILE_BYTES),
    url: attachmentUrlSchema,
    expiresAt: z.iso.datetime()
  })
  .refine((file) => file.url === `/api/ai-chat/attachments/${file.id}`);
export type UploadedAttachment = z.infer<typeof attachmentSchema>;

export function fileMediaType(name: string): string | undefined {
  const extension = name.split('.').at(-1)?.toLowerCase() ?? '';
  return Object.hasOwn(FILE_TYPES, extension)
    ? FILE_TYPES[extension as keyof typeof FILE_TYPES]
    : undefined;
}

/** Both picker hints and the server use this policy; content is checked separately on the server. */
export function validateAttachment(file: {
  name: string;
  size: number;
  type: string;
}): string | null {
  const mediaType = fileMediaType(file.name);
  const declaredType = file.type.split(';')[0].trim().toLowerCase();
  if (!mediaType) return '不支持此文件类型，请选择图片、PDF、Office、文本或数据文件。';
  if (!file.size) return '不能上传空文件。';
  if (file.size > MAX_FILE_BYTES) return '单个文件不能超过 10 MB。';
  if (
    declaredType &&
    declaredType !== 'application/octet-stream' &&
    declaredType !== mediaType &&
    !(declaredType === 'text/plain' && mediaType.startsWith('text/'))
  )
    return '文件类型与扩展名不匹配。';
  return null;
}

export function toFilePart(file: UploadedAttachment): FileUIPart {
  return { type: 'file', url: file.url, filename: file.filename, mediaType: file.mediaType };
}

/** Reject executable/external/data/blob URLs even when restoring browser history. */
export function isSafeFilePart(part: { url: string; mediaType: string }): boolean {
  return (
    attachmentUrlSchema.safeParse(part.url).success &&
    Object.values(FILE_TYPES).some((type) => type === part.mediaType)
  );
}
