# 多格式文件支持

本系统现已支持多种文件格式的智能提取，包括 PDF、Word 文档、文本文件、图片等。

## 支持的文件格式

### 1. PDF 文档
- **格式**: `.pdf`
- **处理方式**: MinerU 解析 + 完整溯源
- **支持功能**: 
  - 文本提取
  - 字段溯源
  - PDF 高亮预览

### 2. 文本文档
- **格式**: `.doc`, `.docx`, `.txt`, `.rtf`, `.odt`, `.html`, `.md`
- **处理方式**: Apache Tika 提取纯文本
- **支持功能**:
  - 文本提取
  - 字段提取
- **注意**: 文本文档不支持溯源和 PDF 高亮预览

### 3. 图片文件
- **格式**: `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tiff`, `.gif`, `.webp`
- **处理方式**: 自动转换为 PDF + MinerU 解析
- **支持功能**:
  - 图片转 PDF
  - 文本提取（OCR）
  - 字段溯源
  - PDF 高亮预览

## 使用方法

### 基本使用

提取 API 的使用方式保持不变，只需要在 `files` 中指定文件即可：

```json
{
  "extraction_type": "有纸大宗实物",
  "files": [
    {
      "file_url": "https://example.com/application.docx",
      "file_name": "信息披露申请书.docx",
      "file_type": "info_disclosure_application"
    },
    {
      "file_url": "https://example.com/image.jpg",
      "file_name": "产权证照片.jpg",
      "file_type": "property_certificate"
    }
  ]
}
```

### 文本文档处理

对于 Word、TXT 等文本文档：
- 系统会使用 Apache Tika 提取纯文本内容
- 提取的字段**不会包含溯源信息**（`tracing_info` 为 `null`）
- 不会生成 PDF 高亮预览图

示例响应：

```json
{
  "status": "success",
  "results": [
    {
      "field_id": "field_001",
      "field_name": "项目名称",
      "field_type": "text",
      "extracted_value": "某某项目",
      "extraction_status": "success",
      "tracing_info": null,  // 文本文档不支持溯源
      "error_message": null
    }
  ]
}
```

### 图片文件处理

对于 JPG、PNG 等图片文件：
- 系统会自动将图片转换为 PDF
- 然后使用 OCR 提取文本
- **支持完整的溯源和高亮功能**

多张图片会被合并为一个 PDF：

```json
{
  "extraction_type": "有纸大宗实物",
  "files": [
    {
      "file_url": "https://example.com/page1.jpg",
      "file_name": "产权证第1页.jpg",
      "file_type": "property_certificate"
    },
    {
      "file_url": "https://example.com/page2.jpg",
      "file_name": "产权证第2页.jpg",
      "file_type": "property_certificate"
    }
  ]
}
```

系统会自动将同一 `file_type` 的多张图片合并为一个 PDF 进行处理。

## 环境配置

### Docker 部署

系统已经配置好 Apache Tika 服务，只需使用 Docker Compose 启动：

```bash
docker-compose up -d
```

这会启动以下服务：
- **app**: 主应用服务（端口 8580）
- **tika**: Apache Tika 服务（端口 9998）

### 本地开发

1. **安装依赖**：

```bash
poetry install
```

2. **启动 Apache Tika 服务**：

```bash
docker run -d -p 9998:9998 apache/tika:latest
```

3. **配置环境变量**（可选）：

在 `.env` 文件中添加：

```env
TIKA_SERVER_URL=http://localhost:9998
TIKA_TIMEOUT=60
```

4. **启动应用**：

```bash
poetry run uvicorn main:app --reload
```

## 技术架构

### 文件处理流程

```
用户上传文件
    ↓
检测文件格式
    ↓
分流处理：
  ├─ PDF → MinerU 解析 → 完整功能（提取 + 溯源 + 高亮）
  ├─ Word/TXT → Tika 提取文本 → 仅提取（无溯源）
  └─ 图片 → 转换为 PDF → MinerU 解析 → 完整功能
    ↓
字段提取
    ↓
返回结果
```

### 核心组件

1. **TikaClient** (`src/services/tika/client.py`)
   - 与 Apache Tika 服务通信
   - 提取 Word、TXT 等文档的纯文本

2. **ImageToPDFConverter** (`src/utils/image_converter.py`)
   - 单张图片转 PDF
   - 多张图片合并为一个 PDF

3. **FileHandler** (`src/utils/file_handler.py`)
   - 扩展支持新的文件格式
   - 文件格式检测和验证

4. **ExtractionService** (`src/services/extraction/service.py`)
   - 智能路由不同格式的文件
   - 纯文本模式跳过溯源逻辑

## 注意事项

### 限制和建议

1. **文本文档**：
   - 不支持溯源和 PDF 高亮
   - 建议客户上传 PDF 版本以获得完整功能

2. **图片文件**：
   - 需要较好的图片质量以保证 OCR 准确性
   - 建议分辨率至少 300 DPI
   - 支持自动合并同类型的多张图片

3. **文件大小**：
   - 单个文件建议不超过 50MB
   - 多文件合并建议总大小不超过 100MB

4. **性能考虑**：
   - Tika 提取文本通常比 MinerU 快
   - 图片转 PDF 会增加一定处理时间
   - 建议使用文件质量检测 API 预先检查图片质量

## 故障排查

### Tika 服务连接失败

**症状**：日志显示 "Tika 服务请求失败"

**解决方案**：
1. 检查 Tika 服务是否启动：
   ```bash
   docker ps | grep tika
   ```

2. 检查 Tika 服务健康状态：
   ```bash
   curl http://localhost:9998/tika
   ```

3. 查看 Tika 日志：
   ```bash
   docker logs bjs-luruzhushen-tika
   ```

### 图片转 PDF 失败

**症状**：日志显示 "图片转 PDF 失败"

**解决方案**：
1. 检查图片格式是否支持
2. 验证图片文件是否完整（未损坏）
3. 检查是否有足够的内存和临时存储空间

### 文本提取结果为空

**症状**：文本文档提取的字段值为空

**解决方案**：
1. 检查文档是否为加密或受保护的文件
2. 确认文档内容不是纯图片（扫描件）
3. 尝试转换为 PDF 格式后重新提取

## 更新日志

### v1.1.0 (2025-11-04)
- ✨ 新增 Word/TXT 等文本文档支持（基于 Apache Tika）
- ✨ 新增图片文件支持（自动转 PDF）
- ✨ 支持多张图片自动合并
- 🔧 优化文件处理流程
- 📚 完善文档说明



