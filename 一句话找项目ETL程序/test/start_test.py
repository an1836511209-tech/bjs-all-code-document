#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
NL2SQL测试工具启动脚本
快速启动Streamlit测试应用

使用方法:
python start_test.py
"""

import subprocess
import sys
import os

def check_dependencies():
    """检查依赖是否已安装"""
    required_packages = ['streamlit', 'pymysql', 'requests', 'pandas', 'numpy']
    missing_packages = []
    
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)
    
    if missing_packages:
        print("❌ 缺少以下依赖包:")
        for package in missing_packages:
            print(f"  - {package}")
        print("\n请运行以下命令安装依赖:")
        print("pip install -r requirements_test.txt")
        return False
    
    print("✅ 所有依赖已安装")
    return True

def start_streamlit():
    """启动Streamlit应用"""
    try:
        print("🚀 正在启动NL2SQL测试工具...")
        print("📂 测试工具将在浏览器中打开")
        print("🛑 按 Ctrl+C 停止应用")
        print("-" * 50)
        
        # 启动streamlit应用
        subprocess.run([
            sys.executable, "-m", "streamlit", "run", 
            "nl2sql_test_app.py", 
            "--server.port", "8501",
            "--server.address", "localhost"
        ])
    except KeyboardInterrupt:
        print("\n\n👋 应用已停止")
    except Exception as e:
        print(f"\n❌ 启动失败: {str(e)}")

if __name__ == "__main__":
    print("🔍 NL2SQL Agent 测试工具")
    print("=" * 50)
    
    # 检查当前目录
    if not os.path.exists("nl2sql_test_app.py"):
        print("❌ 找不到 nl2sql_test_app.py 文件")
        print("请确保在 test 目录下运行此脚本")
        sys.exit(1)
    
    # 检查依赖
    if not check_dependencies():
        sys.exit(1)
    
    # 启动应用
    start_streamlit()
