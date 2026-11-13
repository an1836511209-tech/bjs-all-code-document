"""
LLM Agent数据模型

定义LLM Agent请求和响应的数据结构
"""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class ExtractionState(BaseModel):
    """字段提取State参数"""
    file_content: str = Field(..., description="文件内容（content_list.json）")
    field_name: str = Field(..., description="字段名称")
    extraction_logic: str = Field(..., description="提取逻辑")
    reference_materials: str = Field(..., description="参考材料")


class TracingState(BaseModel):
    """字段溯源State参数"""
    file_content: str = Field(..., description="文件内容（middle.json）")
    field_name: str = Field(..., description="字段名称")
    extraction_logic: str = Field(..., description="提取逻辑")
    reference_materials: str = Field(..., description="参考材料")
    extraction_result: str = Field(..., description="提取结果")


class AuditState(BaseModel):
    """字段审核State参数"""
    audit_type: str = Field(..., description="审核类型：字段审核/文件审核")
    field_name: str = Field(..., description="审核字段/文件名称")
    audit_content: str = Field(..., description="审核内容")
    auto_process_rules: str = Field(..., description="自动处理规则")
    audit_data_sources: str = Field(..., description="审核数据源")
    user_input_key: Optional[str] = Field(None, description="用户输入的字段值")
    reference_materials: str = Field(..., description="参考材料（来自附件提取结果）")


class AgentRequest(BaseModel):
    """Agent请求模型"""
    agentId: str = Field(..., description="Agent ID")
    userChatInput: str = Field(default="", description="用户输入")
    state: Dict[str, Any] = Field(..., description="状态参数")


class BillInfo(BaseModel):
    """低代码智能体返回的计费信息"""
    model: Optional[str] = Field(None, description="模型名称")
    billType: Optional[str] = Field(None, description="计费类型")
    promptTokens: Optional[int] = Field(None, description="输入 token 数")
    completionTokens: Optional[int] = Field(None, description="输出 token 数")
    totalTokens: Optional[int] = Field(None, description="总 token 数")

    model_config = {"extra": "ignore"}


class AgentChoice(BaseModel):
    """Agent响应选项"""
    content: str = Field(default="", description="响应内容")
    bill: Optional[BillInfo] = Field(None, description="本次调用计费信息")

    model_config = {"extra": "ignore"}


class AgentResponse(BaseModel):
    """Agent响应模型"""
    requestId: str = Field(default="", description="请求ID")
    choices: List[AgentChoice] = Field(default_factory=list, description="响应选项列表")

    model_config = {"extra": "ignore"}


class ExtractionResult(BaseModel):
    """提取结果模型"""
    extracted_value: Optional[str] = Field(None, description="提取的字段值")
    confidence: Optional[float] = Field(None, description="置信度")
    raw_response: str = Field(..., description="原始响应内容")
    success: bool = Field(..., description="提取是否成功")
    error: Optional[str] = Field(None, description="错误信息")


class Region(BaseModel):
    """溯源区域模型 - 表示某一页上的一个矩形区域"""
    page_idx: int = Field(..., description="页码索引（从0开始）；Excel 时为 sheet 索引")
    page_number: int = Field(..., description="页面号（从1开始，用于展示）")
    bbox: List[float] = Field(..., description="边界框坐标 [x0, y0, x1, y1]")
    text_segment: Optional[str] = Field(None, description="该区域对应的文本片段（可选，仅用于调试）")
    file_index: Optional[int] = Field(None, description="文件索引（多 Excel 文件时）")
    sheet_name: Optional[str] = Field(None, description="Sheet 名称（Excel）")
    cell_ref: Optional[str] = Field(None, description="单元格引用（Excel）")


class TracingResult(BaseModel):
    """溯源结果模型（V2 - 支持多区域）"""
    matched_text: Optional[str] = Field(None, description="匹配的文本")
    regions: Optional[List[Region]] = Field(None, description="溯源区域列表（支持跨页/多框）")
    
    # 兼容旧版本的单区域字段（Deprecated）
    page_idx: Optional[int] = Field(None, description="页码索引（从0开始）- 已废弃，使用 regions")
    page_number: Optional[int] = Field(None, description="页面号（从1开始）- 已废弃，使用 regions")
    bbox: Optional[List[float]] = Field(None, description="边界框坐标 - 已废弃，使用 regions")
    
    match_type: Optional[str] = Field(None, description="匹配类型：exact/fuzzy/anchor_stitch/llm")
    raw_response: Optional[str] = Field(None, description="原始响应内容")
    success: bool = Field(..., description="溯源是否成功")
    error: Optional[str] = Field(None, description="错误信息")


class AuditResult(BaseModel):
    """审核结果模型"""
    audit_fields: Optional[List[str]] = Field(None, description="审核字段列表")
    audit_rules: Optional[str] = Field(None, description="审核规则")
    audit_analysis: Optional[str] = Field(None, description="审核分析")
    audit_result: Optional[str] = Field(None, description="审核结果：通过/不通过/待确认")
    raw_response: str = Field(..., description="原始响应内容")
    success: bool = Field(..., description="审核是否成功")
    error: Optional[str] = Field(None, description="错误信息")


class ClassificationState(BaseModel):
    """文件分类State参数"""
    file_name: str = Field(..., description="文件名称")
    file_content: str = Field(..., description="文件内容（MinerU解析后的Markdown格式）")
    types_list: str = Field(..., description="可选的文件类型列表")


class ClassificationResult(BaseModel):
    """文件分类结果模型"""
    classified_file_type: Optional[str] = Field(None, description="分类后的文件类型（FileType枚举值）")
    confidence: Optional[float] = Field(None, description="分类置信度 (0-1)")
    reason: Optional[str] = Field(None, description="分类原因说明")
    raw_response: str = Field(..., description="原始响应内容")
    success: bool = Field(..., description="分类是否成功")
    error: Optional[str] = Field(None, description="错误信息")


class UnifiedExtractionState(BaseModel):
    """统一提取溯源 State 参数（Anchor Markdown 方案）"""
    file_content: str = Field(..., description="带锚点的 Markdown 文档内容")
    field_name: str = Field(..., description="字段名称")
    extraction_logic: str = Field(..., description="提取逻辑")
    reference_materials: str = Field(..., description="参考材料名称")


class UnifiedExtractionResult(BaseModel):
    """统一提取溯源结果模型（Anchor Markdown 方案）"""
    # 提取结果
    extracted_value: Optional[str] = Field(None, description="提取的字段值")
    confidence: Optional[float] = Field(default=0.0, description="置信度（默认0.0，避免None导致的格式化错误）")
    
    # 溯源结果（锚点 ID 列表）
    anchor_ids: List[str] = Field(default_factory=list, description="来源锚点 ID 列表")
    
    # 解析后的坐标信息（由后端根据 anchor_ids 查表填充）
    regions: Optional[List[Region]] = Field(None, description="溯源区域列表")
    
    # 兼容旧版本的单区域字段
    page_idx: Optional[int] = Field(None, description="页码索引（从0开始）")
    page_number: Optional[int] = Field(None, description="页面号（从1开始）")
    bbox: Optional[List[float]] = Field(None, description="边界框坐标")
    
    # 元数据
    raw_response: str = Field(default="", description="原始响应内容")
    success: bool = Field(..., description="提取是否成功")
    error: Optional[str] = Field(None, description="错误信息")

