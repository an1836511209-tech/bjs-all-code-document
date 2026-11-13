import { AttachmentRequestError, readLimitedBody } from '@/features/ai-chat/attachments/body';
import {
  isSafeFilePart,
  MAX_ATTACHMENTS,
  MAX_TOTAL_BYTES
} from '@/features/ai-chat/attachments/types';
import { readAttachment } from '@/features/ai-chat/attachments/store';
import {
  createUIMessageStream,
  createUIMessageStreamResponse,
  type UIMessageStreamWriter
} from 'ai';
import { z } from 'zod';
import type { DemoUIMessage } from '@/features/ai-chat/chat';
import {
  createDemoArtifact,
  demoAnswerIntro,
  demoLongAnswer,
  demoReasoning,
  getShortDemoAnswer,
  revenueMetrics
} from '@/features/ai-chat/artifacts/demo-data';
import type { DemoScenarioId } from '@/features/ai-chat/artifacts/types';

export const maxDuration = 60;

const requestSchema = z.object({
  scenario: z.enum(['document', 'spreadsheet', 'presentation', 'dashboard', 'long']).optional(),
  messages: z
    .array(
      z.object({
        role: z.enum(['user', 'assistant', 'system']),
        parts: z.array(z.object({ type: z.string().min(1) }).passthrough()).max(1_000)
      })
    )
    .min(1)
    .max(200)
});

/** Abort-aware delay stops demo generation when useChat.stop() cancels its request. */
async function pause(ms: number, signal: AbortSignal): Promise<void> {
  signal.throwIfAborted();
  await new Promise<void>((resolve, reject) => {
    const onAbort = () => {
      clearTimeout(timer);
      reject(signal.reason ?? new DOMException('Aborted', 'AbortError'));
    };
    const timer = setTimeout(() => {
      signal.removeEventListener('abort', onAbort);
      resolve();
    }, ms);
    signal.addEventListener('abort', onAbort, { once: true });
  });
}

async function streamTextPart(
  writer: UIMessageStreamWriter<DemoUIMessage>,
  signal: AbortSignal,
  kind: 'text' | 'reasoning',
  id: string,
  value: string,
  durationMs: number
): Promise<void> {
  writer.write({ type: `${kind}-start`, id });
  const chunks = value.match(/[\s\S]{1,16}/g) ?? [];
  for (const delta of chunks) {
    await pause(durationMs / Math.max(chunks.length, 1), signal);
    writer.write({ type: `${kind}-delta`, id, delta });
  }
  writer.write({ type: `${kind}-end`, id });
}

