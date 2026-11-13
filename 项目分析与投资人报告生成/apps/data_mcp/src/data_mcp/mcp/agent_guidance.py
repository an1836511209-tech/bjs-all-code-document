from __future__ import annotations

SERVER_INSTRUCTIONS = """
你正在使用“投资报告数据 MCP”。本 Server 只负责查询、提取、匹配和返回证据，不负责撰写最终报告，也不能替代人工复核。

工具选择：
1. 需要从项目材料提取标准商业模式画像时，调用 extract_project_profile。
2. 需要企业赛道标签（四级标签）时，调用 query_track_labels；不要凭空编造赛道。
3. 需要历史成交项目及相对估值时，调用 query_comparable_valuation。
4. 需要上市公司可比标的、相似度证据及 PE/PB/PS 等指标时，调用 match_listed_peers。
5. 已有项目画像和赛道标签，需要筛选潜在投资人时，调用 match_investors。
6. 报告仍缺工商登记、股东、高管、行业或上市状态等可核对事实时，调用 query_company_registry。
7. 报告仍缺主营业务、公开新闻或上市线索，且材料与画像都没有写明时，调用 search_company_web。
8. 用户已经确认当前项目是北交互联挂牌项目，且需要官网披露的主要财务指标时，调用 query_cbex_listing_financials。用户尚未确认、或明确否认时，不要调用。

推荐顺序：先 extract_project_profile；再用 query_track_labels 补齐赛道标签（必须带上画像）；随后可并行调用 query_comparable_valuation 与 match_listed_peers；最后调用 match_investors。若上游已经提供了可信且结构完整的项目画像或赛道标签，可以跳过对应步骤。query_company_registry 与 search_company_web 只在上述结果仍不足以支撑报告事实时补充调用，不能替代项目画像。query_cbex_listing_financials 只在用户确认项目属于北交互联挂牌项目后调用，不能替代上述五个工具。

调用前检查：
- 不得猜测必填参数。company_name、材料、赛道标签或项目画像缺失时，先从当前对话/工作区材料中查找；仍无法得到时再向用户补问。
- extract_project_profile 的 material_url 与 file_info 至少提供一个。两者都有时优先使用 material_url。file_info 必须是已解析的材料文本，不是本地文件路径；超长材料应由上游先清洗、分块或压缩，不要静默截断。search_keywords 可选，用于补充智谱搜索关键词。
- query_track_labels 的 company_name 与 project_profile 均必填；project_profile 优先使用 extract_project_profile 返回的 profile。不要把返回空标签解释为“市场上没有赛道”。
- match_listed_peers 的 tags 必须反映真实细分赛道；summary 应尽量包含产业链位置、主要产品服务、目标客户和盈利模式。没有业务依据时不要自行修改 field_weights。
- match_investors 必须已有 project_profile 和 track_tags。project_profile 优先直接使用 extract_project_profile 返回的 profile 对象。track_tags 使用 query_track_labels 返回的赛道标签；无需填写 label_type（DMP 品类由服务端固定）。

结果解释：
- 所有工具先检查 status：success 可使用；partial 表示有数据但存在降级；empty 表示本次没有合适数据；failed 表示工具未形成业务结果。empty/failed 时 data 为空或不含有效业务对象，禁止补造。
- query_comparable_valuation 的 data.content 是外部智能体生成内容，不得当作已核验事实。
- extract_project_profile 的 data.profile 固定包含 11 个字段；data.field_details 与 conflicts 提供字段证据和冲突。空字符串或 profile=null 时不得补造。
- query_track_labels 只使用 data.tags；tags 为空不得臆造赛道，实际数据源状态读取 sources。
- match_listed_peers 按 data.peers[].final_score 排序。retrieval_v2 的 final_score 是排名融合分，不是可比概率；assessment_status=not_assessed 时所有结果仅是待核验线索，不能称为已验证可比公司。必须结合 evidence、missing_fields 以及 PE / PB(LF) / PS(TTM) / 营业收入 / 净利润 复核。Word 批注使用 data.peers[].citations 的 source_name、source_url、quote。
- match_investors 的 data.candidates 只是候选，不代表投资意向；data.shareholder_filter_applied=false 时不得声称已经排除现有股东。Word 批注使用 data.candidates[].citations 的 source_name、source_url、quote。
- query_company_registry 只使用 data.company。company=null 或 status=empty 表示本次没有工商结果，不得补造登记信息。股东和主要人员只是工商登记摘要，不代表当前投资意向。
- search_company_web 的 data.searches 是公开网页摘要，引用前要核对 title、url 与 summary；不得把搜索摘要写成已审计财务事实。未传 search_keywords 时使用默认模板；传入后只检索这些补充词。
- query_cbex_listing_financials 只读取 data.annual、data.latest 和 data.detail_url。金额单位固定为万元。quality_status 不是 multi_year_extracted，或 status 为 partial 时，只使用已返回期间，缺失指标不要补造。data.candidates 非空时先请用户选定 detail_url，不要把候选项目的财务写成已提取结果。用户否认北交互联挂牌时不要调用。
- warnings 只用于说明会影响 Agent 下一步判断的业务缺口或降级范围。接口地址、状态码、堆栈、配置路径等开发诊断细节只写服务端日志。任何来源为空都不等于“市场上不存在”，只能说明本次查询未返回合适数据；不得据此补造事实。

重试与安全：
- 这些工具不修改项目业务数据，但会访问外部服务。不要因为结果为空而无条件重复调用。
- 工具调用超时后状态可能不确定，不要自动重试；只有连接尚未建立时才可有限重试。
- 不要在回答或日志中暴露 token、数据库口令、企查查密钥、完整内部错误正文或不必要的完整材料文本。
""".strip()


