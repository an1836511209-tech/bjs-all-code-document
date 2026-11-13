# 文档转换工具使用指南

## 概述

文档转换工具 `FileConverter` 提供了强大的文件格式转换功能，支持多种转换后端，将各种格式的文件统一转换为 PDF。

## 主要特性

- ✅ 支持多种转换后端（Gotenberg、LibreOffice、内置）
- ✅ 智能选择最佳转换方法
- ✅ 支持丰富的文件格式
- ✅ 自动重试和错误处理
- ✅ 异步 API
- ✅ 健康检查功能

## 支持的格式

### 图片格式
`.jpg`, `.jpeg`, `.png`, `.bmp`, `.tiff`, `.tif`, `.webp`, `.gif`

### Office 文档
`.docx`, `.doc`, `.xlsx`, `.xls`, `.pptx`, `.ppt`, `.odt`, `.ods`, `.rtf`

### 文本格式
`.txt`, `.md`, `.csv`

### HTML 格式
`.html`, `.htm`

## 转换后端

### 1. Gotenberg（推荐）

Docker 化的专业文档转换服务，转换质量最高。

**优点：**
- ✅ 专业的转换质量
- ✅ 支持所有格式
- ✅ Docker 部署简单
- ✅ HTTP API 易于集成

**部署：**
```bash
# 启动 Gotenberg 服务
docker run -d \
  --name gotenberg \
  -p 3000:3000 \
  --restart unless-stopped \
  gotenberg/gotenberg:8
```

### 2. LibreOffice

开源 Office 套件的命令行转换。

**优点：**
- ✅ 完全免费开源
- ✅ 支持 Office 格式
- ✅ 本地化部署

**安装：**
```bash
# Windows
winget install LibreOffice.LibreOffice

# Linux
sudo apt install libreoffice

# macOS
brew install libreoffice
```

### 3. Internal（内置）

使用 PyMuPDF 和 PIL 的内置实现。

**优点：**
- ✅ 无需外部依赖
- ✅ 图片转换快速
- ✅ 轻量级

**限制：**
- ⚠️ 仅支持图片和简单文本
- ⚠️ Office 文档需要外部工具

## 快速开始

### 基本用法

```python
from src.utils.file_converter import FileConverter

# 转换文件
pdf_content, pdf_name = await FileConverter.convert_to_pdf(
    file_content=file_bytes,
    file_name="document.docx"
)

print(f"转换成功: {pdf_name}")
```

### 使用便捷函数

```python
from src.utils.file_converter import convert_to_pdf_if_needed

# 自动判断是否需要转换
content, name = await convert_to_pdf_if_needed(
    file_content=file_bytes,
    file_name="document.docx"
)
```

### 检查文件格式支持

```python
# 检查是否支持
if FileConverter.is_supported("document.docx"):
    print("支持此格式")

# 检查是否需要转换
if FileConverter.needs_conversion("document.docx"):
    print("需要转换为 PDF")
```

## 配置

### 环境变量

```bash
# 选择转换后端
export CONVERTER_BACKEND=gotenberg  # gotenberg | libreoffice | internal

# Gotenberg 配置
export GOTENBERG_URL=http://localhost:3000
export GOTENBERG_TIMEOUT=120

# LibreOffice 配置
export LIBREOFFICE_PATH=libreoffice
export LIBREOFFICE_TIMEOUT=120
```

### 配置文件

编辑 `config/converter_config.py`：

```python
# 转换后端
CONVERTER_BACKEND = 'gotenberg'

# Gotenberg 配置
GOTENBERG_CONFIG = {
    'base_url': 'http://localhost:3000',
    'timeout': 120,
    'max_retries': 3,
    'retry_delay': 2,
}

# LibreOffice 配置
LIBREOFFICE_CONFIG = {
    'executable': 'libreoffice',
    'timeout': 120,
}
```

## 高级用法

### 切换转换后端

```python
# 临时切换后端（仅当前转换）
pdf_content, pdf_name = await FileConverter.convert_to_pdf(
    file_content=file_bytes,
    file_name="document.docx",
    backend='libreoffice'  # 强制使用 LibreOffice
)

# 全局切换后端
FileConverter.set_backend('gotenberg')
print(f"当前后端: {FileConverter.get_backend()}")
```

