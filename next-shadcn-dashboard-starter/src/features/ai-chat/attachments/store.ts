import { createHash } from 'node:crypto';
import { mkdir, readFile, readdir, stat, unlink, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import sharp from 'sharp';
import { AttachmentRequestError } from './body';
import {
  attachmentIdSchema,
  attachmentSchema,
  ATTACHMENT_TTL_MS,
  fileMediaType,
  validateAttachment,
  type UploadedAttachment
} from './types';

// Demo-only Node filesystem adapter. No secrets or browser-controlled paths.
const root = join(
  tmpdir(),
  'shadcn-ai-chat',
  createHash('sha256').update(process.cwd()).digest('hex').slice(0, 16)
);

/** Opportunistic demo cleanup; real storage needs a scheduled retention policy. */
async function pruneExpiredAttachments(): Promise<void> {
  const cutoff = Date.now() - ATTACHMENT_TTL_MS;
  for (const name of await readdir(root)) {
    const id = name.replace(/\.(bin|json)$/, '');
    if (!attachmentIdSchema.safeParse(id).success || !/\.(bin|json)$/.test(name)) continue;
    const path = join(root, name);
    try {
      if ((await stat(path)).mtimeMs < cutoff) await unlink(path);
    } catch (error) {
      if (!(error instanceof Error && 'code' in error && error.code === 'ENOENT')) throw error;
    }
  }
}

export async function storeAttachment(file: File): Promise<UploadedAttachment> {
  const error = validateAttachment(file);
  if (error) throw new AttachmentRequestError(415, 'INVALID_FILE', error);
  const bytes = Buffer.from(await file.arrayBuffer());
  const mediaType = fileMediaType(file.name)!;
  if (mediaType.startsWith('image/')) {
    const metadata = await sharp(bytes, { limitInputPixels: 40_000_000 })
      .metadata()
      .catch(() => null);
    const format = mediaType === 'image/jpeg' ? 'jpeg' : mediaType.slice(6);
    if (
      !metadata ||
      metadata.format !== format ||
      !metadata.width ||
      !metadata.height ||
      metadata.width * metadata.height * (metadata.pages ?? 1) > 40_000_000
    )
      throw new AttachmentRequestError(415, 'INVALID_FILE', '图片内容无效或尺寸过大。');
  } else if (mediaType === 'application/pdf') {
    if (bytes.subarray(0, 5).toString() !== '%PDF-')
      throw new AttachmentRequestError(415, 'INVALID_FILE', 'PDF 文件内容无效。');
  } else if (mediaType.includes('officedocument')) {
    if (bytes.length < 4 || bytes.readUInt32LE(0) !== 0x04034b50)
      throw new AttachmentRequestError(415, 'INVALID_FILE', 'Office 文件内容无效。');
  } else {
    let text: string;
    try {
      text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    } catch {
      throw new AttachmentRequestError(415, 'INVALID_FILE', '文本文件必须使用 UTF-8 编码。');
    }
    if (text.includes('\0'))
      throw new AttachmentRequestError(415, 'INVALID_FILE', '文本文件包含无效内容。');
    if (mediaType === 'application/json') {
      try {
        JSON.parse(text);
      } catch {
        throw new AttachmentRequestError(415, 'INVALID_FILE', 'JSON 文件格式无效。');
      }
    }
  }
  const id = crypto.randomUUID();
  const attachment: UploadedAttachment = {
    id,
    filename: Array.from(file.name, (char) =>
      char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127 || '/\\'.includes(char) ? '_' : char
    )
      .join('')
      .slice(0, 200),
    mediaType: mediaType as UploadedAttachment['mediaType'],
    size: bytes.length,
    url: `/api/ai-chat/attachments/${id}`,
    expiresAt: new Date(Date.now() + ATTACHMENT_TTL_MS).toISOString()
  };
  await mkdir(root, { recursive: true });
  await pruneExpiredAttachments();
  try {
    await writeFile(join(root, `${id}.bin`), bytes, { flag: 'wx' });
    await writeFile(join(root, `${id}.json`), JSON.stringify(attachment), { flag: 'wx' });
  } catch (error) {
    await Promise.allSettled([unlink(join(root, `${id}.bin`)), unlink(join(root, `${id}.json`))]);
    throw error;
  }
  return attachment;
}

export async function resolveAttachment(id: string): Promise<UploadedAttachment | null> {
  if (!attachmentIdSchema.safeParse(id).success) return null;
  try {
    const file = attachmentSchema.parse(
      JSON.parse(await readFile(join(root, `${id}.json`), 'utf8'))
    );
    return file.id === id && Date.parse(file.expiresAt) > Date.now() ? file : null;
  } catch (error) {
    if (error instanceof Error && 'code' in error && error.code !== 'ENOENT') throw error;
    return null;
  }
}

export async function readAttachment(
  id: string
): Promise<{ attachment: UploadedAttachment; bytes: Buffer } | null> {
  const attachment = await resolveAttachment(id);
  if (!attachment) return null;
  try {
    return { attachment, bytes: await readFile(join(root, `${id}.bin`)) };
  } catch (error) {
    if (error instanceof Error && 'code' in error && error.code === 'ENOENT') return null;
    throw error;
  }
}
