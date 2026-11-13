"""
生成二期智能体功能需求文档（三~六章）Word 版本
"""
from docx import Document
from docx.shared import Pt, Inches, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml


def set_cell_shading(cell, color_hex: str):
    """设置单元格底色"""
    shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}"/>')
    cell._tc.get_or_add_tcPr().append(shading)


def set_table_border(table):
    """给表格加边框"""
    tbl = table._tbl
    tblPr = tbl.tblPr if tbl.tblPr is not None else parse_xml(f'<w:tblPr {nsdecls("w")}/>')
    borders = parse_xml(
        f'<w:tblBorders {nsdecls("w")}>'
        '  <w:top w:val="single" w:sz="4" w:space="0" w:color="999999"/>'
        '  <w:left w:val="single" w:sz="4" w:space="0" w:color="999999"/>'
        '  <w:bottom w:val="single" w:sz="4" w:space="0" w:color="999999"/>'
        '  <w:right w:val="single" w:sz="4" w:space="0" w:color="999999"/>'
        '  <w:insideH w:val="single" w:sz="4" w:space="0" w:color="999999"/>'
        '  <w:insideV w:val="single" w:sz="4" w:space="0" w:color="999999"/>'
        '</w:tblBorders>'
    )
    tblPr.append(borders)


def add_table(doc, headers, rows, col_widths=None):
    """添加带格式的表格"""
    table = doc.add_table(rows=1 + len(rows), cols=len(headers))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    set_table_border(table)

    # 表头
    hdr_cells = table.rows[0].cells
    for i, h in enumerate(headers):
        hdr_cells[i].text = h
        for p in hdr_cells[i].paragraphs:
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
            for run in p.runs:
                run.bold = True
                run.font.size = Pt(10)
                run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        set_cell_shading(hdr_cells[i], "4472C4")

    # 数据行
    for r_idx, row_data in enumerate(rows):
        row_cells = table.rows[r_idx + 1].cells
        for c_idx, val in enumerate(row_data):
            row_cells[c_idx].text = val
            for p in row_cells[c_idx].paragraphs:
                for run in p.runs:
                    run.font.size = Pt(10)
        # 隔行变色
        if r_idx % 2 == 1:
            for c_idx in range(len(headers)):
                set_cell_shading(row_cells[c_idx], "D9E2F3")

    # 列宽
    if col_widths:
        for row in table.rows:
            for idx, width in enumerate(col_widths):
                row.cells[idx].width = Cm(width)

    doc.add_paragraph()  # 表后空行
    return table