QUERY_COMPARABLE_VALUATION_DESCRIPTION = """
中文名称：历史成交可比估值查询。
何时调用：用户需要历史成交可比项目、历史交易估值或相对估值依据时调用；不要用于上市公司可比匹配或项目画像提取。
调用前：tags 必填（优先使用 query_track_labels 返回的可信赛道标签）；company_name 可选，有企业全称时应提供以提升匹配精度。缺少 tags 时先从赛道工具/材料查找，仍缺失再向用户补问。
结果：读取 data.content。该内容属于外部智能体生成结果，引用前应复核；status=empty 只表示本次未获取到合适数据。
""".strip()


EXTRACT_PROJECT_PROFILE_DESCRIPTION = """
中文名称：项目商业模式画像提取。
何时调用：需要把项目材料整理为固定 11 项商业模式画像，或后续可比公司/投资人匹配缺少结构化画像时调用。
调用前：company_name 必填；material_url 与 file_info 至少一个非空。material_url 应是服务端可访问的 Markdown 材料 URL；file_info 应是解析后的材料文本而非文件路径。两者同时提供时 material_url 优先。search_keywords 可选，用于补充智谱搜索关键词。材料超长时先由上游清洗、分块或压缩。user_chat_input 只放必要的补充要求。
结果：data.profile 才是有效画像；data.field_details 与 conflicts 提供字段级证据与冲突。字段为空字符串或 profile=null 表示无法确认，不得补造；数据源使用情况读取 sources。
""".strip()


MATCH_LISTED_PEERS_DESCRIPTION = """
中文名称：上市公司可比标的匹配。
何时调用：已有真实赛道标签，需要寻找商业模式相似的上市公司及估值指标时调用；不要用于查询历史成交案例。
调用前：tags 必填且不可猜测；summary 建议包含产业链位置、主要产品服务、目标客户和盈利模式。top_n 不传时使用配置默认值。除非用户或业务规则明确要求，不要覆盖 field_weights。
结果：按 final_score 使用排序，结合 confidence、field_scores、evidence、missing_fields 以及 PE / PB(LF) / PS(TTM) / 营业收入 / 净利润 复核。检查 assessment_status：not_assessed 表示未经业务可比性验证，必须称为候选线索；final_score 为 RRF 排名分，不能用旧相似度阈值解读。写 Word 批注时使用 data.peers[].citations 的 source_name、source_url、quote，不要写入工具名或 evidence_id。
""".strip()


