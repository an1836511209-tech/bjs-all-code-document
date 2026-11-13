"""
文件预览代理接口

提供 MinIO 文件的代理访问，解决内网 IP 外网无法访问的问题。
前端通过相对路径访问，后端代理从 MinIO 获取文件并返回。
"""

import io
from fastapi import APIRouter, HTTPException, Path
from fastapi.responses import StreamingResponse
from loguru import logger


router = APIRouter(prefix="/preview", tags=["文件预览"])


@router.get(
    "/files/{file_path:path}",
    summary="代理访问 MinIO 文件",
    description="""
    代理访问存储在 MinIO 中的文件。
    
    **使用场景：**
    - PDF 高亮预览图片
    - 其他需要通过代理访问的 MinIO 文件
    
    **路径格式：**
    - /api/v1/preview/files/highlights/batch_xxx.jpg
    """
)
async def proxy_file(file_path: str = Path(..., description="MinIO 中的文件对象路径")):
    """
    代理访问 MinIO 中的文件
    
    Args:
        file_path: MinIO 中的对象路径（如 highlights/batch_xxx.jpg）
        
    Returns:
        StreamingResponse: 文件流响应
    """
    from src.utils.minio.client import get_minio_client, MinIOClientError
    
    try:
        minio_client = get_minio_client()
        file_bytes = minio_client.download_bytes(file_path)
        
        # 根据扩展名确定 content-type
        content_type = _get_content_type(file_path)
        
        logger.debug(f"代理文件访问: {file_path}, 大小: {len(file_bytes)} bytes")
        
        return StreamingResponse(
            io.BytesIO(file_bytes),
            media_type=content_type,
            headers={
                "Cache-Control": "public, max-age=86400",  # 缓存 1 天
                "Content-Disposition": f"inline; filename={file_path.split('/')[-1]}"
            }
        )
        
    except MinIOClientError as e:
        logger.warning(f"MinIO 文件不存在: {file_path}, 错误: {e}")
        raise HTTPException(status_code=404, detail="文件不存在")
    except Exception as e:
        logger.error(f"代理文件访问失败: {file_path}, 错误: {e}")
        raise HTTPException(status_code=500, detail="文件访问失败")


def _get_content_type(file_path: str) -> str:
    """
    根据文件扩展名获取 Content-Type
    
    Args:
        file_path: 文件路径
        
    Returns:
        str: Content-Type
    """
    ext = file_path.lower().split('.')[-1] if '.' in file_path else ''
    
    content_types = {
        'jpg': 'image/jpeg',
        'jpeg': 'image/jpeg',
        'png': 'image/png',
        'gif': 'image/gif',
        'bmp': 'image/bmp',
        'webp': 'image/webp',
        'pdf': 'application/pdf',
        'json': 'application/json',
        'txt': 'text/plain',
    }
    
    return content_types.get(ext, 'application/octet-stream')



