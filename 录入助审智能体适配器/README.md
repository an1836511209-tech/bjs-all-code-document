 poetry run python -m src.main --env dev --debug --no-cache
 poetry run python -m src.main --env prod 

# 北交所录入助审系统

北交所信息披露智能录入和助审系统 - 基于大模型的智能文档处理和规则审核平台

## 📋 项目简介

本系统为北交所信息披露业务提供智能化的文档录入和规则审核服务，主要功能包括：

- **文件质量检测** ✅：自动检测上传文件的清晰度、分辨率、遮挡情况（v2.0 多指标融合算法）
- **智能字段提取** ✅：基于LLM Agent从多种格式文档中提取结构化信息，支持同步/流式两种模式
- **统一提取溯源** ✅：创新的 Anchor Markdown 方案，单次 LLM 调用完成提取和溯源（v3.3）
- **字段溯源定位** ✅：智能定位提取字段在原文件中的位置，生成高亮预览图，支持多文件合并
- **规则配置管理** ✅：可视化规则配置界面，支持提取规则和审核规则的灵活配置
- **任务管理系统** ✅：完整的任务状态追踪、查询和取消功能
- **规则自动审核** ✅：根据配置的审核规则自动进行字段交叉验证和内容审核，支持同步/流式两种模式

## 🎯 典型使用场景

### 场景1：智能录入流程

```
1. 用户上传附件
   ↓
2. 调用文件质量检测接口检测质量
   ↓
3. 调用字段提取接口提取信息（建议使用流式接口实时反馈）
   ↓
4. 用户确认/修改提取的字段
   ↓
5. 完成录入
```

### 场景2：智能助审流程

```
1. 接收用户确认的字段和上传的附件
   ↓
2. 调用字段审核接口进行规则审核（建议使用流式接口）
   ↓
3. 展示审核结果（通过/不通过/待确认）
   ↓
4. 对不通过和待确认的项目，展示审核说明和依据
   ↓
5. 人工复核
```

### 场景3：规则配置管理

```
1. 创建新的业务类型规则配置
   ↓
2. 定义提取字段和提取逻辑
   ↓
3. 定义审核规则和审核要点
   ↓
4. 保存并激活规则
   ↓
5. 在提取和审核时引用该规则
```

## 🏗️ 技术架构

### 技术栈

- **后端框架**：FastAPI (Python 3.10+)
- **异步编程**：asyncio、httpx
- **LLM集成**：通过灵搭Agent API接口集成大模型能力
- **文档解析**：
  - **MinerU**（transformers 后端）：PDF、图片文档解析，输出 Markdown + 坐标信息
  - **Apache Tika**：Word、TXT 等文本文档解析
- **图像处理**：OpenCV、Pillow、scikit-image
- **PDF处理**：PyMuPDF（PDF渲染和高亮标注）
- **文本匹配**：FuzzyWuzzy（模糊匹配）
- **依赖管理**：Poetry
- **API文档**：OpenAPI/Swagger

### 架构决策

#### AD-01: 文档解析方案选择

**决策名称**：混合文档解析方案

**问题**：录入助审系统需要处理多种格式的文档（PDF、Word、图片、TXT），需要评估不同的解析方案，确保既能提取结构化内容，又能支持字段溯源和高亮标注功能。

**假设**：
1. PDF和图片文档需要保留布局信息和坐标，用于字段溯源
2. LLM更适合理解Markdown格式的结构化文本
3. Word和TXT文档主要用于纯文本信息提取，溯源需求较低
4. 文档解析服务需要高可用性和稳定性
5. 不同文档格式的处理时长和资源消耗存在差异

**动机**：
1. 满足字段提取的准确性要求，提供结构化的文档内容给LLM
2. 实现字段溯源功能，需要精确的文本坐标信息
3. 在解析质量、处理速度和资源消耗之间找到平衡
4. 支持多种文档格式，提升系统适用性

**可选方案1**：纯MinerU方案

所有文档格式统一使用MinerU解析

**好处**：
1. 技术栈统一，维护成本低
2. 所有格式都能获得坐标信息，支持溯源
3. 输出格式一致（Markdown + middle.json）

**坏处**：
1. Word文档解析需要先转PDF，增加处理时间
2. 纯文本文档（TXT）使用重度解析方案，资源浪费
3. Word转PDF可能导致格式丢失或错位
4. 单一服务依赖，存在单点故障风险

**可选方案2**：纯Apache Tika方案

所有文档格式统一使用Apache Tika解析

**好处**：
1. 支持格式最全面（Word、PDF、图片、TXT等）
2. 轻量级，处理速度快
3. 成熟稳定，社区支持好

**坏处**：
1. 只能提取纯文本，无法保留文档结构
2. 不提供坐标信息，无法实现字段溯源
3. PDF中的表格、公式等复杂结构解析效果差
4. 不适合LLM理解（纯文本缺乏结构化信息）

**可选方案3**：混合解析方案（MinerU + Tika）

根据文档格式特点选择最佳解析方案：
- **PDF/图片**：MinerU（transformers后端）→ Markdown + 坐标
- **Word/TXT**：Apache Tika → 纯文本

**好处**：
1. 发挥各技术方案优势，针对性优化
2. PDF/图片获得结构化内容和坐标，支持溯源和高亮
3. Word/TXT快速提取文本，满足基本提取需求
4. 资源利用更合理，简单文档不占用MinerU资源
5. 降低单一服务依赖风险，提升系统可用性

**坏处**：
1. 需要维护两套解析服务
2. 文档类型路由逻辑增加系统复杂度
3. Word/TXT文档无法实现字段溯源功能

**决定**：方案3 - 混合解析方案（MinerU + Tika）

**理由**：
1. **业务场景匹配**：实际使用中，需要溯源的主要是PDF和图片类附件（如房产证、申请书扫描件），Word文档多为辅助材料
2. **性能最优**：MinerU处理PDF/图片，Tika处理Word/TXT，各司其职，整体处理效率最高
3. **成本效益好**：避免所有文档都使用重度解析，节省MinerU服务资源
4. **质量有保障**：
   - MinerU的transformers后端对PDF/图片的表格、公式识别效果好
   - 输出Markdown格式更适合LLM理解
   - Tika对Word/TXT的文本提取稳定可靠
5. **系统可用性高**：双服务互为补充，一个服务故障不影响另一类文档的处理
6. **扩展性强**：未来可以根据需要调整路由策略，或增加新的解析引擎

**实施细节**：
- 智能文件路由：根据文件扩展名自动选择解析引擎
- 图片文件自动转PDF后用MinerU解析，保证溯源能力
- MinerU配置：transformers后端 + md_content格式 + middle.json坐标
- Tika配置：本地部署，确保响应速度
- 统一的错误处理和重试机制

### 项目结构

