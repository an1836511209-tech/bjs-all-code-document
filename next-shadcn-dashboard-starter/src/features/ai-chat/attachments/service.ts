import { attachmentSchema, type UploadedAttachment } from './types';

export async function uploadAttachment(
  file: File,
  signal: AbortSignal
): Promise<UploadedAttachment> {
  const body = new FormData();
  body.append('file', file);
  const response = await fetch('/api/ai-chat/attachments', { method: 'POST', body, signal });
  if (!response.ok) throw new Error('上传失败，请检查文件格式和网络后重试。');
  const result: unknown = await response.json();
  if (!result || typeof result !== 'object' || !('attachment' in result))
    throw new Error('上传服务返回格式无效，请联系维护者。');
  return attachmentSchema.parse(result.attachment);
}
