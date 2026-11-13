import { AttachmentRequestError, readLimitedBody } from '@/features/ai-chat/attachments/body';
import { storeAttachment } from '@/features/ai-chat/attachments/store';
import { MAX_FILE_BYTES } from '@/features/ai-chat/attachments/types';

export const runtime = 'nodejs';

export async function POST(request: Request): Promise<Response> {
  try {
    const contentType = request.headers.get('content-type') ?? '';
    if (!contentType.startsWith('multipart/form-data;'))
      throw new AttachmentRequestError(400, 'INVALID_REQUEST', '请选择要上传的文件。');
    const bytes = await readLimitedBody(request, MAX_FILE_BYTES + 64 * 1024);
    const form = await new Response(bytes, { headers: { 'content-type': contentType } })
      .formData()
      .catch(() => null);
    const entries = form ? [...form.entries()] : [];
    if (entries.length !== 1 || entries[0][0] !== 'file' || !(entries[0][1] instanceof File)) {
      throw new AttachmentRequestError(400, 'INVALID_REQUEST', '每次请求需要一个 file 文件字段。');
    }
    return Response.json(
      { attachment: await storeAttachment(entries[0][1]) },
      { status: 201, headers: { 'Cache-Control': 'no-store' } }
    );
  } catch (error) {
    const known = error instanceof AttachmentRequestError;
    return Response.json(
      {
        code: known ? error.code : 'UPLOAD_FAILED',
        error: known ? error.message : '文件上传失败，请稍后重试。'
      },
      { status: known ? error.status : 500 }
    );
  }
}