```
北交所录入助审/
├── src/                          # 源代码目录
│   ├── api/                      # API路由层
│   │   └── v1/                   # API v1版本
│   │       ├── endpoints/        # 接口端点
│   │       │   ├── file.py       # 文件质量检测
│   │       │   ├── extraction.py # 字段提取（同步/流式）
│   │       │   ├── audit.py      # 规则审核（同步/流式）
│   │       │   ├── task.py       # 任务管理
│   │       │   └── rule_config.py/web.py # 规则配置
│   │       └── utils/            # API工具类
│   │           └── task_handler.py # 任务处理公共逻辑
│   ├── core/                     # 核心配置
│   │   └── logging.py            # 日志配置
│   ├── schemas/                  # Pydantic数据模型
│   │   ├── file.py               # 文件相关模型
│   │   ├── extraction.py         # 提取相关模型
│   │   ├── audit.py              # 审核相关模型
│   │   ├── task.py               # 任务相关模型
│   │   └── rule_config.py        # 规则配置模型
│   ├── services/                 # 业务服务层
│   │   ├── llm/                  # LLM服务
│   │   │   ├── client.py         # LLM客户端（单例管理）
│   │   │   └── models.py         # 数据模型
│   │   ├── quality/              # 质量检测服务
│   │   │   └── quality_checker.py # 质量检测器
│   │   ├── extraction/           # 字段提取服务
│   │   │   └── service.py        # 提取服务主逻辑
│   │   ├── audit/                # 规则审核服务
│   │   │   └── service.py        # 审核服务主逻辑
│   │   ├── mineru/               # MinerU文档解析服务
│   │   │   ├── client.py         # MinerU客户端（单例管理）
│   │   │   ├── parser.py         # 响应解析器
│   │   │   └── models.py         # 数据模型
│   │   ├── paddle/               # Paddle OCR服务
│   │   │   ├── client.py         # Paddle客户端（单例管理）
│   │   │   └── models.py         # 数据模型
│   │   ├── tika/                 # Tika文本提取服务
│   │   │   └── client.py         # Tika客户端（单例管理）
│   │   ├── gotenberg/            # Gotenberg PDF服务
│   │   │   └── client.py         # Gotenberg客户端（单例管理）
│   │   ├── storage/              # 存储服务
│   │   │   └── cache_service.py # 磁盘缓存服务（支持orjson）
│   │   ├── task_store.py         # 任务存储（带定期清理）
│   │   ├── rule_config_service.py # 规则配置服务
│   │   └── classification_service.py # 文件分类服务
│   ├── templates/                # Jinja2模板（Web界面）
│   │   └── rule_config/          # 规则配置页面
│   ├── utils/                    # 工具函数
│   │   ├── file_handler.py       # 文件处理
│   │   ├── file_hash.py          # 文件哈希计算
│   │   ├── file_processor.py     # 文件下载和哈希计算
│   │   ├── material_resolver.py  # 材料查找和解析
│   │   ├── field_value_converter.py # 字段值转换
│   │   ├── pdf_highlighter.py    # PDF高亮工具
│   │   ├── anchor_markdown_converter.py # Anchor Markdown转换
│   │   └── rag_handler.py        # RAG检索处理
│   └── middleware/               # 中间件
├── tests/                        # 测试目录
│   ├── unit/                     # 单元测试
│   ├── integration/              # 集成测试
│   └── e2e/                      # 端到端测试
├── docs/                         # 文档目录
│   ├── api/                      # API文档
│   ├── architecture/             # 架构文档
│   ├── development/              # 开发文档
│   ├── deployment/               # 部署文档
│   ├── services/                 # 服务文档
│   └── utils/                    # 工具文档
├── config/                       # 配置文件
│   ├── env_config.py             # 环境配置（带初始化控制）
│   ├── llm_config.py             # LLM配置（并发控制）
│   ├── rag_config.py             # RAG配置（Embedding/Rerank）
│   ├── mineru_config.py          # MinerU配置
│   ├── paddle_config.py          # Paddle配置
│   ├── tika_config.py            # Tika配置
│   ├── gotenberg_config.py       # Gotenberg配置
│   └── quality_config.py         # 质量检测配置
├── scripts/                      # 脚本文件
│   ├── docker_build_and_export.sh # Docker构建导出
│   └── start_tika.sh             # Tika启动脚本
├── logs/                         # 日志目录
│   ├── app_YYYY-MM-DD.log        # 应用日志
│   └── error_YYYY-MM-DD.log      # 错误日志
├── storage/                      # 存储目录
│   └── cache/                    # 磁盘缓存（自动生成）
├── data/                         # 数据目录
│   ├── rule_configs/             # 规则配置JSON文件
│   ├── temp/                     # 临时文件
│   └── uploads/                  # 上传文件
├── 原型图/                       # 原型设计
├── pyproject.toml                # Poetry配置
├── .env.example                  # 环境变量示例
├── .gitignore                    # Git忽略文件
└── README.md                     # 项目说明
```

### Git工作流

项目采用Gitflow工作流：

- `main`：生产环境分支
- `develop`：开发环境分支
- `feature/*`：功能开发分支
- `release/*`：发布准备分支
- `hotfix/*`：生产环境修复分支

## 📋 主要功能模块

### 1. 文件质量检测 ✅

**功能状态**：✅ 已完成并可用

**检测项目**：
- **清晰度检测**：多指标融合算法（拉普拉斯方差 + Tenengrad梯度 + 方差系数）
- **分辨率检测**：检查图像尺寸是否满足最低要求（600x800px以上）
- **遮挡检测**：识别扫描噪点、黑斑、手绘标记等遮挡物

**支持格式**：
- 图片：JPG、PNG、BMP、TIFF、WebP
- 文档：PDF（自动转换为图片进行检测，采用"一票否决"原则）

**技术方案**：
- 使用 **OpenCV** 进行图像预处理和特征检测
- 使用 **多指标融合算法** 提升清晰度评估准确性
- 使用 **PyMuPDF** 进行高质量PDF到图像转换

**API接口**：
- `POST /api/v1/file/quality-check` - 文件质量检测
- `GET /api/v1/file/health` - 服务健康检查

**相关文档**：
- 详细说明：`docs/development/清晰度检测优化说明.md`
- 算法分析：`docs/development/质量检测算法分析与改进.md`

---

### 2. 智能字段提取 ✅

**功能状态**：✅ 已完成并可用

**核心功能**：
- **智能文档解析**：根据文件类型自动选择最佳解析方案
  - **PDF/图片**：MinerU（transformers 后端）→ Markdown + 坐标信息
  - **Word/TXT**：Apache Tika → 纯文本内容
  - **图片格式**：自动转换为 PDF 后用 MinerU 解析
- **基于LLM Agent的智能提取**：使用大模型理解文档语义，准确提取字段信息
  - 输入格式：Anchor Markdown（带锚点的 Markdown，更适合 LLM 理解和溯源）
  - 支持表格、列表、标题、印章等结构化内容
- **统一提取溯源架构**（v3.3 新增）：
  - 单次 LLM 调用同时完成提取和溯源
  - Token 消耗减少 50%+，延迟降低 40%+
  - 提取和溯源结果完全一致，避免信息不一致
