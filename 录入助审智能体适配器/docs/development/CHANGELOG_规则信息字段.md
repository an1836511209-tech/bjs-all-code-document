# 提取和审核接口增加规则信息字段 - 修改日志

## 修改时间
2025-11-24

## 修改概述
在提取和审核接口的返回明细中添加对应的规则信息，方便前端展示和用户了解每个字段的提取/审核依据。

---

## 1. 数据模型修改

### 1.1 提取结果模型 (`src/schemas/extraction.py`)

#### FieldExtractionResult 新增字段

```python
class FieldExtractionResult(BaseModel):
    # ... 原有字段 ...
    
    # 新增：提取规则信息
    extraction_rule: Optional[Dict[str, Any]] = Field(None, description="对应的提取规则信息")
```

**extraction_rule 字段内容**：
```json
{
    "rule_id": "rule_001",
    "field_name": "坐落位置",
    "field_type": "text",
    "extraction_logic": "在文档中查找标的物的具体地址...",
    "reference_materials": ["《信息披露申请书》", "《房屋所有权证》"],
    "enabled": true
}
```

### 1.2 审核结果模型 (`src/schemas/audit.py`)

#### AuditRuleResult 新增字段

```python
class AuditRuleResult(BaseModel):
    # ... 原有字段 ...
    
    # 新增：审核规则信息
    audit_rule: Optional[Dict[str, Any]] = Field(None, description="对应的审核规则信息")
```

**audit_rule 字段内容**：
```json
{
    "rule_id": "audit_rule_001",
    "field_name": "坐落位置",
    "audit_type": "字段审核",
    "audit_content": "检查用户输入的坐落位置是否与...",
    "mapping_type": "auto",
    "source_field_name": "坐落位置",
    "include_user_input": true,
    "use_simple_comparison": false,
    "auto_process_rules": "若一致则通过，否则不通过",
    "audit_data_sources": [
        {
            "material_name": "《信息披露申请书》",
            "field_name": "坐落位置"
        }
    ],
    "enabled": true
}
```

---

## 2. 服务层修改

### 2.1 提取服务 (`src/services/extraction/service.py`)

#### 修改位置：`_extract_single_field` 方法

在构建 `FieldExtractionResult` 时，添加 `extraction_rule` 字段：

```python
# 构建提取规则信息（用于前端展示）
extraction_rule_info = {
    "rule_id": rule.id,
    "field_name": rule.field_name,
    "field_type": rule.field_type.value,
    "extraction_logic": rule.extraction_logic,
    "reference_materials": rule.reference_materials,
    "enabled": rule.enabled
}

return FieldExtractionResult(
    field_id=rule.id,
    field_name=rule.field_name,
    field_type=rule.field_type.value,
    values=extracted_values,
    error_message=None,
    extraction_rule=extraction_rule_info  # 新增
)
```

**修改点**：
- ✅ 正常返回时添加规则信息
- ✅ 异常返回时也添加规则信息

### 2.2 审核服务 (`src/services/audit/service.py`)

#### 新增辅助方法：`_build_audit_rule_info`

```python
def _build_audit_rule_info(self, rule: AuditRule) -> Dict[str, Any]:
    """构建审核规则信息（用于前端展示）"""
    audit_data_sources_list = []
    if rule.audit_data_sources:
        for ds in rule.audit_data_sources:
            audit_data_sources_list.append({
                "material_name": ds.material_name,
                "field_name": ds.field_name
            })
    
    return {
        "rule_id": getattr(rule, 'id', None),
        "field_name": rule.field_name,
        "audit_type": rule.audit_type.value,
        "audit_content": rule.audit_content,
        "mapping_type": rule.mapping_type.value if rule.mapping_type else None,
        "source_field_name": rule.source_field_name,
        "include_user_input": rule.include_user_input,
        "use_simple_comparison": rule.use_simple_comparison,
        "auto_process_rules": rule.auto_process_rules,
        "audit_data_sources": audit_data_sources_list,
        "enabled": rule.enabled
    }
```

#### 修改位置：`_audit_single_rule` 方法

在所有返回 `AuditRuleResult` 的地方，添加 `audit_rule` 字段：

**修改点**：
- ✅ 简单对比模式返回时添加
- ✅ LLM 审核成功返回时添加（字段审核和文件审核）
- ✅ LLM 审核失败返回时添加
- ✅ 异常捕获返回时添加
- ✅ 预检查返回时添加（3个条件分支）

---

## 3. 接口返回示例

