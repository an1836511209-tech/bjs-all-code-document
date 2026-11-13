"""
LLM Agent客户端

提供LLM Agent调用功能，支持字段提取和字段溯源
"""

import re
import json
import time
import httpx
import traceback
from typing import Dict, Any, Optional, List, Union
from loguru import logger

from config.llm_config import AgentConfig
from src.services.llm.models import (
    AgentRequest,
    AgentResponse,
    ExtractionState,
    TracingState,
    AuditState,
    ClassificationState,
    ExtractionResult,
    TracingResult,
    AuditResult,
    ClassificationResult,
    UnifiedExtractionState,
    UnifiedExtractionResult,
    Region
)


# 全局单例实例
_llm_client_instances: Dict[str, 'LLMClient'] = {}


class LLMClient:
    """LLM Agent基础客户端"""
    
    def __init__(self, config: AgentConfig):
        """
        初始化LLM客户端
        
        Args:
            config: Agent配置
        """
        self.config = config
        self.client = httpx.AsyncClient(
            timeout=config.timeout,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "Content-Type": "application/json"
            }
        )
    
    async def call_agent(
        self,
        state: Dict[str, Any],
        user_input: str = ""
    ) -> AgentResponse:
        """
        调用Agent
        
        Args:
            state: 状态参数
            user_input: 用户输入
            
        Returns:
            AgentResponse: Agent响应
            
        Raises:
            Exception: 调用失败时抛出异常
        """
        request = AgentRequest(
            agentId=self.config.agent_id,
            userChatInput=user_input,
            state=state
        )
        
        # # ===== DEBUG: 输出完整的传入内容 =====
        # logger.debug("=" * 100)
        # logger.debug("【LLM 调用 - 完整请求内容】")
        # logger.debug(f"Agent ID: {self.config.agent_id}")
        # logger.debug(f"User Input: {user_input}")
        # logger.debug("-" * 100)
        # logger.debug("State 内容（完整）:")
        # for key, value in state.items():
        #     logger.debug(f"\n[{key}]:")
        #     if isinstance(value, str):
        #         logger.debug(value)  # 完整输出，不省略
        #     else:
        #         logger.debug(json.dumps(value, ensure_ascii=False, indent=2))
        # logger.debug("=" * 100)
        # ===== END DEBUG =====
        
        max_retries = self.config.max_retries
        last_error = None
        
        for attempt in range(max_retries):
            try:
                start_time = time.time()
                logger.debug(f"调用Agent，尝试 {attempt + 1}/{max_retries}")
                
                response = await self.client.post(
                    self.config.base_url,
                    json=request.model_dump()
                )
                response.raise_for_status()
                
                elapsed_time = (time.time() - start_time) * 1000  # 转换为毫秒
                
                response_data = response.json()
                agent_response = AgentResponse(**response_data)

                from src.services.llm.token_usage import record_agent_token_usage
                record_agent_token_usage(agent_response)

                bill = None
                if agent_response.choices:
                    for choice in reversed(agent_response.choices):
                        if choice.bill is not None:
                            bill = choice.bill
                            break

                if bill is not None:
                    logger.info(
                        f"Agent API 调用成功 | "
                        f"AgentID: {self.config.agent_id} | "
                        f"响应时间: {elapsed_time:.0f}ms | "
                        f"尝试次数: {attempt + 1}/{max_retries} | "
                        f"tokens: prompt={bill.promptTokens or 0}, "
                        f"completion={bill.completionTokens or 0}, "
                        f"total={bill.totalTokens or 0}"
                    )
                else:
                    logger.info(
                        f"Agent API 调用成功 | "
                        f"AgentID: {self.config.agent_id} | "
                        f"响应时间: {elapsed_time:.0f}ms | "
                        f"尝试次数: {attempt + 1}/{max_retries}"
                    )

                return agent_response
                
            except httpx.HTTPStatusError as e:
                elapsed_time = (time.time() - start_time) * 1000
                last_error = e
                error_detail = str(e) or repr(e) or type(e).__name__
                logger.warning(
                    f"Agent调用HTTP错误 (尝试 {attempt + 1}/{max_retries}) | "
                    f"响应时间: {elapsed_time:.0f}ms | "
                    f"错误类型: {type(e).__name__} | "
                    f"错误信息: {error_detail}"
                )
                logger.warning(f"响应内容: {e.response.text if e.response else 'N/A'}")
                
            except Exception as e:
                elapsed_time = (time.time() - start_time) * 1000
                last_error = e
                error_detail = str(e) or repr(e) or type(e).__name__
                logger.warning(
                    f"Agent调用异常 (尝试 {attempt + 1}/{max_retries}) | "
                    f"响应时间: {elapsed_time:.0f}ms | "
                    f"错误类型: {type(e).__name__} | "
                    f"错误信息: {error_detail}",
                    exc_info=True  # 打印完整堆栈
                )
        
        # 所有重试都失败
        error_msg = f"Agent调用失败，已重试{max_retries}次: {last_error}"
        logger.error(error_msg)
        raise Exception(error_msg)
    
    async def close(self):
        """关闭客户端"""
        await self.client.aclose()
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器退出"""
        await self.close()


class ExtractionAgent:
    """字段提取Agent"""
    
    def __init__(self, client: LLMClient):
        """
        初始化提取Agent
        
        Args:
            client: LLM客户端
        """
        self.client = client
    
    async def extract_field(
        self,
        file_content: str,
        field_name: str,
        extraction_logic: str,
        reference_materials: str
    ) -> ExtractionResult:
        """
        提取字段
        
        Args:
            file_content: 文件内容（content_list.json内容）
            field_name: 字段名称
            extraction_logic: 提取逻辑
            reference_materials: 参考材料
            
        Returns:
            ExtractionResult: 提取结果
        """
        start_time = time.time()
        try:
            state = ExtractionState(
                file_content=file_content,
                field_name=field_name,
                extraction_logic=extraction_logic,
                reference_materials=reference_materials
            )
            
            state_dict = state.model_dump()
            logger.info(f"调用提取Agent - 字段: {field_name}")
            
            response = await self.client.call_agent(state=state_dict)
            
            # 解析提取结果，取最后一个choice
            if not response.choices:
                logger.warning(f"提取Agent响应中没有choices")
                return ExtractionResult(
                    raw_response="",
                    success=False,
                    error="响应中没有choices"
                )
            
            last_choice = response.choices[-1].content
            logger.info(f"提取Agent响应内容: {last_choice}")
            
            # 使用正则解析JSON对象
            extraction_data = self._parse_extraction_json(last_choice)
            
            extracted_value = extraction_data.get('value') if extraction_data else None
            confidence = extraction_data.get('confidence') if extraction_data else None
            
            if extracted_value is None:
                logger.warning(f"无法从响应中解析提取结果，完整响应: {last_choice}")
            
            elapsed_time = (time.time() - start_time) * 1000
            logger.info(
                f"提取Agent完成 | "
                f"字段: {field_name} | "
                f"总耗时: {elapsed_time:.0f}ms | "
                f"结果: {'成功' if extracted_value else '失败'}"
            )
            
            return ExtractionResult(
                extracted_value=extracted_value,
                confidence=confidence,
                raw_response=last_choice,
                success=extracted_value is not None,
                error=None if extracted_value else "无法解析提取结果"
            )
            
        except Exception as e:
            elapsed_time = (time.time() - start_time) * 1000
            error_detail = str(e) or repr(e) or type(e).__name__
            logger.error(
                f"字段提取失败 | "
                f"字段: {field_name} | "
                f"总耗时: {elapsed_time:.0f}ms | "
                f"错误类型: {type(e).__name__} | "
                f"错误信息: {error_detail}",
                exc_info=True
            )
            return ExtractionResult(
                raw_response="",
                success=False,
                error=error_detail
            )
    
    def _parse_extraction_json(self, content: str) -> Optional[Dict[str, Any]]:
        """
        解析提取结果的 JSON 数据
        
        从响应内容中提取JSON对象
        
        Args:
            content: 响应内容
            
        Returns:
            Optional[Dict]: 包含 value 和 confidence 的字典，解析失败返回None
        """
        try:
            # 尝试匹配 ```json ... ``` 格式
            json_pattern = r'```json\s*(\{.*?\})\s*```'
            match = re.search(json_pattern, content, re.DOTALL)
            
            data = None
            if match:
                json_str = match.group(1)
                data = json.loads(json_str)
            else:
                # 如果没有匹配到，尝试直接解析整个内容
                try:
                    data = json.loads(content)
                except:
                    pass
            
            if data:
                # 提取字段值
                extracted_value = None
                for key in ["提取结果", "extracted_value", "result", "value"]:
                    if key in data:
                        raw_value = data[key]
                        # 智能转换：dict/list 转 JSON 字符串，其他类型转字符串
                        if isinstance(raw_value, (dict, list)):
                            # 使用 json.dumps 确保双引号格式（标准 JSON）
                            extracted_value = json.dumps(raw_value, ensure_ascii=False, indent=None)
                        elif isinstance(raw_value, str):
                            # 已经是字符串，保持原样
                            extracted_value = raw_value
                        else:
                            # 数字、布尔值等其他类型，转为字符串
                            extracted_value = str(raw_value)
                        break
                
                # 提取 confidence，如果不存在则使用默认值 0.8
                confidence = data.get("confidence") or data.get("置信度") or 0.8
                
                return {
                    'value': extracted_value,
                    'confidence': confidence
                }
            
            logger.warning(f"无法解析提取结果，原始内容: {content[:200]}...")
            return None
            
        except Exception as e:
            logger.error(f"解析提取结果异常: {e}")
            return None


class TracingAgent:
    """字段溯源Agent"""
    
    def __init__(self, client: LLMClient):
        """
        初始化溯源Agent
        
        Args:
            client: LLM客户端
        """
        self.client = client
    
    async def trace_field(
        self,
        file_content: str,
        field_name: str,
        extraction_logic: str,
        reference_materials: str,
        extraction_result: str
    ) -> TracingResult:
        """
        溯源字段
        
        Args:
            file_content: 文件内容（middle.json内容）
            field_name: 字段名称
            extraction_logic: 提取逻辑
            reference_materials: 参考材料
            extraction_result: 提取结果
            
        Returns:
            TracingResult: 溯源结果
        """
        start_time = time.time()
        try:
            state = TracingState(
                file_content=file_content,
                field_name=field_name,
                extraction_logic=extraction_logic,
                reference_materials=reference_materials,
                extraction_result=extraction_result
            )
            
            state_dict = state.model_dump()
            logger.info(f"调用溯源Agent - 字段: {field_name}")
            
            response = await self.client.call_agent(state=state_dict)
            
            # 解析溯源结果，取最后一个choice
            if not response.choices:
                logger.warning(f"溯源Agent响应中没有choices")
                return TracingResult(
                    raw_response="",
                    success=False,
                    error="响应中没有choices"
                )
            
            last_choice = response.choices[-1].content
            logger.info(f"溯源Agent响应内容: {last_choice}")
            
            # 解析溯源结果（V2 - 支持多 regions）
            tracing_data = self._parse_tracing_result(last_choice)
            
            if tracing_data and isinstance(tracing_data, dict):
                # 检查状态
                status = tracing_data.get("status", "success")
                if status == "not_found":
                    return TracingResult(
                        raw_response=last_choice,
                        success=False,
                        error="LLM未找到匹配位置"
                    )
                
                # 解析 regions（新格式）
                regions_data = tracing_data.get("regions", [])
                regions = []
                
                if regions_data and isinstance(regions_data, list):
                    from src.services.llm.models import Region
                    for region_dict in regions_data:
                        if not isinstance(region_dict, dict):
                            continue
                        page_idx = region_dict.get("page_idx")
                        bbox = region_dict.get("bbox")
                        if page_idx is not None and bbox:
                            regions.append(Region(
                                page_idx=page_idx,
                                page_number=page_idx + 1,
                                bbox=bbox,
                                text_segment=None
                            ))
                
                # 兼容旧格式（单个 bbox）
                if not regions:
                    page_idx = tracing_data.get("page_idx")
                    bbox = tracing_data.get("bbox")
                    if page_idx is not None and bbox:
                        from src.services.llm.models import Region
                        regions.append(Region(
                            page_idx=page_idx,
                            page_number=page_idx + 1,
                            bbox=bbox,
                            text_segment=None
                        ))
                
                if not regions:
                    return TracingResult(
                        raw_response=last_choice,
                        success=False,
                        error="LLM返回的坐标数据无效"
                    )
                
                # 构建返回结果（兼容旧字段）
                first_region = regions[0]
                elapsed_time = (time.time() - start_time) * 1000
                logger.info(
                    f"溯源Agent完成 | "
                    f"字段: {field_name} | "
                    f"总耗时: {elapsed_time:.0f}ms | "
                    f"结果: 成功 | "
                    f"区域数: {len(regions)}"
                )
                
                return TracingResult(
                    matched_text=extraction_result,
                    regions=regions,
                    page_idx=first_region.page_idx,
                    page_number=first_region.page_number,
                    bbox=first_region.bbox,
                    match_type="llm",
                    raw_response=last_choice,
                    success=True,
                    error=None
                )
                
            else:
                error_msg = "无法解析溯源结果"
                if tracing_data and not isinstance(tracing_data, dict):
                    error_msg = f"溯源结果类型错误: {type(tracing_data)}"
                elapsed_time = (time.time() - start_time) * 1000
                logger.warning(
                    f"溯源Agent失败 | "
                    f"字段: {field_name} | "
                    f"总耗时: {elapsed_time:.0f}ms | "
                    f"错误: {error_msg}"
                )
                return TracingResult(
                    raw_response=last_choice,
                    success=False,
                    error=error_msg
                )
            
        except Exception as e:
            elapsed_time = (time.time() - start_time) * 1000
            error_detail = str(e) or repr(e) or type(e).__name__
            logger.error(
                f"字段溯源失败 | "
                f"字段: {field_name} | "
                f"总耗时: {elapsed_time:.0f}ms | "
                f"错误类型: {type(e).__name__} | "
                f"错误信息: {error_detail}",
                exc_info=True
            )
            return TracingResult(
                raw_response="",
                success=False,
                error=error_detail
            )
    
    def _normalize_matched_text(self, matched_text: Any) -> Optional[str]:
        """
        标准化 matched_text 为字符串
        
        处理多种类型：
        - str: 直接返回
        - dict/list: 转为 JSON 字符串
        - None: 返回 None
        - 其他: 转为字符串
        
        Args:
            matched_text: 原始 matched_text（可能是 str/dict/list/None）
            
        Returns:
            Optional[str]: 标准化后的字符串
        """
        if matched_text is None:
            return None
        
        if isinstance(matched_text, str):
            return matched_text
        
        if isinstance(matched_text, (dict, list)):
            try:
                return json.dumps(matched_text, ensure_ascii=False)
            except Exception as e:
                logger.warning(f"matched_text 转 JSON 失败: {e}, 使用 str() 转换")
                return str(matched_text)
        
        # 其他类型，直接转字符串
        return str(matched_text)
    
    def _parse_tracing_result(self, content: str) -> Optional[Dict[str, Any]]:
        """
        解析溯源结果
        
        从响应内容中提取JSON对象中的定位结果
        
        Args:
            content: 响应内容
            
        Returns:
            Optional[Dict]: 溯源数据，解析失败返回None
        """
        try:
            # 尝试匹配 ```json ... ``` 格式
            json_pattern = r'```json\s*(\{.*?\})\s*```'
            match = re.search(json_pattern, content, re.DOTALL)
            
            if match:
                json_str = match.group(1)
                data = json.loads(json_str)
                
                logger.debug(f"解析到的JSON数据类型: {type(data)}, 内容: {data}")
                
                # 尝试获取定位结果
                result = None
                if "定位结果" in data:
                    result = data["定位结果"]
                elif "tracing_result" in data:
                    result = data["tracing_result"]
                elif "location" in data:
                    result = data["location"]
                
                # 类型检查：确保返回的是字典
                if result is not None:
                    if isinstance(result, dict):
                        logger.debug(f"溯源结果解析成功: {result}")
                        return result
                    else:
                        logger.error(f"溯源结果类型错误: 期望dict，实际为 {type(result)}, 内容: {result}")
                        return None
            
            logger.warning(f"无法解析溯源结果，原始内容: {content[:200]}...")
            return None
            
        except Exception as e:
            logger.error(f"解析溯源结果异常: {e}", exc_info=True)
            return None


class AuditAgent:
    """字段审核Agent"""
    
    def __init__(self, client: LLMClient):
        """
        初始化审核Agent
        
        Args:
            client: LLM客户端
        """
        self.client = client
    
    async def audit_field(
        self,
        audit_type: str,
        field_name: str,
        audit_content: str,
        auto_process_rules: str,
        audit_data_sources: Dict[str, Any],
        user_input_value: Optional[str],
        reference_materials: Dict[str, Any]
    ) -> AuditResult:
        """
        审核字段
        
        Args:
            audit_type: 审核类型（字段审核/文件审核）
            field_name: 字段名称
            audit_content: 审核内容
            auto_process_rules: 自动处理规则
            audit_data_sources: 审核数据源（结构化对象）
            user_input_value: 用户输入的字段值
            reference_materials: 参考材料（从附件提取的结果，结构化对象）
            
        Returns:
            AuditResult: 审核结果
        """
        start_time = time.time()
        try:
            # 构建审核数据源字符串（格式化为易读的文本）
            data_sources_str = self._format_audit_data_sources(audit_data_sources)
            
            # 构建用户输入键值对
            user_input_key = f"{field_name}：{user_input_value}" if user_input_value else ""
            
            # 构建参考材料字符串（格式化为易读的文本）
            reference_materials_str = self._format_reference_materials(reference_materials)
            
            state = AuditState(
                audit_type=audit_type,
                field_name=field_name,
                audit_content=audit_content,
                auto_process_rules=auto_process_rules,
                audit_data_sources=data_sources_str,
                user_input_key=user_input_key,
                reference_materials=reference_materials_str
            )
            
            state_dict = state.model_dump()
            logger.info(f"调用审核Agent - 字段: {field_name}")
            
            response = await self.client.call_agent(state=state_dict)
            
            # 解析审核结果，取最后一个choice
            if not response.choices:
                return AuditResult(
                    raw_response="",
                    success=False,
                    error="响应中没有choices"
                )
            
            last_choice = response.choices[-1].content
            logger.info(f"审核Agent响应内容: {last_choice}...")
            
            # 解析审核结果
            audit_data = self._parse_audit_result(last_choice)
            
            if audit_data and isinstance(audit_data, dict):
                elapsed_time = (time.time() - start_time) * 1000
                audit_result_str = audit_data.get("审核结果", "未知")
                logger.info(
                    f"审核Agent完成 | "
                    f"字段: {field_name} | "
                    f"总耗时: {elapsed_time:.0f}ms | "
                    f"结果: 成功 | "
                    f"审核结论: {audit_result_str}"
                )
                
                return AuditResult(
                    audit_fields=audit_data.get("审核字段"),
                    audit_rules=audit_data.get("审核规则"),
                    audit_analysis=audit_data.get("审核分析"),
                    audit_result=audit_data.get("审核结果"),
                    raw_response=last_choice,
                    success=True,
                    error=None
                )
            else:
                error_msg = "无法解析审核结果"
                elapsed_time = (time.time() - start_time) * 1000
                logger.warning(
                    f"审核Agent失败 | "
                    f"字段: {field_name} | "
                    f"总耗时: {elapsed_time:.0f}ms | "
                    f"错误: {error_msg}"
                )
                return AuditResult(
                    raw_response=last_choice,
                    success=False,
                    error=error_msg
                )
            
        except Exception as e:
            elapsed_time = (time.time() - start_time) * 1000
            error_detail = str(e) or repr(e) or type(e).__name__
            logger.error(
                f"字段审核失败 | "
                f"字段: {field_name} | "
                f"总耗时: {elapsed_time:.0f}ms | "
                f"错误类型: {type(e).__name__} | "
                f"错误信息: {error_detail}",
                exc_info=True
            )
            return AuditResult(
                raw_response="",
                success=False,
                error=error_detail
            )
    
    def _format_audit_data_sources(self, data_sources: Union[List[str], Dict[str, Any]]) -> str:
        """
        格式化审核数据源为字符串（只描述数据源，不包含实际内容）
        
        Args:
            data_sources: 审核数据源描述（列表或字典）
            
        Returns:
            str: 格式化的字符串
        """
        try:
            if not data_sources:
                return ""
            
            # 新格式：data_sources 是字符串列表（只描述数据源）
            # 示例：["信息披露申请书 - 标的名称", "房屋所有权证 - 房屋地址", "抵押情况说明 - 全文"]
            if isinstance(data_sources, list):
                return "\n".join(data_sources)
            
            # 兼容旧格式：data_sources 是字典（包含实际数据，已不推荐）
            # {
            #     "材料名称1": {
            #         "字段1": "值1",
            #         "字段2": "值2"
            #     }
            # }
            parts = []
            for material_name, fields in data_sources.items():
                if isinstance(fields, dict):
                    for field_name in fields.keys():
                        parts.append(f"{material_name} - {field_name}")
                elif isinstance(fields, str):
                    # 如果是全文标识
                    parts.append(f"{material_name} - 全文")
            
            return "\n".join(parts)
            
        except Exception as e:
            logger.error(f"格式化审核数据源失败: {e}")
            return ""
    
    def _format_reference_materials(self, materials: Dict[str, Any]) -> str:
        """
        格式化参考材料为字符串
        
        Args:
            materials: 参考材料（结构化对象）
            
        Returns:
            str: 格式化的字符串
        """
        try:
            if not materials:
                return ""
            
            # materials 格式示例：
            # {
            #     "材料名称1 - 字段1": "值1",
            #     "材料名称2 - 字段2": "值2"
            # }
            
            parts = []
            for key, value in materials.items():
                # 智能格式化值：dict/list 转 JSON 字符串（标准格式）
                if isinstance(value, (dict, list)):
                    formatted_value = json.dumps(value, ensure_ascii=False, indent=2)
                else:
                    formatted_value = str(value) if value is not None else ""
                parts.append(f"{key}：{formatted_value}")
            
            return "\n".join(parts)
            
        except Exception as e:
            logger.error(f"格式化参考材料失败: {e}")
            return json.dumps(materials, ensure_ascii=False)
    
    def _parse_audit_result(self, content: str) -> Optional[Dict[str, Any]]:
        """
        解析审核结果
        
        从响应内容中提取JSON对象中的审核结果
        
        Args:
            content: 响应内容
            
        Returns:
            Optional[Dict]: 审核数据，解析失败返回None
        """
        try:
            # 尝试匹配 ```json ... ``` 格式
            json_pattern = r'```json\s*(\{.*?\})\s*```'
            match = re.search(json_pattern, content, re.DOTALL)
            
            if match:
                json_str = match.group(1)
                data = json.loads(json_str)
                
                logger.debug(f"解析到的审核JSON数据: {data}")
                return data
            
            # 如果没有匹配到，尝试直接解析整个内容
            try:
                data = json.loads(content)
                logger.debug(f"直接解析审核JSON数据: {data}")
                return data
            except:
                pass
            
            logger.warning(f"无法解析审核结果，原始内容: {content[:200]}...")
            return None
            
        except Exception as e:
            logger.error(f"解析审核结果异常: {e}", exc_info=True)
            return None


class UnifiedExtractionAgent:
    """
    统一提取溯源 Agent（Anchor Markdown 方案）
    
    将字段提取和溯源合并为一次 LLM 调用：
    1. LLM 接收带锚点的 Markdown 文档
    2. LLM 提取字段值并返回对应的锚点 ID
    3. 后端根据锚点 ID 查表获取精确坐标
    """
    
    def __init__(self, client: LLMClient):
        """
        初始化统一提取Agent
        
        Args:
            client: LLM客户端
        """
        self.client = client
    
    async def extract_and_trace(
        self,
        file_content: str,
        field_name: str,
        extraction_logic: str,
        reference_materials: str
    ) -> UnifiedExtractionResult:
        """
        统一提取与溯源
        
        Args:
            file_content: 带锚点的 Markdown 文档内容
            field_name: 字段名称
            extraction_logic: 提取逻辑
            reference_materials: 参考材料名称
            
        Returns:
            UnifiedExtractionResult: 包含提取值和锚点 ID 的结果
        """
        start_time = time.time()
        try:
            state = UnifiedExtractionState(
                file_content=file_content,
                field_name=field_name,
                extraction_logic=extraction_logic,
                reference_materials=reference_materials
            )
            
            state_dict = state.model_dump()
            logger.info(f"调用统一提取Agent - 字段: {field_name}")
            
            response = await self.client.call_agent(state=state_dict)
            
            # 解析结果，取最后一个 choice
            if not response.choices:
                logger.warning(f"统一提取Agent响应中没有choices")
                return UnifiedExtractionResult(
                    raw_response="",
                    success=False,
                    error="响应中没有choices"
                )
            
            last_choice = response.choices[-1].content
            logger.info(f"统一提取Agent响应内容长度: {len(last_choice)} 字符")
            logger.debug(f"统一提取Agent完整响应:\n{last_choice}")
            
            # 解析 JSON 结果
            result_data = self._parse_unified_result(last_choice)
            
            if result_data is None:
                # 构建详细的错误信息，包含响应预览
                response_preview = last_choice[:300].replace('\n', ' ') if last_choice else "(空响应)"
                error_detail = f"无法解析提取结果，响应内容不符合预期JSON格式。响应预览: {response_preview}"
                logger.warning(f"无法解析统一提取结果，完整响应: {last_choice}")
                return UnifiedExtractionResult(
                    raw_response=last_choice,
                    success=False,
                    error=error_detail
                )
            
            extracted_value = result_data.get('extracted_value')
            confidence = result_data.get('confidence', 0.8)
            anchor_ids = result_data.get('anchor_ids', [])
            
            elapsed_time = (time.time() - start_time) * 1000
            
            # 空字符串也算成功（表示 LLM 正确返回了"未找到"）
            # 只有 None 或解析失败才算失败
            is_success = extracted_value is not None
            
            # 如果提取失败，构建错误信息
            error_msg = None
            if not is_success:
                error_msg = "LLM返回的extracted_value为null，未能提取到有效值"
            
            logger.info(
                f"统一提取Agent完成 | "
                f"字段: {field_name} | "
                f"总耗时: {elapsed_time:.0f}ms | "
                f"结果: {'成功' if is_success else '失败'} | "
                f"锚点数: {len(anchor_ids)}"
            )
            
            return UnifiedExtractionResult(
                extracted_value=extracted_value,
                confidence=confidence,
                anchor_ids=anchor_ids,
                raw_response=last_choice,
                success=is_success,
                error=error_msg
            )
            
        except Exception as e:
            elapsed_time = (time.time() - start_time) * 1000
            error_detail = str(e) or repr(e) or type(e).__name__
            logger.error(
                f"统一提取失败 | "
                f"字段: {field_name} | "
                f"总耗时: {elapsed_time:.0f}ms | "
                f"错误类型: {type(e).__name__} | "
                f"错误信息: {error_detail}",
                exc_info=True
            )
            return UnifiedExtractionResult(
                raw_response="",
                success=False,
                error=error_detail
            )
    
    def _parse_unified_result(self, content: str) -> Optional[Dict[str, Any]]:
        """
        解析统一提取结果的 JSON 数据
        
        预期格式：
        {
            "field_name": "字段名",
            "extracted_value": "提取值",  # 可以是字符串、数字、对象或数组
            "confidence": 0.95,
            "anchor_ids": ["0-2", "0-5"]
        }
        
        Args:
            content: 响应内容
            
        Returns:
            Optional[Dict]: 解析后的字典，失败返回 None
        """
        try:
            data = None
            
            # 策略1: 尝试匹配 ```json ... ``` 格式（支持对象和数组，使用贪婪匹配）
            # 优先匹配最后一个或最完整的JSON代码块
            json_patterns = [
                r'```json\s*([\s\S]*?)\s*```',  # 标准 json 代码块
                r'```\s*([\{\[][\s\S]*?[\}\]])\s*```',  # 无语言标识的代码块
            ]
            
            for pattern in json_patterns:
                matches = re.findall(pattern, content)
                if matches:
                    # 优先使用最后一个匹配（通常在 ### Result: 后面）
                    json_str = matches[-1].strip()
                    try:
                        parsed = json.loads(json_str)
                        
                        # 如果是数组，取第一个元素
                        if isinstance(parsed, list) and len(parsed) > 0:
                            data = parsed[0]
                        elif isinstance(parsed, dict):
                            data = parsed
                        
                        if data:
                            break
                    except json.JSONDecodeError:
                        # 尝试修复 JSON（复用批量提取的修复逻辑）
                        fixed_json = self._try_fix_single_json(json_str)
                        if fixed_json:
                            try:
                                parsed = json.loads(fixed_json)
                                if isinstance(parsed, list) and len(parsed) > 0:
                                    data = parsed[0]
                                elif isinstance(parsed, dict):
                                    data = parsed
                                if data:
                                    logger.info("单字段 JSON 修复成功")
                                    break
                            except json.JSONDecodeError:
                                pass
                        continue
            
            # 策略2: 尝试直接解析整个内容
            if not data:
                try:
                    parsed = json.loads(content)
                    # 如果是数组，取第一个元素
                    if isinstance(parsed, list) and len(parsed) > 0:
                        data = parsed[0]
                    elif isinstance(parsed, dict):
                        data = parsed
                except json.JSONDecodeError:
                    pass
            
            # 策略3: 尝试查找包含 extracted_value 的 JSON 对象（使用嵌套括号匹配）
            if not data:
                # 查找所有可能的JSON对象
                json_obj_pattern = r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*"extracted_value"[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
                obj_matches = re.findall(json_obj_pattern, content, re.DOTALL)
                
                for obj_str in reversed(obj_matches):  # 从后向前尝试
                    try:
                        data = json.loads(obj_str)
                        if data:
                            break
                    except json.JSONDecodeError:
                        continue
            
            if data and isinstance(data, dict):
                # 提取字段值（支持多种 key 名）
                extracted_value = None
                for key in ["extracted_value", "value", "提取结果", "result"]:
                    if key in data:
                        raw_value = data[key]
                        # 智能处理不同类型的值
                        if isinstance(raw_value, (dict, list)):
                            # 保持对象和数组类型，序列化为JSON字符串
                            extracted_value = json.dumps(raw_value, ensure_ascii=False)
                        elif isinstance(raw_value, (int, float)):
                            # 数字类型转为字符串
                            extracted_value = str(raw_value)
                        elif isinstance(raw_value, bool):
                            # 布尔类型转为字符串
                            extracted_value = str(raw_value).lower()
                        elif isinstance(raw_value, str):
                            # 字符串直接使用
                            extracted_value = raw_value
                        elif raw_value is None:
                            # None 转为空字符串
                            extracted_value = ""
                        else:
                            # 其他类型尝试转为字符串
                            extracted_value = str(raw_value)
                        break
                
                # 提取置信度
                confidence_raw = data.get("confidence") or data.get("置信度")
                if confidence_raw is not None:
                    try:
                        confidence = float(confidence_raw)
                    except (ValueError, TypeError):
                        confidence = 0.8
                else:
                    confidence = 0.8
                
                # 提取锚点 ID（支持多种格式）
                anchor_ids_raw = data.get("anchor_ids") or data.get("source_anchor") or data.get("anchors") or []
                anchor_ids = self._normalize_anchor_ids(anchor_ids_raw)
                
                return {
                    'extracted_value': extracted_value,
                    'confidence': confidence,
                    'anchor_ids': anchor_ids
                }
            
            logger.warning(f"无法解析统一提取结果，原始内容: {content[:200]}...")
            return None
            
        except Exception as e:
            logger.error(f"解析统一提取结果异常: {e}")
            logger.debug(f"异常详情: {traceback.format_exc()}")
            return None
    
    def _normalize_anchor_ids(self, anchor_ids_raw: Any) -> List[str]:
        """
        标准化锚点 ID 列表
        
        支持格式：
        - 列表: ["0-1", "0-2"]
        - 单个字符串: "0-1"
        - 逗号分隔: "0-1, 0-2"
        
        Args:
            anchor_ids_raw: 原始锚点数据
            
        Returns:
            标准化后的锚点 ID 列表
        """
        if anchor_ids_raw is None:
            return []
        
        if isinstance(anchor_ids_raw, list):
            return [str(aid).strip() for aid in anchor_ids_raw if aid]
        
        if isinstance(anchor_ids_raw, str):
            if ',' in anchor_ids_raw:
                return [aid.strip() for aid in anchor_ids_raw.split(',') if aid.strip()]
            return [anchor_ids_raw.strip()] if anchor_ids_raw.strip() else []
        
        return []
    
    async def extract_batch(
        self,
        file_content: str,
        fields_info: List[Dict[str, str]],
        reference_materials: str
    ) -> List[UnifiedExtractionResult]:
        """
        批量提取与溯源
        
        一次 LLM 调用提取多个字段，适用于同一文档的多字段提取场景。
        
        Args:
            file_content: 带锚点的 Markdown 文档内容
            fields_info: 字段信息列表，格式：[{"field_name": "...", "extraction_logic": "..."}, ...]
            reference_materials: 参考材料名称
            
        Returns:
            List[UnifiedExtractionResult]: 批量提取结果列表（顺序与 fields_info 一致）
        """
        start_time = time.time()
        try:
            # 构建批量提取的 state（extraction_logic 由调用方构建）
            # 这里我们需要一个特殊的 state，包含多个字段
            # 但为了复用现有的 UnifiedExtractionState，我们将批量信息放在 extraction_logic 中
            
            # 提取所有字段名（用于日志）
            field_names = [f["field_name"] for f in fields_info]
            
            # 注意：extraction_logic 已经由调用方构建好（包含所有字段的提取逻辑）
            # 我们这里需要从 fields_info[0] 获取，因为调用方会将完整逻辑放在第一个元素
            if not fields_info:
                return []
            
            # 实际上，调用方会传入一个特殊构建的 extraction_logic
            # 这里我们直接使用第一个字段的 extraction_logic（它包含了所有字段）
            batch_extraction_logic = fields_info[0]["extraction_logic"]
            
            state = UnifiedExtractionState(
                file_content=file_content,
                field_name=", ".join(field_names),  # 字段名列表（用于日志）
                extraction_logic=batch_extraction_logic,
                reference_materials=reference_materials
            )
            
            state_dict = state.model_dump()
            logger.info(f"调用批量提取Agent - 字段数: {len(fields_info)}, 字段: {field_names}")
            
            response = await self.client.call_agent(state=state_dict)
            
            # 解析结果，取最后一个 choice
            if not response.choices:
                logger.warning(f"批量提取Agent响应中没有choices")
                # 返回失败结果列表
                return [
                    UnifiedExtractionResult(
                        raw_response="",
                        success=False,
                        error="响应中没有choices"
                    )
                    for _ in fields_info
                ]
            
            last_choice = response.choices[-1].content
            logger.info(f"批量提取Agent响应内容长度: {len(last_choice)} 字符")
            logger.debug(f"批量提取Agent完整响应:\n{last_choice}")
            
            # 解析批量结果
            batch_data = self._parse_batch_result(last_choice)
            
            if batch_data is None:
                logger.warning(f"无法解析批量提取结果，完整响应: {last_choice}...")
                # 返回失败结果列表
                return [
                    UnifiedExtractionResult(
                        raw_response=last_choice,
                        success=False,
                        error="无法解析批量提取结果"
                    )
                    for _ in fields_info
                ]
            
            # 将解析结果匹配到对应的字段
            results = []
            for field_info in fields_info:
                field_name = field_info["field_name"]
                
                # 在批量结果中查找匹配的字段
                matched_item = None
                for item in batch_data:
                    if self._match_result_to_field(item, field_name):
                        matched_item = item
                        break
                
                if matched_item:
                    extracted_value = matched_item.get('extracted_value')
                    confidence = matched_item.get('confidence', 0.8)
                    anchor_ids = self._normalize_anchor_ids(matched_item.get('anchor_ids', []))
                    
                    # 空字符串也算成功（表示 LLM 正确返回了"未找到"）
                    # 只有 None 或解析失败才算失败
                    is_success = extracted_value is not None
                    
                    results.append(UnifiedExtractionResult(
                        extracted_value=extracted_value,
                        confidence=confidence,
                        anchor_ids=anchor_ids,
                        raw_response=last_choice,
                        success=is_success,
                        error=None
                    ))
                else:
                    # 未找到匹配的字段结果
                    logger.warning(f"批量结果中未找到字段 {field_name} 的提取结果")
                    results.append(UnifiedExtractionResult(
                        raw_response=last_choice,
                        success=False,
                        error=f"批量结果中未找到字段 {field_name}"
                    ))
            
            elapsed_time = (time.time() - start_time) * 1000
            success_count = sum(1 for r in results if r.success)
            
            # 输出每个字段的提取结果摘要
            for i, (field_info, result) in enumerate(zip(fields_info, results)):
                field_name = field_info["field_name"]
                status = "成功" if result.success else "失败"
                value_preview = str(result.extracted_value)[:500] if result.extracted_value else "(空)"
                # 防止 confidence 为 None 导致格式化错误
                confidence_value = result.confidence if result.confidence is not None else 0.0
                logger.debug(
                    f"  字段 {i+1}/{len(fields_info)}: {field_name} | "
                    f"状态: {status} | "
                    f"值: {value_preview} | "
                    f"置信度: {confidence_value:.2f} | "
                    f"锚点数: {len(result.anchor_ids)}"
                )
            
            logger.info(
                f"批量提取Agent完成 | "
                f"字段数: {len(fields_info)} | "
                f"总耗时: {elapsed_time:.0f}ms | "
                f"成功: {success_count}/{len(fields_info)} | "
                f"空值: {sum(1 for r in results if r.success and (not r.extracted_value or r.extracted_value == ''))}/{len(fields_info)}"
            )
            
            return results
            
        except Exception as e:
            elapsed_time = (time.time() - start_time) * 1000
            error_detail = str(e) or repr(e) or type(e).__name__
            logger.error(
                f"批量提取失败 | "
                f"字段数: {len(fields_info) if fields_info else 0} | "
                f"总耗时: {elapsed_time:.0f}ms | "
                f"错误类型: {type(e).__name__} | "
                f"错误信息: {error_detail}",
                exc_info=True
            )
            # 返回失败结果列表，使用特殊错误标记以便触发重试
            return [
                UnifiedExtractionResult(
                    raw_response="",
                    success=False,
                    error="批量提取异常，需要重试"  # 使用统一的错误信息标记
                )
                for _ in fields_info
            ]
    
    def _parse_batch_result(self, content: str) -> Optional[List[Dict[str, Any]]]:
        """
        解析批量提取结果的 JSON 数据
        
        预期格式：
        [
            {
                "field_name": "字段名1",
                "extracted_value": "提取值1",
                "confidence": 0.95,
                "anchor_ids": ["0-2", "0-5"]
            },
            {
                "field_name": "字段名2",
                "extracted_value": "提取值2",
                "confidence": 0.90,
                "anchor_ids": ["1-3"]
            }
        ]
        
        Args:
            content: 响应内容
            
        Returns:
            Optional[List[Dict]]: 解析后的批量结果列表，失败返回 None
        """
        try:
            json_str = None
            data = None
            
            # 方法1: 查找 ```json ... ``` 代码块（使用字符串查找，避免正则嵌套括号问题）
            json_start = content.find('```json')
            if json_start != -1:
                # 跳过 ```json 标记，找到下一行开始
                json_start = content.find('\n', json_start)
                if json_start != -1:
                    json_start += 1
                    # 查找结束的 ```
                    json_end = content.find('```', json_start)
                    if json_end != -1:
                        json_str = content[json_start:json_end].strip()
            
            # 尝试解析提取到的 JSON 字符串
            if json_str:
                try:
                    data = json.loads(json_str)
                except json.JSONDecodeError:
                    logger.debug(f"从代码块提取的内容无法解析为JSON: {json_str[:200]}...")
                    # 尝试修复 JSON
                    fixed_json = self._try_fix_json(json_str)
                    if fixed_json:
                        try:
                            data = json.loads(fixed_json)
                            logger.info("JSON 修复成功")
                        except json.JSONDecodeError:
                            logger.debug("JSON 修复后仍无法解析")
            
            # 方法2: 如果代码块解析失败，尝试直接解析整个内容
            if data is None:
                try:
                    data = json.loads(content.strip())
                except json.JSONDecodeError:
                    pass
            
            # 方法3: 如果还是失败，尝试找到 JSON 数组的起始和结束位置
            if data is None:
                # 查找第一个 [ 和最后一个 ] 之间的内容
                first_bracket = content.find('[')
                last_bracket = content.rfind(']')
                if first_bracket != -1 and last_bracket > first_bracket:
                    potential_json = content[first_bracket:last_bracket + 1]
                    try:
                        data = json.loads(potential_json)
                    except json.JSONDecodeError:
                        # 尝试修复 JSON
                        fixed_json = self._try_fix_json(potential_json)
                        if fixed_json:
                            try:
                                data = json.loads(fixed_json)
                                logger.info("JSON 修复成功（方法3）")
                            except json.JSONDecodeError:
                                pass
            
            if data and isinstance(data, list):
                # 验证每个元素都包含必要的字段
                valid_items = []
                for item in data:
                    if isinstance(item, dict) and "field_name" in item:
                        # 标准化每个字段的值
                        extracted_value = None
                        for key in ["extracted_value", "value", "提取结果", "result"]:
                            if key in item:
                                raw_value = item[key]
                                if isinstance(raw_value, (dict, list)):
                                    extracted_value = json.dumps(raw_value, ensure_ascii=False)
                                elif isinstance(raw_value, str):
                                    extracted_value = raw_value
                                else:
                                    extracted_value = str(raw_value) if raw_value is not None else ""
                                break
                        
                        confidence = item.get("confidence") or item.get("置信度") or 0.8
                        anchor_ids = item.get("anchor_ids") or item.get("source_anchor") or item.get("anchors") or []
                        
                        valid_items.append({
                            'field_name': item["field_name"],
                            'extracted_value': extracted_value,
                            'confidence': confidence,
                            'anchor_ids': anchor_ids
                        })
                
                if valid_items:
                    return valid_items
            
            logger.warning(f"无法解析批量提取结果，原始内容: {content}...")
            return None
            
        except Exception as e:
            logger.error(f"解析批量提取结果异常: {e}")
            return None
    
    def _try_fix_json(self, json_str: str) -> Optional[str]:
        """
        尝试修复损坏的 JSON 字符串
        
        主要修复场景：
        1. extracted_value 字段中包含未转义的双引号
        2. 字符串中包含未转义的换行符
        3. 字符串中包含未转义的控制字符
        
        Args:
            json_str: 可能损坏的 JSON 字符串
            
        Returns:
            Optional[str]: 修复后的 JSON 字符串，修复失败返回 None
        """
        try:
            # 策略1: 修复 extracted_value 字段中的未转义双引号
            # 这种情况通常发生在 LLM 返回的长文本中包含引号
            
            # 查找所有 "extracted_value": "..." 模式，并修复其中的未转义引号
            fixed = json_str
            
            # 首先修复常见的控制字符问题
            # 替换未转义的换行符（在字符串值中）
            # 注意：需要保留 JSON 结构中合法的换行符
            
            # 策略2: 逐个字段提取并重建 JSON
            # 使用正则表达式匹配每个字段对象
            field_pattern = r'\{\s*"field_name"\s*:\s*"([^"]+)"\s*,\s*"extracted_value"\s*:\s*"((?:[^"\\]|\\.)*)"\s*,\s*"confidence"\s*:\s*([0-9.]+)\s*,\s*"anchor_ids"\s*:\s*(\[[^\]]*\])\s*\}'
            
            matches = re.findall(field_pattern, fixed, re.DOTALL)
            if matches:
                # 成功匹配到标准格式的字段，直接返回
                return fixed
            
            # 策略3: 尝试修复 extracted_value 中的问题
            # 查找 "extracted_value": " 到下一个 ", "confidence" 之间的内容
            ev_pattern = r'"extracted_value"\s*:\s*"(.*?)"\s*,\s*"confidence"'
            
            def fix_extracted_value(match):
                """修复 extracted_value 字段中的特殊字符"""
                value = match.group(1)
                # 转义其中未转义的双引号（排除已经转义的）
                # 使用负向后行断言，避免重复转义
                fixed_value = re.sub(r'(?<!\\)"', r'\\"', value)
                # 转义未转义的换行符
                fixed_value = fixed_value.replace('\n', '\\n').replace('\r', '\\r')
                fixed_value = fixed_value.replace('\t', '\\t')
                return f'"extracted_value": "{fixed_value}", "confidence"'
            
            fixed = re.sub(ev_pattern, fix_extracted_value, fixed, flags=re.DOTALL)
            
            # 验证修复后的 JSON 是否有效
            try:
                json.loads(fixed)
                return fixed
            except json.JSONDecodeError:
                pass
            
            # 策略4: 更激进的修复 - 逐个解析 JSON 对象
            # 找到每个 { 开始的对象，尝试修复并重建数组
            result_items = []
            
            # 找到数组开始
            array_start = fixed.find('[')
            if array_start == -1:
                return None
            
            # 遍历每个对象
            pos = array_start + 1
            while pos < len(fixed):
                # 跳过空白
                while pos < len(fixed) and fixed[pos] in ' \n\r\t,':
                    pos += 1
                
                if pos >= len(fixed) or fixed[pos] == ']':
                    break
                
                if fixed[pos] == '{':
                    # 尝试找到对象的结束位置
                    # 使用简单的括号计数
                    obj_start = pos
                    depth = 1
                    pos += 1
                    in_string = False
                    escape_next = False
                    
                    while pos < len(fixed) and depth > 0:
                        char = fixed[pos]
                        
                        if escape_next:
                            escape_next = False
                        elif char == '\\':
                            escape_next = True
                        elif char == '"' and not escape_next:
                            in_string = not in_string
                        elif not in_string:
                            if char == '{':
                                depth += 1
                            elif char == '}':
                                depth -= 1
                        
                        pos += 1
                    
                    if depth == 0:
                        obj_str = fixed[obj_start:pos]
                        
                        # 尝试解析这个对象
                        try:
                            obj = json.loads(obj_str)
                            if "field_name" in obj:
                                result_items.append(obj)
                        except json.JSONDecodeError:
                            # 尝试修复这个单独的对象
                            try:
                                # 手动提取字段值
                                fn_match = re.search(r'"field_name"\s*:\s*"([^"]+)"', obj_str)
                                conf_match = re.search(r'"confidence"\s*:\s*([0-9.]+)', obj_str)
                                anchor_match = re.search(r'"anchor_ids"\s*:\s*(\[[^\]]*\])', obj_str)
                                
                                if fn_match:
                                    field_name = fn_match.group(1)
                                    confidence = float(conf_match.group(1)) if conf_match else 0.8
                                    anchor_ids = json.loads(anchor_match.group(1)) if anchor_match else []
                                    
                                    # 尝试提取 extracted_value
                                    ev_start = obj_str.find('"extracted_value"')
                                    if ev_start != -1:
                                        ev_value_start = obj_str.find(':', ev_start) + 1
                                        # 跳过空白和开始引号
                                        while ev_value_start < len(obj_str) and obj_str[ev_value_start] in ' \n\r\t':
                                            ev_value_start += 1
                                        if obj_str[ev_value_start] == '"':
                                            ev_value_start += 1
                                            
                                            # 找到 "confidence" 之前的位置作为结束
                                            ev_value_end = obj_str.find('", "confidence"', ev_value_start)
                                            if ev_value_end == -1:
                                                ev_value_end = obj_str.find('","confidence"', ev_value_start)
                                            
                                            if ev_value_end != -1:
                                                extracted_value = obj_str[ev_value_start:ev_value_end]
                                                result_items.append({
                                                    "field_name": field_name,
                                                    "extracted_value": extracted_value,
                                                    "confidence": confidence,
                                                    "anchor_ids": anchor_ids
                                                })
                            except Exception as e:
                                logger.debug(f"修复单个对象失败: {e}")
                else:
                    pos += 1
            
            if result_items:
                return json.dumps(result_items, ensure_ascii=False)
            
            return None
            
        except Exception as e:
            logger.debug(f"JSON 修复异常: {e}")
            return None
    
    def _try_fix_single_json(self, json_str: str) -> Optional[str]:
        """
        尝试修复单个 JSON 对象（用于单字段提取）
        
        主要修复 extracted_value 字段中的未转义字符
        
        Args:
            json_str: 可能损坏的 JSON 字符串
            
        Returns:
            Optional[str]: 修复后的 JSON 字符串，修复失败返回 None
        """
        try:
            fixed = json_str
            
            # 修复 extracted_value 中的未转义双引号
            ev_pattern = r'"extracted_value"\s*:\s*"(.*?)"\s*,\s*"confidence"'
            
            def fix_extracted_value(match):
                value = match.group(1)
                # 转义未转义的双引号
                fixed_value = re.sub(r'(?<!\\)"', r'\\"', value)
                # 转义未转义的换行符
                fixed_value = fixed_value.replace('\n', '\\n').replace('\r', '\\r').replace('\t', '\\t')
                return f'"extracted_value": "{fixed_value}", "confidence"'
            
            fixed = re.sub(ev_pattern, fix_extracted_value, fixed, flags=re.DOTALL)
            
            # 验证修复后的 JSON 是否有效
            json.loads(fixed)
            return fixed
            
        except Exception as e:
            logger.debug(f"单字段 JSON 修复异常: {e}")
            return None
    
    def _match_result_to_field(self, result_item: Dict, field_name: str) -> bool:
        """
        匹配结果项到字段
        
        Args:
            result_item: 批量结果中的单个字段结果
            field_name: 目标字段名
            
        Returns:
            bool: 是否匹配
        """
        item_field_name = result_item.get("field_name", "")
        
        # 精确匹配
        if item_field_name == field_name:
            return True
        
        # 去除空格后匹配（仅此一种容错）
        if item_field_name.strip() == field_name.strip():
            return True
        
        return False


class ClassificationAgent:
    """文件分类Agent"""
    
    def __init__(self, client: LLMClient):
        """
        初始化分类Agent
        
        Args:
            client: LLM客户端
        """
        self.client = client
    
    async def classify_file(
        self,
        file_name: str,
        file_content: str,
        types_list: str
    ) -> ClassificationResult:
        """
        分类文件
        
        Args:
            file_name: 文件名称
            file_content: 文件内容（MinerU解析后的Markdown格式）
            types_list: 可选的文件类型列表（格式化的字符串）
            
        Returns:
            ClassificationResult: 分类结果
        """
        start_time = time.time()
        try:
            state = ClassificationState(
                file_name=file_name,
                file_content=file_content,
                types_list=types_list
            )
            
            state_dict = state.model_dump()
            logger.info(f"调用分类Agent - 文件: {file_name}")
            
            response = await self.client.call_agent(state=state_dict)
            
            # 解析分类结果，取最后一个choice
            if not response.choices:
                logger.warning(f"分类Agent响应中没有choices")
                return ClassificationResult(
                    raw_response="",
                    success=False,
                    error="响应中没有choices"
                )
            
            last_choice = response.choices[-1].content
            logger.info(f"分类Agent响应内容: {last_choice}")
            
            # 解析分类结果
            classification_data = self._parse_classification_json(last_choice)
            
            if classification_data:
                classified_file_type = classification_data.get('classified_file_type')
                confidence = classification_data.get('confidence')
                reason = classification_data.get('reason')
                
                elapsed_time = (time.time() - start_time) * 1000
                logger.info(
                    f"分类Agent完成 | "
                    f"文件: {file_name} | "
                    f"总耗时: {elapsed_time:.0f}ms | "
                    f"结果: {'成功' if classified_file_type else '失败'} | "
                    f"分类: {classified_file_type or '未知'} | "
                    f"置信度: {confidence or 0.0}"
                )
                
                return ClassificationResult(
                    classified_file_type=classified_file_type,
                    confidence=confidence,
                    reason=reason,
                    raw_response=last_choice,
                    success=classified_file_type is not None,
                    error=None if classified_file_type else "无法解析分类结果"
                )
            else:
                elapsed_time = (time.time() - start_time) * 1000
                logger.warning(
                    f"分类Agent失败 | "
                    f"文件: {file_name} | "
                    f"总耗时: {elapsed_time:.0f}ms | "
                    f"错误: 无法解析分类结果"
                )
                return ClassificationResult(
                    raw_response=last_choice,
                    success=False,
                    error="无法解析分类结果"
                )
            
        except Exception as e:
            elapsed_time = (time.time() - start_time) * 1000
            error_detail = str(e) or repr(e) or type(e).__name__
            logger.error(
                f"文件分类失败 | "
                f"文件: {file_name} | "
                f"总耗时: {elapsed_time:.0f}ms | "
                f"错误类型: {type(e).__name__} | "
                f"错误信息: {error_detail}",
                exc_info=True
            )
            return ClassificationResult(
                raw_response="",
                success=False,
                error=error_detail
            )
    
    def _parse_classification_json(self, content: str) -> Optional[Dict[str, Any]]:
        """
        解析分类结果的 JSON 数据
        
        从响应内容中提取JSON对象
        
        Args:
            content: 响应内容
            
        Returns:
            Optional[Dict]: 包含 classified_file_type, confidence, reason 的字典，解析失败返回None
        """
        try:
            # 尝试匹配 ```json ... ``` 格式
            json_pattern = r'```json\s*(\{.*?\})\s*```'
            match = re.search(json_pattern, content, re.DOTALL)
            
            data = None
            if match:
                json_str = match.group(1)
                data = json.loads(json_str)
            else:
                # 如果没有匹配到，尝试直接解析整个内容
                try:
                    data = json.loads(content)
                except:
                    pass
            
            if data and isinstance(data, dict):
                return {
                    'classified_file_type': data.get('classified_file_type'),
                    'confidence': data.get('confidence'),
                    'reason': data.get('reason')
                }
            
            logger.warning(f"无法解析分类结果，原始内容: {content[:200]}...")
            return None
            
        except Exception as e:
            logger.error(f"解析分类结果异常: {e}")
            return None


# ============ 单例获取函数 ============


def get_llm_client(agent_type: str, config: AgentConfig) -> LLMClient:
    """
    获取LLM客户端单例
    
    Args:
        agent_type: Agent类型标识（用于区分不同的Agent配置）
        config: Agent配置
        
    Returns:
        LLMClient: 客户端实例
    """
    key = f"{agent_type}_{config.agent_id}"
    if key not in _llm_client_instances:
        _llm_client_instances[key] = LLMClient(config)
        logger.debug(f"创建LLM客户端单例: {key}")
    return _llm_client_instances[key]


async def close_all_llm_clients():
    """关闭所有LLM客户端"""
    for key, client in _llm_client_instances.items():
        try:
            await client.close()
            logger.debug(f"关闭LLM客户端: {key}")
        except Exception as e:
            logger.warning(f"关闭LLM客户端失败 {key}: {e}")
    _llm_client_instances.clear()

