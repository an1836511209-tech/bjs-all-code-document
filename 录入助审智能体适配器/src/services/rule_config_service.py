"""
规则配置服务

提供规则配置的增删改查功能，使用JSON文件存储
"""

import json
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from loguru import logger

from src.schemas.rule_config import (
    RuleConfig,
    ExtractionRule,
    AuditRule,
    AuditDataSource,
    BusinessType,
    ExtractionRuleCreate,
    ExtractionRuleUpdate,
    AuditRuleCreate,
    AuditRuleUpdate,
    RuleConfigCreate,
    RuleConfigUpdate
)


class RuleConfigService:
    """规则配置服务类"""
    
    def __init__(self, data_dir: str = "data/rule_configs"):
        """
        初始化规则配置服务
        
        Args:
            data_dir: 数据存储目录
        """
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"规则配置服务初始化，数据目录: {self.data_dir}")
    
    def _get_config_file_path(self, config_id: str) -> Path:
        """获取配置文件路径"""
        return self.data_dir / f"{config_id}.json"
    
    def _generate_id(self) -> str:
        """生成唯一ID"""
        return str(uuid.uuid4())
    
    def _load_config_from_file(self, config_id: str) -> Optional[RuleConfig]:
        """从文件加载配置"""
        file_path = self._get_config_file_path(config_id)
        if not file_path.exists():
            return None
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return RuleConfig(**data)
        except Exception as e:
            logger.error(f"加载配置文件失败 {config_id}: {str(e)}")
            return None
    
    def _save_config_to_file(self, config: RuleConfig) -> bool:
        """保存配置到文件"""
        file_path = self._get_config_file_path(config.id)
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(
                    config.model_dump(mode='json'),
                    f,
                    ensure_ascii=False,
                    indent=2
                )
            logger.info(f"配置已保存: {config.id}")
            return True
        except Exception as e:
            logger.error(f"保存配置文件失败 {config.id}: {str(e)}")
            return False
    
    def _delete_config_file(self, config_id: str) -> bool:
        """删除配置文件"""
        file_path = self._get_config_file_path(config_id)
        try:
            if file_path.exists():
                file_path.unlink()
                logger.info(f"配置文件已删除: {config_id}")
            return True
        except Exception as e:
            logger.error(f"删除配置文件失败 {config_id}: {str(e)}")
            return False
    
    # ===========================
    # 规则配置管理
    # ===========================
    
    def create_config(self, config_create: RuleConfigCreate) -> RuleConfig:
        """
        创建规则配置
        
        Args:
            config_create: 创建配置请求
            
        Returns:
            RuleConfig: 创建的配置
        """
        now = datetime.utcnow()
        config = RuleConfig(
            id=self._generate_id(),
            name=config_create.name,
            business_type=config_create.business_type,
            description=config_create.description,
            extraction_rules=[],
            audit_rules=[],
            version="1.0.0",
            enabled=True,
            created_at=now,
            updated_at=now
        )
        
        if self._save_config_to_file(config):
            logger.info(f"创建规则配置成功: {config.name} (ID: {config.id})")
            return config
        else:
            raise Exception("保存配置失败")
    
    def get_config(self, config_id: str) -> Optional[RuleConfig]:
        """
        获取规则配置
        
        Args:
            config_id: 配置ID
            
        Returns:
            Optional[RuleConfig]: 配置对象，不存在则返回None
        """
        return self._load_config_from_file(config_id)
    
    def list_configs(
        self,
        business_type: Optional[BusinessType] = None,
        enabled: Optional[bool] = None
    ) -> List[RuleConfig]:
        """
        获取规则配置列表
        
        Args:
            business_type: 业务类型过滤
            enabled: 启用状态过滤
            
        Returns:
            List[RuleConfig]: 配置列表
        """
        configs = []
        
        for file_path in self.data_dir.glob("*.json"):
            config_id = file_path.stem
            config = self._load_config_from_file(config_id)
            
            if config is None:
                continue
            
            # 应用过滤条件
            if business_type is not None and config.business_type != business_type:
                continue
            if enabled is not None and config.enabled != enabled:
                continue
            
            configs.append(config)
        
        # 按更新时间倒序排序
        configs.sort(key=lambda x: x.updated_at or x.created_at, reverse=True)
        
        logger.info(f"获取配置列表，共 {len(configs)} 条")
        return configs
    
    def get_default_config_by_business_type(
        self,
        business_type: BusinessType
    ) -> Optional[RuleConfig]:
        """
        根据业务类型获取默认规则配置
        
        优先级：
        1. 查找启用的、匹配业务类型的配置
        2. 返回最新更新的配置（按更新时间倒序）
        
        Args:
            business_type: 业务类型
            
        Returns:
            规则配置，如果没有找到返回None
        """
        logger.info(f"查找业务类型 '{business_type.value}' 的默认规则配置")
        
        # 查找匹配的启用配置
        configs = self.list_configs(business_type=business_type, enabled=True)
        
        if configs:
            default_config = configs[0]  # 最新更新的
            logger.info(f"找到默认规则配置: {default_config.id} ({default_config.name})")
            return default_config
        
        logger.warning(f"未找到业务类型 '{business_type.value}' 的启用规则配置")
        return None
    
    def update_config(self, config_id: str, config_update: RuleConfigUpdate) -> Optional[RuleConfig]:
        """
        更新规则配置
        
        Args:
            config_id: 配置ID
            config_update: 更新内容
            
        Returns:
            Optional[RuleConfig]: 更新后的配置，不存在则返回None
        """
        config = self._load_config_from_file(config_id)
        if config is None:
            return None
        
        # 更新字段
        update_data = config_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(config, key, value)
        
        config.updated_at = datetime.utcnow()
        
        if self._save_config_to_file(config):
            logger.info(f"更新配置成功: {config.name} (ID: {config.id})")
            return config
        else:
            raise Exception("保存配置失败")
    
    def delete_config(self, config_id: str) -> bool:
        """
        删除规则配置
        
        Args:
            config_id: 配置ID
            
        Returns:
            bool: 是否删除成功
        """
        config = self._load_config_from_file(config_id)
        if config is None:
            return False
        
        if self._delete_config_file(config_id):
            logger.info(f"删除配置成功: {config.name} (ID: {config.id})")
            return True
        return False
    
    # ===========================
    # 提取规则管理
    # ===========================
    
    def add_extraction_rule(
        self,
        config_id: str,
        rule_create: ExtractionRuleCreate
    ) -> Optional[ExtractionRule]:
        """
        添加提取规则
        
        Args:
            config_id: 配置ID
            rule_create: 提取规则创建请求
            
        Returns:
            Optional[ExtractionRule]: 创建的提取规则，配置不存在则返回None
        """
        config = self._load_config_from_file(config_id)
        if config is None:
            return None
        
        now = datetime.utcnow()
        rule = ExtractionRule(
            id=self._generate_id(),
            field_name=rule_create.field_name,
            field_type=rule_create.field_type,
            reference_materials=rule_create.reference_materials,
            extraction_logic=rule_create.extraction_logic,
            api_config=rule_create.api_config,
            choices=rule_create.choices,
            enabled=True,
            created_at=now,
            updated_at=now,
            notes=rule_create.notes
        )
        
        config.extraction_rules.append(rule)
        config.updated_at = now
        
        if self._save_config_to_file(config):
            logger.info(f"添加提取规则成功: {rule.field_name} (ID: {rule.id})")
            return rule
        else:
            raise Exception("保存配置失败")
    
    def update_extraction_rule(
        self,
        config_id: str,
        rule_id: str,
        rule_update: ExtractionRuleUpdate
    ) -> Optional[ExtractionRule]:
        """
        更新提取规则
        
        Args:
            config_id: 配置ID
            rule_id: 规则ID
            rule_update: 更新内容
            
        Returns:
            Optional[ExtractionRule]: 更新后的规则，不存在则返回None
        """
        config = self._load_config_from_file(config_id)
        if config is None:
            return None
        
        # 查找规则
        rule = None
        for r in config.extraction_rules:
            if r.id == rule_id:
                rule = r
                break
        
        if rule is None:
            return None
        
        # 更新字段
        update_data = rule_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(rule, key, value)
        
        rule.updated_at = datetime.utcnow()
        config.updated_at = datetime.utcnow()
        
        if self._save_config_to_file(config):
            logger.info(f"更新提取规则成功: {rule.field_name} (ID: {rule.id})")
            return rule
        else:
            raise Exception("保存配置失败")
    
    def delete_extraction_rule(self, config_id: str, rule_id: str) -> bool:
        """
        删除提取规则
        
        Args:
            config_id: 配置ID
            rule_id: 规则ID
            
        Returns:
            bool: 是否删除成功
        """
        config = self._load_config_from_file(config_id)
        if config is None:
            return False
        
        # 查找并删除规则
        original_len = len(config.extraction_rules)
        config.extraction_rules = [r for r in config.extraction_rules if r.id != rule_id]
        
        if len(config.extraction_rules) == original_len:
            # 未找到规则
            return False
        
        config.updated_at = datetime.utcnow()
        
        if self._save_config_to_file(config):
            logger.info(f"删除提取规则成功 (ID: {rule_id})")
            return True
        return False
    
    def get_extraction_rule(self, config_id: str, rule_id: str) -> Optional[ExtractionRule]:
        """
        获取提取规则
        
        Args:
            config_id: 配置ID
            rule_id: 规则ID
            
        Returns:
            Optional[ExtractionRule]: 提取规则，不存在则返回None
        """
        config = self._load_config_from_file(config_id)
        if config is None:
            return None
        
        for rule in config.extraction_rules:
            if rule.id == rule_id:
                return rule
        
        return None
    
    # ===========================
    # 审核规则管理
    # ===========================
    
    def add_audit_rule(
        self,
        config_id: str,
        rule_create: AuditRuleCreate
    ) -> Optional[AuditRule]:
        """
        添加审核规则
        
        Args:
            config_id: 配置ID
            rule_create: 审核规则创建请求
            
        Returns:
            Optional[AuditRule]: 创建的审核规则，配置不存在则返回None
        """
        config = self._load_config_from_file(config_id)
        if config is None:
            return None
        
        now = datetime.utcnow()
        rule = AuditRule(
            id=self._generate_id(),
            audit_type=rule_create.audit_type,
            field_name=rule_create.field_name,
            mapping_type=rule_create.mapping_type,
            source_field_name=rule_create.source_field_name,
            include_user_input=rule_create.include_user_input,
            audit_data_sources=rule_create.audit_data_sources,
            audit_content=rule_create.audit_content,
            auto_process_rules=rule_create.auto_process_rules,
            enabled=True,
            created_at=now,
            updated_at=now,
            notes=rule_create.notes
        )
        
        config.audit_rules.append(rule)
        config.updated_at = now
        
        if self._save_config_to_file(config):
            logger.info(f"添加审核规则成功: {rule.field_name} (ID: {rule.id})")
            return rule
        else:
            raise Exception("保存配置失败")
    
    def update_audit_rule(
        self,
        config_id: str,
        rule_id: str,
        rule_update: AuditRuleUpdate
    ) -> Optional[AuditRule]:
        """
        更新审核规则
        
        Args:
            config_id: 配置ID
            rule_id: 规则ID
            rule_update: 更新内容
            
        Returns:
            Optional[AuditRule]: 更新后的规则，不存在则返回None
        """
        config = self._load_config_from_file(config_id)
        if config is None:
            return None
        
        # 查找规则
        rule = None
        for r in config.audit_rules:
            if r.id == rule_id:
                rule = r
                break
        
        if rule is None:
            return None
        
        # 更新字段
        update_data = rule_update.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(rule, key, value)
        
        rule.updated_at = datetime.utcnow()
        config.updated_at = datetime.utcnow()
        
        if self._save_config_to_file(config):
            logger.info(f"更新审核规则成功: {rule.field_name} (ID: {rule.id})")
            return rule
        else:
            raise Exception("保存配置失败")
    
    def delete_audit_rule(self, config_id: str, rule_id: str) -> bool:
        """
        删除审核规则
        
        Args:
            config_id: 配置ID
            rule_id: 规则ID
            
        Returns:
            bool: 是否删除成功
        """
        config = self._load_config_from_file(config_id)
        if config is None:
            return False
        
        # 查找并删除规则
        original_len = len(config.audit_rules)
        config.audit_rules = [r for r in config.audit_rules if r.id != rule_id]
        
        if len(config.audit_rules) == original_len:
            # 未找到规则
            return False
        
        config.updated_at = datetime.utcnow()
        
        if self._save_config_to_file(config):
            logger.info(f"删除审核规则成功 (ID: {rule_id})")
            return True
        return False
    
    def get_audit_rule(self, config_id: str, rule_id: str) -> Optional[AuditRule]:
        """
        获取审核规则
        
        Args:
            config_id: 配置ID
            rule_id: 规则ID
            
        Returns:
            Optional[AuditRule]: 审核规则，不存在则返回None
        """
        config = self._load_config_from_file(config_id)
        if config is None:
            return None
        
        for rule in config.audit_rules:
            if rule.id == rule_id:
                return rule
        
        return None


# 全局单例
_rule_config_service = None


def get_rule_config_service() -> RuleConfigService:
    """
    获取规则配置服务单例
    
    Returns:
        RuleConfigService: 规则配置服务实例
    """
    global _rule_config_service
    if _rule_config_service is None:
        _rule_config_service = RuleConfigService()
    return _rule_config_service