- **级联提取框架**（v3.6 新增）：
  - **链式级联**：省市区级联提取，上级结果影响下级逻辑
  - **选择性级联**：根据主字段值智能决定子字段提取
  - 支持一对一、一对多、多对一映射
  - 级联与普通字段真正并发执行，性能优化
- **多文件联合提取**：支持从多个参考材料中提取同一字段
- **字段类型支持**：文本、单选、多选三种字段类型
- **智能溯源定位**：
  - **Anchor Markdown 方案**（v3.3 推荐）：LLM 直接返回锚点 ID，后端查表获取坐标
  - 精确匹配：直接字符串匹配（基于 middle.json）
  - 模糊匹配：相似度计算（FuzzyWuzzy）
  - LLM溯源：当匹配失败时调用 LLM Agent 定位
  - 注：纯文本文档（Word/TXT）不支持溯源
- **PDF高亮预览**：生成带高亮标注的PDF预览图
  - 支持同页多框高亮
  - 支持跨页高亮合并
  - 支持多文件高亮合并（v3.3 新增）
- **并发控制**：可配置的并发执行，提升处理速度
- **实时进度反馈**：支持SSE流式输出，实时展示提取进度

**处理流程**：
```
文件上传 → 智能解析（Paddle/MinerU/Tika）→ Anchor Markdown 转换 → 统一提取溯源 → PDF高亮 → 返回结果
        ↓
  - PDF/图片 → Paddle/MinerU → Anchor Markdown + segment_map
  - Word/TXT → Tika → 纯文本（不支持溯源）
```

**统一提取溯源流程**（v3.3）：
```
1. 解析结果 → AnchorMarkdownConverter → tagged_markdown + segment_map
2. RAG 检索（如需）→ 过滤相关页面
3. 统一提取 Agent → extracted_value + anchor_ids
4. 坐标查表 → segment_map[anchor_id] → bbox
5. 高亮生成 → 多文件/多页合并
```

**支持格式**：
- **PDF文档**：MinerU 解析 → 支持溯源和高亮
- **图片文件**（JPG、PNG、BMP、TIFF、WebP）：转 PDF + MinerU 解析 → 支持溯源和高亮
- **Word文档**（DOC、DOCX）：Tika 提取 → 仅文本提取，不支持溯源
- **文本文件**（TXT、RTF）：Tika 提取 → 仅文本提取，不支持溯源

**支持模式**：
- **同步模式**（`/sync`）：等待所有字段提取完成后返回完整结果
- **流式模式**（`/stream`）：通过SSE实时推送提取进度和结果

**API接口**：
- `POST /api/v1/extraction/sync` - 同步字段提取
- `POST /api/v1/extraction/stream` - 流式字段提取（SSE）

**配置文件**：
- LLM配置：`config/llm_config.py`
  - 统一提取溯源Agent配置（v3.3 新增）
  - 提取Agent配置（降级备用）
  - 溯源Agent配置（降级备用）
  - 并发数配置
  - 重试机制配置
- RAG配置：`config/rag_config.py`（v3.3 新增）
  - RAG 触发阈值
  - Embedding 服务配置
  - Rerank 服务配置
  - BM25 降级配置
- MinerU配置：`config/mineru_config.py`
  - API端点配置（开发/生产环境）
  - 后端选择：transformers
  - 解析参数：formula_enable、table_enable 等
  - 返回格式：md_content、middle_json、model_output
  - 超时和重试配置
- Tika配置：`config/tika_config.py`
  - Tika服务器地址
  - 超时配置

**相关文档**：
- 统一提取溯源架构：`docs/services/unified_extraction_tracing.md`（v3.3 新增）
- 开发文档：`docs/development/extraction_api_development.md`
- 快速开始：`docs/development/extraction_api_quickstart.md`
- 流式示例：`docs/development/stream_extraction_example.md`
- LLM对接总结：`docs/development/LLM对接功能开发总结.md`

---

### 3. 规则配置管理 ✅

**功能状态**：✅ 已完成并可用

**核心功能**：
- **可视化配置界面**：基于Bootstrap 5的现代化Web界面
- **业务类型支持**：大宗实物、小宗实物
- **提取规则配置**：
  - 字段名称、类型（文本/单选/多选）
  - 参考材料（支持多选）
  - 提取逻辑（自然语言描述）
  - 选项列表（单选/多选字段）
  - 外部API配置（可选，用于获取字典值）
- **审核规则配置**：
  - 审核类型（字段审核/文件审核）
  - 审核字段定义
  - 审核材料列表（支持多选）
  - 审核内容描述
  - 比对方式配置
  - 自动处理规则
- **规则管理功能**：
  - 创建、查看、编辑、删除规则配置
  - 启用/禁用规则
  - 快速搜索过滤
  - JSON格式存储

**数据存储**：
- 格式：JSON文件
- 位置：`data/rule_configs/`
- 命名：UUID.json

**Web界面**（推荐）：
- 规则配置列表：`http://localhost:8580/web/rule-configs/`
- 创建规则配置：`http://localhost:8580/web/rule-configs/create`

**RESTful API**：
- `GET /api/v1/rule-configs` - 查询规则配置列表
- `POST /api/v1/rule-configs` - 创建规则配置
- `GET /api/v1/rule-configs/{config_id}` - 获取规则配置详情
- `PUT /api/v1/rule-configs/{config_id}` - 更新规则配置
- `DELETE /api/v1/rule-configs/{config_id}` - 删除规则配置
- 提取规则和审核规则的CRUD接口

**相关文档**：
- 功能总结：`docs/development/规则配置功能开发总结.md`
- 使用说明：`docs/development/规则配置管理使用说明.md`
- 快速开始：`docs/development/规则配置快速开始.md`
- 编辑搜索功能：`docs/development/规则配置编辑和搜索功能说明.md`

---

### 4. 任务管理系统 ✅

**功能状态**：✅ 已完成并可用

**核心功能**：
- **任务自动创建**：提取请求自动创建对应任务
- **状态追踪**：6种任务状态（pending、processing、completed、failed、timeout、cancelled）
- **进度查询**：实时查询任务执行进度（0-1）
- **任务取消**：支持取消等待中或处理中的任务
- **自动清理**：自动清理1小时前的已完成任务
- **并发安全**：使用asyncio.Lock保证线程安全

**任务类型**：
- `extraction` - 字段提取任务
- `audit` - 规则审核任务（预留）

**任务状态流转**：
```
创建(pending) → 处理中(processing) → 完成(completed/failed/cancelled)
                      ↓
                 实时更新进度
```

**API接口**：
- `GET /api/v1/task/{taskId}` - 查询任务状态
- `POST /api/v1/task/{taskId}/cancel` - 取消任务

**集成方式**：
- 在提取请求中提供 `task_id` 或 `request_id`
- 系统自动创建任务并更新状态
- 通过任务ID查询执行进度和结果

**相关文档**：
- 使用文档：`docs/development/task_management_api.md`
- 实现总结：`docs/development/task_management_implementation_summary.md`
- 完成报告：`docs/development/TASK_MANAGEMENT_COMPLETE.md`