export async function POST(request: Request): Promise<Response> {
  let raw: unknown;
  try {
    raw = JSON.parse(new TextDecoder().decode(await readLimitedBody(request, 4_000_000)));
  } catch (error) {
    return Response.json(
      { error: '请求格式无效或超过大小限制。' },
      { status: error instanceof AttachmentRequestError ? error.status : 400 }
    );
  }
  const parsed = requestSchema.safeParse(raw);
  if (!parsed.success) {
    return Response.json({ error: '请求格式无效，请重新开始对话。' }, { status: 400 });
  }
  // All historical file parts must be safe references; only the new turn requires live bytes.
  const fileSchema = z.object({
    type: z.literal('file'),
    url: z.string(),
    filename: z.string().max(200),
    mediaType: z.string()
  });
  for (const message of parsed.data.messages) {
    const files = message.parts.filter((part) => part.type === 'file');
    if (
      files.length > MAX_ATTACHMENTS ||
      files.some((part) => {
        const file = fileSchema.safeParse(part);
        return !file.success || !isSafeFilePart(file.data);
      })
    ) {
      return Response.json(
        { code: 'INVALID_FILE', error: '附件引用无效，请重新上传。' },
        { status: 400 }
      );
    }
  }
  const latest = parsed.data.messages.at(-1)!;
  const files = latest.parts
    .filter((part) => part.type === 'file')
    .map((part) => fileSchema.parse(part));
  try {
    const resolved = await Promise.all(
      files.map((part) => readAttachment(part.url.split('/').at(-1)!))
    );
    if (
      resolved.some(
        (file, index) =>
          !file ||
          file.attachment.filename !== files[index].filename ||
          file.attachment.mediaType !== files[index].mediaType
      )
    ) {
      return Response.json(
        { code: 'FILE_UNAVAILABLE', error: '附件已过期或不可用，请移除后重新上传。' },
        { status: 400 }
      );
    }
    if (resolved.reduce((sum, file) => sum + (file?.attachment.size ?? 0), 0) > MAX_TOTAL_BYTES)
      return Response.json({ code: 'TOO_LARGE', error: '附件总大小超过 20 MB。' }, { status: 413 });
  } catch {
    return Response.json(
      { code: 'FILE_UNAVAILABLE', error: '暂时无法读取附件，请稍后重试。' },
      { status: 503 }
    );
  }
  // Scenario is explicit. Natural-language text never opens an artifact.
  const scenario: DemoScenarioId = parsed.data.scenario ?? 'long';
  const longTurn = scenario === 'document' || scenario === 'long';
  const turnId = crypto.randomUUID();
  const artifactId = `artifact-${turnId}`;
  const stream = createUIMessageStream<DemoUIMessage>({
    execute: async ({ writer }) => {
      const signal = request.signal;
      writer.write({ type: 'start', messageId: `assistant-${turnId}` });
      writer.write({ type: 'start-step' });
      if (files.length) {
        writer.write({ type: 'text-start', id: `attachments-${turnId}` });
        writer.write({
          type: 'text-delta',
          id: `attachments-${turnId}`,
          delta: `已收到 ${files.length} 个附件。本模板仅演示上传与消息传输，尚未读取附件内容或调用真实模型。\n\n`
        });
        writer.write({ type: 'text-end', id: `attachments-${turnId}` });
      }
      try {
        await streamTextPart(
          writer,
          signal,
          'reasoning',
          `reasoning-${turnId}`,
          longTurn ? demoReasoning : demoReasoning.split('\n\n').slice(0, 3).join('\n\n'),
          longTurn ? 11_000 : 3_000
        );
        const revenueCallId = `revenue-${turnId}`;
        writer.write({
          type: 'tool-input-available',
          toolCallId: revenueCallId,
          toolName: 'getRevenue',
          input: { period: '2026-09', currency: 'CNY', groupBy: 'week' }
        });
        await pause(700, signal);
        writer.write({
          type: 'tool-output-available',
          toolCallId: revenueCallId,
          output: revenueMetrics
        });
        await streamTextPart(
          writer,
          signal,
          'text',
          `intro-${turnId}`,
          demoAnswerIntro,
          longTurn ? 2_500 : 1_800
        );

        if (scenario !== 'long') {
          const artifactCallId = `create-${turnId}`;
          writer.write({
            type: 'tool-input-available',
            toolCallId: artifactCallId,
            toolName: 'createArtifact',
            input: {
              kind: scenario === 'dashboard' ? 'custom' : scenario,
              source: 'revenue-2026-09',
              format: 'structured-preview'
            }
          });
          writer.write({
            type: 'data-artifact',
            id: artifactId,
            data: createDemoArtifact(scenario, artifactId, 'generating')
          });
          await pause(900, signal);
          writer.write({
            type: 'tool-output-available',
            toolCallId: artifactCallId,
            output: { artifactId, status: 'ready', previewOnly: true }
          });
          writer.write({
            type: 'data-artifact',
            id: artifactId,
            data: createDemoArtifact(scenario, artifactId, 'ready')
          });
        }

        await streamTextPart(
          writer,
          signal,
          'text',
          `answer-${turnId}`,
          longTurn ? demoLongAnswer : getShortDemoAnswer(scenario),
          longTurn ? 23_000 : 5_000
        );
        writer.write({ type: 'finish-step' });
        writer.write({ type: 'finish', finishReason: 'stop' });
      } catch (error) {
        if (!signal.aborted) throw error;
        // Production background jobs need an independent cancellation contract.
        writer.write({ type: 'abort' });
      }
    },
    onError: () => '演示响应中断，请重试或重新开始。'
  });
  return createUIMessageStreamResponse({
    stream,
    headers: { 'Cache-Control': 'no-cache, no-transform' }
  });
}