def build_doc():
    doc = Document()

    # ── 全局样式 ──
    style = doc.styles['Normal']
    style.font.name = '微软雅黑'
    style.font.size = Pt(11)
    style.element.rPr.rFonts.set(qn('w:eastAsia'), '微软雅黑')
    style.paragraph_format.space_after = Pt(4)
    style.paragraph_format.line_spacing = 1.35

    # ── 标题页 ──
    for _ in range(4):
        doc.add_paragraph()

    title = doc.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run('智能录入审核系统二期\n智能体功能需求文档')
    run.bold = True
    run.font.size = Pt(26)
    run.font.color.rgb = RGBColor(0x1F, 0x49, 0x7D)

    doc.add_paragraph()

    subtitle = doc.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = subtitle.add_run('（第三章 ~ 第六章）')
    run.font.size = Pt(16)
    run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    doc.add_paragraph()
    meta = doc.add_paragraph()
    meta.alignment = WD_ALIGN_PARAGRAPH.CENTER
    for line in ['文档版本：v1.0', '编制日期：2026-07-15', '文档性质：技术功能需求（偏技术侧）']:
        run = meta.add_run(line + '\n')
        run.font.size = Pt(11)
        run.font.color.rgb = RGBColor(0x66, 0x66, 0x66)

    doc.add_page_break()

    # ═══════════════════════════════════════════════
    # 第三章
    # ═══════════════════════════════════════════════
    doc.add_heading('三、功能需求详细说明', level=1)

    # ── 3.1 文件分类 ──
    doc.add_heading('3.1 模块一：文件分类服务', level=2)
    doc.add_heading('3.1.1 功能描述', level=3)
    doc.add_paragraph(
        '对业务系统上传的项目附件进行智能分类，自动识别文件所属的文档类型，'
        '为后续字段提取和审核提供分类依据。'
    )

    doc.add_heading('3.1.2 技术实现要点', level=3)
    doc.add_paragraph('输入：文件 URL 列表（支持 PDF、Word、图片、Excel、CSV 等格式）')
    doc.add_paragraph('处理流程：', style='List Bullet')
    for step in [
        '下载文件并判断格式（通过扩展名 + Tika 内容检测双重校验）',
        '解析文件前两页内容（降低处理耗时）',
        '调用 LLM 进行智能分类推理',
        '返回分类结果及置信度',
    ]:
        doc.add_paragraph(step, style='List Number')
    doc.add_paragraph('输出：文件类型枚举值（一期已支持 20+ 种类型）')

    doc.add_heading('3.1.3 二期扩展需求', level=3)
    add_table(doc,
        ['需求编号', '需求描述', '工作量说明'],
        [
            ['CLS-001', '新增业务线对应的文件类型枚举值',
             '需在 classification 模块中新增类型定义、LLM 分类 Prompt 适配'],
            ['CLS-002', '新业务线的分类规则调优',
             '根据新业务线的附件特征，调整分类 Prompt 和前处理逻辑'],
            ['CLS-003', '分类服务 API 对外标准化输出',
             '对齐前后端团队的接口规范，确保返回格式兼容'],
        ],
        col_widths=[2.5, 5.5, 8.0],
    )

    doc.add_heading('3.1.4 对外接口', level=3)
    p = doc.add_paragraph()
    run = p.add_run('POST /api/v1/file/classification')
    run.font.name = 'Consolas'
    run.font.size = Pt(10)

    # ── 3.2 质量检测 ──
    doc.add_heading('3.2 模块二：文件质量检测服务', level=2)
    doc.add_heading('3.2.1 功能描述', level=3)
    doc.add_paragraph(
        '对上传的图像类附件进行质量检测，包括清晰度评估、分辨率检测、遮挡/噪点检测，'
        '对不符合质量要求的文件给出高亮提醒。'
    )

    doc.add_heading('3.2.2 技术实现要点', level=3)
    items = [
        ('清晰度检测', '多指标融合算法（Laplacian 方差 + Tenengrad 梯度 + 灰度方差系数），归一化评分 0-100'),
        ('分辨率检测', '基于像素尺寸的分级评估（excellent / good / poor）'),
        ('遮挡检测', '自适应检测策略，区分彩色图、灰度图、黑白扫描件三种类型，'
                    '使用 Canny 边缘检测 + 形态学运算 + 黑色区域占比分析'),
        ('图像类型自动识别', '色彩饱和度分析 + 灰度直方图统计'),
    ]
    for name, desc in items:
        p = doc.add_paragraph(style='List Bullet')
        run = p.add_run(f'{name}：')
        run.bold = True
        p.add_run(desc)

    doc.add_heading('3.2.3 二期扩展需求', level=3)
    add_table(doc,
        ['需求编号', '需求描述', '工作量说明'],
        [
            ['QUA-001', '新业务线附件的质量阈值配置化',
             '将清晰度/分辨率/遮挡阈值参数化，支持按业务线配置'],
            ['QUA-002', '手写签字区域专项质量检测',
             '新增签字区域定位 + 局部清晰度评估算法'],
            ['QUA-003', '印章区域专项质量检测',
             '新增印章区域定位 + 印章完整性/清晰度评估'],
            ['QUA-004', '质量检测结果结构化增强',
             '输出包含问题区域坐标、问题类型、严重程度等结构化信息'],
        ],
        col_widths=[2.5, 5.5, 8.0],
    )

    doc.add_heading('3.2.4 对外接口', level=3)
    p = doc.add_paragraph()
    run = p.add_run('POST /api/v1/file/quality-check')
    run.font.name = 'Consolas'
    run.font.size = Pt(10)

    # ── 3.3 字段提取 ──
    doc.add_heading('3.3 模块三：字段提取服务（录入智能体核心）', level=2)
    doc.add_heading('3.3.1 功能描述', level=3)
    doc.add_paragraph(
        '按照提取规则，从项目附件中智能提取字段值及其来源位置信息。'
        '支持多来源字段的交叉校验，输出字段值、来源文件名、来源截图、提取状态（已提取 / 待确认）。'
    )

    doc.add_heading('3.3.2 技术实现要点', level=3)
    p = doc.add_paragraph()
    run = p.add_run('提取流程（7 步）：')
    run.bold = True

    steps = [
        ('缓存检查', '基于文件内容哈希的缓存命中机制，命中则直接返回历史结果（无需排队）'),
        ('规则加载', '从 RuleConfigService 加载提取规则配置'),
        ('文档解析', '通过 MinerU（主）/ PaddleOCR（备）进行文档结构化解析，输出 Markdown 内容 + 结构化页面数据（含 bbox 坐标）'),
        ('字段提取', '并发调用 LLM 提取各字段值，支持级联字段依赖关系'),
        ('字段溯源', '将提取到的字段值映射回原文档位置，定位到具体页面和坐标区域'),
        ('PDF 高亮生成', '根据溯源坐标生成高亮截图，上传至 MinIO'),
        ('结果封装', '输出字段提取结果，包含字段值、来源信息、截图 URL、提取状态'),
    ]
    for i, (name, desc) in enumerate(steps, 1):
        p = doc.add_paragraph(style='List Number')
        run = p.add_run(f'{name}：')
        run.bold = True
        p.add_run(desc)

    p = doc.add_paragraph()
    run = p.add_run('关键特性：')
    run.bold = True
    features = [
        ('并发控制', '基于 Semaphore 的 LLM 并发调用控制（unified_extraction_workers）'),
        ('分布式锁', '基于 Redis 的分布式锁防止重复提取'),
        ('多级缓存', '文件哈希缓存 + 磁盘缓存（parse_results）+ 内存缓存'),
        ('RAG 增强', '对超长文档（超过阈值字符数）自动启用 RAG 检索增强提取'),
        ('级联字段', '支持字段间的依赖关系（如"转让方类型"决定后续字段是否提取）'),
        ('降级策略', 'MinerU 不可用时自动降级到 PaddleOCR'),
    ]
    for name, desc in features:
        p = doc.add_paragraph(style='List Bullet')
        run = p.add_run(f'{name}：')
        run.bold = True
        p.add_run(desc)

    doc.add_heading('3.3.3 二期扩展需求', level=3)
    add_table(doc,
        ['需求编号', '需求描述', '工作量说明'],
        [
            ['EXT-001', '新业务线提取规则配置',
             '为每条新业务线配置完整的提取规则集（字段名、字段类型、参考材料、提取逻辑）'],
            ['EXT-002', '新业务线文件类型适配',
             '新文件类型的解析器适配（如新格式的扫描件、特定行业的表单模板等）'],
            ['EXT-003', '提取 Prompt 工程',
             '针对新业务线的字段特征，设计和调优 LLM 提取 Prompt'],
            ['EXT-004', '多来源交叉校验规则扩展',
             '新业务线的多来源字段一致性校验逻辑'],
            ['EXT-005', '级联字段关系扩展',
             '新业务线的字段间依赖关系配置与实现'],
            ['EXT-006', '特殊字段类型处理',
             '如金额格式化、日期标准化、枚举值映射等特殊字段处理逻辑'],
            ['EXT-007', '新业务线的提取结果高亮策略',
             '不同文件类型的高亮截图生成策略调整'],
            ['EXT-008', 'API 接口标准化',
             '对齐前后端团队的接口规范，包括请求/响应格式、错误码体系'],
        ],
        col_widths=[2.5, 5.5, 8.0],
    )

    doc.add_heading('3.3.4 对外接口', level=3)
    for api in [
        'POST /api/v1/extraction/extract          # 同步字段提取',
        'POST /api/v1/extraction/extract-async    # 异步字段提取（返回 task_id）',
        'GET  /api/v1/task/{task_id}              # 查询提取任务状态与结果',
    ]:
        p = doc.add_paragraph()
        run = p.add_run(api)
        run.font.name = 'Consolas'
        run.font.size = Pt(10)

    # ── 3.4 字段审核 ──
    doc.add_heading('3.4 模块四：字段审核服务（助审智能体核心）', level=2)
    doc.add_heading('3.4.1 功能描述', level=3)
    doc.add_paragraph(
        '当业务流转至审核节点时，智能体自动触发审核任务，通过附件解析与内容理解，'
        '按照审核规则对业务系统已填写的字段进行自动审核，输出审核结果'
        '（已通过 / 未通过 / 待确认 / 无需审核）及结果原因说明。'
    )

    doc.add_heading('3.4.2 技术实现要点', level=3)
    p = doc.add_paragraph()
    run = p.add_run('审核流程（8 步）：')
    run.bold = True

    audit_steps = [
        ('文件分类与映射', '将业务系统传入的中台类型代码映射到系统内部 FileType 枚举'),
        ('文件哈希计算', '计算附件内容哈希，用于缓存查询'),
        ('提取结果获取', '优先从缓存获取提取结果；缓存未命中则触发一次完整提取流程'),
        ('全文解析预加载', '预加载审核所需的全文解析数据到内存（支持 RAG 检索）'),
        ('规则遍历审核', '遍历所有审核规则，构建 LLM 请求参数，并发调用 LLM 审核 Agent'),
        ('人工审核项补充', '对未被自动审核覆盖的字段标记为"人工审核"'),
        ('级联过滤', '根据级联关系过滤不应显示的审核结果（如"转让方类型=法人"时过滤"自然人"相关字段）'),
        ('结果统计与封装', '统计通过/失败/待确认/人工审核数量，封装返回'),
    ]
    for i, (name, desc) in enumerate(audit_steps, 1):
        p = doc.add_paragraph(style='List Number')
        run = p.add_run(f'{name}：')
        run.bold = True
        p.add_run(desc)

    p = doc.add_paragraph()
    run = p.add_run('审核结果类型：')
    run.bold = True
    add_table(doc,
        ['结果枚举', '含义'],
        [
            ['PASSED', '审核通过 — 字段值与附件内容一致'],
            ['FAILED', '审核未通过 — 字段值与附件内容不一致'],
            ['PENDING', '待确认 — 无法自动判定，需人工确认'],
            ['MANUAL_REVIEW', '人工审核 — 该字段无自动审核规则覆盖'],
        ],
        col_widths=[4.0, 12.0],
    )

    p = doc.add_paragraph()
    run = p.add_run('审核规则体系：')
    run.bold = True
    for name, desc in [
        ('字段审核 (FIELD_AUDIT)', '字段值一致性比对'),
        ('文件审核 (FILE_AUDIT)', '附件完整性/合规性检查'),
        ('人工审核 (MANUAL_REVIEW)', '无法自动判定的字段'),
    ]:
        p = doc.add_paragraph(style='List Bullet')
        run = p.add_run(f'{name}：')
        run.bold = True
        p.add_run(desc)

    doc.add_heading('3.4.3 二期扩展需求', level=3)
    add_table(doc,
        ['需求编号', '需求描述', '工作量说明'],
        [
            ['AUD-001', '新业务线审核规则配置',
             '为每条新业务线配置完整的审核规则集（审核类型、字段映射、数据来源、审核内容、自动处理规则）'],
            ['AUD-002', '审核 Prompt 工程',
             '针对新业务线的审核逻辑，设计和调优 LLM 审核 Prompt'],
            ['AUD-003', '逻辑交叉检验规则扩展',
             '新业务线中字段间的关联关系校验（如金额与日期的逻辑一致性）'],
            ['AUD-004', '审核依据来源优先级配置',
             '多来源审核时，按配置的优先级排列来源截图'],
            ['AUD-005', '修改字段标记功能',
             '审核后任务单发生修改时，对已修改字段值进行标记'],
            ['AUD-006', '审核结果 API 标准化',
             '对齐前后端团队的接口规范'],
            ['AUD-007', '审核任务并发控制',
             '根据新业务线的并发需求，调整限流信号量配置'],
            ['AUD-008', '流式审核接口适配',
             '支持 SSE/WebSocket 方式实时推送审核进度'],
        ],
        col_widths=[2.5, 5.5, 8.0],
    )

    doc.add_heading('3.4.4 对外接口', level=3)
    for api in [
        'POST /api/v1/audit/audit                # 同步审核',
        'POST /api/v1/audit/audit-async          # 异步审核（返回 task_id）',
        'POST /api/v1/audit/audit-stream         # 流式审核（SSE 推送进度）',
        'GET  /api/v1/task/{task_id}             # 查询审核任务状态与结果',
    ]:
        p = doc.add_paragraph()
        run = p.add_run(api)
        run.font.name = 'Consolas'
        run.font.size = Pt(10)

    # ── 3.5 规则配置 ──
    doc.add_heading('3.5 模块五：规则配置管理服务', level=2)
    doc.add_heading('3.5.1 功能描述', level=3)
    doc.add_paragraph(
        '提供提取规则和审核规则的集中配置与管理能力，支持按业务类型组织规则集，'
        '支持规则的增删改查、启用/禁用、版本管理。'
    )

    doc.add_heading('3.5.2 技术实现要点', level=3)
    items = [
        ('存储方式', '文件系统 JSON 存储（data/rule_configs/{config_id}.json）'),
        ('配置结构', 'RuleConfig = 业务类型 + 提取规则列表 + 审核规则列表'),
        ('提取规则 (ExtractionRule)', '字段名、字段类型、参考材料、提取逻辑、API 配置、枚举选项'),
        ('审核规则 (AuditRule)', '审核类型、字段名、映射类型、来源字段、数据来源、审核内容、自动处理规则'),
        ('Web 管理界面', '基于 Jinja2 模板的规则配置 Web 界面'),
    ]
    for name, desc in items:
        p = doc.add_paragraph(style='List Bullet')
        run = p.add_run(f'{name}：')
        run.bold = True
        p.add_run(desc)

    doc.add_heading('3.5.3 二期扩展需求', level=3)
    add_table(doc,
        ['需求编号', '需求描述', '工作量说明'],
        [
            ['RUL-001', '新业务类型枚举扩展',
             '在 BusinessType 枚举中新增业务线类型'],
            ['RUL-002', '新业务线规则集初始化',
             '为每条新业务线创建初始规则配置集'],
            ['RUL-003', '规则导入/导出功能',
             '支持规则配置的批量导入导出（JSON 格式），便于跨环境迁移'],
            ['RUL-004', '规则版本管理增强',
             '规则变更历史记录、版本回滚能力'],
            ['RUL-005', '规则模板功能',
             '提供常用规则模板，加速新业务线规则配置'],
            ['RUL-006', '级联配置增强',
             '支持更复杂的级联关系配置（多级级联、条件组合）'],
            ['RUL-007', '规则校验与测试',
             '提供规则配置的语法校验和单条规则的测试运行能力'],
        ],
        col_widths=[2.5, 5.5, 8.0],
    )

    doc.add_heading('3.5.4 对外接口', level=3)
    api_groups = [
        ('规则配置 CRUD', [
            'POST   /api/v1/rule-configs                    # 创建配置',
            'GET    /api/v1/rule-configs                    # 查询配置列表',
            'GET    /api/v1/rule-configs/{config_id}        # 获取配置详情',
            'PUT    /api/v1/rule-configs/{config_id}        # 更新配置',
            'DELETE /api/v1/rule-configs/{config_id}        # 删除配置',
        ]),
        ('提取规则管理', [
            'POST   /api/v1/rule-configs/{id}/extraction-rules          # 添加提取规则',
            'PUT    /api/v1/rule-configs/{id}/extraction-rules/{rid}    # 更新提取规则',
            'DELETE /api/v1/rule-configs/{id}/extraction-rules/{rid}    # 删除提取规则',
        ]),
        ('审核规则管理', [
            'POST   /api/v1/rule-configs/{id}/audit-rules               # 添加审核规则',
            'PUT    /api/v1/rule-configs/{id}/audit-rules/{rid}         # 更新审核规则',
            'DELETE /api/v1/rule-configs/{id}/audit-rules/{rid}         # 删除审核规则',
        ]),
        ('Web 管理界面', [
            'GET    /api/v1/web/rule-configs                # 规则配置 Web 管理页面',
        ]),
    ]
    for group_name, apis in api_groups:
        p = doc.add_paragraph()
        run = p.add_run(group_name)
        run.bold = True
        for api in apis:
            p = doc.add_paragraph()
            run = p.add_run(api)
            run.font.name = 'Consolas'
            run.font.size = Pt(9)

    # ── 3.6 任务管理 ──
    doc.add_heading('3.6 模块六：任务管理服务', level=2)
    doc.add_heading('3.6.1 功能描述', level=3)
    doc.add_paragraph(
        '管理异步任务的完整生命周期，包括任务创建、状态流转、进度追踪、结果存储，'
        '支持任务查询和缓存结果复用。'
    )

    doc.add_heading('3.6.2 技术实现要点', level=3)
    items = [
        ('任务状态', 'PENDING → PROCESSING → COMPLETED / FAILED'),
        ('任务类型', 'EXTRACTION（提取任务）/ AUDIT（审核任务）'),
        ('存储后端', 'Redis（支持 TTL 自动过期）'),
        ('进度追踪', '支持细粒度进度百分比和状态消息更新'),
        ('排队管理', '自动统计排队数，向前端展示排队状态'),
        ('缓存复用', '基于文件哈希的任务结果缓存，相同文件不重复处理'),
    ]
    for name, desc in items:
        p = doc.add_paragraph(style='List Bullet')
        run = p.add_run(f'{name}：')
        run.bold = True
        p.add_run(desc)

    doc.add_heading('3.6.3 二期扩展需求', level=3)
    add_table(doc,
        ['需求编号', '需求描述', '工作量说明'],
        [
            ['TSK-001', '任务优先级支持',
             '支持按业务线或紧急程度设置任务处理优先级'],
            ['TSK-002', '任务回调机制',
             '任务完成后主动回调业务系统接口（Webhook 方式）'],
            ['TSK-003', '任务统计与监控',
             '提供任务处理量、成功率、平均耗时等统计接口'],
            ['TSK-004', '并发控制参数化',
             '按业务线配置不同的并发限制参数'],
        ],
        col_widths=[2.5, 5.5, 8.0],
    )

    doc.add_heading('3.6.4 对外接口', level=3)
    for api in [
        'GET    /api/v1/task/{task_id}        # 查询任务状态',
        'DELETE /api/v1/task/{task_id}        # 取消任务',
    ]:
        p = doc.add_paragraph()
        run = p.add_run(api)
        run.font.name = 'Consolas'
        run.font.size = Pt(10)

    doc.add_page_break()

    # ═══════════════════════════════════════════════
    # 第四章
    # ═══════════════════════════════════════════════
    doc.add_heading('四、基础设施与基础能力需求', level=1)

    doc.add_heading('4.1 文档解析能力适配', level=2)
    add_table(doc,
        ['需求编号', '需求描述', '工作量说明'],
        [
            ['INF-001', 'MinerU 解析器适配',
             '针对新业务线的特殊文档格式，调整 MinerU 解析参数'],
            ['INF-002', 'PaddleOCR 降级策略优化',
             '根据新文件类型的特征，优化降级触发条件和处理逻辑'],
            ['INF-003', 'Tika 文件类型识别扩展',
             '新文件 MIME 类型的识别支持'],
            ['INF-004', '解析结果缓存策略优化',
             '针对新业务线的文件特征，优化缓存键生成和 TTL 策略'],
        ],
        col_widths=[2.5, 5.5, 8.0],
    )

    doc.add_heading('4.2 LLM 能力适配', level=2)
    add_table(doc,
        ['需求编号', '需求描述', '工作量说明'],
        [
            ['INF-005', 'LLM Prompt 工程',
             '新业务线的提取/审核 Prompt 设计、测试与调优（核心工作量）'],
            ['INF-006', 'LLM 并发控制优化',
             '根据新业务线的请求量，调整并发参数和限流策略'],
            ['INF-007', 'LLM 降级与重试策略',
             '优化 LLM 调用的超时、重试、降级逻辑'],
            ['INF-008', 'RAG 检索策略优化',
             '针对新业务线的文档特征，优化 RAG 分块和检索策略'],
        ],
        col_widths=[2.5, 5.5, 8.0],
    )

    doc.add_heading('4.3 PDF 高亮与截图能力', level=2)
    add_table(doc,
        ['需求编号', '需求描述', '工作量说明'],
        [
            ['INF-009', '高亮截图引擎适配',
             '针对新文件类型的高亮截图生成适配'],
            ['INF-010', '截图存储策略优化',
             '优化 MinIO 存储路径和清理策略'],
        ],
        col_widths=[2.5, 5.5, 8.0],
    )

    doc.add_page_break()

    # ═══════════════════════════════════════════════
    # 第五章
    # ═══════════════════════════════════════════════
    doc.add_heading('五、接口规范与集成需求', level=1)

    doc.add_heading('5.1 API 接口标准化', level=2)
    add_table(doc,
        ['需求编号', '需求描述', '工作量说明'],
        [
            ['API-001', '接口文档编写与维护',
             '编写完整的 OpenAPI 3.0 规范文档，供前后端团队对接'],
            ['API-002', '统一错误码体系',
             '定义标准化的错误码和错误信息格式'],
            ['API-003', '统一响应格式',
             '确保所有接口的响应格式一致（包含 trace_id、状态码、数据、消息）'],
            ['API-004', '接口版本管理',
             'API 路径版本化（/api/v1/、/api/v2/），支持平滑升级'],
            ['API-005', '鉴权接口对接',
             '对接业务系统的鉴权机制（Token / API Key）'],
        ],
        col_widths=[2.5, 5.5, 8.0],
    )

    doc.add_heading('5.2 与前后端团队的集成边界', level=2)
    add_table(doc,
        ['角色', '职责范围'],
        [
            ['前后端团队（业务系统）', '业务流程控制、字段录入展示、任务单生成、业务逻辑处理、数据持久化'],
            ['智能体服务（我方交付）', '文件分类、质量检测、字段提取、字段审核、规则管理'],
        ],
        col_widths=[5.0, 11.0],
    )

    doc.add_paragraph('接口约定：', style='List Bullet')
    for item in [
        '请求格式：JSON (Content-Type: application/json)',
        '文件传递：通过 URL 引用（业务系统上传至 MinIO 后提供 URL）',
        '异步模式：长耗时操作返回 task_id，前端轮询查询结果',
        '流式模式：审核支持 SSE 实时推送进度',
    ]:
        doc.add_paragraph(item, style='List Bullet 2')

    doc.add_page_break()

    # ═══════════════════════════════════════════════
    # 第六章
    # ═══════════════════════════════════════════════
    doc.add_heading('六、非功能性需求', level=1)

    doc.add_heading('6.1 性能需求', level=2)
    add_table(doc,
        ['指标', '要求'],
        [
            ['分类接口响应时间', '单文件 ≤ 5s'],
            ['质量检测响应时间', '单文件 ≤ 3s'],
            ['字段提取（缓存命中）', '≤ 2s'],
            ['字段提取（无缓存）', '单任务 ≤ 60s（取决于文件页数和字段数）'],
            ['字段审核（无缓存）', '单任务 ≤ 120s（取决于规则数和文件复杂度）'],
            ['并发处理能力', '支持 ≥ 10 个并发提取/审核任务'],
        ],
        col_widths=[5.0, 11.0],
    )

    doc.add_heading('6.2 可靠性需求', level=2)
    add_table(doc,
        ['指标', '要求'],
        [
            ['服务可用性', '≥ 99.5%'],
            ['LLM 调用降级', '主模型不可用时自动切换备选模型'],
            ['解析引擎降级', 'MinerU 不可用时自动降级到 PaddleOCR'],
            ['缓存一致性', '文件哈希变化时自动失效旧缓存'],
        ],
        col_widths=[5.0, 11.0],
    )

    doc.add_heading('6.3 可维护性需求', level=2)
    add_table(doc,
        ['需求编号', '需求描述'],
        [
            ['MAINT-001', '所有配置项支持环境变量覆盖'],
            ['MAINT-002', '日志规范化（结构化日志、trace_id 关联）'],
            ['MAINT-003', '健康检查接口（/health）'],
            ['MAINT-004', '指标暴露接口（Prometheus 格式）'],
        ],
        col_widths=[3.0, 13.0],
    )

    # ── 保存 ──
    out_path = r'd:\Project\bjs_luruzhushen\docs\二期智能体功能需求文档_第三至六章.docx'
    doc.save(out_path)
    print(f'Word 文档已生成: {out_path}')


if __name__ == '__main__':
    build_doc()