---

### 5. 规则自动审核 ✅

**功能状态**：✅ 已完成并可用

**核心功能**：
- **智能附件缓存**：自动检查附件是否已解析，复用提取结果加速审核
- **灵活数据映射**：支持自动映射和自定义映射两种模式
  - **自动映射**：从提取规则自动获取参考材料和字段值
  - **自定义映射**：手动配置审核材料和字段，支持全文审核
- **双重审核类型**：
  - **字段审核**：对字段值进行一致性校验和内容审核
  - **文件审核**：对整个文件内容进行审核
- **基于LLM的智能审核**：调用审核Agent进行语义理解和规则判断
- **并发控制**：可配置的并发数（默认3），提升审核效率
- **用户输入整合**：自动整合用户手工填写的表单数据
- **实时进度反馈**：支持SSE流式输出，实时展示审核进度

**审核流程**：
```
用户确认字段 + 附件材料
         ↓
  1. 检查附件哈希（缓存）
         ↓
  2. 获取/执行字段提取
         ↓
  3. 构建审核数据源
     - 自动映射：从提取结果按field_name获取
     - 自定义映射：按配置的材料+字段获取
     - 用户输入：从confirmed_fields获取
         ↓
  4. 并发调用LLM审核Agent
         ↓
  5. 封装审核结果
     - 通过 (passed)
     - 不通过 (failed)
     - 待确认 (pending)
```

**数据映射模式**：

**模式1：自动映射**（适用于字段审核）
- 复用提取规则的参考材料配置
- 根据 `source_field_name` 自动获取提取结果
- 可选包含用户表单数据（`include_user_input`）
- 适合提取和审核字段一一对应的场景

**模式2：自定义映射**（适用于字段审核和文件审核）
- 灵活配置 `audit_data_sources`
- 支持获取字段值或全文内容
- 适合复杂的审核规则和跨字段验证

**支持模式**：
- **同步模式**（`/sync`）：等待所有审核完成后返回完整结果
- **流式模式**（`/stream`）：通过SSE实时推送审核进度和结果

**API接口**：
- `POST /api/v1/audit/sync` - 同步审核
- `POST /api/v1/audit/stream` - 流式审核（SSE）

**配置文件**：
- LLM配置：`config/llm_config.py`
  - 审核Agent配置
  - 并发数配置（audit_workers）
  - 重试机制配置

**相关文档**：
- 开发文档：`docs/development/audit_api_development.md`
- 规则映射设计：`docs/development/audit_rule_mapping_redesign.md`

## 🚀 快速开始

### 环境要求

**本地环境**：
- Python 3.10+
- Poetry
- 推荐：8GB+ 内存（图像处理需要较多内存）

**外部服务**：
- **MinerU API**：文档解析服务（PDF、图片）
  - 开发环境：http://35.241.77.81:8001
  - 配置文件：`config/mineru_config.py`
- **Apache Tika**：文本提取服务（Word、TXT）
  - 本地服务：http://35.241.77.81:7581
  - 配置文件：`config/tika_config.py`
  - 启动方式：`java -jar tika-server.jar`
- **灵搭Agent API**：LLM推理服务
  - 配置文件：`config/llm_config.py`
  - 需要配置 API Key

### 安装依赖

```bash
# 克隆项目
git clone https://gitee.com/momomomom/bjs_luruzhushen.git
cd bjs_luruzhushen

# 安装依赖
poetry install

# 激活虚拟环境
poetry shell
```

### 启动服务

**基础启动**：
```bash
# 生产模式启动
poetry run python -m src.main

# 或使用uvicorn直接启动
poetry run uvicorn src.main:app --host 0.0.0.0 --port 8580 --reload
```

**调试模式启动**（查看详细日志）：
```bash
# 方式1：环境变量（Linux/Mac）
DEBUG=true LOG_LEVEL=DEBUG poetry run python -m src.main

# 方式2：Windows PowerShell
$env:DEBUG="true"; $env:LOG_LEVEL="DEBUG"; poetry run python -m src.main

# 方式3：Windows CMD
set DEBUG=true && set LOG_LEVEL=DEBUG && poetry run python -m src.main
```

**日志级别配置**：
- `LOG_LEVEL` 环境变量：DEBUG、INFO、WARNING、ERROR、CRITICAL
- 生产环境（`ENV=prod`）默认 INFO 级别
- 开发环境（`ENV=dev`）默认 DEBUG 级别
- 优先级：`LOG_LEVEL` 环境变量 > `ENV` 自动判断

### 访问API文档

启动服务后，访问以下地址查看API文档：
- **Swagger UI**: http://localhost:8580/docs
- **ReDoc**: http://localhost:8580/redoc
- **健康检查**: http://localhost:8580/health

### 📋 日志系统

**日志文件位置**：`logs/` 目录
- `app_YYYY-MM-DD.log`：应用日志（保留30天）
- `error_YYYY-MM-DD.log`：错误日志（保留90天）
- `debug_YYYY-MM-DD.log`：调试日志（仅调试模式，保留7天）
- `quality_check_YYYY-MM-DD.log`：文件质量检测专用日志（仅调试模式）

**调试模式特性**：
- 📊 详细的质量检测评分过程
- 🔍 算法参数和中间结果
- 📏 阈值对比和判断逻辑
- 🆔 trace_id关联请求日志

**示例调试日志**：
```
2025-10-24 16:41:11.587 | DEBUG | quality_checker:check_clarity | trace_abc123 | 拉普拉斯方差计算: 2480.48
2025-10-24 16:41:11.587 | DEBUG | quality_checker:check_clarity | trace_abc123 | 清晰度判断: 分数=2480.48, 等级=excellent, 状态=passed
2025-10-24 16:41:11.588 | DEBUG | quality_checker:check_occlusion | trace_abc123 | 噪点检测: 噪点像素=1,024, 占比=0.0274 (2.74%)
```

## 📚 API使用示例

### 1. 文件质量检测

**请求示例**（使用文件URL）：
```bash
curl -X POST "http://localhost:8580/api/v1/file/quality-check" \
  -H "Content-Type: application/json" \
  -d '{
    "files": [
      {
        "file_url": "https://example.com/documents/application.pdf",
        "file_name": "信息披露申请书.pdf",
        "file_type": "info_disclosure_application"
      }
    ],
    "request_id": "req_20251024100001"
  }'
```

**请求示例**（使用Base64文件流）：
```bash
curl -X POST "http://localhost:8580/api/v1/file/quality-check" \
  -H "Content-Type: application/json" \
  -d '{
    "files": [
      {
        "file_stream": "data:image/png;base64,iVBORw0KGgoAAAANS...",
        "file_name": "房屋所有权证.png", 
        "file_type": "property_certificate"
      }
    ]
  }'
```

