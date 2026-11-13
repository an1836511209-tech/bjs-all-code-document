# MinIO PDF高亮功能使用示例

本文档提供MinIO集成的PDF高亮功能的使用示例。

## 快速开始

### 1. 安装依赖

```bash
# 安装MinIO Python客户端
poetry add minio

# 或使用pip
pip install minio
```

### 2. 配置环境变量

创建 `.env` 文件：

```env
# MinIO配置
MINIO_ENDPOINT=115.190.11.152:9000
MINIO_ACCESS_KEY=j00MvwsnLsZyuEogxPRb
MINIO_SECRET_KEY=TzMr41qepvJZGpmOVdZtFX3WeY6yKlG2U6g3wrmY
MINIO_SECURE=false
MINIO_BUCKET=pdf-highlights
MINIO_FILE_PREFIX=highlights
MINIO_PUBLIC_URL=http://115.190.11.152:9000

# 自动清理配置（可选，默认7天）
MINIO_AUTO_CLEANUP_DAYS=7
```

### 3. 启动应用

应用启动时会自动：
- 连接MinIO服务器
- 创建所需的bucket
- 设置7天自动清理策略

```bash
python -m uvicorn src.main:app --reload
```

查看启动日志确认MinIO已初始化：

```
🚀 北交所录入助审系统启动中...
正在初始化MinIO配置...
✓ MinIO连接成功，使用bucket: pdf-highlights
✓ 生命周期策略已设置: highlights/* 将在 7 天后自动删除
✓ MinIO初始化完成
📋 已加载功能模块：
  - PDF高亮标注 ✅
  - MinIO对象存储 ✅
```

## 基本使用

### 示例1：高亮PDF单个区域

```python
from src.utils.pdf_highlighter import highlight_pdf_page

# 高亮PDF页面的某个区域
url = highlight_pdf_page(
    pdf_path="document.pdf",
    page_num=0,  # 第一页
    regions=[[100, 100, 300, 200]]  # 单个矩形区域
)

print(f"高亮图片URL: {url}")
# 输出: http://115.190.11.152:9000/pdf-highlights/highlights/20241107_143025_a1b2c3d4.png
```

### 示例2：高亮多个区域

```python
from src.utils.pdf_highlighter import highlight_pdf_page

# 高亮多个区域
url = highlight_pdf_page(
    pdf_path="document.pdf",
    page_num=1,
    regions=[
        [100, 100, 300, 200],  # 第一个区域
        [150, 250, 350, 350],  # 第二个区域
        [200, 400, 400, 500]   # 第三个区域
    ]
)

print(f"高亮图片URL: {url}")
```

### 示例3：使用字典格式的坐标

```python
from src.utils.pdf_highlighter import highlight_pdf_page

# 使用字典格式（x0, y0, x1, y1）
url = highlight_pdf_page(
    pdf_path="document.pdf",
    page_num=0,
    regions=[
        {'x0': 100, 'y0': 100, 'x1': 300, 'y1': 200}
    ]
)

# 或使用其他字典格式（left, top, right, bottom）
url = highlight_pdf_page(
    pdf_path="document.pdf",
    page_num=0,
    regions=[
        {'left': 100, 'top': 100, 'right': 300, 'bottom': 200}
    ]
)

# 或使用MinerU格式（x, y, width, height）
url = highlight_pdf_page(
    pdf_path="document.pdf",
    page_num=0,
    regions=[
        {'x': 100, 'y': 100, 'width': 200, 'height': 100}
    ]
)
```

### 示例4：自定义高亮样式

```python
from src.utils.pdf_highlighter import highlight_pdf_page

# 自定义高亮颜色、透明度等
url = highlight_pdf_page(
    pdf_path="document.pdf",
    page_num=0,
    regions=[[100, 100, 300, 200]],
    dpi=300,  # 提高清晰度
    highlight_color=(255, 0, 0),  # 蓝色高亮（BGR格式）
    border_color=(0, 255, 0),     # 绿色边框
    alpha=0.5,                     # 50%透明度
    border_width=3,                # 3像素边框
    output_format='PNG'            # PNG格式
)
```

### 示例5：处理字节流PDF

```python
from src.utils.pdf_highlighter import highlight_pdf_page

# 从字节流处理PDF
with open("document.pdf", "rb") as f:
    pdf_bytes = f.read()

url = highlight_pdf_page(
    pdf_path=pdf_bytes,  # 直接传入字节流
    page_num=0,
    regions=[[100, 100, 300, 200]]
)
```

## FastAPI集成示例

### 创建API端点

```python
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel
from typing import List
from src.utils.pdf_highlighter import highlight_pdf_page

router = APIRouter(prefix="/api/v1/pdf", tags=["PDF处理"])

class BBox(BaseModel):
    x0: float
    y0: float
    x1: float
    y1: float

class HighlightRequest(BaseModel):
    page_num: int
    regions: List[BBox]
    dpi: int = 200
    alpha: float = 0.3

class HighlightResponse(BaseModel):
    success: bool
    url: str
    message: str = "PDF高亮成功"

@router.post("/highlight", response_model=HighlightResponse)
async def highlight_pdf(
    file: UploadFile = File(...),
    request: HighlightRequest
):
    """
    上传PDF并高亮指定区域
    """
    try:
        # 读取PDF文件
        pdf_bytes = await file.read()
        
        # 转换regions为列表格式
        regions = [
            [bbox.x0, bbox.y0, bbox.x1, bbox.y1]
            for bbox in request.regions
        ]
        
        # 高亮PDF
        url = highlight_pdf_page(
            pdf_path=pdf_bytes,
            page_num=request.page_num,
            regions=regions,
            dpi=request.dpi,
            alpha=request.alpha
        )
        
        return HighlightResponse(
            success=True,
            url=url
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"PDF高亮失败: {str(e)}"
        )
```

