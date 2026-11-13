# 2.3.8 录入-文档内容解析子模块详细设计

## 2.3.8.1 类设计

```mermaid
classDiagram
    class ExtractionService {
        -MinerUClient mineru_client
        -PaddleClient paddle_client
        -TikaClient tika_client
        -ImageToPDFConverter image_converter
        -WordToPDFConverter word_converter
        +_parse_single_file(file_input) ParseResult
        +_parse_files(files, cache) Dict
        -_merge_md_content(parse_results) str
        -_merge_middle_json(parse_results) str
        -_create_text_parse_result(text, file_name) ParseResult
        -_create_word_parse_result(text, pdf_result, file_name) ParseResult
    }
    
    class PaddleClient {
        -str api_base_url
        -int timeout
        -Dict config
        +parse_file(file_path, options) ParseResult
        -_call_api(file_content, file_name, options) Dict
    }
    
    class MinerUClient {
        -str api_base_url
        -int timeout
        -Dict config
        -MinerUParser parser
        +parse_file(file_path, file_content, file_name, options) ParseResult
        -_call_api(file_content, file_name, options) Dict
        -_get_content_type(file_name) str
    }
    
    class TikaClient {
        -str tika_server_url
        -int timeout
        +extract_text(file_content, file_name) Dict
        -_extract_metadata(file_content, file_name) Dict
        +check_health() bool
    }
    
    class MinerUParser {
        +parse_response(raw_response, file_name, file_type) ParseResult
        -_parse_pages(pages_data) List~ParsedPage~
        -_extract_layout_blocks(page_data) List~LayoutBlock~
    }
    
    class ParseResult {
        +bool success
        +List~ParsedPage~ pages
        +str md_content
        +str backend
        +int total_pages
        +float parse_time
        +str error_message
        +get_page(page_num) ParsedPage
        +get_all_text() str
    }
    
    class ParsedPage {
        +int page_num
        +str text
        +int width
        +int height
        +List~Content~ contents
        +List~LayoutBlock~ layout_blocks
    }
    
    class FileHandler {
        <<utility>>
        +is_pdf_format(extension) bool
        +is_image_format(extension) bool
        +is_word_format(extension) bool
        +is_text_document_format(extension) bool
        +process_file_input(file_url, file_name) Tuple
    }
    
    class ImageToPDFConverter {
        <<utility>>
        +convert_single_image(image_content, file_name) bytes
        +convert_multiple_images(image_contents) bytes
    }
    
    class WordToPDFConverter {
        <<utility>>
        +convert_to_pdf_async(word_content, file_name) bytes
    }
    
    ExtractionService --> PaddleClient : uses
    ExtractionService --> MinerUClient : uses
    ExtractionService --> TikaClient : uses
    ExtractionService --> ImageToPDFConverter : uses
    ExtractionService --> WordToPDFConverter : uses
    ExtractionService --> FileHandler : uses
    MinerUClient --> MinerUParser : uses
    MinerUClient --> ParseResult : creates
    PaddleClient --> ParseResult : creates
    TikaClient --> ParseResult : creates
    ParseResult --> ParsedPage : contains
```

### 类说明

1. **ExtractionService**：文档解析服务主类
   - 协调多个解析引擎，实现智能路由
   - 根据文件类型选择最佳解析方案
   - 支持文件批量解析和结果合并

2. **PaddleClient**：Paddle解析客户端（优先使用）
   - 基于PaddleOCR-VL的文档解析
   - 支持印章识别和高精度OCR
   - 144 DPI像素坐标系统

3. **MinerUClient**：MinerU解析客户端（降级备选）
   - Transformers后端的PDF/图片解析
   - 输出Markdown格式和坐标信息
   - 支持表格、公式识别

4. **TikaClient**：Tika文本提取客户端
   - 用于Word、TXT等文本文档
   - 快速纯文本提取
   - 不支持坐标溯源

5. **MinerUParser**：MinerU响应解析器
   - 解析MinerU API返回的复杂JSON结构
   - 提取页面、布局块、文本内容
   - 构建统一的ParseResult对象

