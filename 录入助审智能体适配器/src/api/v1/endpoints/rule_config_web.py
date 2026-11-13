"""
规则配置管理Web界面

使用Jinja2模板和Bootstrap5提供前端管理界面
"""

from fastapi import APIRouter, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from typing import Optional, List
from loguru import logger

from src.schemas.rule_config import (
    BusinessType,
    FieldType,
    HttpMethod,
    AuditType,
    MappingType,
    RuleConfigCreate,
    ExtractionRuleCreate,
    ExtractionRuleUpdate,
    AuditRuleCreate,
    AuditRuleUpdate,
    AuditDataSource,
    ApiConfig
)
from src.schemas.file import FileType, FILE_TYPE_LABELS
from src.services.rule_config_service import get_rule_config_service


# 创建路由和模板引擎
router = APIRouter(prefix="/web/rule-configs", tags=["规则配置Web界面"])
templates = Jinja2Templates(directory="src/templates")


@router.get("/", response_class=HTMLResponse, summary="规则配置列表页面")
async def rule_configs_list_page(request: Request):
    """规则配置列表页面"""
    service = get_rule_config_service()
    configs = service.list_configs()
    
    return templates.TemplateResponse(
        "rule_config/list.html",
        {
            "request": request,
            "configs": configs,
            "business_types": [bt.value for bt in BusinessType]
        }
    )


@router.get("/create", response_class=HTMLResponse, summary="创建规则配置页面")
async def create_rule_config_page(request: Request):
    """创建规则配置页面"""
    return templates.TemplateResponse(
        "rule_config/create.html",
        {
            "request": request,
            "business_types": [bt.value for bt in BusinessType]
        }
    )


@router.post("/create", response_class=HTMLResponse, summary="创建规则配置")
async def create_rule_config(
    request: Request,
    name: str = Form(...),
    business_type: str = Form(...),
    description: Optional[str] = Form(None)
):
    """创建规则配置"""
    try:
        service = get_rule_config_service()
        config_create = RuleConfigCreate(
            name=name,
            business_type=BusinessType(business_type),
            description=description
        )
        config = service.create_config(config_create)
        logger.info(f"创建规则配置成功: {config.name}")
        
        # 重定向到详情页
        return RedirectResponse(
            url=f"/web/rule-configs/{config.id}",
            status_code=303
        )
    except Exception as e:
        logger.error(f"创建规则配置失败: {str(e)}")
        return templates.TemplateResponse(
            "rule_config/create.html",
            {
                "request": request,
                "error": f"创建失败: {str(e)}",
                "business_types": [bt.value for bt in BusinessType],
                "name": name,
                "business_type": business_type,
                "description": description
            }
        )


@router.get("/{config_id}", response_class=HTMLResponse, summary="规则配置详情页面")
async def rule_config_detail_page(request: Request, config_id: str):
    """规则配置详情页面"""
    service = get_rule_config_service()
    config = service.get_config(config_id)
    
    if config is None:
        raise HTTPException(status_code=404, detail="规则配置不存在")
    
    return templates.TemplateResponse(
        "rule_config/detail.html",
        {
            "request": request,
            "config": config,
            "field_types": [ft.value for ft in FieldType],
            "http_methods": [m.value for m in HttpMethod],
            "audit_types": [at.value for at in AuditType],
            "mapping_types": [mt.value for mt in MappingType],
            "file_types": FILE_TYPE_LABELS
        }
    )


@router.post("/{config_id}/delete", response_class=HTMLResponse, summary="删除规则配置")
async def delete_rule_config(config_id: str):
    """删除规则配置"""
    service = get_rule_config_service()
    success = service.delete_config(config_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="规则配置不存在")
    
    logger.info(f"删除规则配置成功: {config_id}")
    return RedirectResponse(url="/web/rule-configs", status_code=303)


