#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
北交所数据ETL系统安装配置
"""

from setuptools import setup, find_packages
import os

# 读取README文件
def read_readme():
    with open('README.md', 'r', encoding='utf-8') as f:
        return f.read()

# 读取requirements文件
def read_requirements():
    with open('requirements.txt', 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip() and not line.startswith('#')]

# 获取版本号
def get_version():
    version_file = os.path.join('src', '__init__.py')
    with open(version_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.startswith('__version__'):
                return line.split('=')[1].strip().strip('"').strip("'")
    return '1.0.0'

setup(
    name='bjs-data-etl',
    version=get_version(),
    author='北交所数据团队',
    author_email='data-team@bjs.com',
    description='北交所数据同步ETL系统',
    long_description=read_readme(),
    long_description_content_type='text/markdown',
    url='https://gitee.com/momomomom/bjs_data_etl',
    packages=find_packages(),
    classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Topic :: Database',
        'Topic :: Internet :: WWW/HTTP',
    ],
    python_requires='>=3.8',
    install_requires=read_requirements(),
    extras_require={
        'dev': [
            'pytest>=6.2.4',
            'pytest-cov>=2.12.1',
            'flake8>=3.9.2',
            'black>=21.6b0',
            'isort>=5.9.3',
        ],
        'monitoring': [
            'psutil>=5.8.0',
            'prometheus-client>=0.11.0',
        ]
    },
    entry_points={
        'console_scripts': [
            'bjs-etl-sync=scripts.run_sync:main',
            'bjs-etl-kafka=scripts.run_kafka:main',
        ],
    },
    include_package_data=True,
    package_data={
        'bjs_data_etl': [
            'config/*.yaml',
            'docs/*.md',
        ],
    },
    project_urls={
        'Bug Reports': 'https://gitee.com/momomomom/bjs_data_etl/issues',
        'Source': 'https://gitee.com/momomomom/bjs_data_etl',
        'Documentation': 'https://gitee.com/momomomom/bjs_data_etl/blob/main/README.md',
    },
    keywords='etl data-sync kafka mysql api north-exchange',
    zip_safe=False,
)