### 3.1 提取接口返回

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "request_id": "req_001",
        "status": "success",
        "extraction_type": "有纸大宗实物",
        "rule_config_id": "config_001",
        "results": [
            {
                "field_id": "field_001",
                "field_name": "坐落位置",
                "field_type": "text",
                "values": [
                    {
                        "source_file_type": "info_disclosure_application",
                        "source_file_name": "信息披露申请书.pdf",
                        "extracted_value": "北京市朝阳区建国路1号",
                        "confidence": 0.95,
                        "sources": [...]
                    }
                ],
                "extraction_rule": {
                    "rule_id": "rule_001",
                    "field_name": "坐落位置",
                    "field_type": "text",
                    "extraction_logic": "在《信息披露申请书》中查找标的物的具体地址...",
                    "reference_materials": ["《信息披露申请书》"],
                    "enabled": true
                }
            }
        ],
        "total_fields": 20,
        "success_count": 18,
        "failed_count": 2
    }
}
```

### 3.2 审核接口返回

```json
{
    "code": 0,
    "message": "success",
    "data": {
        "request_id": "req_002",
        "status": "completed",
        "audit_type": "有纸大宗实物",
        "audit_results": [
            {
                "audit_id": "audit_001",
                "audit_rule_id": "audit_rule_001",
                "audit_rule_name": "坐落位置一致性校验",
                "audit_type": "字段审核",
                "audit_result": "passed",
                "audit_status": "completed",
                "audit_explanation": null,
                "confidence": 0.95,
                "related_fields": [
                    {
                        "field_name": "坐落位置",
                        "field_value": "北京市朝阳区建国路1号",
                        "extraction_data": {...}
                    }
                ],
                "audit_rule": {
                    "rule_id": "audit_rule_001",
                    "field_name": "坐落位置",
                    "audit_type": "字段审核",
                    "audit_content": "检查用户输入的坐落位置是否与申请书和房本一致",
                    "mapping_type": "auto",
                    "source_field_name": "坐落位置",
                    "include_user_input": true,
                    "use_simple_comparison": false,
                    "auto_process_rules": "若一致则通过，否则不通过",
                    "audit_data_sources": [
                        {
                            "material_name": "《信息披露申请书》",
                            "field_name": "坐落位置"
                        },
                        {
                            "material_name": "《房屋所有权证》",
                            "field_name": "坐落"
                        }
                    ],
                    "enabled": true
                }
            }
        ],
        "summary": {
            "total": 15,
            "passed": 12,
            "failed": 2,
            "pending": 1,
            "manual_review": 0
        }
    }
}
```

---

## 4. 使用场景

### 4.1 前端展示规则详情

前端可以在结果列表中展示每个字段对应的规则信息：

- 鼠标悬停在字段名上时，显示提取逻辑/审核内容
- 点击"查看规则"按钮，弹窗展示完整规则信息
- 在规则配置页面，可以快速定位到当前字段使用的规则

### 4.2 问题排查

当提取/审核结果不符合预期时：

- 用户可以查看具体使用了哪条规则
- 检查规则的 `extraction_logic` 或 `audit_content` 是否合理
- 查看 `reference_materials` 或 `audit_data_sources` 是否正确

### 4.3 规则优化

通过分析规则信息和结果：

- 统计哪些规则的成功率低
- 优化提取逻辑或审核内容
- 调整参考材料来源

---

## 5. 向后兼容性

- ✅ **完全向后兼容**：新增字段为 `Optional`，不影响现有代码
- ✅ **不影响性能**：规则信息只是简单的字典转换，无额外计算开销
- ✅ **不影响数据库**：规则信息只在内存中构建，不存储

---

## 6. 注意事项

### 6.1 数据安全

规则信息可能包含业务逻辑，需注意：
- 确保只有授权用户可以访问接口
- 前端展示时注意敏感信息脱敏

### 6.2 数据量

- 规则信息字典较小（通常 < 1KB）
- 对于批量提取/审核（如 50 个字段），额外数据量约 50KB
- 不会对网络传输造成明显影响

---

## 7. 测试建议

### 7.1 提取接口测试

- ✅ 测试单字段提取时，`extraction_rule` 字段存在且内容正确
- ✅ 测试多字段提取时，每个字段的规则信息不同
- ✅ 测试提取失败时，规则信息仍然返回

### 7.2 审核接口测试

- ✅ 测试字段审核时，`audit_rule` 字段存在且内容正确
- ✅ 测试文件审核时，规则信息包含文件相关配置
- ✅ 测试审核失败/待确认时，规则信息仍然返回
- ✅ 测试人工审核项时，规则信息为 None（因为没有配置规则）

---

## 总结

本次修改在提取和审核接口的返回明细中增加了对应的规则信息字段，便于：
1. 前端展示和用户理解
2. 问题排查和调试
3. 规则优化和迭代

所有修改完全向后兼容，不影响现有功能和性能。

