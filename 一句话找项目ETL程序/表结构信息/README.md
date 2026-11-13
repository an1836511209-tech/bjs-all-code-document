# MySQL DDL生成器

这个脚本可以根据JSON表结构信息自动生成MySQL建表语句（DDL）。

## 功能特性

- 支持从JSON文件生成MySQL DDL语句
- 自动添加主键ID字段和时间戳字段
- 支持单个文件和批量目录处理
- 自动清理表名，确保符合MySQL命名规范
- 支持多种MySQL数据类型映射
- 生成的SQL文件包含完整的注释信息

## 使用方法

### 1. 演示模式（默认）
```bash
python generate_mysql_ddl.py
# 或者
python generate_mysql_ddl.py --demo
```

### 2. 处理单个JSON文件
```bash
python generate_mysql_ddl.py -f "文件路径.json" -o "输出文件.sql"
```

指定表名：
```bash
python generate_mysql_ddl.py -f "文件路径.json" -t "自定义表名" -o "输出文件.sql"
```

### 3. 批量处理目录
```bash
python generate_mysql_ddl.py -d "目录路径" -o "输出文件.sql"
```

### 4. 查看帮助信息
```bash
python generate_mysql_ddl.py --help
```

## 命令行参数

- `-f, --file`: 指定单个JSON文件路径
- `-d, --directory`: 指定包含JSON文件的目录路径
- `-o, --output`: 指定输出SQL文件路径
- `-t, --table`: 指定表名（仅在处理单个文件时有效）
- `--demo`: 运行演示模式（使用默认的股权转让表）

## JSON文件格式要求

JSON文件应包含字段定义的数组，每个字段对象应包含：

```json
[
  {
    "字段名": "field_name",
    "字段类型": "varchar(255)",
    "字段中文名称": "字段描述"
  }
]
```

## 支持的数据类型

- 字符串类型：varchar, text, longtext, mediumtext, char
- 数值类型：int, bigint, tinyint, smallint, mediumint, decimal, float, double
- 日期时间类型：datetime, date, time, timestamp, year
- 其他类型：json, blob, longblob, mediumblob, tinyblob

## 生成的DDL特性

- 自动添加主键ID字段（BIGINT AUTO_INCREMENT）
- 自动添加created_at和updated_at时间戳字段
- 使用utf8mb4字符集和unicode排序规则
- 使用InnoDB存储引擎
- 包含完整的字段注释

## 示例

### 输入JSON文件
```json
[
  {
    "字段名": "project_name",
    "字段类型": "varchar(500)",
    "字段中文名称": "项目名称"
  },
  {
    "字段名": "project_status",
    "字段类型": "tinyint(1)",
    "字段中文名称": "项目状态"
  }
]
```

### 生成的DDL
```sql
CREATE TABLE `project_table` (
  `id` BIGINT AUTO_INCREMENT PRIMARY KEY COMMENT '主键ID',
  `project_name` VARCHAR(500) COMMENT '项目名称',
  `project_status` TINYINT(1) COMMENT '项目状态',
  `created_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `updated_at` TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间'
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='project_table表';
```

## 注意事项

1. 确保JSON文件格式正确
2. 表名会自动清理，移除特殊字符并转换为小写
3. 如果表名以数字开头，会自动添加"table_"前缀
4. 生成的SQL文件使用UTF-8编码保存