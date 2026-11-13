#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NL2SQL测试应用程序
使用Streamlit构建的自动化测试工具，用于验证NL2SQL Agent的准确率和召回率

依赖安装：
pip install streamlit pymysql requests pandas numpy

使用方法：
streamlit run nl2sql_test_app.py
"""

import streamlit as st
import pymysql
import requests
import pandas as pd
import json
import random
import time
from typing import Dict, List, Tuple, Any, Optional
from datetime import datetime
import traceback

# 页面配置
st.set_page_config(
    page_title="NL2SQL测试工具",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# 测试模式选项
TEST_MODES = {
    "single_field": {"name": "单字段测试", "field_count": 1, "description": "每个测试用例使用一个字段条件"},
    "double_field": {"name": "双字段测试", "field_count": 2, "description": "每个测试用例使用两个字段条件"},
    "multi_field": {"name": "多字段测试", "field_count": 5, "description": "每个测试用例使用最多五个字段条件"}
}

# 数据库配置
DB_CONFIG = {
    "host": "10.254.89.160",
    "port": 3306,
    "user": "hiagent",
    "password": "hiAgent2025M",
    "database": "testnl2sql",
    "charset": "utf8mb4"
}

# Agent接口配置
AGENT_CONFIG = {
    "url": "http://10.224.98.172/openapi/agents/chat/completions/v1",
    "headers": {
        "Authorization": "Bearer ae80dcd4bf3c4180bc44d3df2f66143a.oLlO0tI981LDnhTtojAMBPqm3TF2ZZuA",
        "Content-Type": "application/json"
    },
    "agent_id": "b49193100608468e86f441c2b16c4a9b"
}

# 需要测试的表名
TABLES_TO_TEST = [
    'debt_assets',        # 债权资产表
    'other_assets',       # 其他资产表  
    'property_rental',    # 房屋出租表
    'property_land',      # 房屋土地表
    'culture_tourism_sports',  # 文旅体育表
    'equity_increase',    # 股权增资表
    'equity_transfer'     # 股权转让表
]

# 表名映射
TABLE_NAME_MAP = {
    'debt_assets': '债权资产表',
    'other_assets': '其他资产表',
    'property_rental': '房屋出租表',
    'property_land': '房屋土地表',
    'culture_tourism_sports': '文旅体育表',
    'equity_increase': '股权增资表',
    'equity_transfer': '股权转让表'
}


class DatabaseManager:
    """数据库管理类"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.connection = None
    
    def connect(self) -> bool:
        """连接数据库"""
        try:
            self.connection = pymysql.connect(**self.config)
            return True
        except Exception as e:
            st.error(f"数据库连接失败: {str(e)}")
            return False
    
    def close(self):
        """关闭数据库连接"""
        if self.connection:
            self.connection.close()
    
    def get_table_columns(self, table_name: str) -> List[str]:
        """获取表的所有列名"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(f"DESCRIBE {table_name}")
                columns = [row[0] for row in cursor.fetchall()]
                return columns
        except Exception as e:
            st.error(f"获取表 {table_name} 列信息失败: {str(e)}")
            return []
    
    def get_column_comment(self, table_name: str, column_name: str) -> str:
        """获取字段的注释"""
        try:
            with self.connection.cursor() as cursor:
                sql = """
                SELECT COLUMN_COMMENT 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s
                """
                cursor.execute(sql, (self.config['database'], table_name, column_name))
                result = cursor.fetchone()
                if result and result[0]:
                    comment = result[0].strip()
                    # 如果注释为空或者就是字段名，返回字段名
                    if not comment or comment == column_name:
                        return column_name
                    return comment
                return column_name
        except Exception as e:
            st.warning(f"获取字段注释失败 {table_name}.{column_name}: {str(e)}")
            return column_name
    
    def check_column_has_data(self, table_name: str, column_name: str) -> bool:
        """检查字段是否有非空值"""
        try:
            with self.connection.cursor() as cursor:
                # 使用反引号包围字段名，防止保留字冲突
                # 对于TIMESTAMP和DATETIME字段，特殊处理空字符串
                sql = f"""
                SELECT COUNT(*) FROM `{table_name}` 
                WHERE `{column_name}` IS NOT NULL 
                AND `{column_name}` != '' 
                AND `{column_name}` != '0000-00-00 00:00:00'
                """
                cursor.execute(sql)
                count = cursor.fetchone()[0]
                return count > 0
        except Exception as e:
            st.warning(f"检查字段 {table_name}.{column_name} 时出错: {str(e)}")
            return False
    
    def get_random_value(self, table_name: str, column_name: str) -> Optional[str]:
        """获取字段的随机非空值"""
        try:
            with self.connection.cursor() as cursor:
                sql = f"""
                SELECT `{column_name}` FROM `{table_name}` 
                WHERE `{column_name}` IS NOT NULL 
                AND `{column_name}` != '' 
                AND `{column_name}` != '0000-00-00 00:00:00'
                ORDER BY RAND() LIMIT 1
                """
                cursor.execute(sql)
                result = cursor.fetchone()
                if result and result[0]:
                    value = str(result[0])
                    # 清理值，避免过长或包含特殊字符的值
                    if len(value) > 100:  # 限制值的长度，超过100字符跳过
                        return None
                    # 过滤包含特殊字符的值，可能导致SQL问题
                    if any(char in value for char in ['\n', '\r', '\t', '\\', '"']):
                        # 尝试清理这些字符
                        value = value.replace('\n', ' ').replace('\r', ' ').replace('\t', ' ')
                        value = value.replace('\\', '').replace('"', '')
                        if not value.strip():
                            return None
                    return value.strip()
                return None
        except Exception as e:
            st.warning(f"获取随机值 {table_name}.{column_name} 时出错: {str(e)}")
            return None
    
    def execute_sql(self, sql: str) -> List[str]:
        """执行SQL并返回project_code列表"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql)
                results = cursor.fetchall()
                return [str(row[0]) for row in results] if results else []
        except Exception as e:
            st.warning(f"执行SQL时出错: {str(e)}")
            return []
    
    def execute_sql_with_params(self, sql: str, params: tuple) -> List[str]:
        """使用参数化查询执行SQL并返回project_code列表"""
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(sql, params)
                results = cursor.fetchall()
                return [str(row[0]) for row in results] if results else []
        except Exception as e:
            st.warning(f"执行参数化SQL时出错: {str(e)}")
            return []


