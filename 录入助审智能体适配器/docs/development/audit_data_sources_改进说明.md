# 审核数据源（audit_data_sources）改进说明

## 📝 改进概述

本次改进明确了审核流程中 `audit_data_sources` 和 `reference_materials` 的职责划分，使数据流更加清晰合理。

## 🔧 核心改进

### 1. audit_data_sources 职责调整

**改进前**：
- 类型：字典 `Dict[str, Any]`
- 内容：包含实际数据内容
- 问题：数据源描述和实际内容混在一起，全文内容直接放在数据源中

```python
# 旧格式（不推荐）
audit_data_sources = {
    "材料名称1": {
        "字段1": "实际值1",  # 包含实际数据
        "字段2": "实际值2"
    },
    "材料名称2": "全文内容..."  # 全文直接放在这里
}
```

**改进后**：
- 类型：列表 `List[str]`
- 内容：只描述数据源，不包含实际内容
- 优势：职责清晰，元数据与数据分离

```python
# 新格式（推荐）
audit_data_sources = [
    "信息披露申请书 - 标的名称",
    "信息披露申请书 - 坐落位置",
    "房屋所有权证 - 房屋地址",
    "抵押情况说明 - 全文"  # 只标识需要全文，不包含实际内容
]
```

### 2. reference_materials 职责明确

**职责**：包含实际的参考数据内容，供 LLM 进行审核判断

**格式**：字典 `Dict[str, str]`

**数据来源**：
- **字段值**：从 `extraction_results` 获取（提取结果）
- **全文内容**：从 `parsed_files` 获取（MinerU 解析的 `md_content`）

```python
# reference_materials 示例
reference_materials = {
    # 字段值（来自提取结果）
    "信息披露申请书 - 标的名称": "广东省海珠区光大花园1o栋转让",
    "房屋所有权证 - 房屋地址": "广东省海珠区光大花园10栋",
    
    # 全文内容（来自 parsed_files 的 md_content）
    "抵押情况说明 - 全文": "# 关于抵押情况的说明\n\n根据实地查看..."
}
```

### 3. 全文内容的获取

**改进前**：
- 全文内容处理不完善，有 `logger.warning(f"暂不支持获取全文: {material_name}")`

**改进后**：
- 新增 `_get_parsed_files()` 方法，专门解析文件获取全文内容
- 支持 PDF、图片、Word、TXT 等格式
- 使用 MinerU（PDF/图片）和 Tika（Word/TXT）解析

```python
async def _get_parsed_files(request, enable_cache, files_hash) -> Dict[str, Any]:
    """
    获取解析后的文件内容（包含md_content）
    
    Returns:
        Dict: {file_type: {"file_name": str, "md_content": str}}
    """
```

## 📁 修改文件清单

### 1. `src/services/audit/service.py`

**主要修改**：

1. **新增导入**：
   ```python
   from pathlib import Path
   ```

2. **新增 `_get_parsed_files()` 方法**：
   - 解析所有附件文件
   - 根据文件类型选择解析方案（MinerU/Tika）
   - 返回包含 `md_content` 的字典

3. **修改 `audit_fields()` 方法**：
   ```python
   # 新增：获取解析后的文件内容
   parsed_files = await self._get_parsed_files(request, enable_cache, files_hash)
   
   # 传递给审核方法
   audit_results = await self._audit_all_rules(
       audit_rules=config.audit_rules,
       extraction_results=extraction_results,
       confirmed_fields_map=confirmed_fields_map,
       parsed_files=parsed_files  # 新增参数
   )
   ```

4. **修改 `_audit_all_rules()` 方法**：
   - 新增 `parsed_files: Dict[str, Any]` 参数
   - 传递给 `_audit_single_rule()`

5. **重构 `_audit_single_rule()` 方法**：
   - 新增 `parsed_files: Dict[str, Any]` 参数
   - 改变 `audit_data_sources` 为列表类型（只描述）
   - 从 `parsed_files` 获取全文内容到 `reference_materials`
   - 支持字段审核和文件审核的全文处理

   ```python
   # 改进后的逻辑
   audit_data_sources = []  # 只描述数据源
   reference_materials = {}  # 实际数据内容
   
   # 对于全文：
   if not field_name:  # 全文
       for file_type, file_data in parsed_files.items():
           if material_name in file_data.get("file_name", ""):
               # 只描述
               audit_data_sources.append(f"{material_name} - 全文")
               # 实际内容来自 md_content
               reference_materials[f"{material_name} - 全文"] = file_data.get("md_content", "")
               break
   ```