### 调用API示例

```bash
# 使用curl调用API
curl -X POST "http://localhost:8000/api/v1/pdf/highlight" \
  -F "file=@document.pdf" \
  -F "request={
    \"page_num\": 0,
    \"regions\": [
      {\"x0\": 100, \"y0\": 100, \"x1\": 300, \"y1\": 200}
    ],
    \"dpi\": 200,
    \"alpha\": 0.3
  }"
```

## 高级用法

### 使用PDFHighlighter类

```python
from src.utils.pdf_highlighter import PDFHighlighter, BBox

# 创建边界框对象
bbox1 = BBox(x0=100, y0=100, x1=300, y1=200)
bbox2 = BBox.from_list([150, 250, 350, 350])
bbox3 = BBox.from_dict({'x': 200, 'y': 400, 'width': 200, 'height': 100})

# 高亮多个区域
url = PDFHighlighter.highlight_pdf_regions(
    pdf_path="document.pdf",
    page_num=0,
    bboxes=[bbox1, bbox2, bbox3],
    dpi=300,
    highlight_color=(0, 255, 255),  # 黄色
    border_color=(0, 0, 255),       # 红色
    alpha=0.3,
    border_width=2
)

# 高亮单个区域
url = PDFHighlighter.highlight_single_region(
    pdf_path="document.pdf",
    page_num=0,
    bbox=bbox1
)

# 获取页面尺寸
width, height = PDFHighlighter.get_page_dimensions(
    pdf_path="document.pdf",
    page_num=0
)
print(f"页面尺寸: {width} x {height} 点")
```

### 直接使用MinIO客户端

```python
from src.utils.minio_client import get_minio_client

# 获取MinIO客户端
client = get_minio_client()

# 上传文件
with open("image.png", "rb") as f:
    image_bytes = f.read()

url = client.upload_bytes(
    data=image_bytes,
    content_type="image/png",
    expires_days=7  # 7天后过期
)

# 下载文件
image_bytes = client.download_bytes("highlights/20241107_143025_a1b2c3d4.png")

# 删除文件
client.delete_file("highlights/20241107_143025_a1b2c3d4.png")

# 检查文件是否存在
exists = client.file_exists("highlights/20241107_143025_a1b2c3d4.png")

# 获取文件元数据
metadata = client.get_object_metadata("highlights/20241107_143025_a1b2c3d4.png")
print(f"上传时间: {metadata.get('upload-time')}")
print(f"过期时间: {metadata.get('expires-at')}")
```

## 管理和维护

### 查看MinIO状态

```python
from src.utils.minio_init import check_minio_health

# 检查MinIO连接
if check_minio_health():
    print("MinIO连接正常")
else:
    print("MinIO连接失败")
```

### 手动清理过期文件

```bash
# 通过命令行清理
python -m src.utils.minio_cleanup --cleanup

# 查看清理状态
python -m src.utils.minio_cleanup --status
```

### 修改清理策略

```bash
# 修改为3天后删除
python -m src.utils.minio_cleanup --setup 3

# 修改为14天后删除
python -m src.utils.minio_cleanup --setup 14

# 禁用自动清理
python -m src.utils.minio_cleanup --remove
```

## 常见问题

### Q1: 如何修改过期天数？

**方法1：修改环境变量**
```env
MINIO_AUTO_CLEANUP_DAYS=14  # 改为14天
```

**方法2：运行时修改**
```bash
python -m src.utils.minio_cleanup --setup 14
```

### Q2: 如何禁用自动清理？

```bash
python -m src.utils.minio_cleanup --remove
```

或在启动时设置：
```env
MINIO_AUTO_CLEANUP_DAYS=0  # 0表示不启用
```

### Q3: 如何查看已上传的文件？

```python
from src.utils.minio_client import get_minio_client

client = get_minio_client()
objects = client.client.list_objects(
    client.bucket_name,
    prefix="highlights",
    recursive=True
)

for obj in objects:
    print(f"文件: {obj.object_name}, 大小: {obj.size}, 时间: {obj.last_modified}")
```

### Q4: 图片URL无法访问怎么办？

检查以下配置：
1. MinIO服务器是否正常运行
2. `MINIO_PUBLIC_URL` 是否配置正确
3. MinIO bucket策略是否允许公开访问

```bash
# 设置bucket为公开访问（在MinIO控制台或使用mc命令）
mc anonymous set download myminio/pdf-highlights
```

## 性能优化建议

1. **使用合适的DPI**
   - 默认200 DPI适合大多数场景
   - 需要更高清晰度时使用300 DPI
   - 不要超过400 DPI，文件会很大

2. **批量处理**
   - 如果需要高亮多页，考虑异步处理
   - 使用队列（Celery）处理大量请求

3. **缓存策略**
   - 对相同的PDF和区域，可以缓存URL
   - 使用Redis存储URL映射关系

4. **监控存储空间**
   - 定期检查MinIO存储使用情况
   - 根据实际情况调整过期天数

## 安全建议

1. **保护密钥**
   - 不要在代码中硬编码密钥
   - 使用环境变量或密钥管理服务

2. **访问控制**
   - 根据需要设置bucket访问策略
   - 考虑使用预签名URL而非公开访问

3. **网络安全**
   - 生产环境建议使用HTTPS（设置 `MINIO_SECURE=true`）
   - 配置防火墙规则

## 总结

- ✅ 上传PDF高亮图片到MinIO
- ✅ 自动生成公网访问URL
- ✅ 7天后自动删除过期文件
- ✅ 支持多种坐标格式
- ✅ 可自定义高亮样式
- ✅ 提供完整的API和命令行工具



