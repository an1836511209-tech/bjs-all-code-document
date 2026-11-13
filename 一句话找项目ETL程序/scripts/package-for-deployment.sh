#!/bin/bash

# 北交所数据同步程序 - 部署包打包脚本
# 用于创建内网部署包

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# 日志函数
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_step() {
    echo -e "${BLUE}[STEP]${NC} $1"
}

log_title() {
    echo -e "${CYAN}[TITLE]${NC} $1"
}

# 获取版本号
VERSION=${1:-"v2.0.0"}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 切换到项目根目录
cd "$PROJECT_ROOT"

log_title "北交所数据同步程序 - 部署包打包工具"
echo ""
echo "版本: $VERSION"
echo "项目目录: $PROJECT_ROOT"
echo ""

# 检查Docker环境
check_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        log_error "Docker未安装或不在PATH中"
        exit 1
    fi
    log_info "Docker环境检查通过"
}

# 1. 准备配置文件并构建Docker镜像
build_docker_image() {
    log_step "准备配置文件..."
    
    # 检查是否存在实际配置文件
    if [ -f "config/config.yaml" ]; then
        log_info "发现配置文件 config/config.yaml，将打包到镜像中"
        CONFIG_EXISTS=true
    else
        log_warn "未找到 config/config.yaml，将使用模板配置"
        CONFIG_EXISTS=false
    fi
    
    log_step "构建Docker镜像..."
    
    # 创建临时构建上下文
    mkdir -p temp_build_context
    
    # 复制项目文件到临时目录
    cp -r src/ temp_build_context/
    cp -r scripts/ temp_build_context/
    cp -r config/ temp_build_context/
    cp requirements.txt temp_build_context/
    cp setup.py temp_build_context/
    
    # 创建优化的Dockerfile
    cat > temp_build_context/Dockerfile << 'EOF'
# 北交所数据同步程序 - 生产版Docker镜像
FROM python:3.10-slim

LABEL maintainer="dev-team" \
      description="北交所数据ETL系统-生产版" \
      version="2.0.0"

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    TZ=Asia/Shanghai

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    default-libmysqlclient-dev \
    gcc \
    g++ \
    pkg-config \
    curl \
    wget \
    tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 设置时区
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 创建应用目录
WORKDIR /app

# 创建非root用户
RUN useradd -m -u 1000 etl && \
    mkdir -p /app/logs /app/exports && \
    chown -R etl:etl /app

# 复制requirements文件并安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 复制应用代码和配置
COPY . .

# 确保脚本有执行权限
RUN chmod +x scripts/*.py && \
    chown -R etl:etl /app

# 创建健康检查脚本
RUN cat > /app/healthcheck.sh << 'HEALTH_EOF'
#!/bin/bash
# 检查调度器进程
if ! pgrep -f "scheduler.py" > /dev/null; then
    echo "调度器未运行"
    exit 1
fi

# 检查配置文件
if [ ! -f "/app/config/config.yaml" ]; then
    echo "配置文件不存在"
    exit 1
fi

echo "健康检查通过"
exit 0
HEALTH_EOF

RUN chmod +x /app/healthcheck.sh

# 创建启动脚本
RUN cat > /app/docker-entrypoint.sh << 'ENTRY_EOF'
#!/bin/bash
set -e

echo "========================================"
echo "北交所数据ETL系统启动"
echo "========================================"

# 检查配置文件
if [ ! -f "/app/config/config.yaml" ]; then
    echo "错误: 配置文件不存在"
    exit 1
fi

# 创建必要目录
mkdir -p /app/logs /app/exports

# 设置文件权限
chown -R etl:etl /app/logs /app/exports

echo "配置文件检查通过，启动调度器..."

# 切换到etl用户并启动调度器
exec su etl -c "python scripts/scheduler.py"
ENTRY_EOF

RUN chmod +x /app/docker-entrypoint.sh

# 创建数据卷
VOLUME ["/app/logs", "/app/exports"]

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD /app/healthcheck.sh

# 暴露端口（如果需要监控接口）
EXPOSE 8080

# 设置启动命令
ENTRYPOINT ["/app/docker-entrypoint.sh"]
EOF
    
    # 在临时目录中构建镜像
    cd temp_build_context
    docker build -t bjs-etl:$VERSION .
    docker build -t bjs-etl:latest .
    cd ..
    
    # 清理临时目录
    rm -rf temp_build_context
    
    log_info "✅ Docker镜像构建完成"
    docker images | grep bjs-etl
}

# 2. 导出Docker镜像
export_docker_image() {
    log_step "导出Docker镜像..."
    
    # 创建临时目录
    mkdir -p temp_build
    
    # 导出镜像（压缩）
    docker save bjs-etl:$VERSION | gzip > temp_build/bjs-etl-$VERSION.tar.gz
    
    log_info "✅ Docker镜像导出完成: bjs-etl-$VERSION.tar.gz"
    ls -lh temp_build/bjs-etl-$VERSION.tar.gz
}

# 3. 创建部署包
create_deployment_package() {
    log_step "创建部署包..."
    
    DEPLOY_DIR="bjs-etl-deploy-$VERSION"
    
    # 清理旧的部署目录
    rm -rf "$DEPLOY_DIR"
    mkdir -p "$DEPLOY_DIR"
    
    # 复制必要文件
    log_info "复制项目文件..."
    cp docker-compose.yaml "$DEPLOY_DIR/"
    cp scripts/manage.sh "$DEPLOY_DIR/"
    cp README.md "$DEPLOY_DIR/"
    
    # 只有在配置文件未打包到镜像中时才复制配置目录
    if [ "$CONFIG_EXISTS" = false ]; then
        cp -r config/ "$DEPLOY_DIR/"
        log_info "配置文件已复制到部署包（镜像中未包含配置）"
    else
        log_info "配置文件已内置在Docker镜像中，无需单独复制"
    fi
    
    # 复制Docker镜像
    cp temp_build/bjs-etl-$VERSION.tar.gz "$DEPLOY_DIR/"
    
    # 创建部署脚本
    log_info "创建部署脚本..."
    
    if [ "$CONFIG_EXISTS" = true ]; then
        # 配置已在镜像中的部署脚本
        cat > "$DEPLOY_DIR/deploy.sh" << 'EOF'
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
IMAGE_FILE=""
for file in bjs-etl-*.tar.gz; do
    if [ -f "$file" ]; then
        IMAGE_FILE="$file"
        break
    fi
done

if [ -n "$IMAGE_FILE" ]; then
    echo "正在加载镜像: $IMAGE_FILE"
    gunzip -c "$IMAGE_FILE" | docker load
else
    echo "❌ 找不到Docker镜像文件"
    exit 1
fi

echo "✅ 镜像加载完成"
echo "ℹ️  配置文件已内置在Docker镜像中，无需额外配置"

# 创建必要目录
mkdir -p logs exports

# 启动服务
echo "🚀 启动服务..."
chmod +x manage.sh
./manage.sh docker start

echo ""
echo "✅ 部署完成！"
echo ""
echo "常用命令："
echo "  查看状态: ./manage.sh docker status"
echo "  查看日志: ./manage.sh docker logs -f"
echo "  手动同步: ./manage.sh docker sync"
echo "  停止服务: ./manage.sh docker stop"
echo ""
echo "注意：配置文件已内置在镜像中，如需修改配置请重新构建镜像"
echo ""
EOF
    else
        # 需要外部配置的部署脚本
        cat > "$DEPLOY_DIR/deploy.sh" << 'EOF'
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
IMAGE_FILE=""
for file in bjs-etl-*.tar.gz; do
    if [ -f "$file" ]; then
        IMAGE_FILE="$file"
        break
    fi
done

if [ -n "$IMAGE_FILE" ]; then
    echo "正在加载镜像: $IMAGE_FILE"
    gunzip -c "$IMAGE_FILE" | docker load
else
    echo "❌ 找不到Docker镜像文件"
    exit 1
fi

# 检查配置文件
if [ ! -f "config/config.yaml" ]; then
    echo "⚠️  配置文件不存在，从模板创建..."
    cp config/config.template.yaml config/config.yaml
    echo ""
    echo "⚠️  重要：请编辑 config/config.yaml 填入正确的配置信息！"
    echo "   主要配置项："
    echo "   - database.host: 内网数据库IP"
    echo "   - database.user: 数据库用户名"
    echo "   - database.password: 数据库密码"
    echo "   - api.headers.token: API Token"
    echo "   - kafka.bootstrap_servers: Kafka服务器地址"
    echo ""
    read -p "配置完成后按任意键继续..."
fi

# 创建必要目录
mkdir -p logs exports

# 启动服务
echo "🚀 启动服务..."
chmod +x manage.sh
./manage.sh docker start

echo ""
echo "✅ 部署完成！"
echo ""
echo "常用命令："
echo "  查看状态: ./manage.sh docker status"
echo "  查看日志: ./manage.sh docker logs -f"
echo "  手动同步: ./manage.sh docker sync"
echo "  停止服务: ./manage.sh docker stop"
echo ""
EOF
    fi

    chmod +x "$DEPLOY_DIR/deploy.sh"
    
    # 创建环境检查脚本
    log_info "创建环境检查脚本..."
    cat > "$DEPLOY_DIR/pre-check.sh" << 'EOF'
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

# 检查Docker权限
if docker ps >/dev/null 2>&1; then
    echo "✅ Docker权限: 正常"
else
    echo "❌ Docker权限: 当前用户无权限，请执行: sudo usermod -aG docker $USER"
fi

echo "========================================"
echo "环境检查完成"
echo "========================================"
EOF

    chmod +x "$DEPLOY_DIR/pre-check.sh"
    
    # 创建服务管理脚本
    log_info "创建服务管理脚本..."
    cat > "$DEPLOY_DIR/service-control.sh" << 'EOF'
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
    *)
        echo "用法: $0 {start|stop|restart|status|logs|sync|backup|health}"
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
        exit 1
        ;;
esac
EOF

    chmod +x "$DEPLOY_DIR/service-control.sh"
    
    # 创建生产环境配置模板
    log_info "创建生产环境配置模板..."
    cat > "$DEPLOY_DIR/config/config.prod.yaml" << 'EOF'
# 生产环境配置文件模板
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

    # 创建部署说明文档
    log_info "创建部署说明文档..."
    cat > "$DEPLOY_DIR/DEPLOY_GUIDE.md" << 'EOF'
# 北交所数据同步程序 - 内网部署指南

## 快速部署步骤

### 1. 环境检查
```bash
# 执行环境检查
./pre-check.sh
```

### 2. 配置服务
```bash
# 编辑配置文件，填入内网环境信息
vim config/config.yaml
```

### 3. 部署启动
```bash
# 一键部署
./deploy.sh
```

### 4. 服务管理
```bash
# 查看状态
./service-control.sh status

# 查看日志
./service-control.sh logs

# 手动同步
./service-control.sh sync

# 停止服务
./service-control.sh stop
```

## 配置要点

必须修改的配置项：
- `database.host`: 内网数据库IP
- `database.user`: 数据库用户名
- `database.password`: 数据库密码
- `api.headers.token`: API认证Token
- `kafka.bootstrap_servers`: Kafka服务器地址

## 服务说明

- 系统会自动启动调度器
- Kafka监听器7×24小时运行
- T+1全量同步每天凌晨2点执行
- 日志文件保存在 `logs/` 目录

## 故障排除

1. 镜像加载失败：检查tar.gz文件完整性
2. 配置错误：检查config.yaml语法和参数
3. 网络问题：确认内网服务器网络连通性
4. 权限问题：确保当前用户在docker组中

## 技术支持

查看完整文档：README.md
EOF

    log_info "✅ 部署包创建完成"
}

# 4. 打包最终文件
package_final() {
    log_step "打包最终部署文件..."
    
    # 打包部署目录
    tar -czf "$DEPLOY_DIR.tar.gz" "$DEPLOY_DIR/"
    
    # 清理临时文件
    rm -rf temp_build/
    rm -rf "$DEPLOY_DIR/"
    
    log_info "✅ 最终部署包创建完成: $DEPLOY_DIR.tar.gz"
    
    # 显示文件信息
    echo ""
    log_title "部署包信息"
    ls -lh "$DEPLOY_DIR.tar.gz"
    echo ""
    log_info "部署包内容："
    tar -tzf "$DEPLOY_DIR.tar.gz" | head -20
    echo "..."
    
    # 显示MD5校验和
    if command -v md5sum >/dev/null 2>&1; then
        echo ""
        log_info "MD5校验和："
        md5sum "$DEPLOY_DIR.tar.gz"
    fi
}

# 显示使用说明
show_usage() {
    echo ""
    log_title "部署包使用说明"
    echo ""
    echo "1. 将 $DEPLOY_DIR.tar.gz 传输到内网服务器"
    echo ""
    echo "2. 在内网服务器上执行："
    echo "   tar -xzf $DEPLOY_DIR.tar.gz"
    echo "   cd $DEPLOY_DIR"
    echo "   ./pre-check.sh"
    echo "   ./deploy.sh"
    echo ""
    echo "3. 配置完成后可使用："
    echo "   ./service-control.sh status    # 查看状态"
    echo "   ./service-control.sh logs      # 查看日志"
    echo "   ./service-control.sh sync      # 手动同步"
    echo ""
}

# 主执行流程
main() {
    echo ""
    log_step "开始创建部署包..."
    echo ""
    
    # 检查Docker环境
    check_docker
    
    # 构建Docker镜像
    build_docker_image
    
    # 导出Docker镜像
    export_docker_image
    
    # 创建部署包
    create_deployment_package
    
    # 打包最终文件
    package_final
    
    # 显示使用说明
    show_usage
    
    echo ""
    log_title "🎉 部署包创建完成！"
    echo ""
}

# 执行主函数
main