**响应示例**：
```json
{
  "code": 200,
  "message": "success",
  "trace_id": "trace_abc123456789",
  "timestamp": "2025-10-24T10:00:00Z",
  "data": [
    {
      "file_id": "file_20251024100001",
      "file_name": "信息披露申请书.pdf",
      "quality_status": "passed",
      "quality_result": {
        "clarity": "passed",
        "clarity_score": 725.5,
        "resolution": "passed",
        "resolution_value": "1920x1080",
        "occlusion": "passed",
        "occlusion_score": 0.02
      },
      "message": "文件质量校验通过"
    }
  ]
}
```

### 质量检测结果说明

**质量状态**：
- `passed`：质量检测通过
- `warning`：质量存在问题但可接受
- `failed`：质量检测不通过

**清晰度分数**（拉普拉斯方差）：
- >1000：优秀
- 500-1000：良好
- 100-500：一般
- <100：较差

**分辨率要求**：
- 最低要求：600x800像素
- 推荐规格：1200x1600像素或更高

**遮挡检测**：
- 检测黑色区域占比（警告>10%，失败>15%）
- 识别噪点和异常标记（警告>6%，失败>8%）
- 小异常区域累计面积>1%才警告（避免PDF转换伪影误判）
- 分数越低表示遮挡越少
- 针对文档图片深度优化，大幅提高容忍度

### 2. 智能字段提取

**同步提取示例**：

方式1: 显式指定规则配置ID（推荐生产环境）

**示例1：PDF文档提取**（支持溯源和高亮）
```bash
curl -X POST "http://localhost:8580/api/v1/extraction/sync" \
  -H "Content-Type: application/json" \
  -d '{
    "extraction_type": "有纸大宗实物",
    "files": [
      {
        "file_url": "https://example.com/application.pdf",
        "file_name": "信息披露申请书.pdf",
        "file_type": "info_disclosure_application"
      }
    ],
    "rule_config_id": "c000453b-f782-480d-9585-52332e25e55b",
    "request_id": "req_20251103_001"
  }'
```

**示例2：Word文档提取**（仅文本提取）
```bash
curl -X POST "http://localhost:8580/api/v1/extraction/sync" \
  -H "Content-Type: application/json" \
  -d '{
    "extraction_type": "有纸大宗实物",
    "files": [
      {
        "file_url": "https://example.com/application.docx",
        "file_name": "信息披露申请书.docx",
        "file_type": "info_disclosure_application"
      }
    ],
    "rule_config_id": "c000453b-f782-480d-9585-52332e25e55b",
    "request_id": "req_20251103_002"
  }'
```
> **注意**：Word/TXT 文档通过 Tika 提取纯文本，提取速度更快但不支持溯源和高亮功能。

**示例3：图片文件提取**（支持溯源和高亮）
```bash
curl -X POST "http://localhost:8580/api/v1/extraction/sync" \
  -H "Content-Type: application/json" \
  -d '{
    "extraction_type": "有纸大宗实物",
    "files": [
      {
        "file_url": "https://example.com/certificate.jpg",
        "file_name": "房屋所有权证.jpg",
        "file_type": "property_certificate"
      }
    ],
    "rule_config_id": "c000453b-f782-480d-9585-52332e25e55b",
    "request_id": "req_20251103_003"
  }'
```
> **注意**：图片文件会自动转换为 PDF 后用 MinerU 解析，支持溯源和高亮功能。

方式2: 自动选择规则配置（适用于测试环境）

```bash
curl -X POST "http://localhost:8580/api/v1/extraction/sync" \
  -H "Content-Type: application/json" \
  -d '{
    "extraction_type": "有纸大宗实物",
    "files": [
      {
        "file_url": "https://example.com/application.pdf",
        "file_name": "信息披露申请书.pdf",
        "file_type": "info_disclosure_application"
      }
    ],
    "request_id": "req_20251103_002"
  }'
```

> **说明**：当不提供 `rule_config_id` 时，系统会根据 `extraction_type` 自动查找对应业务类型的最新启用规则配置。
> 支持的extraction_type: `有纸大宗实物`、`无纸大宗实物`、`有纸小宗实物`、`无纸小宗实物`、`大宗实物`、`小宗实物`。
> 详见：`docs/development/自动规则配置选择功能说明.md`

**流式提取示例**（Python）：

```python
import requests
import json

def extract_fields_stream(files, rule_config_id):
    url = "http://localhost:8580/api/v1/extraction/stream"
    payload = {
        "extraction_type": "有纸大宗实物",
        "files": files,
        "rule_config_id": rule_config_id,
        "request_id": "req_20251103_002"
    }
    
    response = requests.post(url, json=payload, stream=True)
    
    for line in response.iter_lines():
        if line:
            # 解析SSE事件
            line_str = line.decode('utf-8')
            if line_str.startswith('event:'):
                event_type = line_str.split(':', 1)[1].strip()
            elif line_str.startswith('data:'):
                data = json.loads(line_str.split(':', 1)[1].strip())
                
                if event_type == 'task_start':
                    print(f"任务开始: 总字段数={data['total_fields']}")
                elif event_type == 'field_progress':
                    print(f"字段进度: {data['field_name']} - {data['progress']*100:.1f}%")
                elif event_type == 'field_complete':
                    print(f"字段完成: {data['field_name']} = {data['extracted_value']}")
                elif event_type == 'task_complete':
                    print(f"任务完成: 成功={data['success_count']}, 失败={data['failed_count']}")

# 使用示例
files = [{
    "file_url": "https://example.com/file.pdf",
    "file_name": "test.pdf",
    "file_type": "info_disclosure_application"
}]
extract_fields_stream(files, "config_id_here")
```

### 3. 任务状态查询

```python
import requests

# 查询任务状态
def get_task_status(task_id):
    url = f"http://localhost:8580/api/v1/task/{task_id}"
    response = requests.get(url)
    return response.json()

# 取消任务
def cancel_task(task_id):
    url = f"http://localhost:8580/api/v1/task/{task_id}/cancel"
    response = requests.post(url)
    return response.json()

# 使用示例
task = get_task_status("req_20251103_001")
print(f"任务状态: {task['status']}")
print(f"进度: {task['progress'] * 100}%")

if task['status'] == 'processing':
    # 取消任务
    result = cancel_task("req_20251103_001")
    print(f"取消结果: {result['message']}")
```

### 4. 规则配置管理

**通过Web界面**（推荐）：
- 访问：http://localhost:8580/web/rule-configs/
- 可视化创建、编辑、删除规则配置

**通过API**：

```python
import requests

# 创建规则配置
def create_rule_config(name, business_type):
    url = "http://localhost:8580/api/v1/rule-configs"
    payload = {
        "name": name,
        "business_type": business_type,
        "description": "规则配置描述",
        "extraction_rules": [],
        "audit_rules": []
    }
    response = requests.post(url, json=payload)
    return response.json()

# 添加提取规则
def add_extraction_rule(config_id, field_name, field_type):
    url = f"http://localhost:8580/api/v1/rule-configs/{config_id}/extraction-rules"
    payload = {
        "field_name": field_name,
        "field_type": field_type,
        "reference_materials": ["info_disclosure_application"],
        "extraction_logic": "从信息披露申请书中提取字段值",
        "notes": "备注信息"
    }
    response = requests.post(url, json=payload)
    return response.json()

# 使用示例
config = create_rule_config("大宗实物规则", "大宗实物")
rule = add_extraction_rule(config['id'], "坐落位置", "text")
print(f"规则配置ID: {config['id']}")
print(f"提取规则ID: {rule['id']}")
```