6. **ParseResult/ParsedPage**：解析结果数据类
   - 统一的解析结果格式
   - 包含页面信息、文本内容、坐标数据
   - 支持多种后端（paddle/mineru/tika）

7. **FileHandler**：文件处理工具类
   - 文件格式识别
   - 文件下载和内容处理
   - 支持URL和Base64输入

8. **ImageToPDFConverter/WordToPDFConverter**：格式转换工具
   - 图片转PDF（用于溯源）
   - Word转PDF（通过Gotenberg服务）

## 2.3.8.2 时序设计

```mermaid
sequenceDiagram
    participant ES as ExtractionService
    participant FH as FileHandler
    participant PC as PaddleClient
    participant MC as MinerUClient
    participant TC as TikaClient
    participant Conv as Converter
    participant Parser as MinerUParser
    
    ES->>FH: 获取文件扩展名
    FH-->>ES: 文件类型
    
    alt PDF文件
        ES->>PC: 优先使用Paddle解析
        PC->>PC: 调用Paddle API
        alt Paddle成功
            PC-->>ES: ParseResult (backend=paddle)
        else Paddle失败
            PC-->>ES: PaddleError异常
            ES->>MC: 降级到MinerU
            MC->>MC: 调用MinerU API
            MC->>Parser: 解析响应
            Parser-->>MC: ParseResult (backend=mineru)
            MC-->>ES: ParseResult
        end
        
    else 图片文件
        ES->>Conv: 转换图片为PDF
        Conv-->>ES: PDF字节流
        ES->>PC: 优先使用Paddle解析PDF
        alt Paddle成功
            PC-->>ES: ParseResult (backend=paddle)
        else Paddle失败
            ES->>MC: 降级到MinerU
            MC-->>ES: ParseResult (backend=mineru)
        end
        
    else Word文件
        ES->>TC: 使用Tika提取文本
        TC-->>ES: 文本内容
        
        par 并行转PDF用于溯源
            ES->>Conv: Word转PDF (Gotenberg)
            Conv-->>ES: PDF字节流
            ES->>MC: MinerU解析PDF获取坐标
            MC-->>ES: PDF解析结果
        end
        
        ES->>ES: 创建混合ParseResult
        Note over ES: md_content=Tika文本<br/>middle_json=MinerU坐标
        
    else TXT/RTF文件
        ES->>TC: 使用Tika提取文本
        TC-->>ES: 文本内容
        ES->>ES: 创建简单ParseResult
        Note over ES: 纯文本模式<br/>不支持溯源
    end
    
    ES->>ES: 标记解析后端和模式
    ES-->>ES: 返回ParseResult
```

### 时序说明

1. **文件类型识别**：根据扩展名判断文件格式
2. **智能路由策略**：
   - PDF/图片：Paddle优先 → MinerU降级
   - Word：Tika提取 + Gotenberg转PDF + MinerU获取坐标
   - TXT：Tika提取（纯文本模式）
3. **降级机制**：Paddle服务故障时自动降级到MinerU
4. **并行处理**：Word文档同时进行文本提取和PDF转换
5. **结果标记**：标记解析后端和是否支持溯源

## 2.3.8.3 其他设计

**异常处理**

1. **解析引擎故障**：
   - Paddle故障：自动降级到MinerU
   - MinerU故障：返回解析失败
   - Tika故障：返回服务不可用

2. **文件转换异常**：
   - 图片转PDF失败：捕获异常，返回转换错误
   - Word转PDF失败：降级为纯文本模式（不支持溯源）

3. **网络异常**：
   - 超时重试：默认3次，指数退避
   - 连接失败：返回服务不可达

**配置管理**

- **PaddleConfig** (`config/paddle_config.py`)：
  - API端点、超时、重试配置
  - 降级开关：`fallback_to_mineru`
  - 144 DPI渲染参数

- **MinerUConfig** (`config/mineru_config.py`)：
  - API端点、后端选择（transformers）
  - 返回格式：md_content、middle_json、model_output
  - 表格、公式识别开关