### 健康检查

```python
# 检查当前后端
health = await FileConverter.check_backend_health()
print(f"后端: {health['backend']}")
print(f"可用: {health['available']}")
print(f"版本: {health['version']}")
print(f"错误: {health['error']}")

# 检查特定后端
gotenberg_health = await FileConverter.check_backend_health('gotenberg')
libreoffice_health = await FileConverter.check_backend_health('libreoffice')
```

### 获取支持的格式

```python
# 当前后端支持的格式
formats = await FileConverter.get_supported_formats()
print(f"图片格式: {formats['images']}")
print(f"文档格式: {formats['documents']}")
print(f"文本格式: {formats['text']}")

# 特定后端支持的格式
gotenberg_formats = await FileConverter.get_supported_formats('gotenberg')
```

## 使用示例

### 示例 1：转换 Word 文档

```python
from pathlib import Path
from src.utils.file_converter import FileConverter

# 读取文件
file_path = Path("report.docx")
file_content = file_path.read_bytes()

# 转换为 PDF
pdf_content, pdf_name = await FileConverter.convert_to_pdf(
    file_content=file_content,
    file_name=file_path.name
)

# 保存 PDF
output_path = Path("report.pdf")
output_path.write_bytes(pdf_content)
print(f"已保存: {output_path}")
```

### 示例 2：批量转换图片

```python
from pathlib import Path
from src.utils.file_converter import FileConverter

# 图片目录
image_dir = Path("images")
output_dir = Path("pdfs")
output_dir.mkdir(exist_ok=True)

# 批量转换
for image_file in image_dir.glob("*.jpg"):
    print(f"转换: {image_file.name}")
    
    file_content = image_file.read_bytes()
    pdf_content, pdf_name = await FileConverter.convert_to_pdf(
        file_content=file_content,
        file_name=image_file.name
    )
    
    output_path = output_dir / pdf_name
    output_path.write_bytes(pdf_content)
    print(f"  → {output_path}")
```

### 示例 3：FastAPI 集成

```python
from fastapi import FastAPI, UploadFile, HTTPException
from fastapi.responses import Response
from src.utils.file_converter import FileConverter

app = FastAPI()

@app.post("/convert-to-pdf")
async def convert_to_pdf(file: UploadFile):
    """上传文件并转换为 PDF"""
    
    # 检查格式支持
    if not FileConverter.is_supported(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {file.filename}"
        )
    
    try:
        # 读取文件
        file_content = await file.read()
        
        # 转换为 PDF
        pdf_content, pdf_name = await FileConverter.convert_to_pdf(
            file_content=file_content,
            file_name=file.filename
        )
        
        # 返回 PDF
        return Response(
            content=pdf_content,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{pdf_name}"'
            }
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

### 示例 4：带重试的转换

```python
from src.utils.file_converter import FileConverter
from src.utils.exceptions import FileProcessingError

async def convert_with_fallback(file_content: bytes, file_name: str):
    """尝试多个后端进行转换"""
    backends = ['gotenberg', 'libreoffice', 'internal']
    
    for backend in backends:
        try:
            print(f"尝试使用 {backend} 转换...")
            pdf_content, pdf_name = await FileConverter.convert_to_pdf(
                file_content=file_content,
                file_name=file_name,
                backend=backend
            )
            print(f"✅ {backend} 转换成功")
            return pdf_content, pdf_name
            
        except FileProcessingError as e:
            print(f"❌ {backend} 转换失败: {e}")
            continue
    
    raise FileProcessingError("所有后端都转换失败")
```

## 错误处理

### 常见错误

#### 1. Gotenberg 服务不可用

```python
from src.utils.exceptions import FileProcessingError

try:
    pdf_content, pdf_name = await FileConverter.convert_to_pdf(
        file_content=file_bytes,
        file_name="document.docx"
    )
except FileProcessingError as e:
    if "Gotenberg" in str(e):
        # 切换到 LibreOffice
        FileConverter.set_backend('libreoffice')
        pdf_content, pdf_name = await FileConverter.convert_to_pdf(
            file_content=file_bytes,
            file_name="document.docx"
        )