### 5. 规则审核

**同步审核示例**：

```bash
curl -X POST "http://localhost:8580/api/v1/audit/sync" \
  -H "Content-Type: application/json" \
  -d '{
    "audit_type": "有纸大宗实物",
    "confirmed_fields": [
      {
        "field_name": "标的名称",
        "field_value": "广东省海珠区光大花园10栋转让",
        "field_type": "text"
      },
      {
        "field_name": "坐落位置",
        "field_value": "北京市朝阳区建国路1号",
        "field_type": "text"
      }
    ],
    "files": [
      {
        "file_url": "https://example.com/files/application.pdf",
        "file_name": "信息披露申请书.pdf",
        "file_type": "info_disclosure_application"
      },
      {
        "file_url": "https://example.com/files/certificate.pdf",
        "file_name": "房屋所有权证.pdf",
        "file_type": "property_certificate"
      }
    ],
    "rule_config_id": "c000453b-f782-480d-9585-52332e25e55b",
    "request_id": "req_20251110_001"
  }'
```

**响应示例**：
```json
{
  "code": 200,
  "message": "success",
  "timestamp": "2025-11-10T10:00:00Z",
  "data": {
    "request_id": "req_20251110_001",
    "task_id": "task_audit_123",
    "status": "completed",
    "audit_type": "有纸大宗实物",
    "audit_results": [
      {
        "audit_id": "audit_001",
        "audit_rule_name": "标的名称一致性校验",
        "related_fields": [
          {
            "field_name": "标的名称"
          }
        ],
        "audit_result": "failed",
        "audit_status": "completed",
        "audit_explanation": "项目名称中包含'转让'字眼，违反审核规则",
        "confidence": 0.95
      },
      {
        "audit_id": "audit_002",
        "audit_rule_name": "坐落位置一致性校验",
        "related_fields": [
          {
            "field_name": "坐落位置"
          }
        ],
        "audit_result": "passed",
        "audit_status": "completed",
        "audit_explanation": null,
        "confidence": 0.98
      }
    ],
    "summary": {
      "total": 15,
      "passed": 12,
      "failed": 2,
      "pending": 1
    },
    "processing_time_ms": 8500
  }
}
```

**流式审核示例**（Python）：

```python
import requests
import json

def audit_fields_stream(confirmed_fields, files, rule_config_id):
    url = "http://localhost:8580/api/v1/audit/stream"
    payload = {
        "audit_type": "有纸大宗实物",
        "confirmed_fields": confirmed_fields,
        "files": files,
        "rule_config_id": rule_config_id,
        "request_id": "req_20251110_002"
    }
    
    response = requests.post(url, json=payload, stream=True)
    
    for line in response.iter_lines():
        if line:
            line_str = line.decode('utf-8')
            if line_str.startswith('event:'):
                event_type = line_str.split(':', 1)[1].strip()
            elif line_str.startswith('data:'):
                data = json.loads(line_str.split(':', 1)[1].strip())
                
                if event_type == 'task_start':
                    print(f"审核开始: 审核类型={data['audit_type']}")
                elif event_type == 'audit_progress':
                    print(f"审核进度: {data['current']}/{data['total']}")
                elif event_type == 'audit_complete':
                    print(f"审核完成: {data['audit_rule_name']} - {data['audit_result']}")
                elif event_type == 'task_complete':
                    summary = data['summary']
                    print(f"全部完成: 通过={summary['passed']}, 不通过={summary['failed']}, 待确认={summary['pending']}")

# 使用示例
confirmed_fields = [
    {"field_name": "标的名称", "field_value": "测试标的", "field_type": "text"}
]
files = [
    {
        "file_url": "https://example.com/file.pdf",
        "file_name": "信息披露申请书.pdf",
        "file_type": "info_disclosure_application"
    }
]
audit_fields_stream(confirmed_fields, files, "config_id_here")
```

### 6. Python完整示例

```python
import requests
import base64

# 1. 文件质量检测
def check_file_quality(file_path):
    url = "http://localhost:8580/api/v1/file/quality-check"
    
    # 读取文件并编码为Base64
    with open(file_path, "rb") as f:
        file_content = base64.b64encode(f.read()).decode()
    
    payload = {
        "files": [{
            "file_stream": f"data:application/pdf;base64,{file_content}",
            "file_name": "test.pdf",
            "file_type": "info_disclosure_application"
        }]
    }
    
    response = requests.post(url, json=payload)
    return response.json()

# 2. 字段提取（同步）
def extract_fields(file_url, rule_config_id):
    url = "http://localhost:8580/api/v1/extraction/sync"
    payload = {
        "extraction_type": "有纸大宗实物",
        "files": [{
            "file_url": file_url,
            "file_name": "test.pdf",
            "file_type": "info_disclosure_application"
        }],
        "rule_config_id": rule_config_id,
        "request_id": "req_test_001"
    }
    response = requests.post(url, json=payload)
    return response.json()

# 3. 查询任务状态
def get_task_status(task_id):
    url = f"http://localhost:8580/api/v1/task/{task_id}"
    response = requests.get(url)
    return response.json()

# 完整流程示例
file_path = "path/to/your/file.pdf"

# 步骤1：质量检测
print("步骤1：文件质量检测...")
quality_result = check_file_quality(file_path)
print(f"检测结果: {quality_result['data'][0]['quality_status']}")

# 步骤2：字段提取
print("\n步骤2：字段提取...")
file_url = "https://example.com/file.pdf"
rule_config_id = "your_rule_config_id"
extract_result = extract_fields(file_url, rule_config_id)
print(f"提取状态: {extract_result['status']}")

# 步骤3：查询任务
if 'task_id' in extract_result:
    print("\n步骤3：查询任务状态...")
    task = get_task_status(extract_result['task_id'])
    print(f"任务进度: {task['progress'] * 100}%")
    print(f"任务状态: {task['status']}")
```

## 🤝 贡献

欢迎提交Issue和Pull Request！

## 📄 许可证

[待定]

## 📧 联系方式

- 项目负责人：[待填写]
- 技术支持：support@example.com
- 项目地址：https://gitee.com/momomomom/bjs_luruzhushen

---

## 📚 详细文档

### 开发文档
- 项目初始化：`docs/development/项目初始化说明.md`
- 项目完成报告：`docs/development/项目初始化完成报告.md`

### 功能文档
- **质量检测**：
  - 清晰度优化：`docs/development/清晰度检测优化说明.md`
  - 算法分析：`docs/development/质量检测算法分析与改进.md`
  - 改进总结：`docs/development/质量检测改进总结.md`

