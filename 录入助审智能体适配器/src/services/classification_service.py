"""
文件分类服务

负责将中台传入的文件类型映射到系统的FileType枚举
支持直接映射和LLM智能分类两种方式
"""

from typing import Dict, Optional, Any
from loguru import logger

from config.llm_config import LLMConfig
from src.services.llm.client import LLMClient, ClassificationAgent
from src.schemas.file import FileType, FILE_TYPE_LABELS


class FileClassificationService:
    """文件分类服务"""
    
    # 中台类型代码到系统FileType的直接映射表（一对一映射）
    MIDDLE_PLATFORM_MAPPING = {
        # 旧的映射关系（保留）
        "NBJYHYQPZJGJCWJ": FileType.INTERNAL_DECISION,           # 内部决议或有权批准机构决策文件
        "ZCPGBGSHQTDJWJ": FileType.EVALUATION_REPORT,            # 资产评估报告书或其他定价文件
        "PGBGDHZHBACL": FileType.EVALUATION_FILING,              # 评估报告的核准或备案材料
        "FWCQZS": FileType.PROPERTY_CERTIFICATE,                 # 房屋产权证书
        "TDCQZS": FileType.LAND_USE_CERTIFICATE,                 # 土地产权证书（国有土地使用证）
        "ZCQD": FileType.ASSET_LIST,                             # 资产清单
        "TKCNS": FileType.INSPECTION_COMMITMENT,                 # 踏勘承诺函
        # 新增的映射关系
        "CZQDWJ": FileType.ASSET_LIST,                           # 处置清单 -> 资产清单
        "ZCPGBGS": FileType.EVALUATION_REPORT,                   # 资产评估报告书或其他定价文件 -> 评估报告或其他定价文件
        "NBJYWJ": FileType.INTERNAL_DECISION,                    # 内部决议或有权批准机构决策文件 -> 内部决议或有权批准机构决策文件
        "ZRFQYFRYYZZ": FileType.BUSINESS_LICENSE,                # 转让方企业法人营业执照 -> 营业执照
        "ZTZGZMWJ": FileType.BUSINESS_LICENSE,                   # 主体资格证明文件 -> 营业执照
        "XXPLSQS_WDQ": FileType.INFO_DISCLOSURE_APPLICATION,     # 信息披露申请书_未电签 -> 信息披露申请书
        "QYXZSWZCXXPLSQS_WDQ": FileType.INFO_DISCLOSURE_APPLICATION,  # 企业形式实物资产信息披露申请书_未电签 -> 信息披露申请书
        # 以下文件类型暂不需要读取，对审核无帮助，故不进行映射：
        # "ZRFZC": 转让方章程
        # "SWZCJYHT": 实物资产交易合同
        # "CCXY": 拆除协议
    }
    
    # 需要走LLM智能分类的中台类型（一对多关系）
    # 这些类型无法直接映射，需要根据文件名和内容进行智能判断
    REQUIRE_LLM_CLASSIFICATION = {
        "QTWJ",     # 其他文件（可能对应多种系统类型）
        "BJSYQWJ",  # 北交所要求提供的其他材料（可能对应以下多种系统类型）:
                    # - 信息披露申请书
                    # - 踏勘承诺函
                    # - 中央行政事业单位国有资产处置委托书
                    # - 中央行政事业单位国有资产转让申请表
                    # - 中央行政事业单位国有资产接收单
                    # - 行政事业单位国有资产处置申请表
                    # - 行政事业单位国有资产接收确认书
                    # - 行政事业单位国有资产确认单
                    # - 项目进度记录表
    }
    
    # 文件名关键词到FileType的映射规则（用于快速分类，优先级从高到低）
    # 格式：(关键词列表, 目标FileType, 置信度)
    FILENAME_KEYWORDS_MAPPING = [
        # 营业执照相关
        (["营业执照", "工商执照", "企业法人营业执照"], FileType.BUSINESS_LICENSE, 0.95),
        (["事业单位法人证书", "法人证书"], FileType.BUSINESS_LICENSE, 0.95),
        (["身份证"], FileType.BUSINESS_LICENSE, 0.9),
        # 信息披露申请书
        (["信息披露申请", "披露申请书", "情况说明"], FileType.INFO_DISCLOSURE_APPLICATION, 0.95),
        # 评估报告
        (["评估报告", "资产评估", "定价文件", "估价报告"], FileType.EVALUATION_REPORT, 0.9),
        # 评估备案
        (["评估备案", "核准文件", "备案表"], FileType.EVALUATION_FILING, 0.85),
        # 内部决议
        (["内部决议", "决策文件", "批准文件", "董事会决议", "股东会决议", "会议纪要"], FileType.INTERNAL_DECISION, 0.85),
        # 资产清单
        (["资产清单", "处置清单", "资产明细", "资产列表"], FileType.ASSET_LIST, 0.9),
        # 踏勘承诺函
        (["踏勘承诺", "踏勘确认", "现场踏勘"], FileType.INSPECTION_COMMITMENT, 0.9),
        # 房屋产权证
        (["房屋产权", "不动产权证", "房产证", "产权证"], FileType.PROPERTY_CERTIFICATE, 0.9),
        # 土地使用证
        (["土地使用证", "国有土地", "土地证"], FileType.LAND_USE_CERTIFICATE, 0.9),
        # 土地出让合同
        (["土地出让", "建设用地使用权出让"], FileType.LAND_USE_CONTRACT, 0.9),
        # 车辆证书
        (["行驶证", "机动车登记", "车辆登记"], FileType.VEHICLE_CERTIFICATE, 0.9),
        # 船舶证书
        (["船舶所有权", "船舶检验", "船舶国籍"], FileType.SHIP_CERTIFICATE, 0.9),
        # 飞机证书
        (["适航证", "电台执照", "国籍登记证", "航空器"], FileType.AIRCRAFT_CERTIFICATE, 0.9),
        # 专利证书
        (["专利证书", "专利权证", "发明专利", "实用新型"], FileType.PATENT_CERTIFICATE, 0.9),
        # 中央行政事业单位相关
        (["中央行政事业单位国有资产处置委托"], FileType.CENTRAL_ASSET_DISPOSAL_AUTHORIZATION, 0.95),
        (["中央行政事业单位国有资产转让申请"], FileType.CENTRAL_ASSET_TRANSFER_APPLICATION, 0.95),
        (["中央行政事业单位国有资产接收单"], FileType.CENTRAL_ASSET_RECEIPT, 0.95),
        # 行政事业单位相关
        (["行政事业单位国有资产处置申请"], FileType.ASSET_DISPOSAL_APPLICATION, 0.95),
        (["行政事业单位国有资产接收确认"], FileType.ASSET_RECEIPT_CONFIRMATION, 0.95),
        (["行政事业单位国有资产确认单"], FileType.ASSET_CONFIRMATION_FORM, 0.95),
        # 项目进度记录
        (["项目进度记录", "进度记录表"], FileType.PROJECT_PROGRESS_RECORD, 0.9),
    ]
    
    def __init__(self):
        """初始化分类服务"""
        self.llm_config = LLMConfig()
    
    def _classify_by_filename(self, file_name: str) -> Optional[Dict[str, Any]]:
        """
        基于文件名关键词进行快速分类
        
        Args:
            file_name: 文件名称
            
        Returns:
            分类结果字典，如果无法匹配则返回 None
        """
        # 移除文件扩展名，只保留文件名主体
        name_without_ext = file_name.rsplit('.', 1)[0] if '.' in file_name else file_name
        
        for keywords, file_type, confidence in self.FILENAME_KEYWORDS_MAPPING:
            for keyword in keywords:
                if keyword in name_without_ext:
                    logger.info(f"文件名关键词匹配成功: '{file_name}' 包含 '{keyword}' -> {file_type.value}")
                    return {
                        "file_type": file_type.value,
                        "method": "filename_keyword",
                        "confidence": confidence,
                        "reason": f"文件名包含关键词 '{keyword}'，识别为 {FILE_TYPE_LABELS[file_type]}"
                    }
        
        return None
    
    async def classify_file(
        self,
        file_name: str,
        original_type_code: Optional[str],
        file_content: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        分类文件
        
        Args:
            file_name: 文件名称
            original_type_code: 中台传入的原始类型代码（如ZRFZC、NBJYHYQPZJGJCWJ等）
            file_content: 文件内容（MinerU解析后的Markdown格式，用于LLM分类）
            
        Returns:
            Dict: 分类结果
                {
                    "file_type": FileType枚举值,
                    "method": "direct_mapping" | "llm_classification" | "filename_hint" | "default",
                    "confidence": 0.0-1.0,
                    "reason": "分类原因说明"
                }
        """
        logger.info(f"开始分类文件: {file_name}, 中台类型: {original_type_code}")
        
        # 1. 检查是否需要LLM智能分类（一对多关系）
        if original_type_code and original_type_code in self.REQUIRE_LLM_CLASSIFICATION:
            logger.info(f"中台类型 {original_type_code} 需要LLM智能分类（一对多关系）")
            
            # 1.1 首先尝试基于文件名关键词快速分类
            filename_result = self._classify_by_filename(file_name)
            if filename_result:
                logger.info(f"文件名关键词分类成功: {file_name} -> {filename_result['file_type']}")
                return filename_result
            
            # 1.2 如果有文件内容，使用LLM进行智能分类
            if file_content:
                logger.info(f"使用LLM智能分类: {file_name}")
                llm_result = await self._classify_by_llm(file_name, file_content)
                
                if llm_result.get("success"):
                    logger.info(f"LLM分类成功: {llm_result['file_type']}, 置信度: {llm_result['confidence']}")
                    return llm_result
                else:
                    logger.warning(f"LLM分类失败: {llm_result.get('error')}")
            else:
                logger.warning(f"文件 {file_name} 没有文件内容，无法使用LLM分类")
            
            # 1.3 如果文件名和LLM都无法分类，使用默认分类
            logger.warning(f"文件 {file_name} 文件名关键词和LLM分类均失败，使用默认分类")
            return {
                "file_type": FileType.OTHER_DOCUMENTS.value,
                "method": "default",
                "confidence": 0.3,
                "reason": f"中台类型 {original_type_code} 无法通过文件名或内容识别，默认归类为其他文件"
            }
        
        # 2. 尝试直接映射（一对一关系）
        if original_type_code and original_type_code in self.MIDDLE_PLATFORM_MAPPING:
            mapped_type = self.MIDDLE_PLATFORM_MAPPING[original_type_code]
            logger.info(f"直接映射成功: {original_type_code} -> {mapped_type.value}")
            return {
                "file_type": mapped_type.value,
                "method": "direct_mapping",
                "confidence": 1.0,
                "reason": f"中台类型代码 {original_type_code} 直接映射到 {FILE_TYPE_LABELS[mapped_type]}"
            }
        
        # 3. 无法识别的中台类型，先尝试文件名关键词分类
        filename_result = self._classify_by_filename(file_name)
        if filename_result:
            logger.info(f"无法识别中台类型 {original_type_code}，但文件名关键词分类成功: {file_name} -> {filename_result['file_type']}")
            return filename_result
        
        # 4. 尝试LLM分类（如果有文件内容）
        if file_content:
            logger.info(f"无法识别的中台类型 {original_type_code}，尝试LLM分类: {file_name}")
            llm_result = await self._classify_by_llm(file_name, file_content)
            
            if llm_result.get("success"):
                logger.info(f"LLM分类成功: {llm_result['file_type']}, 置信度: {llm_result['confidence']}")
                return llm_result
            else:
                logger.warning(f"LLM分类失败: {llm_result.get('error')}")
        
        # 5. 默认策略：映射到"其他文件"
        logger.info(f"使用默认分类策略: {file_name} -> other_documents")
        return {
            "file_type": FileType.OTHER_DOCUMENTS.value,
            "method": "default",
            "confidence": 0.3,
            "reason": f"无法识别中台类型 {original_type_code}，默认归类为其他文件"
        }
    
    async def _classify_by_llm(
        self,
        file_name: str,
        file_content: str
    ) -> Dict[str, Any]:
        """
        使用LLM分类文件
        
        Args:
            file_name: 文件名称
            file_content: 文件内容
            
        Returns:
            Dict: LLM分类结果
        """
        try:
            # 构建可选类型列表
            types_list = self._build_types_list()
            
            # 限制文件内容长度（避免超出token限制）
            max_content_length = 10000
            truncated_content = file_content[:max_content_length]
            if len(file_content) > max_content_length:
                truncated_content += "\n\n...(内容已截断)..."
            
            # 调用LLM分类Agent
            classification_config = self.llm_config.get_classification_agent_config()
            
            async with LLMClient(classification_config) as client:
                agent = ClassificationAgent(client)
                result = await agent.classify_file(
                    file_name=file_name,
                    file_content=truncated_content,
                    types_list=types_list
                )
            
            if result.success and result.classified_file_type:
                # 验证分类结果是否在有效范围内
                try:
                    file_type = FileType(result.classified_file_type)
                    return {
                        "file_type": file_type.value,
                        "method": "llm_classification",
                        "confidence": result.confidence or 0.8,
                        "reason": result.reason or "LLM自动分类",
                        "success": True
                    }
                except ValueError:
                    logger.error(f"LLM返回的文件类型无效: {result.classified_file_type}")
                    return {
                        "success": False,
                        "error": f"LLM返回的文件类型无效: {result.classified_file_type}"
                    }
            else:
                return {
                    "success": False,
                    "error": result.error or "LLM分类失败"
                }
                
        except Exception as e:
            logger.error(f"LLM分类异常: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }
    
    def _build_types_list(self) -> str:
        """
        构建可选文件类型列表（格式化为字符串）
        
        Returns:
            str: 格式化的类型列表
        """
        types_items = []
        for file_type, label in FILE_TYPE_LABELS.items():
            types_items.append(f"- {file_type.value}: {label}")
        
        return "\n".join(types_items)
    
    def get_middle_platform_mapping(self) -> Dict[str, str]:
        """
        获取中台类型映射表
        
        Returns:
            Dict[str, str]: 中台类型代码 -> 系统FileType的映射
        """
        return {
            code: file_type.value 
            for code, file_type in self.MIDDLE_PLATFORM_MAPPING.items()
        }


# 创建全局服务实例
classification_service = FileClassificationService()