MATCH_INVESTORS_DESCRIPTION = """
中文名称：潜在投资人匹配。
何时调用：已有 company_name、track_tags 和 project_profile，需要生成潜在投资人候选名单时调用，通常位于项目画像之后。
调用前：三个核心参数都必须有业务依据；project_profile 优先传项目画像工具返回的 profile 对象；track_tags 优先使用 query_track_labels 返回的赛道标签。不要填写或臆测 label_type（服务端固定 DMP 品类）。
结果：data.candidates 只是候选机构名单（含内部 DMP/库与网络 HiAgent），不代表已确认投资意愿；个人投资人仅以 counts.internal_individuals_excluded 计数、不进入 candidates。必须检查 status、sources 和 data.shareholder_filter_applied；数据为空不能推断市场上没有投资人。写 Word 批注时使用 data.candidates[].citations 的 source_name、source_url、quote，不要写入工具名或 evidence_id。
""".strip()


QUERY_TRACK_LABELS_DESCRIPTION = """
中文名称：查询企业赛道标签。
何时调用：需要四级赛道标签，供可比估值、上市公司匹配或投资人匹配使用，且当前尚无可信标签时调用。
调用前：company_name 与 project_profile 均必填；project_profile 优先传 extract_project_profile 返回的 profile。不要猜测标签。
结果：data.tags 为赛道标签列表；优先 API 平台，失败后使用 HiAgent 兜底，实际来源读取 sources。tags 为空不得补造。
""".strip()


QUERY_COMPANY_REGISTRY_DESCRIPTION = """
中文名称：企业工商信息查询。
何时调用：项目材料或画像缺少可核对的工商登记、股东、主要人员、行业或上市状态，且报告需要这些事实时调用。不要用它替代 extract_project_profile，也不要在已有充分工商事实时重复调用。
调用前：company_name 必须是已确认的企业全称，不得猜测或使用简称。
结果：读取 data.company。status=empty 或 company=null 只表示本次未查到，不得补造。股东和主要人员是工商摘要，不代表投资意向。
""".strip()


SEARCH_COMPANY_WEB_DESCRIPTION = """
中文名称：企业公开网页搜索。
何时调用：材料、画像和工商摘要仍缺少主营业务、公开报道或上市线索，需要补充公开网页信息时调用。搜索摘要不是已审计事实。
调用前：company_name 必须是已确认的企业全称。search_keywords 可选；不传时按默认模板检索主营业务、行业赛道和上市信息，传入后只检索这些补充词，并自动带上企业名称。
结果：读取 data.searches[].results 的 title、url、summary、site_name。部分查询失败时 status=partial，只使用已返回的结果。status=empty 不得把“没有搜索结果”写成“企业没有相关业务”。
""".strip()


QUERY_CBEX_LISTING_FINANCIALS_DESCRIPTION = """
中文名称：北交互联挂牌财务查询。
何时调用：先询问用户当前项目是否为北交互联挂牌项目；只有用户明确确认是之后才调用。用户否认、尚未回答，或只是普通企业财务需求时不要调用。不要用它替代项目画像、赛道、上市公司或投资人匹配。
调用前：project_name 必须是挂牌项目全称，不得猜测简称。detail_url 只在用户从候选中选定官网详情页后传入，且必须是 https://otc.cbex.com 的项目详情地址。category 不传时搜索全部挂牌类型。
结果：读取 data.annual 与 data.latest，金额单位为万元。detail_url 是披露页。status=partial 或 quality_status 不是 multi_year_extracted 时只使用已返回期间。data.candidates 非空表示尚未选定项目，先向用户确认后再带 detail_url 重试。status=empty 不得写成“企业没有财务数据”。
""".strip()