- **规则配置**：
  - 功能总结：`docs/development/规则配置功能开发总结.md`
  - 使用说明：`docs/development/规则配置管理使用说明.md`
  - 快速开始：`docs/development/规则配置快速开始.md`
  - 编辑搜索：`docs/development/规则配置编辑和搜索功能说明.md`

- **字段提取**：
  - LLM对接总结：`docs/development/LLM对接功能开发总结.md`
  - 开发文档：`docs/development/extraction_api_development.md`
  - 快速开始：`docs/development/extraction_api_quickstart.md`
  - 流式示例：`docs/development/stream_extraction_example.md`

- **任务管理**：
  - 使用文档：`docs/development/task_management_api.md`
  - 实现总结：`docs/development/task_management_implementation_summary.md`
  - 完成报告：`docs/development/TASK_MANAGEMENT_COMPLETE.md`

- **规则审核**：
  - 开发文档：`docs/development/audit_api_development.md`
  - 规则映射设计：`docs/development/audit_rule_mapping_redesign.md`

### API规范
- API规范文档：`docs/api/api-specification.yaml`
- 规范一致性检查：`docs/development/api_specification_compliance.md`

---

## 📝 更新日志

### v3.7 (2025-12-11)
**网络下载可靠性优化 & Paddle 并发控制**
- 🔧 **文件下载优化**：
  - 超时时间从 30 秒增加到 120 秒，更好支持大文件（10+ MB）
  - 添加智能重试机制：最多 3 次重试，指数退避策略（1s → 2s → 4s）
  - 新增内容完整性验证：自动检测下载内容是否完整
- 🛡️ **增强错误处理**：
  - 新增 `RemoteProtocolError` 处理：应对服务器提前关闭连接
  - 改进 `TimeoutException` 处理：支持自动重试
  - 增强日志记录：每次重试都有详细的诊断信息
- ⚡ **统一下载接口**：
  - `FileHandler._download_from_url()` 提供统一的下载能力
  - Paddle 和 MinerU 客户端统一使用优化后的下载函数
  - 向后兼容：所有新参数都有默认值，现有代码无需修改
- 🎯 **Paddle 并发控制**：
  - 修复 PaddleOCR-VL 服务缺少并发限制的问题
  - 统一控制 OCR-VL 和印章识别两个服务的并发数（当前配置：10）
  - 使用 `asyncio.Semaphore` 实现优雅的并发控制
  - 改进初始化日志，显示并发配置和服务地址
- 📊 **问题修复**：
  - 解决生成高亮图片时文件下载不完整的问题
  - 修复网络波动导致的传输中断错误
  - 防止 Paddle 服务器因过高并发而压力过大
  - 提升在不稳定网络环境下的系统可靠性
- 📝 **文档更新**：
  - 新增 `OPTIMIZATION_SUMMARY.md` 详细说明下载优化方案
  - 新增 `docs/PADDLE_CONCURRENCY_CONFIG.md` 并发配置完整指南
  - 提供性能调优建议和监控方法

### v3.6 (2025-12-07)
**通用级联提取框架**
- ✨ **级联提取框架**：
  - 实现通用级联配置框架，支持链式和选择性两种级联类型
  - 链式级联：省市区级联，每一级结果影响下一级提取逻辑
  - 选择性级联：主字段值决定子字段提取（如资产类别、转让方类型、交易方式等）
- 🔧 **增强的映射能力**：
  - 支持一对一映射：`{"值": "字段"}`
  - 支持一对多映射：`{"值": ["字段1", "字段2", ...]}`
  - 支持多对一映射：多个值映射到同一个字段（自动去重）
  - 支持共享字段：同一字段在多个条件下都需要提取
- ⚡ **性能优化**：
  - 级联与普通字段真正并发执行
  - 充分利用 LLM 并发能力，整体耗时显著减少
  - 级联组内部保持串行（保证依赖关系）
- 📊 **进度计算优化**：
  - 修复多来源字段导致进度超过100%的问题
  - 使用任务完成数替代字段完成数计算进度
- 🐛 **LLM 响应解析增强**：
  - 支持多种 JSON 代码块格式（带/不带语言标识）
  - 优先匹配最后一个 JSON 块（适配 Markdown 格式响应）
  - 兼容 extracted_value 的所有类型（字符串、数字、对象、数组）
- 🎯 **支持的级联场景**（共8个）：
  - 标的所在地：省 → 市 → 区（链式）
  - 转让方住所：省 → 市 → 区（链式）
  - 资产类别：ZCLB → 9种资产类型字段（选择性）
  - 转让方类型：ZRFLX → 自然人/法人字段集（选择性）
  - 交易方式：JYFS → 集中报价/动态报价/拍卖字段集（选择性）
  - 未征集意向受让方：WYXSRF → YDGZR（选择性）
  - 信息披露起始时间：XXPLQSSJXX → 披露时间字段（选择性）
  - 受让方人工审核：SFXRGSH → 审核原因字段（选择性）
- 🏗️ **架构优势**：
  - 统一框架：所有级联场景通过配置定义
  - 易于扩展：新增级联只需添加配置
  - 类型安全：使用 Pydantic 模型
  - 代码清晰：级联逻辑集中管理，避免补丁化
- 📚 **新增文件**：
  - `src/schemas/cascade_config.py`：级联配置数据结构
  - `src/services/extraction/cascade_configs.py`：级联配置常量

### v3.5 (2025-12-04)
**代码清理和架构优化**
- 🧹 **废弃代码清理**：
  - 删除已弃用的提取和溯源方法（`_call_extraction_agent`、`_trace_field`）
  - 移除未使用的导入和实例变量（`ThreadPoolExecutor`、`MinerUParser` 等）
  - 清理孤立代码块和冗余方法实现
  - 代码量减少约 200 行，提升可维护性
- 🔧 **HTTP客户端资源管理**（P0-1）：
  - 所有HTTP客户端添加 `close()` 方法和单例管理
  - 在 FastAPI lifespan 中统一管理客户端生命周期
  - 修复资源泄漏问题，确保连接正确关闭
  - 涉及客户端：LLM、Paddle、MinerU、Tika、Gotenberg
- 💾 **任务存储优化**（P0-3）：
  - 实现定期清理机制，自动清理超过30天的已完成任务
  - 支持配置清理频率和保留天数
  - 在应用启动时自动启动清理任务
  - 避免内存无限增长
- ♻️ **代码重构和冗余消除**（P1-2）：
  - 新增 `task_handler.py`：提取API层公共任务处理逻辑
  - 新增 `material_resolver.py`：统一材料查找和解析逻辑
  - 新增 `field_value_converter.py`：统一字段值转换逻辑
  - 新增 `file_processor.py`：统一文件下载和哈希计算逻辑
  - 审核服务重构使用工具类，消除冗余实现
- 📊 **日志配置优化**（M2）：
  - 支持通过 `LOG_LEVEL` 环境变量动态配置日志级别
  - 生产环境默认 INFO 级别，开发环境默认 DEBUG 级别
  - 优先级：参数 > LOG_LEVEL 环境变量 > ENV 环境变量
