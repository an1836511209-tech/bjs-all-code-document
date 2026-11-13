from __future__ import annotations

from urllib.parse import urlparse

from data_mcp.shared.http.retry_client import http_request

DEFAULT_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_TIMEOUT_SECONDS = 60.0


def download_markdown_from_url(
    url: str,
    *,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> str:
    """从 MinIO / 文件存储 URL 下载材料，解码为 markdown 文本。"""
    raw_url = str(url or "").strip()
    if not raw_url:
        raise ValueError("material_url 不能为空")

    parsed = urlparse(raw_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("material_url 仅支持 http/https")

    try:
        response = http_request(
            "GET",
            raw_url,
            timeout=timeout_seconds,
            service_name="material_url_download",
            max_retries=0,
            follow_redirects=True,
        )
    except Exception as exc:
        raise RuntimeError(f"材料 URL 下载失败: {exc}") from exc

    content = response.content
    if len(content) > max_bytes:
        raise RuntimeError(
            f"材料文件过大: {len(content)} bytes，上限 {max_bytes} bytes"
        )

    for encoding in ("utf-8", "utf-8-sig", "gb18030"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            text = ""
    else:
        raise RuntimeError("材料内容无法按文本解码（期望 UTF-8 / GB18030 的 markdown）")

    text = text.strip()
    if not text:
        raise RuntimeError("材料 URL 下载结果为空")
    return text
