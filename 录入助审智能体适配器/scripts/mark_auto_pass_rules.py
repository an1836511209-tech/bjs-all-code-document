#!/usr/bin/env python3
"""
标记审核规则自动通过脚本

此脚本用于标记【无纸项目】审核规则的 auto_pass_when_missing 字段。
注意：只处理无纸项目（无纸大宗实物、无纸小宗实物），有纸项目不会被处理。

自动通过的条件：
1. 字段审核规则，且 audit_data_sources 只有一个元素，且该元素的 material_name 是 "《信息披露申请书》"
2. 字段审核规则，且 mapping_type 是 "auto"，根据 source_field_name 去提取规则中查找对应字段，
   如果该提取规则的 reference_materials 只有一个元素且是 "《信息披露申请书》"
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Optional


# 信息披露申请书的材料名称
INFO_DISCLOSURE_MATERIAL = "《信息披露申请书》"

# 只处理无纸业务类型
PAPERLESS_TYPES = ["无纸大宗实物", "无纸小宗实物"]


def load_config(file_path: Path) -> Dict[str, Any]:
    """加载规则配置文件"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_config(file_path: Path, config: Dict[str, Any]):
    """保存规则配置文件"""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def build_extraction_rules_map(extraction_rules: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """构建提取规则映射 {field_name: rule}"""
    return {rule.get('field_name'): rule for rule in extraction_rules if rule.get('field_name')}


def should_mark_auto_pass(
    audit_rule: Dict[str, Any],
    extraction_rules_map: Dict[str, Dict[str, Any]]
) -> tuple[bool, str]:
    """
    判断审核规则是否应该标记为自动通过
    
    Returns:
        (should_mark, reason): 是否应该标记以及原因
    """
    # 只处理字段审核类型
    if audit_rule.get('audit_type') != '字段审核':
        return False, "非字段审核类型"
    
    # 如果已经标记了自动通过，跳过
    if audit_rule.get('auto_pass_when_missing') is True:
        return False, "已标记自动通过"
    
    audit_data_sources = audit_rule.get('audit_data_sources')
    mapping_type = audit_rule.get('mapping_type')
    source_field_name = audit_rule.get('source_field_name')
    
    # 条件1: audit_data_sources 只有一个元素，且 material_name 是《信息披露申请书》
    if audit_data_sources and len(audit_data_sources) == 1:
        material_name = audit_data_sources[0].get('material_name', '').strip()
        if material_name == INFO_DISCLOSURE_MATERIAL:
            return True, f"audit_data_sources只有一个《信息披露申请书》"
    
    # 条件2: mapping_type 是 "auto"，根据 source_field_name 查找提取规则
    if mapping_type == 'auto' and source_field_name:
        extraction_rule = extraction_rules_map.get(source_field_name)
        if extraction_rule:
            reference_materials = extraction_rule.get('reference_materials', [])
            # 只有一个参考材料且是《信息披露申请书》
            if len(reference_materials) == 1 and reference_materials[0] == INFO_DISCLOSURE_MATERIAL:
                return True, f"mapping_type=auto，提取规则'{source_field_name}'只引用《信息披露申请书》"
    
    return False, "不满足自动通过条件"


def process_config_file(file_path: Path, dry_run: bool = False) -> Dict[str, Any]:
    """
    处理单个配置文件
    
    注意：只处理无纸项目（无纸大宗实物、无纸小宗实物）
    
    Args:
        file_path: 配置文件路径
        dry_run: 是否为测试运行（不实际修改文件）
        
    Returns:
        处理统计信息
    """
    config = load_config(file_path)
    
    business_type = config.get('business_type', 'Unknown')
    
    stats = {
        'file': file_path.name,
        'config_name': config.get('name', 'Unknown'),
        'business_type': business_type,
        'total_audit_rules': 0,
        'marked_rules': [],
        'skipped_rules': [],
        'skipped_reason': None
    }
    
    # 只处理无纸项目
    if business_type not in PAPERLESS_TYPES:
        stats['skipped_reason'] = f"跳过（{business_type}不是无纸项目）"
        return stats
    
    audit_rules = config.get('audit_rules', [])
    extraction_rules = config.get('extraction_rules', [])
    extraction_rules_map = build_extraction_rules_map(extraction_rules)
    
    stats['total_audit_rules'] = len(audit_rules)
    modified = False
    
    for rule in audit_rules:
        rule_name = rule.get('field_name', 'Unknown')
        should_mark, reason = should_mark_auto_pass(rule, extraction_rules_map)
        
        if should_mark:
            rule['auto_pass_when_missing'] = True
            rule['updated_at'] = datetime.now().isoformat()
            stats['marked_rules'].append({
                'field_name': rule_name,
                'reason': reason
            })
            modified = True
        else:
            stats['skipped_rules'].append({
                'field_name': rule_name,
                'reason': reason
            })
    
    # 保存修改
    if modified and not dry_run:
        save_config(file_path, config)
        print(f"  [已保存] {file_path.name}")
    
    return stats


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='标记审核规则的 auto_pass_when_missing 字段'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='测试运行，不实际修改文件'
    )
    parser.add_argument(
        '--file',
        type=str,
        help='指定处理单个文件（相对于项目根目录）'
    )
    parser.add_argument(
        '--verbose',
        '-v',
        action='store_true',
        help='显示详细信息'
    )
    
    args = parser.parse_args()
    
    # 确定配置文件目录
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    config_dir = project_root / 'data' / 'rule_configs'
    
    if args.dry_run:
        print("=" * 60)
        print("【测试运行模式 - 不会实际修改文件】")
        print("=" * 60)
    
    # 获取要处理的文件列表
    if args.file:
        files = [project_root / args.file]
    else:
        files = list(config_dir.glob('*.json'))
    
    if not files:
        print("未找到任何配置文件")
        return
    
    print(f"\n找到 {len(files)} 个配置文件\n")
    
    total_marked = 0
    all_stats = []
    
    for file_path in files:
        if not file_path.exists():
            print(f"文件不存在: {file_path}")
            continue
            
        print(f"\n处理: {file_path.name}")
        print("-" * 40)
        
        stats = process_config_file(file_path, dry_run=args.dry_run)
        all_stats.append(stats)
        
        print(f"  配置名称: {stats['config_name']}")
        print(f"  业务类型: {stats['business_type']}")
        
        # 检查是否因为业务类型被跳过
        if stats.get('skipped_reason'):
            print(f"  处理结果: {stats['skipped_reason']}")
            continue
        
        print(f"  审核规则总数: {stats['total_audit_rules']}")
        print(f"  标记自动通过: {len(stats['marked_rules'])} 条")
        
        if stats['marked_rules']:
            total_marked += len(stats['marked_rules'])
            print("\n  已标记的规则:")
            for item in stats['marked_rules']:
                print(f"    - {item['field_name']}: {item['reason']}")
        
        if args.verbose and stats['skipped_rules']:
            print("\n  跳过的规则:")
            for item in stats['skipped_rules']:
                if '不满足' not in item['reason'] and '非字段审核' not in item['reason']:
                    print(f"    - {item['field_name']}: {item['reason']}")
    
    # 汇总
    print("\n" + "=" * 60)
    print("【处理汇总】")
    print("=" * 60)
    print(f"处理文件数: {len(all_stats)}")
    print(f"总共标记自动通过: {total_marked} 条规则")
    
    if args.dry_run:
        print("\n注意: 这是测试运行，未实际修改任何文件。")
        print("如需实际执行，请移除 --dry-run 参数。")


if __name__ == '__main__':
    main()