- 🗂️ **临时文件清理增强**（M3）：
  - 所有临时文件使用 `try...finally` 块确保清理
  - 添加清理失败的日志记录
  - 使用 `Path.unlink(missing_ok=True)` 避免清理异常
- 🏗️ **架构改进**：
  - 服务实例化统一使用单例模式
  - 减少循环依赖风险
  - 提升代码可测试性

### v3.4 (2025-12-03)
**缓存机制优化和性能提升**
- 🔧 **修复缓存未命中问题**：
  - 修复审核服务和提取服务 `files_hash` 计算不一致导致的缓存失效
  - 审核服务现在也会在计算哈希前先下载文件并计算 `content_hash`
  - 确保提取任务和审核任务使用相同的缓存 Key
  - 性能提升：审核任务可节省 80-95% 的处理时间
- ⚡ **RAG 预加载优化**：
  - 在并发审核之前预加载所有 `parse_results` 到内存
  - 消除并发执行导致的重复磁盘加载问题
  - 每个文件只加载一次，减少磁盘 I/O（从 N 次降到 1 次）
  - 性能提升：节省 ~400ms（10个规则使用同一文件场景）
- 💾 **磁盘缓存机制完善**：
  - 修复异步版本未使用导致磁盘缓存失效的问题
  - 使用稳定的 `hashlib.md5` 替代 `hash()` 生成缓存 Key
  - 移除同步版本中的大对象内存存储，避免 OOM
  - 实现定期清理功能（默认7天过期）
- 📚 **文档更新**：
  - 更新 README.md 添加本次优化说明

### v3.3 (2025-12-01)
**统一提取溯源架构重构**
- ✨ **Anchor Markdown 方案**：创新的文档表示格式
  - 将文档内容与坐标信息融合为带锚点的 Markdown
  - 锚点格式：`(¶P-ID)`，P 为页码，ID 为片段索引
  - 支持印章、表格等特殊元素的锚点标记
- ⚡ **统一提取溯源**：单次 LLM 调用完成提取和溯源
  - Token 消耗减少 50%+
  - 延迟降低 40%+
  - 提取和溯源结果完全一致
- 🔍 **RAG 检索优化**：
  - 新增 `config/rag_config.py` 集中管理配置
  - 支持 Embedding 和 Rerank 服务集成
  - BM25 降级机制保障可用性
- 🖼️ **多文件高亮合并**：
  - 支持跨文件的高亮图合并
  - 按全局页码排序后垂直拼接
  - 自动处理不同文件的页码偏移
- 🚀 **性能优化**：
  - Anchor Markdown 缓存：同一文件只转换一次
  - 异步 RAG 检索：避免阻塞
- 📚 **新增文档**：`docs/services/unified_extraction_tracing.md`

### v3.2 (2025-11-10)
**规则自动审核功能上线**
- ✨ **智能审核系统**：基于LLM Agent的规则审核功能
  - 支持字段审核和文件审核两种类型
  - 灵活的数据映射：自动映射和自定义映射
  - 智能附件缓存：自动复用提取结果
- 🎯 **双模式支持**：
  - 同步模式：等待所有审核完成返回结果
  - 流式模式：实时推送审核进度（SSE）
- ⚡ **并发优化**：
  - 可配置的审核并发数（默认3）
  - 与提取、溯源保持一致的并发控制策略
- 🔄 **用户数据整合**：
  - 自动整合用户手工填写的表单数据
  - 支持与提取结果混合审核
- 📊 **审核结果分类**：
  - 通过（passed）：符合审核要求
  - 不通过（failed）：不符合审核要求
  - 待确认（pending）：无法判断或提取失败
- 📚 **完善的开发文档**

### v3.1 (2025-11-04)
**文档解析能力增强**
- ✨ **集成 Apache Tika**：支持 Word、TXT 等文本文档格式
  - 自动识别文件类型并选择最佳解析方案
  - Word/TXT → Tika 提取纯文本
  - PDF/图片 → MinerU 提取结构化内容
- ⚡ **优化 MinerU 配置**：
  - 后端切换为 transformers（更稳定的解析效果）
  - 提取内容改用 md_content 格式传给 LLM（更好的语义理解）
  - 保留 middle.json 用于坐标溯源
  - 启用 model_output 获取更详细的解析信息
- 🔧 **智能文件路由**：
  - 文本文档：Tika → 纯文本（快速提取，不支持溯源）
  - 图片文件：自动转 PDF → MinerU → 结构化内容
  - PDF文档：MinerU → Markdown + 坐标信息（支持溯源）

### v3.0 (2025-11-03)
**核心功能完整实现**
- ✅ **智能字段提取**：基于LLM Agent的完整提取流程
  - 文档解析（MinerU + Tika）
  - 字段提取（提取Agent）
  - 智能溯源（精确匹配 → 模糊匹配 → LLM溯源）
  - PDF高亮预览
  - 同步/流式两种模式
  - 并发控制和错误重试
- ✅ **规则配置管理**：可视化Web界面
  - 提取规则配置（字段定义、提取逻辑、参考材料）
  - 审核规则配置（审核类型、审核内容、比对方式）
  - 规则CRUD和搜索功能
  - 规则启用/禁用
- ✅ **任务管理系统**：完整的任务生命周期管理
  - 任务自动创建和状态追踪
  - 进度查询和任务取消
  - 并发安全和自动清理
  - 与提取服务无缝集成
- 📚 完善的文档体系

### v2.0 (2025-10-24)
**清晰度检测算法优化**
- ✨ 引入多指标融合算法（Laplacian + Tenengrad + 方差系数）
- ✨ 添加图像尺寸归一化，消除分辨率差异影响
- 🔧 优化评分阈值，更贴近人眼判断
- 📈 评分一致性提升：变异系数从25%降至13.5%

### v1.0 (2025-10-23)
**项目初始化**
- 🎉 项目基础架构搭建
- ✅ 文件质量检测功能（清晰度、分辨率、遮挡）
- 📦 完整的项目结构和配置

---

## 🎯 系统状态

| 功能模块 | 状态 | 完成度 |
|---------|------|--------|
| 文件质量检测 | ✅ 生产就绪 | 100% |
| 智能字段提取 | ✅ 生产就绪 | 100% |
| 规则配置管理 | ✅ 生产就绪 | 100% |
| 任务管理系统 | ✅ 生产就绪 | 100% |
| 规则自动审核 | ✅ 生产就绪 | 100% |

**当前版本**: v3.6  
**API规范一致性**: ⭐⭐⭐⭐⭐ (5/5)  
**系统状态**: 🎉 **所有核心功能已完整实现，支持复杂级联提取，代码架构优化，可投入生产使用！**

**文档解析能力**：
- ✅ PDF文档（MinerU transformers 后端）
- ✅ 图片文档（自动转PDF + MinerU）
- ✅ Word文档（Apache Tika）
- ✅ TXT文本（Apache Tika）

---

**文档版本**: v3.6.0  
**最后更新**: 2025-12-07