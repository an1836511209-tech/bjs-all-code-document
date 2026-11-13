#!/usr/bin/env python3
"""
修复脚本：移除有纸项目中误标记的 auto_pass_when_missing 字段

只有无纸项目（无纸大宗实物、无纸小宗实物）才需要标记自动通过
有纸项目（有纸大宗实物、有纸小宗实物）不需要这个标记
"""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List


# 无纸业务类型（这些需要保留 auto_pass_when_missing）
PAPERLESS_TYPES = ["无纸大宗实物", "无纸小宗实物"]

# 有纸业务类型（这些需要移除 auto_pass_when_missing）
PAPER_TYPES = ["有纸大宗实物", "有纸小宗实物"]


def load_config(file_path: Path) -> Dict[str, Any]:
    """加载规则配置文件"""
    with open(file_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_config(file_path: Path, config: Dict[str, Any]):
    """保存规则配置文件"""
    with open(file_path, 'w', encoding='utf-8') as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def fix_config_file(file_path: Path, dry_run: bool = False) -> Dict[str, Any]:
    """
    修复单个配置文件
    
    对于有纸项目，移除所有 auto_pass_when_missing 字段
    
    Args:
        file_path: 配置文件路径
        dry_run: 是否为测试运行
        
    Returns:
        处理统计信息
    """
    config = load_config(file_path)
    
    business_type = config.get('business_type', 'Unknown')
    config_name = config.get('name', 'Unknown')
    
    stats = {
        'file': file_path.name,
        'config_name': config_name,
        'business_type': business_type,
        'action': None,
        'fixed_rules': []
    }
    
    # 只处理有纸类型
    if business_type not in PAPER_TYPES:
        stats['action'] = f"跳过（{business_type}是无纸类型，保留标记）"
        return stats
    
    stats['action'] = "移除 auto_pass_when_missing 标记"
    
    audit_rules = config.get('audit_rules', [])
    modified = False
    
    for rule in audit_rules:
        if 'auto_pass_when_missing' in rule:
            rule_name = rule.get('field_name', 'Unknown')
            # 移除该字段
            del rule['auto_pass_when_missing']
            stats['fixed_rules'].append(rule_name)
            modified = True
    
    # 保存修改
    if modified and not dry_run:
        save_config(file_path, config)
        print(f"  [已修复] {file_path.name}")
    
    return stats


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description='修复有纸项目中误标记的 auto_pass_when_missing 字段'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='测试运行，不实际修改文件'
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
    
    files = list(config_dir.glob('*.json'))
    
    if not files:
        print("未找到任何配置文件")
        return
    
    print(f"\n找到 {len(files)} 个配置文件\n")
    
    total_fixed = 0
    all_stats = []
    
    for file_path in files:
        print(f"\n处理: {file_path.name}")
        print("-" * 40)
        
        stats = fix_config_file(file_path, dry_run=args.dry_run)
        all_stats.append(stats)
        
        print(f"  配置名称: {stats['config_name']}")
        print(f"  业务类型: {stats['business_type']}")
        print(f"  处理操作: {stats['action']}")
        
        if stats['fixed_rules']:
            total_fixed += len(stats['fixed_rules'])
            print(f"  修复规则数: {len(stats['fixed_rules'])} 条")
            print(f"  修复的规则: {', '.join(stats['fixed_rules'][:5])}{'...' if len(stats['fixed_rules']) > 5 else ''}")
    
    # 汇总
    print("\n" + "=" * 60)
    print("【修复汇总】")
    print("=" * 60)
    print(f"处理文件数: {len(all_stats)}")
    print(f"总共修复规则: {total_fixed} 条")
    
    if args.dry_run:
        print("\n注意: 这是测试运行，未实际修改任何文件。")
        print("如需实际执行，请移除 --dry-run 参数。")


if __name__ == '__main__':
    main()