### 2. `src/services/llm/client.py`

**主要修改**：

1. **新增导入**：
   ```python
   from typing import Dict, Any, Optional, List, Union
   ```

2. **重构 `_format_audit_data_sources()` 方法**：
   ```python
   def _format_audit_data_sources(
       self, 
       data_sources: Union[List[str], Dict[str, Any]]
   ) -> str:
       """
       格式化审核数据源为字符串（只描述数据源，不包含实际内容）
       """
       # 新格式：列表（推荐）
       if isinstance(data_sources, list):
           return "\n".join(data_sources)
       
       # 兼容旧格式：字典（不推荐）
       parts = []
       for material_name, fields in data_sources.items():
           if isinstance(fields, dict):
               for field_name in fields.keys():
                   parts.append(f"{material_name} - {field_name}")
           elif isinstance(fields, str):
               parts.append(f"{material_name} - 全文")
       return "\n".join(parts)
   ```

### 3. `docs/development/audit_api_development.md`

**主要修改**：

1. **新增"关键概念说明"章节**：
   - 详细解释 `audit_data_sources` vs `reference_materials`
   - 提供字段审核和全文审核的完整示例
   - 说明数据来源（提取结果 vs 解析文件）

2. **更新时序图**：
   - 添加 `_get_parsed_files()` 步骤
   - 明确全文内容的获取流程

## 📊 数据流对比

### 改进前的数据流

```
audit_data_sources (包含实际数据) ──┐
                                  ├─→ 格式化 ─→ LLM Agent
reference_materials (实际数据)  ──┘
```

问题：数据源和实际内容混在一起，全文内容直接在 `audit_data_sources` 中

### 改进后的数据流

```
                    ┌─→ extraction_results (字段值)
                    │
parsed_files ───────┼─→ md_content (全文内容)
                    │
                    └─→ 构建 reference_materials (实际数据)

audit_data_sources (只描述) ─→ 格式化 ─→ LLM Agent
                             ┌──────────┘
reference_materials (实际数据) ─┘
```

优势：
1. ✅ 职责清晰：数据源描述 vs 实际数据内容
2. ✅ 全文支持：从 `parsed_files` 的 `md_content` 获取
3. ✅ 类型安全：`audit_data_sources` 为列表，`reference_materials` 为字典
4. ✅ 易于扩展：新增数据源类型更方便

## 🎯 使用示例

### 字段审核（自动映射）

```python
# 规则配置
rule = AuditRule(
    field_name="标的名称",
    audit_type=AuditType.FIELD_AUDIT,
    mapping_type=MappingType.AUTO,
    source_field_name="标的名称",
    include_user_input=True
)

# 生成的参数
audit_data_sources = [
    "信息披露申请书.pdf - 标的名称",
    "房屋所有权证.pdf - 标的名称"
]

reference_materials = {
    "信息披露申请书.pdf - 标的名称": "广东省海珠区光大花园1o栋转让",
    "房屋所有权证.pdf - 标的名称": "广东省海珠区光大花园10栋"
}
```

### 字段审核（自定义映射 + 全文）

```python
# 规则配置
rule = AuditRule(
    field_name="是否有抵押",
    audit_type=AuditType.FIELD_AUDIT,
    mapping_type=MappingType.MANUAL,
    audit_data_sources=[
        AuditDataSource(material_name="信息披露申请书", field_name="是否有抵押"),
        AuditDataSource(material_name="抵押情况说明", field_name=None)  # 全文
    ],
    include_user_input=True
)

# 生成的参数
audit_data_sources = [
    "信息披露申请书 - 是否有抵押",
    "抵押情况说明 - 全文"  # 只标识，不包含内容
]

reference_materials = {
    "信息披露申请书 - 是否有抵押": "无",
    "抵押情况说明 - 全文": "# 关于抵押情况的说明\n\n根据实地查看和权属调查..."  # 完整 md_content
}
```

### 文件审核

```python
# 规则配置
rule = AuditRule(
    field_name="材料完整性",
    audit_type=AuditType.FILE_AUDIT,
    audit_data_sources=[
        AuditDataSource(material_name="信息披露申请书", field_name=None),
        AuditDataSource(material_name="房屋所有权证", field_name=None)
    ]
)

# 生成的参数
audit_data_sources = [
    "信息披露申请书 - 全文",
    "房屋所有权证 - 全文"
]

reference_materials = {
    "信息披露申请书 - 全文": "# 信息披露申请书\n\n## 基本信息\n...",
    "房屋所有权证 - 全文": "# 房屋所有权证\n\n房屋所有权人：..."
}
```

