"""
规则配置管理API端点
"""

from typing import List, Optional

from fastapi import APIRouter, HTTPException, status, Query
from loguru import logger

from src.schemas.rule_config import (
    RuleConfig,
    RuleConfigCreate,
    RuleConfigUpdate,
    RuleConfigList,
    RuleConfigResponse,
    ExtractionRule,
    ExtractionRuleCreate,
    ExtractionRuleUpdate,
    AuditRule,
    AuditRuleCreate,
    AuditRuleUpdate,
    AuditDataSource,
    BusinessType,
    MappingType
)
from src.services.rule_config_service import get_rule_config_service


router = APIRouter(prefix="/rule-configs", tags=["规则配置管理"])


# ===========================
# 规则配置CRUD
# ===========================

@router.post(
    "",
    response_model=RuleConfig,
    status_code=status.HTTP_201_CREATED,
    summary="创建规则配置",
    description="创建新的规则配置集合"
)
async def create_rule_config(config_create: RuleConfigCreate):
    """创建规则配置"""
    try:
        service = get_rule_config_service()
        config = service.create_config(config_create)
        logger.info(f"创建规则配置成功: {config.name}")
        return config
    except Exception as e:
        logger.error(f"创建规则配置失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"创建规则配置失败: {str(e)}"
        )


@router.get(
    "",
    response_model=RuleConfigList,
    summary="获取规则配置列表",
    description="获取所有规则配置列表，支持按业务类型和启用状态过滤"
)
async def list_rule_configs(
    business_type: Optional[BusinessType] = Query(None, description="业务类型过滤"),
    enabled: Optional[bool] = Query(None, description="启用状态过滤")
):
    """获取规则配置列表"""
    try:
        service = get_rule_config_service()
        configs = service.list_configs(business_type=business_type, enabled=enabled)
        return RuleConfigList(total=len(configs), items=configs)
    except Exception as e:
        logger.error(f"获取规则配置列表失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"获取规则配置列表失败: {str(e)}"
        )


@router.get(
    "/{config_id}",
    response_model=RuleConfig,
    summary="获取规则配置详情",
    description="根据配置ID获取规则配置详细信息"
)
async def get_rule_config(config_id: str):
    """获取规则配置详情"""
    service = get_rule_config_service()
    config = service.get_config(config_id)
    
    if config is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"规则配置不存在: {config_id}"
        )
    
    return config


@router.put(
    "/{config_id}",
    response_model=RuleConfig,
    summary="更新规则配置",
    description="更新规则配置的基本信息"
)
async def update_rule_config(config_id: str, config_update: RuleConfigUpdate):
    """更新规则配置"""
    try:
        service = get_rule_config_service()
        config = service.update_config(config_id, config_update)
        
        if config is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"规则配置不存在: {config_id}"
            )
        
        logger.info(f"更新规则配置成功: {config.name}")
        return config
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新规则配置失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新规则配置失败: {str(e)}"
        )


@router.delete(
    "/{config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除规则配置",
    description="删除指定的规则配置"
)
async def delete_rule_config(config_id: str):
    """删除规则配置"""
    service = get_rule_config_service()
    success = service.delete_config(config_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"规则配置不存在: {config_id}"
        )
    
    logger.info(f"删除规则配置成功: {config_id}")


# ===========================
# 提取规则管理
# ===========================

@router.post(
    "/{config_id}/extraction-rules",
    response_model=ExtractionRule,
    status_code=status.HTTP_201_CREATED,
    summary="添加提取规则",
    description="在指定配置中添加新的提取规则"
)
async def create_extraction_rule(config_id: str, rule_create: ExtractionRuleCreate):
    """添加提取规则"""
    try:
        service = get_rule_config_service()
        rule = service.add_extraction_rule(config_id, rule_create)
        
        if rule is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"规则配置不存在: {config_id}"
            )
        
        logger.info(f"添加提取规则成功: {rule.field_name}")
        return rule
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加提取规则失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"添加提取规则失败: {str(e)}"
        )


