# 北交所数据同步程序

[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://python.org)
[![Docker](https://img.shields.io/badge/Docker-Supported-blue.svg)](https://docker.com)
[![License](https://img.shields.io/badge/License-Proprietary-red.svg)]()

> 企业级的北交所数据ETL系统，支持实时监听和T+1全量数据同步。

## 🎯 项目简介

北交所数据同步程序是一个专为北京证券交易所数据处理设计的ETL系统，采用Python开发，支持：

- **T+1全量同步**：启动时立即同步一次，然后每天凌晨2点自动执行全量数据同步（重新刷盘）
- **多数据源集成**：支持项目数据API和房源运营API
- **智能调度管理**：内置Python定时任务调度器，无需依赖外部cron
- **容器化部署**：支持Docker一键部署和本地直接运行
- **~~实时数据监听~~**：Kafka实时监听功能已禁用，专注T+1全量同步

## 📋 目录

- [快速开始](#-快速开始)
- [系统架构](#-系统架构)
- [部署方式](#-部署方式)
- [使用说明](#-使用说明)
- [配置文档](#-配置文档)
- [监控运维](#-监控运维)
- [故障排除](#-故障排除)

## 🚀 快速开始

### 环境要求

- Python 3.10+
- MySQL 8.0+
- Docker 20.0+ (可选)

### 一键部署

#### Docker方式（推荐）

```bash
# 1. 配置文件
cp config/config.template.yaml config/config.yaml
vim config/config.yaml  # 填入正确的数据库和API配置

# 2. 一键启动
./scripts/manage.sh docker start

# 3. 查看状态
./scripts/manage.sh docker status
```

#### 本地方式

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置文件
cp config/config.template.yaml config/config.yaml
vim config/config.yaml

# 3. 启动服务
./scripts/manage.sh local start
```

### 验证部署

```bash
# Docker环境
./scripts/manage.sh docker test

# 本地环境
./scripts/manage.sh local test
```

## 🏗️ 系统架构

### 整体架构

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   项目数据API    │    │   房源运营API    │    │ ~~Kafka消息队列~~ │
│ 10.254.95.156   │    │10.254.95.167:8088│    │ (已禁用)         │
└─────────┬───────┘    └─────────┬───────┘    └─────────────────┘
          │                      │                     
          └──────────────────────┘                      
                                 │
          ┌─────────────────────────────────────────────────┐
          │             ETL调度器系统                        │
          │  ┌─────────────────┐  ┌─────────────────────┐   │
          │  │  T+1全量同步     │  │ ~~实时Kafka监听~~    │   │
          │  │ (每天凌晨2点)    │  │   (已禁用)          │   │
          │  │ 清空旧数据+重建   │  │                     │   │
          │  └─────────────────┘  └─────────────────────┘   │
          └─────────────────┬───────────────────────────────┘
                           │
          ┌─────────────────▼───────────────────────────────┐
          │                MySQL数据库                      │
          │  ┌─────────────┐  ┌─────────────┐  ┌──────────┐ │
          │  │   子表数据   │  │   运营数据   │  │  主表数据 │ │
          │  │(10+业务表)  │  │ (房源信息)   │  │ (汇总表) │ │
          │  └─────────────┘  └─────────────┘  └──────────┘ │
          └─────────────────────────────────────────────────┘
```

### 核心特性

#### ✨ T+1全量同步模式
- **清空重建**：每次同步前清空旧数据，确保数据一致性
- **全量获取**：API调用`is_full=1`参数获取全量数据
- **定时执行**：内置Python调度器，每天凌晨2点自动执行
- **事务保证**：完整的事务管理和错误回滚机制

#### 🎯 智能调度系统
```python
# 新的调度器架构 - scripts/scheduler.py
class SyncScheduler:
    def run(self):
        # 启动Kafka监听器 (实时)
        self.start_kafka_listener()
        
        # 配置定时任务 (T+1全量同步)
        schedule.every().day.at("02:00").do(self.sync_all_data_full)
        
        # 主循环
        while self.running:
            schedule.run_pending()
            time.sleep(60)
```

#### ~~📡 实时数据监听（已禁用）~~
- **~~Kafka集成~~**：实时监听功能已禁用，专注T+1全量同步
- **~~断线重连~~**：相关功能已注释，可重新启用
- **~~消息处理~~**：实时处理功能暂停使用

## 🛠️ 部署方式

### Docker容器化部署

#### 特点
- ✅ 环境隔离，部署简单
- ✅ 自动健康检查
- ✅ 统一管理脚本
- ✅ 资源限制和监控

#### 部署命令
```bash
# 启动服务
./scripts/manage.sh docker start

# 查看状态
./scripts/manage.sh docker status

# 查看日志
./scripts/manage.sh docker logs -f

# 手动同步
./scripts/manage.sh docker sync

# 重启服务
./scripts/manage.sh docker restart

# 停止服务
./scripts/manage.sh docker stop
```

### 本地直接部署

#### 特点
- ✅ 性能最优，资源消耗小
- ✅ 调试方便
- ✅ 灵活配置

#### 部署命令
```bash
# 启动服务
./scripts/manage.sh local start

# 仅启动Kafka监听
./scripts/manage.sh local start --kafka-only

# 查看状态
./scripts/manage.sh local status

# 立即同步
./scripts/manage.sh local sync

# 停止服务
./scripts/manage.sh local stop
```

## 📖 使用说明

### 核心脚本

#### 1. 统一管理脚本 - `scripts/manage.sh`

这是系统的总入口，支持Docker和本地两种运行模式：

```bash
# 格式：./scripts/manage.sh [模式] [命令] [选项]

# Docker模式
./scripts/manage.sh docker start    # 启动Docker服务
./scripts/manage.sh docker status   # 查看Docker状态
./scripts/manage.sh docker logs -f  # 实时查看日志

# 本地模式
./scripts/manage.sh local start     # 启动本地服务
./scripts/manage.sh local status    # 查看本地状态
./scripts/manage.sh local sync      # 立即执行同步
```

#### 2. 智能调度器 - `scripts/scheduler.py`

新一代调度器，集成定时任务和启动时同步：

```bash
# 完整启动（推荐）- 启动时立即同步一次，然后进入定时任务模式
python scripts/scheduler.py

# 跳过启动同步，直接进入定时任务模式
python scripts/scheduler.py --no-startup-sync

# 立即执行同步（一次性）
python scripts/scheduler.py --sync-now

# 测试连接
python scripts/scheduler.py --test
```

**启动时同步策略**：
- 🎯 **默认行为**：启动时立即执行一次T+1全量同步，确保数据最新
- ⏰ **定时任务**：然后进入定时任务模式（每天凌晨2点自动同步）
- 🚀 **优势**：无需等到定时任务，服务启动后立即有最新数据

#### 3. 传统同步脚本 - `scripts/run_sync.py`

保留的传统接口，支持灵活的同步控制：

```bash
# 全部同步
python scripts/run_sync.py --mode all

# 子表同步
python scripts/run_sync.py --mode subtables

# 指定表同步
python scripts/run_sync.py --mode subtables --table bjhl_info_disclosure

# 强制全量同步
python scripts/run_sync.py --mode all --full
```

### 数据同步流程

#### T+1全量同步流程
```
1. 清空目标表数据
2. 调用API获取全量数据 (is_full=1)
3. 数据映射和清洗
4. 批量插入数据库
5. 更新同步状态
6. 记录同步日志
```

#### ~~实时同步流程（已禁用）~~
```
# 以下流程已禁用，如需启用请修改代码中的注释
1. ~~Kafka监听器接收消息~~
2. ~~解析项目ID~~  
3. ~~调用房源运营API获取最新数据~~
4. ~~更新对应记录~~
5. ~~记录操作日志~~
```

## ⚙️ 配置文档

### 核心配置项

#### T+1全量同步配置
```yaml
# API配置
api:
  request_params:
    is_full: 1              # 全量同步模式
    projectCode: []         # 空数组表示获取所有项目
    
# 同步配置  
sync:
  full_sync_mode: true      # 启用T+1全量模式
  clear_old_data: true      # 每次同步前清空旧数据
  enable_upsert: false      # 禁用更新插入，使用清空重建
  schedule_time: "02:00"    # 定时同步时间
```

#### 数据库配置
```yaml
database:
  host: "YOUR_DB_HOST"
  port: 3306
  user: "YOUR_DB_USER"
  password: "YOUR_DB_PASSWORD"
  database: "nlchatdemo"
  charset: "utf8mb4"
  pool_size: 10
```

#### API认证配置
```yaml
api:
  headers:
    token: "YOUR_API_TOKEN"
    Content-Type: "application/json"
    
operational_api:
  channel: "sszt"
```

#### Kafka配置
```yaml
kafka:
  bootstrap_servers: "10.254.95.167:9092"
  group_id: "volcengine_ai"
  topic: "BJDC_FYXXYYTZ"
  auto_offset_reset: "earliest"
```

### 业务表映射

系统支持的业务表：

| 业务系统 | 表名 | 说明 |
|---------|------|------|
| 互联股权 | bjhl_property_transfer | 股权转让信息 |
| 汇投股权 | bjht_equity_transfer | 股权转让信息 |
| 互联信息披露 | bjhl_info_disclosure | 信息披露 |
| 互联企业增资 | bjhl_enterprise_increase | 企业增资 |
| 汇投增资 | bjht_equity_increase | 股权增资 |
| 汇投房产转让 | bjht_real_estate_transfer | 房产转让 |
| 互联大宗 | bjhl_bulk | 大宗商品 |
| 汇投债权 | bjht_credit_asset | 债权资产 |
| 汇投房屋出租 | bjht_house_rent | 房屋出租 |
| 互联房屋出租 | bjhl_house_rent | 房屋出租 |
| 北交地产 | bjdc_lease_house | 房源运营信息 |

## 📊 监控运维

### 服务状态监控

```bash
# 查看整体状态
./scripts/manage.sh docker status    # Docker模式
./scripts/manage.sh local status     # 本地模式

# 查看详细信息
docker ps | grep bjs-etl             # Docker容器状态
ps aux | grep scheduler.py           # 本地进程状态
```

### 日志管理

#### 日志文件结构
```
logs/
├── scheduler.log          # 调度器主日志
├── kafka_listener.log     # Kafka监听器日志  
├── sync.log              # 数据同步日志
└── sync_cron.log         # 定时任务日志
```

#### 日志查看命令
```bash
# 实时跟踪日志
tail -f logs/scheduler.log

# 查看同步结果
grep "同步完成" logs/sync.log | tail -10

# 查看错误信息
grep "ERROR" logs/*.log

# 统计同步数量
grep "共同步" logs/sync.log | tail -5
```

### 健康检查

系统内置健康检查机制：

```bash
# 自动健康检查（Docker）
docker exec bjs-etl /app/healthcheck.sh

# 手动连接测试
python scripts/scheduler.py --test

# 数据库连接测试
mysql -h HOST -u USER -p -e "SELECT 1"

# API连接测试
curl -H "token: YOUR_TOKEN" "http://10.254.95.156/mservice/synProject/getProjectDetail/page"
```

### 性能监控

#### 资源使用监控
```bash
# 系统资源
top | grep python
free -h
df -h

# Docker资源
docker stats bjs-etl

# 数据库连接
mysql -e "SHOW PROCESSLIST" | wc -l
```

#### 同步性能统计
```bash
# 同步耗时统计
grep "同步耗时" logs/sync.log | tail -10

# 同步数量统计
grep "共同步.*条记录" logs/sync.log | tail -10

# 错误率统计
total=$(grep -c "开始.*同步" logs/sync.log)
errors=$(grep -c "同步失败" logs/sync.log)
echo "错误率: $(($errors * 100 / $total))%"
```

## 🔧 故障排除

### 常见问题诊断

#### 1. 服务启动失败

**症状**：容器或进程无法启动

**诊断步骤**：
```bash
# 检查配置文件
python -c "import yaml; yaml.safe_load(open('config/config.yaml'))"

# 检查依赖
pip check

# 检查端口占用
netstat -tulpn | grep :8080

# 查看详细错误
./scripts/manage.sh docker logs
```

**解决方案**：
- 修复配置文件语法错误
- 重新安装缺失依赖
- 释放被占用端口

#### 2. 数据库连接失败

**症状**：`数据库连接测试失败`

**诊断步骤**：
```bash
# 测试网络连通性
telnet DB_HOST 3306

# 测试数据库认证
mysql -h HOST -u USER -p -e "SELECT 1"

# 检查防火墙
sudo ufw status
```

**解决方案**：
- 检查数据库服务状态
- 验证用户名密码
- 配置防火墙规则

#### 3. API连接超时

**症状**：`API连接测试失败`

**诊断步骤**：
```bash
# 测试API连通性
curl -I "http://10.254.95.156/mservice/synProject/getProjectDetail/page"

# 检查Token有效性
curl -H "token: YOUR_TOKEN" "API_URL"

# 查看网络延迟
ping 10.254.95.156
```

**解决方案**：
- 检查网络连接
- 更新API Token
- 增加超时时间

#### 4. Kafka连接问题

**症状**：`Kafka监听器启动失败`

**诊断步骤**：
```bash
# 测试Kafka连接
telnet 10.254.95.167 9092

# 检查防火墙
sudo firewall-cmd --list-all

# 查看Kafka日志
grep -i kafka logs/*.log
```

**解决方案**：
- 检查Kafka服务状态
- 配置网络访问权限
- 更新Kafka配置

### 数据同步问题

#### 1. 同步数据为空

**可能原因**：
- API返回数据为空
- 字段映射配置错误
- 数据过滤条件过严

**排查方法**：
```bash
# 手动测试API
curl -X POST -H "Content-Type: application/json" \
  -H "token: YOUR_TOKEN" \
  -d '{"page":1,"limit":10,"is_full":1,"projectCode":[]}' \
  "http://10.254.95.156/mservice/synProject/getProjectDetail/page"

# 检查字段映射
grep -A 10 "field_mapping" config/config.yaml

# 查看详细同步日志
grep -A 20 "开始.*同步" logs/sync.log | tail -30
```

#### 2. 同步数据不完整

**可能原因**：
- 网络中断
- 内存不足
- 批处理配置不当

**解决方案**：
- 检查网络稳定性
- 增加内存或减小批处理大小
- 启用增量同步模式

### 性能优化

#### 1. 提高同步速度

```yaml
# config.yaml优化配置
sync:
  batch_size: 500          # 增加批处理大小

database:
  pool_size: 20           # 增加连接池

api:
  timeout: 60             # 增加超时时间
```

#### 2. 减少资源消耗

```yaml
# 减少内存使用
sync:
  batch_size: 100         # 减小批处理

# 减少并发连接
database:
  pool_size: 5
```

#### 3. 优化定时任务

```bash
# 错峰执行，避免高峰期
0 3 * * * python scripts/scheduler.py --sync-now

# 分别执行不同同步任务
0 2 * * * python scripts/run_sync.py --mode subtables
0 3 * * * python scripts/run_sync.py --mode operational
```

## 📝 维护清单

### 日常维护（每天）
- [ ] 检查服务运行状态
- [ ] 查看同步日志确认正常执行
- [ ] 检查错误日志数量

### 周度维护（每周）
- [ ] 清理过期日志文件
- [ ] 检查磁盘空间使用
- [ ] 备份重要配置文件

### 月度维护（每月）
- [ ] 更新系统依赖包
- [ ] 检查数据库性能
- [ ] 优化系统配置参数
- [ ] 更新安全补丁

## 🔒 安全说明

### 配置文件安全
- ✅ 敏感配置已从版本控制中排除
- ✅ 配置模板提供安全的配置示例
- ✅ 生产环境配置文件权限控制（600）

### 数据传输安全
- ✅ API通信支持HTTPS加密
- ✅ 数据库连接支持TLS加密
- ✅ 日志中敏感信息自动脱敏

### 访问控制
- ✅ 数据库用户权限最小化
- ✅ API Token定期更新
- ✅ 容器运行在非root用户下

## 📦 Docker打包与内网迁移

### Docker镜像打包

#### 1. 构建Docker镜像

```bash
# 在项目根目录执行
cd 北交所数据同步程序

# 构建镜像（带版本标签）
docker build -t bjs-etl:v2.0.0 .

# 构建镜像（最新版本）
docker build -t bjs-etl:latest .

# 查看构建的镜像
docker images | grep bjs-etl
```

#### 2. 打包镜像为tar文件

```bash
# 方法一：打包单个镜像
docker save -o bjs-etl-v2.0.0.tar bjs-etl:v2.0.0

# 方法二：打包多个版本
docker save -o bjs-etl-all.tar bjs-etl:v2.0.0 bjs-etl:latest

# 方法三：使用压缩（推荐，减小文件大小）
docker save bjs-etl:v2.0.0 | gzip > bjs-etl-v2.0.0.tar.gz

# 查看打包文件大小
ls -lh bjs-etl-*.tar*
```

#### 3. 一键打包脚本（推荐）

使用提供的自动化打包脚本：

```bash
# 🔧 前提：确保config/config.yaml存在并已正确配置
cp config/config.template.yaml config/config.yaml
vim config/config.yaml  # 填入内网环境的实际配置

# 执行一键打包（Linux/macOS）
./scripts/package-for-deployment.sh

# 或指定版本号
./scripts/package-for-deployment.sh v2.1.0

# 🎯 脚本智能处理：
# - 如果存在config/config.yaml → 配置文件会打包到Docker镜像中
# - 如果不存在config/config.yaml → 使用模板配置，需要内网部署时手动配置

# 脚本会自动完成以下步骤：
# 1. 检测并打包配置文件到Docker镜像
# 2. 构建Docker镜像
# 3. 导出镜像为tar.gz文件
# 4. 创建完整部署包
# 5. 生成智能部署脚本
# 6. 打包为最终的部署文件

# 最终会生成：bjs-etl-deploy-v2.0.0.tar.gz
```

#### 4. 手动打包完整部署包

如果需要手动创建部署包：

```bash
# 创建部署包目录
mkdir bjs-etl-deploy

# 复制必要文件
cp -r config/ bjs-etl-deploy/
cp docker-compose.yaml bjs-etl-deploy/
cp scripts/manage.sh bjs-etl-deploy/
cp README.md bjs-etl-deploy/
cp requirements.txt bjs-etl-deploy/

# 创建部署脚本
cat > bjs-etl-deploy/deploy.sh << 'EOF'
#!/bin/bash
set -e

echo "========================================"
echo "北交所数据同步程序 - 内网部署脚本"
echo "========================================"

# 检查Docker环境
if ! command -v docker >/dev/null 2>&1; then
    echo "❌ Docker未安装，请先安装Docker"
    exit 1
fi

# 加载镜像
echo "🔄 正在加载Docker镜像..."
if [ -f "bjs-etl-v2.0.0.tar.gz" ]; then
    gunzip -c bjs-etl-v2.0.0.tar.gz | docker load
elif [ -f "bjs-etl-v2.0.0.tar" ]; then
    docker load -i bjs-etl-v2.0.0.tar
else
    echo "❌ 找不到Docker镜像文件"
    exit 1
fi

# 检查配置文件
if [ ! -f "config/config.yaml" ]; then
    echo "⚠️  配置文件不存在，从模板创建..."
    cp config/config.template.yaml config/config.yaml
    echo "请编辑 config/config.yaml 填入正确的配置信息"
    exit 1
fi

# 创建必要目录
mkdir -p logs exports

# 启动服务
echo "🚀 启动服务..."
chmod +x manage.sh
./manage.sh docker start

echo "✅ 部署完成！"
echo "📊 查看状态: ./manage.sh docker status"
echo "📋 查看日志: ./manage.sh docker logs -f"
EOF

chmod +x bjs-etl-deploy/deploy.sh

# 复制Docker镜像文件
cp bjs-etl-v2.0.0.tar.gz bjs-etl-deploy/

# 打包整个部署包
tar -czf bjs-etl-deploy-v2.0.0.tar.gz bjs-etl-deploy/

echo "✅ 部署包创建完成: bjs-etl-deploy-v2.0.0.tar.gz"
```

### 内网服务器部署

#### 1. 传输部署包到内网服务器

```bash
# 方法一：使用scp传输
scp bjs-etl-deploy-v2.0.0.tar.gz user@内网服务器IP:/opt/

# 方法二：使用U盘等物理介质传输
# 将 bjs-etl-deploy-v2.0.0.tar.gz 复制到内网服务器
```

#### 2. 在内网服务器上部署

```bash
# 登录内网服务器
ssh user@内网服务器IP

# 切换到部署目录
cd /opt

# 解压部署包
tar -xzf bjs-etl-deploy-v2.0.0.tar.gz
cd bjs-etl-deploy-v2.0.0

# 查看部署包内容
ls -la
# 应该看到：
# - docker-compose.yaml    Docker编排文件
# - manage.sh              管理脚本
# - deploy.sh              智能部署脚本
# - bjs-etl-v2.0.0.tar.gz  Docker镜像（包含配置）
# - README.md              说明文档
# - config/                配置文件目录（仅在未打包到镜像时存在）

# 执行智能部署脚本
./deploy.sh

# 🎯 智能部署：
# - 如果配置已在镜像中 → 直接启动，无需额外配置
# - 如果配置需要手动设置 → 会提示编辑配置文件
```

#### 3. 验证和测试（可选）

```bash
# 如果配置已打包在镜像中，直接进行验证测试
# 如果需要手动配置，部署脚本会自动提示

# 手动配置的关键参数（仅在需要时）：
# - database.host: "内网数据库IP"
# - database.user: "数据库用户名"
# - database.password: "数据库密码"
# - api.headers.token: "API Token"
# - kafka.bootstrap_servers: "内网Kafka服务器IP:9092"
```

#### 4. 启动和验证服务

```bash
# 启动服务
./manage.sh docker start

# 查看服务状态
./manage.sh docker status

# 测试连接
./manage.sh docker test

# 查看日志
./manage.sh docker logs -f

# 手动执行一次同步测试
./manage.sh docker sync
```

### 内网部署最佳实践

#### 1. 环境准备清单

**内网服务器要求：**
- ✅ Linux操作系统（Ubuntu 18.04+ / CentOS 7+）
- ✅ Docker 20.0+
- ✅ Docker Compose 1.27+
- ✅ 至少4GB内存，2CPU核心
- ✅ 50GB可用磁盘空间

**网络要求：**
- ✅ 能访问内网MySQL数据库
- ✅ 能访问内网Kafka服务器
- ✅ 能访问项目数据API服务器
- ✅ 能访问房源运营API服务器

#### 2. 部署前检查脚本

创建 `pre-check.sh` 脚本：

```bash
cat > pre-check.sh << 'EOF'
#!/bin/bash
echo "========================================"
echo "内网部署环境检查"
echo "========================================"

# 检查Docker
if command -v docker >/dev/null 2>&1; then
    echo "✅ Docker: $(docker --version)"
else
    echo "❌ Docker: 未安装"
    exit 1
fi

# 检查Docker Compose
if command -v docker-compose >/dev/null 2>&1; then
    echo "✅ Docker Compose: $(docker-compose --version)"
elif docker compose version >/dev/null 2>&1; then
    echo "✅ Docker Compose: $(docker compose version)"
else
    echo "❌ Docker Compose: 未安装"
    exit 1
fi

# 检查系统资源
echo "📊 系统资源:"
echo "   CPU: $(nproc) 核心"
echo "   内存: $(free -h | grep '^Mem:' | awk '{print $2}')"
echo "   磁盘: $(df -h / | tail -1 | awk '{print $4}') 可用"

# 检查网络连通性（需要根据实际环境调整IP）
echo "🌐 网络连通性检查:"

# 检查数据库连接（示例）
if timeout 3 bash -c "</dev/tcp/数据库IP/3306" 2>/dev/null; then
    echo "✅ 数据库端口 3306: 可达"
else
    echo "❌ 数据库端口 3306: 不可达"
fi

# 检查Kafka连接（示例）
if timeout 3 bash -c "</dev/tcp/KafkaIP/9092" 2>/dev/null; then
    echo "✅ Kafka端口 9092: 可达"
else
    echo "❌ Kafka端口 9092: 不可达"
fi

echo "========================================"
echo "环境检查完成"
echo "========================================"
EOF

chmod +x pre-check.sh
```

#### 3. 生产环境配置模板

创建生产环境专用配置：

```bash
cat > config/config.prod.yaml << 'EOF'
# 生产环境配置文件
# 请根据实际内网环境修改以下配置

# API接口配置
api:
  base_url: "http://内网API服务器IP/mservice/synProject/getProjectDetail/page"
  headers:
    token: "生产环境API_TOKEN"
    Content-Type: "application/json"
  request_params:
    page: 1
    limit: 999999999
    is_full: 1
    projectCode: []
  timeout: 30
  retry_times: 3
  retry_delay: 5

# 房源运营信息API配置
operational_api:
  base_url: "http://内网运营API服务器IP:8088/bjdc/website/project/operational"
  headers:
    Content-Type: "application/json"
  timeout: 120
  retry_times: 3
  retry_delay: 10
  channel: "sszt"

# Kafka配置
kafka:
  bootstrap_servers: "内网Kafka服务器IP:9092"
  group_id: "volcengine_ai"
  topic: "BJDC_FYXXYYTZ"
  auto_offset_reset: "earliest"
  enable_auto_commit: true
  auto_commit_interval_ms: 1000
  session_timeout_ms: 30000
  max_poll_records: 100

# 数据库配置
database:
  host: "内网数据库IP"
  port: 3306
  user: "生产环境数据库用户"
  password: "生产环境数据库密码"
  database: "nlchatdemo"
  charset: "utf8mb4"
  pool_size: 10
  pool_recycle: 3600

# 同步配置
sync:
  batch_size: 100
  enable_upsert: false
  clear_old_data: true
  unique_key: "id"
  date_format: "%Y-%m-%d %H:%M:%S"
  full_sync_mode: true
  schedule_time: "02:00"

# 日志配置
logging:
  level: "INFO"
  format: "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
  file: "logs/sync.log"
  max_bytes: 10485760
  backup_count: 5
EOF
```

#### 4. 服务管理脚本

创建生产环境服务管理脚本：

```bash
cat > service-control.sh << 'EOF'
#!/bin/bash
# 生产环境服务管理脚本

set -e

SERVICE_NAME="bjs-etl"
LOG_DIR="logs"

case "$1" in
    start)
        echo "🚀 启动北交所数据同步服务..."
        ./manage.sh docker start
        ;;
    stop)
        echo "🛑 停止北交所数据同步服务..."
        ./manage.sh docker stop
        ;;
    restart)
        echo "🔄 重启北交所数据同步服务..."
        ./manage.sh docker restart
        ;;
    status)
        echo "📊 查看服务状态..."
        ./manage.sh docker status
        ;;
    logs)
        echo "📋 查看实时日志..."
        ./manage.sh docker logs -f
        ;;
    sync)
        echo "🔄 手动执行数据同步..."
        ./manage.sh docker sync
        ;;
    backup)
        echo "💾 备份配置和日志..."
        backup_dir="backup_$(date +%Y%m%d_%H%M%S)"
        mkdir -p "$backup_dir"
        cp -r config/ "$backup_dir/"
        cp -r logs/ "$backup_dir/" 2>/dev/null || true
        tar -czf "${backup_dir}.tar.gz" "$backup_dir"
        rm -rf "$backup_dir"
        echo "✅ 备份完成: ${backup_dir}.tar.gz"
        ;;
    health)
        echo "🏥 健康检查..."
        if ./manage.sh docker test; then
            echo "✅ 系统健康状态良好"
        else
            echo "❌ 系统健康检查失败"
            exit 1
        fi
        ;;
    update)
        echo "⬆️ 更新服务..."
        read -p "确认要更新服务吗？(y/N): " confirm
        if [[ $confirm == [yY] ]]; then
            ./manage.sh docker stop
            docker system prune -f
            echo "请上传新的镜像文件并重新部署"
        fi
        ;;
    *)
        echo "用法: $0 {start|stop|restart|status|logs|sync|backup|health|update}"
        echo ""
        echo "命令说明:"
        echo "  start   - 启动服务"
        echo "  stop    - 停止服务"
        echo "  restart - 重启服务"
        echo "  status  - 查看状态"
        echo "  logs    - 查看日志"
        echo "  sync    - 手动同步"
        echo "  backup  - 备份数据"
        echo "  health  - 健康检查"
        echo "  update  - 更新服务"
        exit 1
        ;;
esac
EOF

chmod +x service-control.sh
```

### 故障排除

#### 常见内网部署问题

1. **Docker镜像加载失败**
```bash
# 检查镜像文件完整性
md5sum bjs-etl-v2.0.0.tar.gz

# 手动加载镜像
gunzip -c bjs-etl-v2.0.0.tar.gz | docker load

# 验证镜像加载
docker images | grep bjs-etl
```

2. **网络连接问题**
```bash
# 测试API连通性
curl -I "http://内网API服务器IP/mservice/synProject/getProjectDetail/page"

# 测试数据库连接
telnet 内网数据库IP 3306

# 测试Kafka连接
telnet 内网KafkaIP 9092
```

3. **权限问题**
```bash
# 添加用户到docker组
sudo usermod -aG docker $USER

# 重新登录或执行
newgrp docker

# 检查Docker权限
docker ps
```

### 版本升级流程

#### 1. 准备新版本镜像
```bash
# 在开发环境构建新版本
docker build -t bjs-etl:v2.1.0 .
docker save bjs-etl:v2.1.0 | gzip > bjs-etl-v2.1.0.tar.gz
```

#### 2. 内网升级步骤
```bash
# 1. 备份当前版本
./service-control.sh backup

# 2. 停止服务
./service-control.sh stop

# 3. 加载新镜像
gunzip -c bjs-etl-v2.1.0.tar.gz | docker load

# 4. 更新docker-compose.yaml中的镜像版本
sed -i 's/bjs-etl:v2.0.0/bjs-etl:v2.1.0/g' docker-compose.yaml

# 5. 启动新版本
./service-control.sh start

# 6. 验证升级
./service-control.sh health
```

## 📞 技术支持

### 获取帮助

```bash
# 查看脚本帮助
./scripts/manage.sh help

# 查看调度器帮助  
python scripts/scheduler.py --help

# 查看同步脚本帮助
python scripts/run_sync.py --help
```

### 问题反馈

如遇到问题，请按以下步骤收集信息：

1. **收集错误日志**
   ```bash
   grep "ERROR" logs/*.log > error_report.log
   ```

2. **收集系统信息**
   ```bash
   python --version > system_info.txt
   pip list >> system_info.txt
   docker version >> system_info.txt
   ```

3. **收集配置信息**（注意脱敏）
   ```bash
   # 移除敏感信息后的配置
   grep -v -E "(password|token|secret)" config/config.yaml > config_safe.yaml
   ```

4. **执行健康检查**
   ```bash
   ./scripts/manage.sh docker health > health_check.log
   ```

---

## 📄 许可证

本项目为内部专用系统，版权所有。未经授权不得复制、分发或修改。

---

## 📚 快速参考

### Docker打包命令速查

```bash
# 🔧 开发环境（打包准备）
# 1. 配置文件准备（重要！）
cp config/config.template.yaml config/config.yaml
vim config/config.yaml  # 填入内网环境配置

# 2. 一键打包（配置会自动打包到镜像中）
./scripts/package-for-deployment.sh v2.0.0    # 智能打包
docker build -t bjs-etl:v2.0.0 .             # 手动构建镜像
docker save bjs-etl:v2.0.0 | gzip > bjs-etl-v2.0.0.tar.gz  # 手动导出镜像

# 📦 传输到内网（物理介质/网络传输）
scp bjs-etl-deploy-v2.0.0.tar.gz user@内网服务器:/opt/
```

### 内网部署命令速查

```bash
# 🚀 内网服务器（简化部署流程）
cd /opt
tar -xzf bjs-etl-deploy-v2.0.0.tar.gz        # 解压部署包
cd bjs-etl-deploy-v2.0.0
./pre-check.sh                               # 环境检查（可选）
./deploy.sh                                  # 智能一键部署

# ✨ 优势：如果配置已打包在镜像中，无需手动配置即可启动！

# 🛠️ 服务管理
./service-control.sh status                  # 查看状态
./service-control.sh logs                    # 查看日志
./service-control.sh sync                    # 手动同步
./service-control.sh restart                 # 重启服务
./service-control.sh backup                  # 备份数据
```

### 本地开发命令速查

```bash
# 🔧 本地开发运行
./scripts/manage.sh local start              # 启动本地服务
./scripts/manage.sh local status             # 查看状态
./scripts/manage.sh local sync               # 立即同步
python scripts/scheduler.py --test           # 测试连接

# 🐳 Docker本地运行
./scripts/manage.sh docker start             # 启动Docker服务
./scripts/manage.sh docker logs -f           # 实时查看日志
./scripts/manage.sh docker sync              # Docker手动同步
```

### 配置文件核心参数

```yaml
# 必须修改的关键配置
database:
  host: "内网数据库IP"                        # ⚠️ 必须修改
  user: "数据库用户名"                        # ⚠️ 必须修改  
  password: "数据库密码"                      # ⚠️ 必须修改

api:
  headers:
    token: "API认证Token"                     # ⚠️ 必须修改

kafka:
  bootstrap_servers: "内网Kafka服务器IP:9092" # ⚠️ 必须修改

# T+1全量同步关键配置（已优化，一般不需修改）
api:
  request_params:
    is_full: 1                               # ✅ 全量模式
    projectCode: []                          # ✅ 获取所有项目

sync:
  clear_old_data: true                       # ✅ 清空重建
  schedule_time: "02:00"                     # ✅ 凌晨2点执行
```

---

**🎉 部署完成后，您将拥有一个稳定、高效的北交所数据同步系统！**

> 💡 **提示**：首次部署建议先在测试环境验证，确认无误后再部署到生产环境。