```

#### 2. LibreOffice 未安装

```python
# 检查 LibreOffice 是否可用
health = await FileConverter.check_backend_health('libreoffice')
if not health['available']:
    print(f"LibreOffice 不可用: {health['error']}")
    print("请安装 LibreOffice 或使用 Gotenberg 后端")
```

#### 3. 不支持的格式

```python
file_name = "document.xyz"

if not FileConverter.is_supported(file_name):
    print(f"不支持的格式: {file_name}")
    
    # 获取支持的格式
    formats = await FileConverter.get_supported_formats()
    print(f"支持的格式: {formats}")
```

## 性能优化

### 1. 并发转换

```python
import asyncio
from src.utils.file_converter import FileConverter

async def convert_files(files: list):
    """并发转换多个文件"""
    tasks = [
        FileConverter.convert_to_pdf(
            file_content=file['content'],
            file_name=file['name']
        )
        for file in files
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    return results
```

### 2. 预检查后端

```python
# 应用启动时检查后端
async def startup_check():
    health = await FileConverter.check_backend_health()
    if not health['available']:
        print(f"警告: 转换后端不可用 ({health['backend']})")
        print(f"错误: {health['error']}")
        # 切换到备用后端
        FileConverter.set_backend('internal')
```

## 部署建议

### Docker Compose 部署

创建 `docker-compose.yml`：

```yaml
version: '3.8'

services:
  # Gotenberg 转换服务
  gotenberg:
    image: gotenberg/gotenberg:8
    container_name: gotenberg
    ports:
      - "3000:3000"
    restart: unless-stopped
    environment:
      - GOTENBERG_LOG_LEVEL=INFO
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:3000/health"]
      interval: 30s
      timeout: 5s
      retries: 3

  # 你的应用
  app:
    build: .
    environment:
      - CONVERTER_BACKEND=gotenberg
      - GOTENBERG_URL=http://gotenberg:3000
    depends_on:
      - gotenberg
```

启动服务：

```bash
docker-compose up -d
```

### 生产环境配置

1. **使用 Gotenberg**：专业稳定，推荐用于生产环境
2. **配置重试**：网络波动时自动重试
3. **监控健康**：定期检查后端健康状态
4. **日志记录**：记录转换成功/失败日志
5. **资源限制**：限制并发转换数量

## 故障排查

### 问题：Gotenberg 连接超时

**解决方案：**
1. 检查 Gotenberg 服务是否运行：`docker ps | grep gotenberg`
2. 检查网络连接：`curl http://localhost:3000/health`
3. 增加超时时间：`GOTENBERG_TIMEOUT=300`

### 问题：LibreOffice 转换失败

**解决方案：**
1. 检查 LibreOffice 是否安装：`libreoffice --version`
2. 检查文件权限
3. 尝试使用完整路径：`LIBREOFFICE_PATH=/usr/bin/libreoffice`

### 问题：转换质量不佳

**解决方案：**
1. 优先使用 Gotenberg 或 LibreOffice
2. 图片转换可调整 DPI 设置
3. 复杂文档建议使用 Gotenberg

## 最佳实践

1. **后端选择**：
   - 生产环境：Gotenberg（Docker 部署）
   - 简单场景：LibreOffice（本地安装）
   - 仅图片：Internal（无需外部工具）

2. **错误处理**：
   - 实现后端降级策略
   - 记录详细的错误日志
   - 向用户提供友好的错误信息

3. **性能优化**：
   - 使用异步转换
   - 实现文件大小限制
   - 考虑使用缓存

4. **监控告警**：
   - 定期健康检查
   - 转换成功率监控
   - 转换时长统计

## 相关文档

- [配置文件说明](../../config/converter_config.py)
- [文件格式支持列表](../file-format-support.md)
- [异常处理文档](../../src/utils/exceptions.py)

## 更新日志

### v2.0.0 (2024-11-04)
- ✅ 重构为多后端架构
- ✅ 集成 Gotenberg 和 LibreOffice
- ✅ 支持更多文件格式
- ✅ 添加健康检查功能
- ✅ 改进错误处理和重试机制