class TestCaseGenerator:
    """测试用例生成器"""
    
    def __init__(self, db_manager: DatabaseManager, test_mode: str = "single_field"):
        self.db_manager = db_manager
        self.test_mode = test_mode
        self.field_count = TEST_MODES[test_mode]["field_count"]
    
    def generate_test_cases(self) -> List[Dict[str, Any]]:
        """生成所有测试用例"""
        test_cases = []
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        total_tables = len(TABLES_TO_TEST)
        
        # 创建详细进度显示
        current_table_container = st.empty()
        current_field_container = st.empty()
        
        for i, table_name in enumerate(TABLES_TO_TEST):
            status_text.text(f"正在处理表: {TABLE_NAME_MAP[table_name]} ({i+1}/{total_tables})")
            
            with current_table_container:
                st.write(f"**当前处理表:** {TABLE_NAME_MAP[table_name]} ({table_name})")
                st.write(f"**测试模式:** {TEST_MODES[self.test_mode]['name']} ({self.field_count}个字段)")
            
            columns = self.db_manager.get_table_columns(table_name)
            if not columns:
                with current_field_container:
                    st.write("❌ 无法获取表结构")
                continue
            
            # 过滤掉不需要测试的字段
            excluded_fields = [
                'project_code',  # 目标查询字段
                'created_at',    # 系统时间字段
                'updated_at',    # 系统时间字段
                'id',           # 主键字段
                'uuid'          # UUID字段
            ]
            columns = [col for col in columns if col.lower() not in [f.lower() for f in excluded_fields]]
            
            with current_field_container:
                st.write(f"**可用字段:** {len(columns)} 个")
            
            # 获取有效字段及其数据
            valid_field_data = self._get_valid_field_data(table_name, columns, current_field_container)
            
            # 根据测试模式生成测试用例
            if self.test_mode == "single_field":
                table_test_cases = self._generate_single_field_cases(table_name, valid_field_data)
            else:
                table_test_cases = self._generate_multi_field_cases(table_name, valid_field_data)
            
            test_cases.extend(table_test_cases)
            
            with current_field_container:
                st.write(f"**{TABLE_NAME_MAP[table_name]} 总结:** 生成了 {len(table_test_cases)} 个测试用例")
            
            progress_bar.progress((i + 1) / total_tables)
        
        # 清空进度显示
        current_table_container.empty()
        current_field_container.empty()
        
        status_text.text(f"✅ 测试用例生成完成，共生成 {len(test_cases)} 个测试用例")
        return test_cases
    
    def _get_valid_field_data(self, table_name: str, columns: List[str], container) -> List[Dict[str, Any]]:
        """获取有效字段及其数据"""
        valid_field_data = []
        
        for j, column in enumerate(columns):
            with container:
                st.write(f"正在检查字段: {column} ({j+1}/{len(columns)})")
            
            # 获取字段注释
            column_comment = self.db_manager.get_column_comment(table_name, column)
            
            if self.db_manager.check_column_has_data(table_name, column):
                value = self.db_manager.get_random_value(table_name, column)
                if value and len(value) <= 100:
                    valid_field_data.append({
                        'column_name': column,
                        'column_comment': column_comment,
                        'value': value,
                        'field_display_name': column_comment if column_comment != column else column
                    })
                    with container:
                        st.write(f"✅ {column}({column_comment}): 已加入有效字段 (值: {value[:30]}{'...' if len(value) > 30 else ''})")
                elif value and len(value) > 100:
                    with container:
                        st.write(f"⏭️ {column}({column_comment}): 值过长跳过 (长度: {len(value)})")
                else:
                    with container:
                        st.write(f"❌ {column}({column_comment}): 获取值失败")
            else:
                with container:
                    st.write(f"❌ {column}({column_comment}): 无数据")
        
        return valid_field_data
    
    def _generate_single_field_cases(self, table_name: str, valid_field_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """生成单字段测试用例"""
        test_cases = []
        for field_data in valid_field_data:
            test_case = self._create_single_field_test_case(table_name, field_data)
            if test_case:
                test_cases.append(test_case)
        return test_cases
    
    def _generate_multi_field_cases(self, table_name: str, valid_field_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """生成多字段测试用例"""
        test_cases = []
        
        if len(valid_field_data) < 2:
            # 如果有效字段不足，降级为单字段测试
            st.info(f"表 {table_name} 有效字段不足2个，降级为单字段测试")
            return self._generate_single_field_cases(table_name, valid_field_data)
        
        # 随机生成多字段组合
        import itertools
        
        # 计算不同字段数量的组合数量
        for current_count in range(2, min(self.field_count + 1, len(valid_field_data) + 1)):
            field_combinations = list(itertools.combinations(valid_field_data, current_count))
            
            if field_combinations:
                # 根据字段数量调整生成的测试用例数量
                if current_count == 2:
                    max_combinations = min(50, len(field_combinations))  # 双字段：最多50个
                elif current_count == 3:
                    max_combinations = min(30, len(field_combinations))  # 三字段：最多30个
                else:
                    max_combinations = min(20, len(field_combinations))  # 更多字段：最多20个
                
                st.info(f"表 {table_name} - {current_count}字段组合：共{len(field_combinations)}种可能，选择{max_combinations}个")
                
                selected_combinations = random.sample(field_combinations, max_combinations)
                
                successful_cases = 0
                failed_cases = 0
                
                for combination in selected_combinations:
                    test_case = self._create_multi_field_test_case(table_name, list(combination))
                    if test_case:
                        test_cases.append(test_case)
                        successful_cases += 1
                    else:
                        failed_cases += 1
                
                st.success(f"表 {table_name} - {current_count}字段：成功生成{successful_cases}个，失败{failed_cases}个")
        
        return test_cases
    
    def _create_single_field_test_case(self, table_name: str, field_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """创建单字段测试用例"""
        try:
            chinese_table_name = TABLE_NAME_MAP.get(table_name, table_name)
            
            column_name = field_data['column_name']
            value = field_data['value']
            field_display_name = field_data['field_display_name']
            
            question = f"请在{chinese_table_name}中帮我找一下{field_display_name}为{value}的项目"
            
            # 使用参数化查询避免SQL注入
            standard_sql = f"SELECT DISTINCT `project_code` FROM `{table_name}` WHERE `{column_name}` = %s"
            
            # 执行标准SQL获取正确答案
            correct_answers = self.db_manager.execute_sql_with_params(standard_sql, (value,))
            
            if not correct_answers:
                return None
            
            # 为显示目的生成可读的SQL
            escaped_value = value.replace("'", "''")
            display_sql = f"SELECT DISTINCT project_code FROM {table_name} WHERE {column_name} = '{escaped_value}'"
            
            return {
                "test_type": "single_field",
                "table_name": table_name,
                "chinese_table_name": chinese_table_name,
                "column_name": column_name,
                "column_comment": field_data['column_comment'],
                "field_display_name": field_display_name,
                "value": value,
                "question": question,
                "standard_sql": display_sql,
                "correct_answers": correct_answers,
                "field_count": 1,
                "fields_info": [field_data]
            }
        except Exception as e:
            st.warning(f"创建单字段测试用例失败 {table_name}.{field_data['column_name']}: {str(e)}")
            return None
    
    def _create_multi_field_test_case(self, table_name: str, fields_data: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """创建多字段测试用例"""
        try:
            chinese_table_name = TABLE_NAME_MAP.get(table_name, table_name)
            
            # 构造复杂问题
            conditions = []
            where_clauses = []
            params = []
            
            for field_data in fields_data:
                field_display_name = field_data['field_display_name']
                value = field_data['value']
                column_name = field_data['column_name']
                
                conditions.append(f"{field_display_name}为{value}")
                where_clauses.append(f"`{column_name}` = %s")
                params.append(value)
            
            # 生成问题
            if len(conditions) == 2:
                question = f"请在{chinese_table_name}中帮我找一下{conditions[0]}且{conditions[1]}的项目"
            elif len(conditions) == 3:
                question = f"请在{chinese_table_name}中帮我找一下{conditions[0]}、{conditions[1]}且{conditions[2]}的项目"
            else:
                question = f"请在{chinese_table_name}中帮我找一下{'、'.join(conditions[:-1])}且{conditions[-1]}的项目"
            
            # 构造SQL
            standard_sql = f"SELECT DISTINCT `project_code` FROM `{table_name}` WHERE {' AND '.join(where_clauses)}"
            
            # 执行标准SQL获取正确答案
            correct_answers = self.db_manager.execute_sql_with_params(standard_sql, tuple(params))
            
            if not correct_answers:
                # 记录无结果的组合
                field_names = [fd['column_name'] for fd in fields_data]
                st.info(f"跳过无结果组合: {table_name}.{', '.join(field_names)}")
                return None
            
            # 为显示目的生成可读的SQL
            display_conditions = []
            for field_data in fields_data:
                column_name = field_data['column_name']
                value = field_data['value']
                escaped_value = value.replace("'", "''")
                display_conditions.append(f"{column_name} = '{escaped_value}'")
            
            display_sql = f"SELECT DISTINCT project_code FROM {table_name} WHERE {' AND '.join(display_conditions)}"
            
            # 生成字段摘要
            field_summary = ', '.join([f"{fd['column_name']}({fd['field_display_name']})" for fd in fields_data])
            
            return {
                "test_type": "multi_field",
                "table_name": table_name,
                "chinese_table_name": chinese_table_name,
                "column_name": field_summary,  # 用于显示
                "column_comment": f"多字段组合 ({len(fields_data)}个字段)",
                "field_display_name": field_summary,
                "value": ' & '.join([fd['value'] for fd in fields_data]),
                "question": question,
                "standard_sql": display_sql,
                "correct_answers": correct_answers,
                "field_count": len(fields_data),
                "fields_info": fields_data
            }
        except Exception as e:
            field_names = [fd['column_name'] for fd in fields_data] if fields_data else []
            st.error(f"创建多字段测试用例异常 {table_name}.{', '.join(field_names)}: {str(e)}")
            return None
    
    def _create_test_case(self, table_name: str, column_name: str, value: str, column_comment: str) -> Optional[Dict[str, Any]]:
        """创建单个测试用例（保持向后兼容）"""
        field_data = {
            'column_name': column_name,
            'column_comment': column_comment,
            'value': value,
            'field_display_name': column_comment if column_comment != column_name else column_name
        }
        return self._create_single_field_test_case(table_name, field_data)


class AgentTester:
    """Agent测试器"""
    
    def __init__(self, config: Dict[str, Any], db_manager: DatabaseManager = None):
        self.config = config
        self.db_manager = db_manager
    
    def call_agent(self, question: str) -> Optional[Dict[str, Any]]:
        """调用Agent接口"""
        try:
            payload = {
                "agentId": self.config["agent_id"],
                "userChatInput": question
            }
            
            response = requests.post(
                self.config["url"],
                headers=self.config["headers"],
                json=payload,
                timeout=360
            )
            
            if response.status_code == 200:
                return response.json()
            else:
                st.warning(f"Agent API调用失败: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            st.warning(f"调用Agent时出错: {str(e)}")
            return None
    
    def extract_project_codes(self, response: Dict[str, Any]) -> List[str]:
        """从Agent响应中提取项目代码"""
        try:
            if "choices" in response and len(response["choices"]) > 0:
                content_str = response["choices"][0].get("content", "")
                # content是JSON字符串，需要解析
                if isinstance(content_str, str):
                    content = json.loads(content_str)
                else:
                    content = content_str
                
                project_list_str = content.get("projectList", "[]")
                # projectList也可能是JSON字符串
                if isinstance(project_list_str, str):
                    # 处理转义的JSON字符串
                    if project_list_str.startswith('[') and project_list_str.endswith(']'):
                        project_list = json.loads(project_list_str)
                    else:
                        # 可能是转义的JSON字符串，先解转义
                        try:
                            project_list = json.loads(project_list_str)
                        except:
                            return []
                else:
                    project_list = project_list_str
                
                return [str(code) for code in project_list] if project_list else []
            return []
        except Exception as e:
            st.warning(f"提取项目代码时出错: {str(e)}")
            return []
    
    def extract_sql(self, response: Dict[str, Any]) -> str:
        """从Agent响应中提取SQL"""
        try:
            if "choices" in response and len(response["choices"]) > 0:
                content_str = response["choices"][0].get("content", "")
                # content是JSON字符串，需要解析
                if isinstance(content_str, str):
                    content = json.loads(content_str)
                else:
                    content = content_str
                
                return content.get("sql", "")
            return ""
        except Exception as e:
            st.warning(f"提取SQL时出错: {str(e)}")
            return ""
    
    def execute_agent_sql(self, sql: str) -> List[str]:
        """执行Agent生成的SQL并只提取project_code字段"""
        if not self.db_manager or not sql:
            return []
        
        try:
            with self.db_manager.connection.cursor() as cursor:
                # 执行Agent的原始SQL
                cursor.execute(sql)
                rows = cursor.fetchall()
                
                # 获取列名
                column_names = [desc[0].lower() for desc in cursor.description]
                project_code_index = None
                
                # 尝试找到project_code列（不区分大小写）
                for i, col_name in enumerate(column_names):
                    if 'project_code' in col_name:
                        project_code_index = i
                        break
                
                if project_code_index is not None:
                    # 提取project_code列的值
                    return [str(row[project_code_index]) for row in rows if row[project_code_index] is not None]
                else:
                    # 如果没找到project_code列，尝试使用第一列
                    if rows and len(rows[0]) > 0:
                        st.warning("未找到project_code列，使用第一列作为项目代码")
                        return [str(row[0]) for row in rows if row[0] is not None]
                    return []
                    
        except Exception as e:
            st.warning(f"执行Agent SQL时出错: {str(e)}")
            return []


class ResultAnalyzer:
    """结果分析器"""
    
    @staticmethod
    def calculate_metrics(correct_answers: List[str], agent_answers: List[str]) -> Dict[str, float]:
        """计算准确率、召回率和F1分数"""
        if not correct_answers and not agent_answers:
            return {"precision": 1.0, "recall": 1.0, "f1": 1.0}
        
        if not agent_answers:
            return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
        
        if not correct_answers:
            return {"precision": 0.0, "recall": 0.0, "f1": 0.0}
        
        correct_set = set(correct_answers)
        agent_set = set(agent_answers)
        
        # 计算交集
        intersection = correct_set.intersection(agent_set)
        
        # 计算精确率 (Precision)
        precision = len(intersection) / len(agent_set) if agent_set else 0.0
        
        # 计算召回率 (Recall)
        recall = len(intersection) / len(correct_set) if correct_set else 0.0
        
        # 计算F1分数
        f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0
        
        return {
            "precision": precision,
            "recall": recall,
            "f1": f1
        }


def main():
    """主函数"""
    st.title("🔍 NL2SQL Agent 测试工具")
    st.markdown("---")
    
    # 侧边栏配置
    with st.sidebar:
        st.header("⚙️ 配置信息")
        st.subheader("数据库配置")
        st.text(f"主机: {DB_CONFIG['host']}")
        st.text(f"端口: {DB_CONFIG['port']}")
        st.text(f"数据库: {DB_CONFIG['database']}")
        
        st.subheader("测试表")
        for table in TABLES_TO_TEST:
            st.text(f"• {TABLE_NAME_MAP[table]}")
    
    # 初始化session state
    if 'test_cases' not in st.session_state:
        st.session_state.test_cases = []
    if 'test_results' not in st.session_state:
        st.session_state.test_results = []
    if 'db_connected' not in st.session_state:
        st.session_state.db_connected = False
    if 'test_paused' not in st.session_state:
        st.session_state.test_paused = False
    if 'test_running' not in st.session_state:
        st.session_state.test_running = False
    if 'current_test_index' not in st.session_state:
        st.session_state.current_test_index = 0
        
    # 数据库连接
    if not st.session_state.db_connected:
        with st.spinner("正在连接数据库..."):
            db_manager = DatabaseManager(DB_CONFIG)
            if db_manager.connect():
                st.session_state.db_manager = db_manager
                st.session_state.db_connected = True
                st.success("✅ 数据库连接成功！")
            else:
                st.error("❌ 数据库连接失败，请检查配置！")
                return
    else:
        db_manager = st.session_state.db_manager
    
    # 主界面
    tab1, tab2, tab3 = st.tabs(["🚀 开始测试", "📊 测试结果", "📋 测试详情"])
    
    with tab1:
        st.header("测试流程")
        
        col1, col2, col3 = st.columns([1, 1, 1])
        
        with col1:
            # 测试模式选择
            selected_mode = st.selectbox(
                "🎯 选择测试模式",
                options=list(TEST_MODES.keys()),
                format_func=lambda x: TEST_MODES[x]['name'],
                help="\n".join([f"**{TEST_MODES[k]['name']}**: {TEST_MODES[k]['description']}" for k in TEST_MODES.keys()])
            )
            
            # 显示模式说明
            st.info(f"📝 **当前模式**: {TEST_MODES[selected_mode]['description']}")
            
            if st.button("🔄 生成测试用例", type="primary", use_container_width=True):
                with st.spinner("正在生成测试用例..."):
                    generator = TestCaseGenerator(db_manager, selected_mode)
                    test_cases = generator.generate_test_cases()
                    st.session_state.test_cases = test_cases
                    st.session_state.test_mode = selected_mode  # 保存测试模式
                    st.success(f"✅ 生成了 {len(test_cases)} 个{TEST_MODES[selected_mode]['name']}用例")
        
        with col2:
            # 测试控制按钮
            if not st.session_state.test_running:
                if st.button("🧪 开始测试", type="primary", use_container_width=True, disabled=len(st.session_state.test_cases) == 0):
                    if st.session_state.test_cases:
                        st.session_state.test_running = True
                        st.session_state.test_paused = False
                        st.session_state.current_test_index = 0
                        st.rerun()
            else:
                col_pause, col_stop = st.columns(2)
                with col_pause:
                    if st.session_state.test_paused:
                        if st.button("▶️ 恢复", type="primary", use_container_width=True):
                            st.session_state.test_paused = False
                            st.rerun()
                    else:
                        if st.button("⏸️ 暂停", type="secondary", use_container_width=True):
                            st.session_state.test_paused = True
                            st.rerun()
                with col_stop:
                    if st.button("⏹️ 停止", use_container_width=True):
                        st.session_state.test_running = False
                        st.session_state.test_paused = False
                        st.rerun()
        
        with col3:
            if st.button("🗑️ 清空结果", use_container_width=True, disabled=st.session_state.test_running):
                st.session_state.test_cases = []
                st.session_state.test_results = []
                st.session_state.test_running = False
                st.session_state.test_paused = False
                st.session_state.current_test_index = 0
                st.success("✅ 已清空所有结果")
        
        # 显示测试用例概览
        if st.session_state.test_cases:
            st.subheader("📝 测试用例概览")
            test_summary = {}
            for case in st.session_state.test_cases:
                table = case['chinese_table_name']
                if table not in test_summary:
                    test_summary[table] = 0
                test_summary[table] += 1
            
            cols = st.columns(len(test_summary))
            for i, (table, count) in enumerate(test_summary.items()):
                with cols[i]:
                    st.metric(table, count)
            
            # 显示详细测试用例预览
            st.subheader("🔍 测试用例详情预览")
            
            # 显示测试模式统计
            test_mode_name = TEST_MODES.get(st.session_state.get('test_mode', 'single_field'), {}).get('name', '单字段测试')
            st.info(f"🎯 **当前模式**: {test_mode_name}")
            
            # 统计不同类型的测试用例
            type_stats = {}
            for case in st.session_state.test_cases:
                test_type = case.get('test_type', 'single_field')
                field_count = case.get('field_count', 1)
                key = f"{field_count}字段"
                if key not in type_stats:
                    type_stats[key] = 0
                type_stats[key] += 1
            
            if type_stats:
                st.write("📈 **测试类型统计:**")
                type_cols = st.columns(len(type_stats))
                for i, (type_name, count) in enumerate(type_stats.items()):
                    with type_cols[i]:
                        st.metric(type_name, count)
            
            # 选择要查看的表
            selected_table_preview = st.selectbox(
                "选择要预览的表",
                ["全部"] + list(test_summary.keys()),
                key="preview_table_select"
            )
            
            # 筛选测试用例
            preview_cases = st.session_state.test_cases
            if selected_table_preview != "全部":
                preview_cases = [case for case in preview_cases if case['chinese_table_name'] == selected_table_preview]
            
            # 限制显示数量
            max_preview = min(10, len(preview_cases))
            st.write(f"显示前 {max_preview} 个测试用例（共 {len(preview_cases)} 个）")
            
            for i, case in enumerate(preview_cases[:max_preview]):
                test_type_icon = "🔢" if case.get('field_count', 1) == 1 else "🔣"
                field_display = case.get('field_display_name', case['column_name'])
                with st.expander(f"{test_type_icon} 测试用例 {i+1}: {case['chinese_table_name']} - {field_display} ({case.get('field_count', 1)}字段)"):
                    col1, col2 = st.columns([1, 1])
                    with col1:
                        st.write("**测试问题:**")
                        st.write(case['question'])
                        st.write("**测试信息:**")
                        st.write(f"表: {case['table_name']}")
                        if case.get('field_count', 1) == 1:
                            st.write(f"字段: {case['column_name']}")
                            if case.get('column_comment') and case['column_comment'] != case['column_name']:
                                st.write(f"字段注释: {case['column_comment']}")
                            st.write(f"测试值: {case['value']}")
                        else:
                            st.write(f"字段数量: {case.get('field_count', 1)}")
                            st.write(f"字段组合: {case['column_name']}")
                            if 'fields_info' in case:
                                for field_info in case['fields_info']:
                                    st.write(f"  - {field_info['column_name']}: {field_info['value']}")
                    with col2:
                        st.write("**标准SQL:**")
                        st.code(case['standard_sql'], language='sql')
                        st.write("**预期结果数量:**")
                        st.write(f"{len(case['correct_answers'])} 个项目")
                        if len(case['correct_answers']) <= 5:
                            st.write("**预期项目代码:**")
                            st.write(", ".join(case['correct_answers']))
    
    # 自动执行测试
    if st.session_state.test_running and not st.session_state.test_paused:
        execute_tests()
    
    # 显示实时测试进度和已完成的测试结果
    if st.session_state.test_results or st.session_state.test_running:
        display_real_time_results()
    
    # 显示已完成的测试结果（支持重新测试）
    if st.session_state.test_results:
        display_completed_tests()
    
    with tab2:
        if st.session_state.test_results:
            display_test_results()
        else:
            st.info("暂无测试结果，请先执行测试。")
    
    with tab3:
        if st.session_state.test_results:
            display_test_details()
        else:
            st.info("暂无测试详情，请先执行测试。")


def execute_tests():
    """执行测试（支持暂停恢复）"""
    # 检查是否有测试用例
    if not st.session_state.test_cases:
        st.session_state.test_running = False
        return
    
    # 如果测试被暂停，显示暂停状态
    if st.session_state.test_paused:
        st.warning("⏸️ 测试已暂停，点击'恢复'按钮继续测试")
        return
    
    # 确保test_results初始化
    if not hasattr(st.session_state, 'test_results'):
        st.session_state.test_results = []
    
    agent_tester = AgentTester(AGENT_CONFIG, st.session_state.db_manager)
    analyzer = ResultAnalyzer()
    
    total_tests = len(st.session_state.test_cases)
    current_index = st.session_state.current_test_index
    
    # 如果所有测试都完成了
    if current_index >= total_tests:
        st.session_state.test_running = False
        st.success("🎉 所有测试已完成！")
        return
    
    # 只执行当前测试
    test_case = st.session_state.test_cases[current_index]
    
    # 显示当前测试状态
    with st.container():
        st.markdown("## 🧪 正在执行测试")
        
        # 显示测试进度
        progress = (current_index + 1) / total_tests
        st.progress(progress)
        st.text(f"进度: {current_index + 1}/{total_tests} - {test_case['question'][:50]}...")
        
        # 当前测试信息
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("当前表", test_case['chinese_table_name'])
        with col2:
            field_display = test_case.get('field_display_name', test_case['column_name'])
            st.metric("测试字段", field_display)
        with col3:
            st.metric("测试值", test_case['value'])
        
        # 执行当前测试
        with st.spinner(f"正在调用Agent API... (第 {current_index + 1} 个测试)"):
            response = agent_tester.call_agent(test_case['question'])
        
        # 处理结果
        if response:
            agent_project_codes = agent_tester.extract_project_codes(response)
            agent_sql = agent_tester.extract_sql(response)
            
            # 如果Agent返回了SQL，执行它来获取实际的project_code结果
            if agent_sql:
                try:
                    agent_sql_results = agent_tester.execute_agent_sql(agent_sql)
                    # 使用SQL执行结果，如果有的话
                    if agent_sql_results:
                        agent_project_codes = agent_sql_results
                except Exception as e:
                    st.warning(f"执行Agent SQL失败: {str(e)}")
            
            metrics = analyzer.calculate_metrics(test_case['correct_answers'], agent_project_codes)
            
            result = {
                **test_case,
                'test_index': current_index,
                'agent_response': response,
                'agent_project_codes': agent_project_codes,
                'agent_sql': agent_sql,
                'metrics': metrics,
                'test_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        else:
            result = {
                **test_case,
                'test_index': current_index,
                'agent_response': None,
                'agent_project_codes': [],
                'agent_sql': '',
                'metrics': {"precision": 0.0, "recall": 0.0, "f1": 0.0},
                'test_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        
        # 更新或添加结果
        if current_index < len(st.session_state.test_results):
            st.session_state.test_results[current_index] = result
        else:
            st.session_state.test_results.append(result)
        
        # 显示当前测试结果
        display_single_test_result(result)
        
        # 更新测试索引
        st.session_state.current_test_index += 1
        
        # 短暂延迟后继续下一个测试
        time.sleep(0.5)
        st.rerun()


def execute_single_test(test_index: int):
    """执行单个测试"""
    if test_index >= len(st.session_state.test_cases):
        st.error("测试索引超出范围")
        return
    
    agent_tester = AgentTester(AGENT_CONFIG, st.session_state.db_manager)
    analyzer = ResultAnalyzer()
    
    test_case = st.session_state.test_cases[test_index]
    
    with st.spinner(f"正在重新测试: {test_case['question'][:50]}..."):
        response = agent_tester.call_agent(test_case['question'])
    
    # 处理结果
    if response:
        agent_project_codes = agent_tester.extract_project_codes(response)
        agent_sql = agent_tester.extract_sql(response)
        
        # 如果Agent返回了SQL，执行它来获取实际的project_code结果
        if agent_sql:
            try:
                agent_sql_results = agent_tester.execute_agent_sql(agent_sql)
                # 使用SQL执行结果，如果有的话
                if agent_sql_results:
                    agent_project_codes = agent_sql_results
            except Exception as e:
                st.warning(f"执行Agent SQL失败: {str(e)}")
        
        metrics = analyzer.calculate_metrics(test_case['correct_answers'], agent_project_codes)
        
        result = {
            **test_case,
            'test_index': test_index,
            'agent_response': response,
            'agent_project_codes': agent_project_codes,
            'agent_sql': agent_sql,
            'metrics': metrics,
            'test_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    else:
        result = {
            **test_case,
            'test_index': test_index,
            'agent_response': None,
            'agent_project_codes': [],
            'agent_sql': '',
            'metrics': {"precision": 0.0, "recall": 0.0, "f1": 0.0},
            'test_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    
    # 更新结果
    st.session_state.test_results[test_index] = result
    
    # 强制刷新相关的缓存状态
    if hasattr(st.session_state, '_test_results_updated'):
        st.session_state._test_results_updated = datetime.now().isoformat()
    else:
        st.session_state._test_results_updated = datetime.now().isoformat()
    
    st.success(f"✅ 测试完成！F1分数: {result['metrics']['f1']:.1%}")
    st.balloons()  # 添加视觉反馈
    
    # 延迟一下再刷新，确保状态更新完成
    time.sleep(0.2)
    st.rerun()


def display_single_test_result(result):
    """显示单个测试结果"""
    f1_score = result['metrics']['f1']
    
    # 结果状态
    if f1_score > 0.8:
        st.success("### ✅ 测试成功")
    elif f1_score > 0.3:
        st.warning("### ⚠️ 测试部分成功")
    else:
        st.error("### ❌ 测试失败")
    
    # 结果对比
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### 🎯 预期结果")
        st.metric("项目数量", len(result['correct_answers']))
        st.code(result['standard_sql'], language='sql')
        if len(result['correct_answers']) <= 3:
            for code in result['correct_answers']:
                st.write(f"• {code}")
        else:
            st.write(f"前3个: {', '.join(result['correct_answers'][:3])}...")
    
    with col2:
        st.markdown("#### 🤖 Agent结果")
        agent_count = len(result['agent_project_codes'])
        expected_count = len(result['correct_answers'])
        
        if agent_count == expected_count:
            st.metric("项目数量", agent_count, delta="✅ 数量正确")
        else:
            delta_val = agent_count - expected_count
            st.metric("项目数量", agent_count, delta=f"{delta_val:+d}")
        
        if result['agent_sql']:
            st.code(result['agent_sql'], language='sql')
        else:
            st.warning("未返回SQL")
        
        if len(result['agent_project_codes']) <= 3:
            for code in result['agent_project_codes']:
                st.write(f"• {code}")
        elif len(result['agent_project_codes']) > 0:
            st.write(f"前3个: {', '.join(result['agent_project_codes'][:3])}...")
        else:
            st.warning("无返回结果")
    
    # 性能指标
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("精确率", f"{result['metrics']['precision']:.1%}")
    with col2:
        st.metric("召回率", f"{result['metrics']['recall']:.1%}")
    with col3:
        st.metric("F1分数", f"{f1_score:.1%}")


def display_real_time_results():
    """显示实时测试进度和结果"""
    if not st.session_state.test_results and not st.session_state.test_running:
        return
    
    st.markdown("## 📊 实时测试进度")
    
    # 计算进度统计
    total_tests = len(st.session_state.test_cases) if st.session_state.test_cases else 0
    completed_tests = len(st.session_state.test_results) if st.session_state.test_results else 0
    current_index = st.session_state.get('current_test_index', 0)
    
    # 显示总体进度
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("总测试数", total_tests)
    
    with col2:
        st.metric("已完成", completed_tests)
    
    with col3:
        if st.session_state.test_running:
            st.metric("当前进度", f"{current_index + 1}/{total_tests}")
        else:
            st.metric("测试状态", "已完成" if completed_tests == total_tests else "已停止")
    
    with col4:
        if completed_tests > 0:
            success_count = sum(1 for r in st.session_state.test_results if r['metrics']['f1'] > 0.8)
            success_rate = success_count / completed_tests * 100
            st.metric("成功率", f"{success_rate:.1f}%")
        else:
            st.metric("成功率", "0%")
    
    # 显示进度条
    if total_tests > 0:
        progress = completed_tests / total_tests
        st.progress(progress)
        st.text(f"测试进度: {completed_tests}/{total_tests} ({progress:.1%})")
    
    # 显示最近完成的测试结果
    if st.session_state.test_results:
        st.subheader("📋 最近测试结果")
        
        # 显示最近5个测试结果的简要信息
        recent_results = st.session_state.test_results[-5:]  # 最近5个
        
        for i, result in enumerate(reversed(recent_results)):
            f1_score = result['metrics']['f1']
            status_icon = "✅" if f1_score > 0.8 else "⚠️" if f1_score > 0.3 else "❌"
            
            # 显示测试类型图标
            type_icon = "🔢" if result.get('field_count', 1) == 1 else "🔣"
            
            with st.expander(f"{status_icon} {type_icon} 最近测试 {i+1}: {result['question'][:50]}... (F1: {f1_score:.1%})", expanded=i==0):
                col1, col2 = st.columns([2, 1])
                
                with col1:
                    st.write(f"**问题**: {result['question']}")
                    st.write(f"**表**: {result['chinese_table_name']}")
                    if result.get('field_count', 1) == 1:
                        st.write(f"**字段**: {result['field_display_name']}")
                        st.write(f"**测试值**: {result['value']}")
                    else:
                        st.write(f"**字段数量**: {result.get('field_count', 1)}")
                        st.write(f"**字段组合**: {result['column_name']}")
                
                with col2:
                    st.metric("精确率", f"{result['metrics']['precision']:.1%}")
                    st.metric("召回率", f"{result['metrics']['recall']:.1%}")
                    st.metric("F1分数", f"{f1_score:.1%}")
                
                # 显示结果对比
                col_expected, col_actual = st.columns(2)
                with col_expected:
                    st.write("**预期结果**:")
                    expected_count = len(result['correct_answers'])
                    st.write(f"数量: {expected_count}")
                    if expected_count <= 3:
                        for code in result['correct_answers']:
                            st.write(f"• {code}")
                    else:
                        st.write(f"前3个: {', '.join(result['correct_answers'][:3])}...")
                
                with col_actual:
                    st.write("**Agent结果**:")
                    actual_count = len(result['agent_project_codes'])
                    st.write(f"数量: {actual_count}")
                    if actual_count <= 3:
                        for code in result['agent_project_codes']:
                            st.write(f"• {code}")
                    elif actual_count > 0:
                        st.write(f"前3个: {', '.join(result['agent_project_codes'][:3])}...")
                    else:
                        st.write("无结果")


def display_completed_tests():
    """显示已完成的测试（支持重新测试）"""
    if not st.session_state.test_results:
        return
    
    # 添加缓存键，确保重新测试后能刷新
    cache_key = getattr(st.session_state, '_test_results_updated', 'default')
    
    st.markdown("## 📋 已完成的测试")
    
    # 过滤掉None值（如果有的话）
    valid_results = [r for r in st.session_state.test_results if r is not None]
    
    if not valid_results:
        st.info("暂无已完成的测试结果")
        return
    
    # 测试结果统计
    total_completed = len(valid_results)
    successful_tests = sum(1 for r in valid_results if r['metrics']['f1'] > 0.8)
    avg_f1 = sum(r['metrics']['f1'] for r in valid_results) / total_completed
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("已完成", total_completed)
    with col2:
        st.metric("成功率", f"{successful_tests/total_completed*100:.1f}%")
    with col3:
        st.metric("平均F1", f"{avg_f1:.1%}")
    
    # 显示测试列表
    for i, result in enumerate(st.session_state.test_results):
        if result is None:
            continue
            
        f1_score = result['metrics']['f1']
        status_icon = "✅" if f1_score > 0.8 else "⚠️" if f1_score > 0.3 else "❌"
        
        # 使用缓存键确保能检测到变化
        expander_key = f"test_result_{i}_{cache_key}"
        
        with st.expander(f"{status_icon} 测试 {i+1}: {result['question'][:60]}... (F1: {f1_score:.1%})", expanded=False):
            col1, col2 = st.columns([3, 1])
            
            with col1:
                st.write(f"**表**: {result['chinese_table_name']}")
                st.write(f"**字段**: {result.get('field_display_name', result['column_name'])}")
                st.write(f"**测试值**: {result['value']}")
                st.write(f"**测试时间**: {result['test_time']}")
                
                # 显示详细结果对比
                col_detail1, col_detail2 = st.columns(2)
                with col_detail1:
                    st.write("**预期结果:**")
                    expected_count = len(result['correct_answers'])
                    st.write(f"数量: {expected_count}")
                    if expected_count <= 3:
                        for code in result['correct_answers']:
                            st.write(f"• {code}")
                    else:
                        st.write(f"前3个: {', '.join(result['correct_answers'][:3])}...")
                
                with col_detail2:
                    st.write("**Agent结果:**")
                    agent_count = len(result['agent_project_codes'])
                    st.write(f"数量: {agent_count}")
                    if agent_count <= 3:
                        for code in result['agent_project_codes']:
                            st.write(f"• {code}")
                    elif agent_count > 0:
                        st.write(f"前3个: {', '.join(result['agent_project_codes'][:3])}...")
                    else:
                        st.write("无结果")
                
                col_metric1, col_metric2, col_metric3 = st.columns(3)
                with col_metric1:
                    st.metric("精确率", f"{result['metrics']['precision']:.1%}")
                with col_metric2:
                    st.metric("召回率", f"{result['metrics']['recall']:.1%}")
                with col_metric3:
                    st.metric("F1分数", f"{f1_score:.1%}")
            
            with col2:
                if st.button(f"🔄 重新测试", key=f"retest_{i}_{cache_key}", use_container_width=True):
                    # 确保有足够的测试结果空间
                    while len(st.session_state.test_results) <= i:
                        st.session_state.test_results.append(None)
                    execute_single_test(i)


def display_test_results():
    """显示测试结果"""
    st.header("📊 测试结果总览")
    
    if not st.session_state.test_results:
        return
    
    # 计算总体指标
    all_precision = [r['metrics']['precision'] for r in st.session_state.test_results]
    all_recall = [r['metrics']['recall'] for r in st.session_state.test_results]
    all_f1 = [r['metrics']['f1'] for r in st.session_state.test_results]
    
    avg_precision = sum(all_precision) / len(all_precision)
    avg_recall = sum(all_recall) / len(all_recall)
    avg_f1 = sum(all_f1) / len(all_f1)
    
    # 显示总体指标
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("总测试数", len(st.session_state.test_results))
    with col2:
        st.metric("平均精确率", f"{avg_precision:.2%}")
    with col3:
        st.metric("平均召回率", f"{avg_recall:.2%}")
    with col4:
        st.metric("平均F1分数", f"{avg_f1:.2%}")
    
    # 按表分组的结果
    st.subheader("📋 分表统计")
    table_stats = {}
    for result in st.session_state.test_results:
        table = result['chinese_table_name']
        if table not in table_stats:
            table_stats[table] = {
                'count': 0,
                'precision': [],
                'recall': [],
                'f1': []
            }
        table_stats[table]['count'] += 1
        table_stats[table]['precision'].append(result['metrics']['precision'])
        table_stats[table]['recall'].append(result['metrics']['recall'])
        table_stats[table]['f1'].append(result['metrics']['f1'])
    
    # 创建表格数据
    table_data = []
    for table, stats in table_stats.items():
        avg_p = sum(stats['precision']) / len(stats['precision'])
        avg_r = sum(stats['recall']) / len(stats['recall'])
        avg_f = sum(stats['f1']) / len(stats['f1'])
        
        table_data.append({
            '表名': table,
            '测试数': stats['count'],
            '平均精确率': f"{avg_p:.2%}",
            '平均召回率': f"{avg_r:.2%}",
            '平均F1分数': f"{avg_f:.2%}"
        })
    
    df = pd.DataFrame(table_data)
    st.dataframe(df, use_container_width=True)
    
    # 导出结果
    if st.button("📥 导出测试结果"):
        export_results()


def display_test_details():
    """显示测试详情"""
    st.header("📋 测试详情")
    
    if not st.session_state.test_results:
        return
    
    # 筛选选项
    col1, col2 = st.columns([1, 1])
    with col1:
        selected_table = st.selectbox(
            "选择表",
            ["全部"] + list(set([r['chinese_table_name'] for r in st.session_state.test_results]))
        )
    
    with col2:
        filter_option = st.selectbox(
            "筛选条件",
            ["全部", "成功 (F1 > 0.8)", "部分成功 (0.3 < F1 ≤ 0.8)", "失败 (F1 ≤ 0.3)"]
        )
    
    # 应用筛选
    filtered_results = st.session_state.test_results
    
    if selected_table != "全部":
        filtered_results = [r for r in filtered_results if r['chinese_table_name'] == selected_table]
    
    if filter_option == "成功 (F1 > 0.8)":
        filtered_results = [r for r in filtered_results if r['metrics']['f1'] > 0.8]
    elif filter_option == "部分成功 (0.3 < F1 ≤ 0.8)":
        filtered_results = [r for r in filtered_results if 0.3 < r['metrics']['f1'] <= 0.8]
    elif filter_option == "失败 (F1 ≤ 0.3)":
        filtered_results = [r for r in filtered_results if r['metrics']['f1'] <= 0.3]
    
    st.write(f"显示 {len(filtered_results)} 个测试结果")
    
    # 显示详细结果
    for i, result in enumerate(filtered_results):
        with st.expander(
            f"{i+1}. {result['chinese_table_name']} - {result['column_name']} "
            f"(F1: {result['metrics']['f1']:.2%})"
        ):
            col1, col2 = st.columns([1, 1])
            
            with col1:
                st.write("**测试问题:**")
                st.write(result['question'])
                
                st.write("**标准SQL:**")
                st.code(result['standard_sql'], language='sql')
                
                st.write("**正确答案:**")
                st.write(f"项目数量: {len(result['correct_answers'])}")
                if len(result['correct_answers']) <= 10:
                    st.write(", ".join(result['correct_answers']))
                else:
                    st.write(", ".join(result['correct_answers'][:10]) + "...")
            
            with col2:
                st.write("**Agent SQL:**")
                if result['agent_sql']:
                    st.code(result['agent_sql'], language='sql')
                else:
                    st.write("未返回SQL")
                
                st.write("**Agent答案:**")
                st.write(f"项目数量: {len(result['agent_project_codes'])}")
                if len(result['agent_project_codes']) <= 10:
                    st.write(", ".join(result['agent_project_codes']))
                else:
                    st.write(", ".join(result['agent_project_codes'][:10]) + "...")
                
                st.write("**指标:**")
                st.write(f"精确率: {result['metrics']['precision']:.2%}")
                st.write(f"召回率: {result['metrics']['recall']:.2%}")
                st.write(f"F1分数: {result['metrics']['f1']:.2%}")
            
            # 添加原始响应查看功能
            if st.button(f"🔍 查看原始响应 {i+1}", key=f"debug_{i}"):
                st.subheader("原始Agent响应")
                if result['agent_response']:
                    st.json(result['agent_response'])
                else:
                    st.write("无响应数据")


def export_results():
    """导出测试结果"""
    if not st.session_state.test_results:
        return
    
    # 准备导出数据
    export_data = []
    for result in st.session_state.test_results:
        export_data.append({
            '表名': result['chinese_table_name'],
            '测试类型': result.get('test_type', 'single_field'),
            '字段数量': result.get('field_count', 1),
            '字段名': result['column_name'],
            '字段注释': result.get('column_comment', ''),
            '字段显示名': result.get('field_display_name', result['column_name']),
            '测试值': result['value'],
            '测试问题': result['question'],
            '标准SQL': result['standard_sql'],
            '正确答案数量': len(result['correct_answers']),
            '正确答案': ','.join(result['correct_answers']),
            'Agent SQL': result['agent_sql'],
            'Agent答案数量': len(result['agent_project_codes']),
            'Agent答案': ','.join(result['agent_project_codes']),
            '精确率': result['metrics']['precision'],
            '召回率': result['metrics']['recall'],
            'F1分数': result['metrics']['f1'],
            '测试时间': result['test_time']
        })
    
    df = pd.DataFrame(export_data)
    # 使用utf-8-sig编码解决Windows中文乱码问题
    csv = df.to_csv(index=False, encoding='utf-8-sig')
    
    st.download_button(
        label="📥 下载CSV文件",
        data=csv,
        file_name=f"nl2sql_test_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv"
    )


if __name__ == "__main__":
    main()