## ✅ 改进效果

1. **职责清晰**：
   - `audit_data_sources`：元数据，描述需要什么数据
   - `reference_materials`：实际数据，供 LLM 审核

2. **类型安全**：
   - `audit_data_sources`：`List[str]`（描述性列表）
   - `reference_materials`：`Dict[str, str]`（键值对）

3. **全文支持**：
   - 提取阶段生成 `parsed_files` 快照
   - 审核阶段复用 MinerU/Tika 的 `md_content`
   - 缺失时按需解析补齐

4. **易于维护**：
   - 数据来源明确（`extraction_results` vs `parsed_files`）
   - 逻辑清晰，便于调试和扩展

## ⚡ 性能优化

### 按需解析文件（v1.1）

**优化目标**：避免不必要的文件解析，节省资源

**实现方式**：

1. **材料名称 ↔ 文件类型映射**：
   - 基于 `FileType` 枚举和请求中的 `file_type`
   - 统一去除文件名后缀、书名号，保证匹配准确

2. **按需解析缺失文件**：
   - 提前收集需要全文的 `file_type`
   - 已有解析结果直接复用，缺失的类型才触发 MinerU/Tika

3. **复用提取服务能力**：
   - 通过 `ExtractionService._parse_files()` 获取解析结果
   - 构建快照 `{file_type: {"file_names": [...], "file_label": "...", "md_content": "..."}}`

4. **日志增强**：
   - 明确列出需要解析的 `file_type`
   - 输出缺失材料、补充解析的明细

**优化效果**：

```python
# 场景1：只有字段审核（自动映射）
# 审核规则：标的名称、坐落位置（都是字段审核，自动映射）
# 优化前：解析所有附件（5个文件）
# 优化后：跳过文件解析（0个文件）✅ 节省100%资源

# 场景2：混合审核（字段 + 文件）
# 审核规则：标的名称（字段审核） + 材料完整性（文件审核，需要2个文件）
# 优化前：解析所有附件（5个文件）
# 优化后：只解析需要的文件（2个文件）✅ 节省60%资源

# 场景3：全文字段审核
# 审核规则：是否有抵押（字段审核 + 自定义映射，需要1个全文）
# 优化前：解析所有附件（5个文件）
# 优化后：只解析需要的文件（1个文件）✅ 节省80%资源
```

**日志示例**：

```log
# 无需全文审核
2025-11-11 10:00:00 | INFO | 无需额外解析文件，复用提取阶段的解析结果

# 需要全文审核
2025-11-11 10:00:00 | INFO | 检测到需要额外解析全文的文件类型: {'info_disclosure_application'}
2025-11-11 10:00:00 | INFO | 按需解析 1 个文件用于全文审核: {'info_disclosure_application'}
2025-11-11 10:00:01 | INFO | 解析文件完成，补充 1 个文件的 md_content
```

### 复用提取解析结果（v1.2）

**优化目标**：提取与审核共享 MinerU/Tika 的解析结果，避免重复解析

**实现方式**：

1. `ExtractionData` 新增 `parsed_files` 字段，存储解析快照  
2. 审核服务优先复用快照；旧缓存缺失时再触发按需解析  
3. 解析快照包含 `file_names`、`file_label`、`md_content` 等信息，便于呈现

**收益**：
- ✅ 避免同一批附件重复解析  
- ✅ 审核阶段直接拿到 `md_content`，构建 LLM 请求更高效  
- ✅ 缓存兼容：旧数据缺失时自动补齐

## 📝 后续建议

1. ✅ 已完成：
   - 基础功能实现和文档更新
   - 按需解析文件优化（v1.1）
   - 复用提取解析结果（v1.2）
   
2. 🔄 建议优化：
   - 考虑缓存 `parsed_files` 结果（类似 `extraction_results`）
   - 添加文件解析结果的哈希缓存
   - 优化全文内容的截断策略（避免 token 超限）
   - 改进材料名称匹配逻辑（目前是简单的字符串包含，可以考虑更精确的匹配）
   
3. 📊 性能监控：
   - 监控文件解析时间
   - 优化大文件的处理策略
   - 统计文件解析跳过率

---

**版本**: v1.2  
**日期**: 2025-11-11  
**更新**: 按需解析 + 解析结果复用  
**状态**: ✅ 已完成