@router.post(
    "/{config_id}/extraction-rules/create",
    response_class=HTMLResponse,
    summary="添加提取规则"
)
async def create_extraction_rule(
    request: Request,
    config_id: str,
    field_name: str = Form(...),
    field_type: str = Form(...),
    reference_materials: List[str] = Form(...),  # 多选下拉框
    extraction_logic: str = Form(...),
    choices: Optional[str] = Form(None),  # 逗号分隔
    api_url: Optional[str] = Form(None),
    api_method: Optional[str] = Form(None),
    api_timeout: Optional[int] = Form(30),
    notes: Optional[str] = Form(None)
):
    """添加提取规则"""
    try:
        service = get_rule_config_service()
        
        # 处理参考材料列表（已经是列表，无需split）
        materials_list = reference_materials
        
        # 处理选项列表
        choices_list = None
        if choices:
            choices_list = [c.strip() for c in choices.split(',') if c.strip()]
        
        # 处理API配置
        api_config = None
        if api_url:
            api_config = ApiConfig(
                url=api_url,
                method=HttpMethod(api_method) if api_method else HttpMethod.GET,
                timeout=api_timeout or 30
            )
        
        rule_create = ExtractionRuleCreate(
            field_name=field_name,
            field_type=FieldType(field_type),
            reference_materials=materials_list,
            extraction_logic=extraction_logic,
            api_config=api_config,
            choices=choices_list,
            notes=notes
        )
        
        rule = service.add_extraction_rule(config_id, rule_create)
        
        if rule is None:
            raise HTTPException(status_code=404, detail="规则配置不存在")
        
        logger.info(f"添加提取规则成功: {rule.field_name}")
        return RedirectResponse(
            url=f"/web/rule-configs/{config_id}",
            status_code=303
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加提取规则失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"添加提取规则失败: {str(e)}")


@router.post(
    "/{config_id}/extraction-rules/{rule_id}/delete",
    response_class=HTMLResponse,
    summary="删除提取规则"
)
async def delete_extraction_rule(config_id: str, rule_id: str):
    """删除提取规则"""
    service = get_rule_config_service()
    success = service.delete_extraction_rule(config_id, rule_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="提取规则不存在")
    
    logger.info(f"删除提取规则成功: {rule_id}")
    return RedirectResponse(
        url=f"/web/rule-configs/{config_id}",
        status_code=303
    )


