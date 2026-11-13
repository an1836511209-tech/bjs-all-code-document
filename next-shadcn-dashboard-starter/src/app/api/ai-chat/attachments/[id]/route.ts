import { readAttachment } from '@/features/ai-chat/attachments/store';

export const runtime = 'nodejs';

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ id: string }> }
): Promise<Response> {
  try {
    const result = await readAttachment((await params).id);
    if (!result)
      return Response.json(
        { code: 'FILE_UNAVAILABLE', error: '附件已过期或不可用，请重新上传。' },
        { status: 404 }
      );
    const { attachment, bytes } = result;
    return new Response(new Uint8Array(bytes), {
      headers: {
        'Content-Type': attachment.mediaType,
        'Content-Length': String(bytes.length),
        'Content-Disposition': `${attachment.mediaType.startsWith('image/') ? 'inline' : 'attachment'}; filename*=UTF-8''${encodeURIComponent(attachment.filename)}`,
        'Cache-Control': 'private, no-store',
        'X-Content-Type-Options': 'nosniff',
        'Content-Security-Policy': "default-src 'none'; sandbox"
      }
    });
  } catch {
    return Response.json(
      { code: 'FILE_UNAVAILABLE', error: '暂时无法读取附件，请稍后重试。' },
      { status: 500 }
    );
  }
}
