"""
字段值转换工具

提供字段值的类型转换和字段映射构建功能
"""

import json
from typing import Any, Dict, List, Set
from loguru import logger


# 需要展开的嵌套字段列表
# 这些字段的 field_value 是对象数组，需要将其内部字段也展开到映射中
NESTED_FIELD_NAMES: Set[str] = {"ZRF"}

# 需要特殊处理的字段：如果ZRF里有这些字段，即使主字段也有，也要用ZRF里的值覆盖
# 这些字段在嵌套字段中具有更高优先级
NESTED_FIELD_OVERRIDE_NAMES: Set[str] = {"BZ"}


class FieldValueConverter:
    """字段值转换工具类"""
    
    @staticmethod
    def convert_field_value_to_string(value: Any) -> str:
        """
        将字段值转换为字符串（用于 LLM 输入）
        
        支持各种 JSON 类型：
        - 字符串：直接返回
        - 数字/布尔值：转为字符串
        - 列表：如果元素是字符串，用逗号连接；否则转为 JSON 格式
        - 对象/字典：转为 JSON 格式
        - None：返回空字符串
        
        Args:
            value: 字段值（任意类型）
            
        Returns:
            str: 字符串形式的字段值
            
        Examples:
            >>> convert_field_value_to_string("test")
            'test'
            
            >>> convert_field_value_to_string(123)
            '123'
            
            >>> convert_field_value_to_string(["a", "b", "c"])
            'a, b, c'
            
            >>> convert_field_value_to_string([1, 2, 3])
            '[1, 2, 3]'
            
            >>> convert_field_value_to_string({"key": "value"})
            '{"key": "value"}'
            
            >>> convert_field_value_to_string(None)
            ''
        """
        if value is None:
            return ""
        
        # 如果已经是字符串，直接返回
        if isinstance(value, str):
            return value
        
        # 如果是数字或布尔值，转为字符串
        if isinstance(value, (int, float, bool)):
            return str(value)
        
        # 如果是列表
        if isinstance(value, list):
            # 如果所有元素都是字符串，用逗号连接
            if value and all(isinstance(item, str) for item in value):
                return ", ".join(value)
            # 否则转为 JSON 格式
            return json.dumps(value, ensure_ascii=False)
        
        # 其他类型（对象/字典等），转为 JSON 格式
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError) as e:
            logger.warning(f"字段值转换为字符串失败: {e}, value={value}")
            return str(value)
    
    @staticmethod
    def build_confirmed_fields_map(confirmed_fields: List[Any]) -> Dict[str, Any]:
        """
        构建用户确认字段映射表
        
        将字段列表转换为字典，便于快速查找字段值
        对于嵌套字段（如 ZRF），会自动展开其子字段到映射中
        
        Args:
            confirmed_fields: 确认字段列表（每项需包含field_name和field_value属性）
            
        Returns:
            Dict[str, Any]: 字段映射 {field_name: field_value}
            
        Examples:
            >>> fields = [
            ...     ConfirmedField(field_name="标的名称", field_value="测试标的"),
            ...     ConfirmedField(field_name="ZRF", field_value=[{"NBJCWJLX": "股东会决议"}])
            ... ]
            >>> build_confirmed_fields_map(fields)
            {
                "标的名称": "测试标的",
                "ZRF": [{"NBJCWJLX": "股东会决议"}],
                "NBJCWJLX": "股东会决议"  # 展开的子字段
            }
        """
        result = {}
        
        for field in confirmed_fields:
            field_name = field.field_name
            field_value = field.field_value
            
            # 添加原始字段映射
            result[field_name] = field_value
            
            # 对于嵌套字段，展开其子字段
            if field_name in NESTED_FIELD_NAMES:
                FieldValueConverter._expand_nested_field(result, field_name, field_value)
        
        return result
    
    @staticmethod
    def _expand_nested_field(result: Dict[str, Any], parent_name: str, field_value: Any) -> None:
        """
        展开嵌套字段的子字段到映射中
        
        注意：嵌套字段（如 ZRF）的子字段具有更高优先级，会覆盖同名的独立字段
        
        Args:
            result: 结果映射字典
            parent_name: 父字段名称（用于日志）
            field_value: 嵌套字段的值（通常是对象数组）
        """
        if not field_value:
            return
        
        # 如果是列表（对象数组），取第一个元素展开
        if isinstance(field_value, list) and len(field_value) > 0:
            first_item = field_value[0]
            if isinstance(first_item, dict):
                expanded_count = 0
                overwritten_count = 0
                for sub_field_name, sub_field_value in first_item.items():
                    # ZRF 子字段具有更高优先级，允许覆盖同名独立字段
                    if sub_field_name in result:
                        logger.debug(f"嵌套字段 {parent_name} 的子字段 '{sub_field_name}' 覆盖了独立字段（旧值: {result[sub_field_name]}, 新值: {sub_field_value}）")
                        overwritten_count += 1
                    result[sub_field_name] = sub_field_value
                    expanded_count += 1
                if expanded_count > 0:
                    logger.debug(f"从嵌套字段 {parent_name} 展开了 {expanded_count} 个子字段（覆盖: {overwritten_count}）")
        
        # 如果直接是字典
        elif isinstance(field_value, dict):
            expanded_count = 0
            overwritten_count = 0
            for sub_field_name, sub_field_value in field_value.items():
                # ZRF 子字段具有更高优先级，允许覆盖同名独立字段
                if sub_field_name in result:
                    logger.debug(f"嵌套字段 {parent_name} 的子字段 '{sub_field_name}' 覆盖了独立字段（旧值: {result[sub_field_name]}, 新值: {sub_field_value}）")
                    overwritten_count += 1
                result[sub_field_name] = sub_field_value
                expanded_count += 1
            if expanded_count > 0:
                logger.debug(f"从嵌套字段 {parent_name} 展开了 {expanded_count} 个子字段（覆盖: {overwritten_count}）")
    
    @staticmethod
    def expand_confirmed_fields(confirmed_fields: List[Any]) -> List[Dict[str, Any]]:
        """
        展开确认字段列表，将嵌套字段的子字段也转换为独立的字段项
        
        用于 _add_manual_review_items 等需要遍历所有字段（包括嵌套子字段）的场景
        
        Args:
            confirmed_fields: 确认字段列表（每项需包含field_name和field_value属性）
            
        Returns:
            List[Dict[str, Any]]: 展开后的字段列表，每项包含 field_name, field_value, field_type
            
        Examples:
            >>> fields = [
            ...     ConfirmedField(field_name="标的名称", field_value="测试标的", field_type="text"),
            ...     ConfirmedField(field_name="ZRF", field_value=[{"NBJCWJLX": "股东会决议"}], field_type="object")
            ... ]
            >>> expand_confirmed_fields(fields)
            [
                {"field_name": "标的名称", "field_value": "测试标的", "field_type": "text"},
                {"field_name": "ZRF", "field_value": [{"NBJCWJLX": "股东会决议"}], "field_type": "object"},
                {"field_name": "NBJCWJLX", "field_value": "股东会决议", "field_type": "text"}  # 展开的子字段
            ]
        """
        result = []
        seen_field_names = set()  # 用于避免重复添加
        
        for field in confirmed_fields:
            field_name = field.field_name
            field_value = field.field_value
            field_type = getattr(field, 'field_type', 'text')
            
            # 添加原始字段
            if field_name not in seen_field_names:
                result.append({
                    "field_name": field_name,
                    "field_value": field_value,
                    "field_type": field_type
                })
                seen_field_names.add(field_name)
            
            # 对于嵌套字段，展开其子字段
            if field_name in NESTED_FIELD_NAMES:
                sub_fields = FieldValueConverter._get_nested_sub_fields(field_value)
                for sub_field_name, sub_field_value in sub_fields.items():
                    # 特殊处理：对于BZ等字段，如果ZRF里有，即使主字段也有，也要用ZRF里的值覆盖
                    if sub_field_name in NESTED_FIELD_OVERRIDE_NAMES and sub_field_name in seen_field_names:
                        # 找到result中对应的字段并更新
                        for item in result:
                            if item["field_name"] == sub_field_name:
                                old_value = item["field_value"]
                                item["field_value"] = sub_field_value
                                item["field_type"] = FieldValueConverter._infer_field_type(sub_field_value)
                                logger.debug(f"嵌套字段 {field_name} 的子字段 '{sub_field_name}' 覆盖了独立字段（旧值: {old_value}, 新值: {sub_field_value}）")
                                break
                    elif sub_field_name not in seen_field_names:
                        # 推断子字段类型
                        sub_field_type = FieldValueConverter._infer_field_type(sub_field_value)
                        result.append({
                            "field_name": sub_field_name,
                            "field_value": sub_field_value,
                            "field_type": sub_field_type
                        })
                        seen_field_names.add(sub_field_name)
                        logger.debug(f"从嵌套字段 {field_name} 展开子字段: {sub_field_name}")
        
        return result
    
    @staticmethod
    def _get_nested_sub_fields(field_value: Any) -> Dict[str, Any]:
        """
        从嵌套字段值中获取子字段
        
        Args:
            field_value: 嵌套字段的值（通常是对象数组或字典）
            
        Returns:
            Dict[str, Any]: 子字段映射 {field_name: field_value}
        """
        result = {}
        
        if not field_value:
            return result
        
        # 如果是列表（对象数组），取第一个元素展开
        if isinstance(field_value, list) and len(field_value) > 0:
            first_item = field_value[0]
            if isinstance(first_item, dict):
                result.update(first_item)
        
        # 如果直接是字典
        elif isinstance(field_value, dict):
            result.update(field_value)
        
        return result
    
    @staticmethod
    def _infer_field_type(value: Any) -> str:
        """
        推断字段类型
        
        Args:
            value: 字段值
            
        Returns:
            str: 字段类型（text, number, boolean, object, array）
        """
        if value is None:
            return "text"
        if isinstance(value, str):
            return "text"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, (int, float)):
            return "number"
        if isinstance(value, list):
            return "array"
        if isinstance(value, dict):
            return "object"
        return "text"
    
    @staticmethod
    def _parse_multi_value(value: Any) -> List[str]:
        """
        解析多值字段（支持数组、JSON字符串、逗号分隔字符串）
        
        Args:
            value: 字段值（可能是字符串、数组等）
            
        Returns:
            List[str]: 解析后的值列表
            
        Examples:
            >>> _parse_multi_value("土地,房屋建筑物")
            ["土地", "房屋建筑物"]
            
            >>> _parse_multi_value(["土地", "房屋建筑物"])
            ["土地", "房屋建筑物"]
            
            >>> _parse_multi_value('["土地", "房屋建筑物"]')
            ["土地", "房屋建筑物"]
            
            >>> _parse_multi_value("土地")
            ["土地"]
        """
        if not value:
            return []
        
        # 如果已经是列表，直接返回（转换为字符串列表）
        if isinstance(value, list):
            return [str(v).strip() for v in value if v]
        
        # 如果是字符串，尝试多种解析方式
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return []
            
            # 1. 尝试解析为 JSON 数组
            if value.startswith('[') and value.endswith(']'):
                try:
                    parsed = json.loads(value)
                    if isinstance(parsed, list):
                        return [str(v).strip() for v in parsed if v]
                except (json.JSONDecodeError, TypeError):
                    pass
            
            # 2. 按逗号分割（如果包含逗号）
            if ',' in value:
                return [v.strip() for v in value.split(',') if v.strip()]
            
            # 3. 单个值
            return [value]
        
        # 其他类型，转为字符串后返回
        return [str(value).strip()]
    
    @staticmethod
    def is_field_value_empty(value: Any) -> bool:
        """
        判断字段值是否为空
        
        Args:
            value: 字段值
            
        Returns:
            bool: 是否为空
            
        Examples:
            >>> is_field_value_empty(None)
            True
            
            >>> is_field_value_empty("")
            True
            
            >>> is_field_value_empty([])
            True
            
            >>> is_field_value_empty("test")
            False
        """
        if value is None:
            return True
        
        if isinstance(value, str) and not value.strip():
            return True
        
        if isinstance(value, (list, dict)) and not value:
            return True
        
        return False
    
    @staticmethod
    def filter_fields_by_cascade(
        confirmed_fields: List[Any],
        audit_type: str
    ) -> List[Any]:
        """
        根据级联关系过滤不应显示的字段
        
        根据业务类型获取对应的选择性级联配置，然后根据主字段的值
        确定哪些子字段是"活跃"的，过滤掉非活跃的子字段。
        
        只在 audit_type 为大宗实物或小宗实物类型时生效。
        
        Args:
            confirmed_fields: 确认字段列表（每项需包含field_name和field_value属性）
            audit_type: 审核/提取类型（如"有纸大宗实物"、"无纸大宗实物"等）
            
        Returns:
            List[Any]: 过滤后的字段列表，已移除因级联关系不应显示的字段
            
        Examples:
            假设转让方类型(ZRFLX)选择了"自然人"，则：
            - 保留：ZJLX（证件类型）、ZJHM（证件号码）、ZCD（注册地）
            - 过滤：YYZZSFCQ（营业执照是否存期）等法人相关字段
        """
        from src.services.extraction.cascade_configs import get_conditional_cascade_configs
        
        # 获取该业务类型的级联配置
        cascade_configs = get_conditional_cascade_configs(audit_type)
        if not cascade_configs:
            # 无配置（如小宗实物暂未配置），不过滤
            return confirmed_fields
        
        # 构建字段值映射（用于查询主字段的值）
        field_values: Dict[str, Any] = {}
        for field in confirmed_fields:
            field_values[field.field_name] = field.field_value
        
        # 收集所有应该被过滤的字段
        fields_to_filter: Set[str] = set()
        
        for config in cascade_configs:
            # 获取主字段的值
            master_value = field_values.get(config.master_field)
            
            # 获取该配置中所有可能的子字段
            all_children: Set[str] = set()
            for children in config.field_mapping.values():
                if isinstance(children, list):
                    all_children.update(children)
                else:
                    all_children.add(children)
            
            # 计算共享字段（在所有选项中都出现的字段）
            # 共享字段无论选择哪个选项都应该保留，不应该被过滤
            shared_children: Set[str] = set()
            option_sets = []
            for children in config.field_mapping.values():
                if isinstance(children, list):
                    option_sets.append(set(children))
                else:
                    option_sets.append({children})
            
            if option_sets:
                shared_children = option_sets[0].copy()
                for option_set in option_sets[1:]:
                    shared_children &= option_set
            
            # 获取当前应该显示的"活跃"子字段
            active_children: Set[str] = set()
            if master_value:
                # 支持多值：解析为列表（支持数组、JSON字符串、逗号分隔字符串）
                master_values = FieldValueConverter._parse_multi_value(master_value)
                
                # 遍历所有值，收集对应的子字段
                for value in master_values:
                    value_clean = value.strip() if isinstance(value, str) else str(value).strip()
                    mapped = config.field_mapping.get(value_clean, [])
                    if isinstance(mapped, list):
                        active_children.update(mapped)
                    elif mapped:  # 非空字符串或其他值
                        active_children.add(mapped)
                
                if master_values:
                    logger.debug(
                        f"级联过滤 - 主字段 {config.master_field}="
                        f"{master_values}, 活跃子字段: {active_children}"
                    )
            
            # 不应显示的子字段 = (所有子字段 - 活跃子字段) - 共享字段
            inactive_children = (all_children - active_children) - shared_children
            fields_to_filter.update(inactive_children)
        
        if fields_to_filter:
            logger.debug(f"根据级联关系过滤字段: {fields_to_filter}")
        
        # 过滤字段
        return [f for f in confirmed_fields if f.field_name not in fields_to_filter]
    
    @staticmethod
    def get_fields_to_filter_by_cascade(
        confirmed_fields: List[Any],
        audit_type: str
    ) -> Set[str]:
        """
        获取根据级联关系应该被过滤的字段名集合
        
        与 filter_fields_by_cascade 类似，但只返回字段名集合，
        用于在审核结果中过滤不应显示的字段。
        
        Args:
            confirmed_fields: 确认字段列表（每项需包含field_name和field_value属性）
            audit_type: 审核/提取类型（如"有纸大宗实物"、"无纸大宗实物"等）
            
        Returns:
            Set[str]: 应该被过滤的字段名集合
        """
        from src.services.extraction.cascade_configs import get_conditional_cascade_configs
        
        # 获取该业务类型的级联配置
        cascade_configs = get_conditional_cascade_configs(audit_type)
        if not cascade_configs:
            return set()
        
        # 构建字段值映射（用于查询主字段的值）
        # 使用 build_confirmed_fields_map 以正确处理嵌套字段（如ZRF）的展开
        field_values = FieldValueConverter.build_confirmed_fields_map(confirmed_fields)
        
        # 收集所有应该被过滤的字段
        fields_to_filter: Set[str] = set()
        
        for config in cascade_configs:
            # 获取主字段的值
            master_value = field_values.get(config.master_field)
            
            # 获取该配置中所有可能的子字段
            all_children: Set[str] = set()
            for children in config.field_mapping.values():
                if isinstance(children, list):
                    all_children.update(children)
                else:
                    all_children.add(children)
            
            # 计算共享字段（在所有选项中都出现的字段）
            # 共享字段无论选择哪个选项都应该保留，不应该被过滤
            # 例如：ZCD 在"自然人"和"法人"中都有，应该永远保留
            shared_children: Set[str] = set()
            option_sets = []
            for children in config.field_mapping.values():
                if isinstance(children, list):
                    option_sets.append(set(children))
                else:
                    option_sets.append({children})
            
            if option_sets:
                # 共享字段 = 所有选项的交集
                shared_children = option_sets[0].copy()
                for option_set in option_sets[1:]:
                    shared_children &= option_set
            
            # 获取当前应该显示的"活跃"子字段
            active_children: Set[str] = set()
            if master_value:
                # 支持多值：解析为列表（支持数组、JSON字符串、逗号分隔字符串）
                master_values = FieldValueConverter._parse_multi_value(master_value)
                
                # 遍历所有值，收集对应的子字段
                for value in master_values:
                    value_clean = value.strip() if isinstance(value, str) else str(value).strip()
                    mapped = config.field_mapping.get(value_clean, [])
                    if isinstance(mapped, list):
                        active_children.update(mapped)
                    elif mapped:  # 非空字符串或其他值
                        active_children.add(mapped)
                
                if master_values:
                    logger.debug(
                        f"级联过滤 - 主字段 {config.master_field}="
                        f"{master_values}, 活跃子字段: {active_children}"
                    )
            
            # 不应显示的子字段 = (所有子字段 - 活跃子字段) - 共享字段
            # 共享字段永远不过滤
            inactive_children = (all_children - active_children) - shared_children
            fields_to_filter.update(inactive_children)
        
        return fields_to_filter