@router.post(
    "/{config_id}/audit-rules/create",
    response_class=HTMLResponse,
    summary="添加审核规则"
)
async def create_audit_rule(
    request: Request,
    config_id: str,
    audit_type: str = Form(...),
    field_name: str = Form(...),
    mapping_type: Optional[str] = Form(None),
    source_field_name: Optional[str] = Form(None),
    include_user_input: bool = Form(True),
    audit_data_sources_json: Optional[str] = Form(None),  # JSON 字符串
    audit_content: str = Form(...),
    use_simple_comparison: bool = Form(False),
    auto_pass_when_missing: bool = Form(False),
    auto_process_rules: str = Form(...),
    notes: Optional[str] = Form(None)
):
    """添加审核规则"""
    try:
        service = get_rule_config_service()
        
        # 处理审核数据源
        audit_data_sources = None
        if audit_data_sources_json:
            import json
            data_sources_data = json.loads(audit_data_sources_json)
            audit_data_sources = [AuditDataSource(**ds) for ds in data_sources_data]
        
        # 处理映射类型
        final_mapping_type = None
        if AuditType(audit_type) == AuditType.FIELD_AUDIT:
            final_mapping_type = MappingType(mapping_type) if mapping_type else MappingType.AUTO
        
        rule_create = AuditRuleCreate(
            audit_type=AuditType(audit_type),
            field_name=field_name,
            mapping_type=final_mapping_type,
            source_field_name=source_field_name,
            include_user_input=include_user_input,
            audit_data_sources=audit_data_sources,
            audit_content=audit_content,
            use_simple_comparison=use_simple_comparison,
            auto_pass_when_missing=auto_pass_when_missing,
            auto_process_rules=auto_process_rules,
            notes=notes
        )
        
        rule = service.add_audit_rule(config_id, rule_create)
        
        if rule is None:
            raise HTTPException(status_code=404, detail="规则配置不存在")
        
        logger.info(f"添加审核规则成功: {rule.field_name}")
        return RedirectResponse(
            url=f"/web/rule-configs/{config_id}",
            status_code=303
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"添加审核规则失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"添加审核规则失败: {str(e)}")


@router.post(
    "/{config_id}/audit-rules/{rule_id}/delete",
    response_class=HTMLResponse,
    summary="删除审核规则"
)
async def delete_audit_rule(config_id: str, rule_id: str):
    """删除审核规则"""
    service = get_rule_config_service()
    success = service.delete_audit_rule(config_id, rule_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="审核规则不存在")
    
    logger.info(f"删除审核规则成功: {rule_id}")
    return RedirectResponse(
        url=f"/web/rule-configs/{config_id}",
        status_code=303
    )


@router.post(
    "/{config_id}/extraction-rules/{rule_id}/update",
    response_class=HTMLResponse,
    summary="更新提取规则"
)
async def update_extraction_rule(
    request: Request,
    config_id: str,
    rule_id: str,
    field_name: str = Form(...),
    field_type: str = Form(...),
    reference_materials: List[str] = Form(...),
    extraction_logic: str = Form(...),
    choices: str = Form(""),
    api_url: str = Form(""),
    api_method: str = Form("GET"),
    api_timeout: int = Form(30),
    api_description: str = Form(""),
    notes: str = Form(""),
    enabled: bool = Form(True)
):
    """更新提取规则"""
    try:
        service = get_rule_config_service()
        
        # 处理参考材料
        materials_list = reference_materials
        
        # 处理选项列表
        choices_list = []
        if choices:
            choices_list = [c.strip() for c in choices.split('\n') if c.strip()]
        
        # 处理API配置
        api_config = None
        if api_url:
            api_config = ApiConfig(
                url=api_url,
                method=HttpMethod(api_method),
                timeout=api_timeout,
                description=api_description if api_description else None
            )
        
        rule_update = ExtractionRuleUpdate(
            field_name=field_name,
            field_type=FieldType(field_type),
            reference_materials=materials_list,
            extraction_logic=extraction_logic,
            choices=choices_list if choices_list else None,
            api_config=api_config,
            notes=notes if notes else None,
            enabled=enabled
        )
        
        rule = service.update_extraction_rule(config_id, rule_id, rule_update)
        
        if rule is None:
            raise HTTPException(status_code=404, detail="提取规则不存在")
        
        logger.info(f"更新提取规则成功: {rule.field_name}")
        return RedirectResponse(
            url=f"/web/rule-configs/{config_id}",
            status_code=303
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新提取规则失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新提取规则失败: {str(e)}")


@router.post(
    "/{config_id}/audit-rules/{rule_id}/update",
    response_class=HTMLResponse,
    summary="更新审核规则"
)
async def update_audit_rule(
    request: Request,
    config_id: str,
    rule_id: str,
    audit_type: str = Form(...),
    field_name: str = Form(...),
    mapping_type: Optional[str] = Form(None),
    source_field_name: str = Form(""),
    include_user_input: bool = Form(True),
    audit_data_sources_json: Optional[str] = Form(None),
    audit_content: str = Form(...),
    use_simple_comparison: bool = Form(False),
    auto_pass_when_missing: bool = Form(False),
    auto_process_rules: str = Form(...),
    notes: str = Form(""),
    enabled: bool = Form(True)
):
    """更新审核规则"""
    try:
        service = get_rule_config_service()
        
        # 处理审核数据源
        audit_data_sources = None
        if audit_data_sources_json:
            import json
            data_sources_data = json.loads(audit_data_sources_json)
            audit_data_sources = [AuditDataSource(**ds) for ds in data_sources_data]
        
        # 处理映射类型
        final_mapping_type = None
        if mapping_type:
            final_mapping_type = MappingType(mapping_type)
        
        rule_update = AuditRuleUpdate(
            audit_type=AuditType(audit_type),
            field_name=field_name,
            mapping_type=final_mapping_type,
            source_field_name=source_field_name if source_field_name else None,
            include_user_input=include_user_input,
            audit_data_sources=audit_data_sources,
            audit_content=audit_content,
            use_simple_comparison=use_simple_comparison,
            auto_pass_when_missing=auto_pass_when_missing,
            auto_process_rules=auto_process_rules,
            notes=notes if notes else None,
            enabled=enabled
        )
        
        rule = service.update_audit_rule(config_id, rule_id, rule_update)
        
        if rule is None:
            raise HTTPException(status_code=404, detail="审核规则不存在")
        
        logger.info(f"更新审核规则成功: {rule.field_name}")
        return RedirectResponse(
            url=f"/web/rule-configs/{config_id}",
            status_code=303
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"更新审核规则失败: {str(e)}")
        raise HTTPException(status_code=500, detail=f"更新审核规则失败: {str(e)}")