- **TikaConfig** (`config/tika_config.py`)：
  - Tika服务器地址
  - 超时配置（60秒）

## 2.3.8.4 实现方式

**混合解析方案决策**

根据文件特点选择最佳解析引擎：

| 文件类型 | 解析引擎 | 输出格式 | 溯源支持 | 优势 |
|---------|---------|---------|---------|------|
| PDF | Paddle → MinerU | Markdown + 坐标 | ✅ | 高精度OCR + 印章识别 |
| 图片 | Paddle → MinerU | Markdown + 坐标 | ✅ | 自动转PDF + 结构化识别 |
| Word | Tika + Gotenberg + MinerU | 文本 + 坐标 | ✅ | 快速提取 + 支持溯源 |
| TXT | Tika | 纯文本 | ❌ | 快速轻量 |

**Paddle优先策略**

1. **优势**：
   - PaddleOCR-VL高精度识别
   - 印章检测和提取
   - 更准确的表格识别
   - 144 DPI像素坐标（适合高亮）

2. **降级条件**：
   - Paddle API返回错误
   - 超时或连接失败
   - 解析结果success=False

3. **降级流程**：
   ```python
   try:
       result = await paddle_client.parse_file(file_path)
       if result.success:
           return result
       else:
           raise PaddleError("Paddle解析失败")
   except (PaddleError, Exception):
       if config['fallback_to_mineru']:
           logger.info("降级到MinerU")
           return await mineru_client.parse_file(file_path)
       else:
           raise
   ```

**Word文档双模式处理**

Word文档需要同时满足两个需求：
1. **快速文本提取**（用于LLM提取）→ Tika
2. **坐标溯源**（用于PDF高亮）→ 转PDF + MinerU

**实现流程**：
```python
# 1. Tika提取文本（快速）
text = await tika_client.extract_text(word_content)

# 2. Gotenberg转PDF
pdf_bytes = await word_converter.convert_to_pdf(word_content)

# 3. MinerU解析PDF获取坐标
pdf_result = await mineru_client.parse_file(pdf_bytes)

# 4. 创建混合结果
return WordParseResult(
    md_content=text,           # Tika文本（用于提取）
    pages=pdf_result.pages,    # MinerU坐标（用于溯源）
    is_word_document=True,     # 标记Word模式
    pdf_content=pdf_bytes      # 保存PDF用于高亮
)
```

**MinerU配置优化**

选择**Transformers后端**：
- 更稳定的解析效果
- 更好的表格、公式识别
- 输出格式：
  - `md_content`：Markdown格式（给LLM）
  - `middle_json`：坐标信息（用于溯源）
  - `model_output`：详细解析数据

**批量文件并行解析**

支持多个文件同时解析，提升效率：

```python
async def _parse_files(files):
    # 创建并行任务
    tasks = [parse_single_file(f) for f in files]
    
    # 并发执行
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    # 按file_type分组并合并
    grouped_results = group_by_file_type(results)
    
    return {
        file_type: {
            "md_content": merge_md_content(results),
            "middle_json": merge_middle_json(results)
        }
        for file_type, results in grouped_results.items()
    }
```

**结果合并策略**

同一file_type的多个文件合并为一个逻辑文档：

1. **md_content合并**：
   - 添加文件分隔符：`# === 文件名 ===`
   - 保持原始文本格式
   - 适合LLM理解多文件上下文

2. **middle_json合并**：
   - 调整页码：累加页面偏移量
   - 保持坐标数据完整性
   - 支持跨文件溯源

**性能优化**

1. **缓存机制**：
   - 文件哈希检测，避免重复解析
   - 提取阶段的解析结果可复用到审核阶段

2. **流式处理**：
   - 大文件逐块下载
   - 及时释放内存

3. **并发控制**：
   - 限制并发解析数量
   - 避免API服务过载

4. **降级开关**：
   - 可配置是否启用MinerU降级
   - 生产环境建议开启




