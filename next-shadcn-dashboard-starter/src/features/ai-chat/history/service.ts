import { attachmentSchema, isSafeFilePart, MAX_ATTACHMENTS } from '../attachments/types';
import { safeValidateUIMessages } from 'ai';
import { z } from 'zod';
import { parseArtifact } from '../artifacts/schemas';
import type { DemoUIMessage } from '../chat';
import type { ConversationHistory } from './types';
import { MAX_CONVERSATIONS, MAX_TITLE_LENGTH } from './state';

export const HISTORY_STORAGE_KEY = 'ai-chat:history:v1';
export const MAX_HISTORY_BYTES = 4_000_000;

export class HistoryStorageError extends Error {
  constructor(
    public readonly code: 'invalid' | 'unavailable' | 'quota' | 'limit',
    options?: ErrorOptions
  ) {
    super(`History storage: ${code}`, options);
    this.name = 'HistoryStorageError';
  }
}

export function classifyStorageError(error: unknown): HistoryStorageError {
  if (error instanceof HistoryStorageError) return error;
  return new HistoryStorageError(
    error instanceof DOMException && error.name === 'QuotaExceededError' ? 'quota' : 'unavailable',
    { cause: error }
  );
}

const historySchema = z.object({
  schemaVersion: z.literal(1),
  activeId: z.string().min(1),
  conversations: z
    .array(
      z.object({
        id: z.string().min(1),
        title: z.string().trim().min(1).max(MAX_TITLE_LENGTH),
        titleSource: z.enum(['automatic', 'manual']),
        createdAt: z.iso.datetime(),
        updatedAt: z.iso.datetime(),
        draft: z.string().max(100_000),
        draftAttachments: z.array(attachmentSchema).max(MAX_ATTACHMENTS).optional(),
        scenario: z.enum(['document', 'spreadsheet', 'presentation', 'dashboard', 'long']),
        messages: z.array(z.unknown()).max(200),
        artifacts: z.record(z.string(), z.unknown())
      })
    )
    .min(1)
    .max(MAX_CONVERSATIONS)
});

/** Validate browser data before mounting useChat. Preserve complete SDK parts. */
export async function decodeHistory(raw: string): Promise<ConversationHistory> {
  if (new Blob([raw]).size > MAX_HISTORY_BYTES) throw new Error('历史记录超过本地存储大小限制。');
  const history = historySchema.parse(JSON.parse(raw));
  const ids = history.conversations.map((item) => item.id);
  if (new Set(ids).size !== ids.length || !ids.includes(history.activeId)) {
    throw new Error('历史会话标识无效。');
  }
  const conversations = await Promise.all(
    history.conversations.map(async (item) => {
      // The SDK requires messages; a new or draft-only conversation is valid history.
      const result =
        item.messages.length === 0
          ? { success: true as const, data: [] as DemoUIMessage[] }
          : await safeValidateUIMessages<DemoUIMessage>({ messages: item.messages });
      if (
        !result.success ||
        new Set(result.data.map((message) => message.id)).size !== result.data.length
      ) {
        throw new Error('历史消息格式无效。');
      }
      if (
        result.data.some((message) =>
          message.parts.some((part) => part.type === 'file' && !isSafeFilePart(part))
        )
      )
        throw new Error('历史附件格式无效。');
      const artifacts = Object.fromEntries(
        Object.entries(item.artifacts).map(([id, value]) => {
          const artifact = parseArtifact(value);
          if (!artifact || artifact.id !== id) throw new Error('历史成果格式无效。');
          return [id, artifact];
        })
      );
      return { ...item, messages: result.data, artifacts };
    })
  );
  return { ...history, conversations };
}

/** Browser-only demo adapter. Production integrations replace this with an authenticated repository. */
export async function loadHistory(): Promise<ConversationHistory | null> {
  let raw: string | null;
  try {
    raw = localStorage.getItem(HISTORY_STORAGE_KEY);
  } catch (error) {
    throw classifyStorageError(error);
  }
  if (raw === null) return null;
  try {
    return await decodeHistory(raw);
  } catch (cause) {
    throw new HistoryStorageError('invalid', { cause });
  }
}

export function saveHistory(history: ConversationHistory): void {
  const raw = JSON.stringify(history);
  if (new Blob([raw]).size > MAX_HISTORY_BYTES) throw new HistoryStorageError('limit');
  try {
    localStorage.setItem(HISTORY_STORAGE_KEY, raw);
  } catch (error) {
    throw classifyStorageError(error);
  }
}