@router.get(
    "/{config_id}/extraction-rules/{rule_id}",
    response_model=ExtractionRule,
    summary="获取提取规则详情",
    description="获取指定提取规则的详细信息"
)
async def get_extraction_rule(config_id: str, rule_id: str):
    """获取提取规则详情"""
    service = get_rule_config_service()
    rule = service.get_extraction_rule(config_id, rule_id)
    
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"提取规则不存在: {rule_id}"
        )
    
    return rule


@router.put(
    "/{config_id}/extraction-rules/{rule_id}",
    response_model=ExtractionRule,
    summary="更新提取规则",
    description="更新指定的提取规则"
)
async def update_extraction_rule(
    config_id: str,
    rule_id: str,
    rule_update: ExtractionRuleUpdate
):
    """更新提取规则"""
    try:
        service = get_rule_config_service()
        rule = service.update_extraction_rule(config_id, rule_id, rule_update)
        
        if rule is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"提取规则不存在: {rule_id}"
            )
        
        logger.info(f"更新提取规则成功: {rule.field_name}")
        return rule
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新提取规则失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新提取规则失败: {str(e)}"
        )


@router.delete(
    "/{config_id}/extraction-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除提取规则",
    description="删除指定的提取规则"
)
async def delete_extraction_rule(config_id: str, rule_id: str):
    """删除提取规则"""
    service = get_rule_config_service()
    success = service.delete_extraction_rule(config_id, rule_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"提取规则不存在: {rule_id}"
        )
    
    logger.info(f"删除提取规则成功: {rule_id}")


# ===========================
# 审核规则管理
# ===========================

@router.post(
    "/{config_id}/audit-rules",
    response_model=AuditRule,
    status_code=status.HTTP_201_CREATED,
    summary="添加审核规则",
    description="在指定配置中添加新的审核规则"
)
async def create_audit_rule(config_id: str, rule_create: AuditRuleCreate):
    """添加审核规则"""
    try:
        service = get_rule_config_service()
        rule = service.add_audit_rule(config_id, rule_create)
        
        if rule is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"规则配置不存在: {config_id}"
            )
        
        logger.info(f"添加审核规则成功: {rule.field_name}")
        return rule
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加审核规则失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"添加审核规则失败: {str(e)}"
        )


@router.get(
    "/{config_id}/audit-rules/{rule_id}",
    response_model=AuditRule,
    summary="获取审核规则详情",
    description="获取指定审核规则的详细信息"
)
async def get_audit_rule(config_id: str, rule_id: str):
    """获取审核规则详情"""
    service = get_rule_config_service()
    rule = service.get_audit_rule(config_id, rule_id)
    
    if rule is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"审核规则不存在: {rule_id}"
        )
    
    return rule


@router.put(
    "/{config_id}/audit-rules/{rule_id}",
    response_model=AuditRule,
    summary="更新审核规则",
    description="更新指定的审核规则"
)
async def update_audit_rule(
    config_id: str,
    rule_id: str,
    rule_update: AuditRuleUpdate
):
    """更新审核规则"""
    try:
        service = get_rule_config_service()
        rule = service.update_audit_rule(config_id, rule_id, rule_update)
        
        if rule is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"审核规则不存在: {rule_id}"
            )
        
        logger.info(f"更新审核规则成功: {rule.field_name}")
        return rule
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新审核规则失败: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"更新审核规则失败: {str(e)}"
        )


@router.delete(
    "/{config_id}/audit-rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除审核规则",
    description="删除指定的审核规则"
)
async def delete_audit_rule(config_id: str, rule_id: str):
    """删除审核规则"""
    service = get_rule_config_service()
    success = service.delete_audit_rule(config_id, rule_id)
    
    if not success:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"审核规则不存在: {rule_id}"
        )
    
    logger.info(f"删除审核规则成功: {rule_id}")

