#!/bin/bash

# 北交所数据同步程序 - 统一管理脚本
# 支持Docker和本地运行两种模式

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

# 获取脚本目录和项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# 切换到项目根目录
cd "$PROJECT_ROOT"

# 显示帮助信息
show_help() {
    echo ""
    log_title "北交所数据同步程序 - 统一管理脚本"
    echo ""
    echo "用法: $0 [模式] [命令] [选项]"
    echo ""
    echo "模式:"
    echo "  docker        Docker容器运行模式"
    echo "  local         本地直接运行模式"
    echo ""
    echo "命令:"
    echo "  start         启动服务"
    echo "  stop          停止服务"
    echo "  restart       重启服务"
    echo "  status        查看服务状态"
    echo "  logs          查看日志"
    echo "  sync          手动执行数据同步"
    echo "  test          测试连接"
    echo "  build         构建镜像（仅Docker模式）"
    echo "  clean         清理资源"
    echo ""
    echo "选项:"
    echo "  -f, --follow      跟踪日志输出"
    echo "  -h, --help        显示此帮助信息"
    echo "  --rebuild         重新构建镜像"
    echo "  --kafka-only      仅启动Kafka监听器（已禁用）"
    echo ""
    echo "示例:"
    echo "  $0 docker start           # Docker模式启动"
    echo "  $0 local start            # 本地模式启动"
    echo "  $0 docker logs -f         # 实时查看Docker日志"
    echo "  $0 local sync             # 本地模式立即同步"
    echo "  $0 docker build --rebuild # 重新构建Docker镜像"
    echo ""
}

# 检查Docker环境
check_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        log_error "Docker未安装或不在PATH中"
        exit 1
    fi
    
    if ! command -v docker-compose >/dev/null 2>&1 && ! docker compose version >/dev/null 2>&1; then
        log_error "Docker Compose未安装或不在PATH中"
        exit 1
    fi
    
    # 确定使用的compose命令
    if docker compose version >/dev/null 2>&1; then
        COMPOSE_CMD="docker compose"
    else
        COMPOSE_CMD="docker-compose"
    fi
}

# 检查Python环境
check_python() {
    if command -v python3 >/dev/null 2>&1; then
        PYTHON_CMD=python3
    elif command -v python >/dev/null 2>&1; then
        PYTHON_CMD=python
    else
        log_error "未找到Python环境"
        exit 1
    fi
    
    # 检查Python版本
    PYTHON_VERSION=$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    log_info "Python版本: $PYTHON_VERSION"
}

# 检查配置文件
check_config() {
    if [ ! -f "config/config.yaml" ]; then
        log_error "配置文件 config/config.yaml 不存在"
        log_warn "请从 config/config.template.yaml 复制并配置"
        exit 1
    fi
    log_info "配置文件检查通过"
}

# 创建必要目录
create_directories() {
    log_step "创建必要目录..."
    mkdir -p logs exports
    log_info "目录创建完成"
}

# Docker模式启动
docker_start() {
    log_title "Docker模式启动服务"
    
    check_docker
    check_config
    create_directories
    
    local rebuild_flag=""
    if [ "$1" == "--rebuild" ]; then
        rebuild_flag="--build"
        log_step "重新构建镜像..."
    fi
    
    log_step "启动主服务..."
    $COMPOSE_CMD up -d $rebuild_flag bjs-etl
    
    # 等待服务启动
    log_step "等待服务启动..."
    sleep 10
    
    # 检查服务状态
    if $COMPOSE_CMD ps bjs-etl | grep -q "Up"; then
        log_info "✅ 服务启动成功"
    else
        log_error "❌ 服务启动失败"
        $COMPOSE_CMD logs bjs-etl
        exit 1
    fi
    
    log_info "========================================"
    log_info "🎉 Docker服务启动完成！"
    log_info "🚀 调度器: 运行中（T+1全量同步模式）"
    log_info "⏰ 定时同步: 每天凌晨2点T+1全量同步"
    log_info "📝 说明: Kafka实时监听已禁用"
    log_info "📊 查看状态: $0 docker status"
    log_info "📋 查看日志: $0 docker logs -f"
    log_info "========================================"
}

# Docker模式停止
docker_stop() {
    log_title "Docker模式停止服务"
    
    check_docker
    
    log_step "停止所有服务..."
    $COMPOSE_CMD down
    
    log_info "✅ 所有服务已停止"
}

# Docker模式状态
docker_status() {
    log_title "Docker服务状态"
    
    check_docker
    
    echo ""
    echo "Docker容器状态:"
    $COMPOSE_CMD ps
    
    echo ""
    echo "服务健康状态:"
    
    if $COMPOSE_CMD ps bjs-etl | grep -q "Up"; then
        CONTAINER_ID=$($COMPOSE_CMD ps -q bjs-etl)
        
        # 检查调度器
        if docker exec $CONTAINER_ID pgrep -f "scheduler.py" >/dev/null 2>&1; then
            echo -e "${GREEN}✅ 调度器: 运行中${NC}"
        else
            echo -e "${RED}❌ 调度器: 未运行${NC}"
        fi
        
        # 检查系统连接
        if docker exec $CONTAINER_ID python scripts/scheduler.py --test >/dev/null 2>&1; then
            echo -e "${GREEN}✅ 系统连接: 正常${NC}"
        else
            echo -e "${RED}❌ 系统连接: 异常${NC}"
        fi
    else
        echo -e "${RED}❌ 主服务: 未运行${NC}"
    fi
    
    echo ""
    echo "资源使用情况:"
    docker stats --no-stream --format "table {{.Container}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" | grep bjs-etl || echo "无运行中的容器"
}

# Docker模式日志
docker_logs() {
    local follow_flag=""
    
    if [ "$1" == "-f" ] || [ "$1" == "--follow" ]; then
        follow_flag="-f"
        log_info "实时跟踪日志（按 Ctrl+C 退出）..."
    fi
    
    check_docker
    $COMPOSE_CMD logs $follow_flag bjs-etl
}

# Docker模式同步
docker_sync() {
    log_title "Docker模式手动执行数据同步"
    
    check_docker
    
    log_step "启动同步容器..."
    $COMPOSE_CMD --profile manual run --rm bjs-etl-sync
    
    log_info "✅ 数据同步完成"
}

# Docker模式构建
docker_build() {
    log_title "构建Docker镜像"
    
    check_docker
    
    local build_args=""
    
    if [ "$1" == "--no-cache" ]; then
        build_args="$build_args --no-cache"
    fi
    
    log_step "构建镜像..."
    $COMPOSE_CMD build $build_args
    
    log_info "✅ 镜像构建完成"
}

# Docker模式清理
docker_clean() {
    log_title "清理Docker资源"
    
    check_docker
    
    log_step "停止并移除容器..."
    $COMPOSE_CMD down --volumes --remove-orphans
    
    log_step "移除镜像..."
    docker images | grep bjs-etl | awk '{print $3}' | xargs -r docker rmi -f
    
    log_step "清理未使用的资源..."
    docker system prune -f
    
    log_info "✅ 清理完成"
}

# 本地模式启动
local_start() {
    log_title "本地模式启动服务"
    
    check_python
    check_config
    create_directories
    
    # 激活虚拟环境（如果存在）
    if [ -d "venv" ]; then
        log_step "激活Python虚拟环境..."
        source venv/bin/activate
        log_info "虚拟环境已激活"
    fi
    
    # 检查依赖
    log_step "检查Python依赖..."
    if ! $PYTHON_CMD -c "import requests, pymysql, yaml, kafka, schedule" >/dev/null 2>&1; then
        log_warn "正在安装缺失的依赖..."
        pip install -r requirements.txt
    fi
    log_info "依赖检查完成"
    
    # 测试连接
    log_step "测试系统连接..."
    if ! $PYTHON_CMD scripts/scheduler.py --test >/dev/null 2>&1; then
        log_error "系统连接测试失败，请检查配置"
        exit 1
    fi
    log_info "系统连接测试通过"
    
    # 检查是否已有调度器在运行
    if pgrep -f "scheduler.py" >/dev/null; then
        log_warn "调度器已在运行中"
        SCHEDULER_PID=$(pgrep -f "scheduler.py")
        log_info "现有进程PID: $SCHEDULER_PID"
        exit 0
    fi
    
    # 启动调度器
    if [ "$1" == "--kafka-only" ]; then
        log_warn "⚠️  Kafka监听器已禁用，将启动T+1全量同步模式"
        log_step "启动T+1全量同步调度器..."
        nohup $PYTHON_CMD scripts/scheduler.py > logs/scheduler.log 2>&1 &
    else
        log_step "启动T+1全量同步调度器..."
        nohup $PYTHON_CMD scripts/scheduler.py > logs/scheduler.log 2>&1 &
    fi
    
    SCHEDULER_PID=$!
    echo $SCHEDULER_PID > logs/scheduler.pid
    
    # 等待服务启动
    sleep 3
    
    if kill -0 $SCHEDULER_PID 2>/dev/null; then
        log_info "✅ 调度器启动成功 (PID: $SCHEDULER_PID)"
    else
        log_error "❌ 调度器启动失败"
        cat logs/scheduler.log
        exit 1
    fi
    
    log_info "========================================"
    log_info "🎉 本地服务启动完成！"
    log_info "🚀 调度器: 运行中 (PID: $SCHEDULER_PID)"
    log_info "🔄 运行模式: T+1全量同步（Kafka已禁用）"
    log_info "⏰ 定时同步: 每天凌晨2点T+1全量同步"
    log_info "📊 查看状态: $0 local status"
    log_info "📋 查看日志: tail -f logs/scheduler.log"
    log_info "========================================"
}

# 本地模式停止
local_stop() {
    log_title "本地模式停止服务"
    
    if [ -f "logs/scheduler.pid" ]; then
        SCHEDULER_PID=$(cat logs/scheduler.pid)
        if kill -0 $SCHEDULER_PID 2>/dev/null; then
            log_step "停止调度器 (PID: $SCHEDULER_PID)..."
            kill $SCHEDULER_PID
            sleep 2
            
            if kill -0 $SCHEDULER_PID 2>/dev/null; then
                log_warn "强制终止调度器..."
                kill -9 $SCHEDULER_PID
            fi
        fi
        rm -f logs/scheduler.pid
    fi
    
    # 停止所有相关进程
    pkill -f "scheduler.py" 2>/dev/null || true
    
    log_info "✅ 本地服务已停止"
}

# 本地模式状态
local_status() {
    log_title "本地服务状态"
    
    echo ""
    echo "进程状态:"
    
    if pgrep -f "scheduler.py" >/dev/null; then
        SCHEDULER_PID=$(pgrep -f "scheduler.py")
        echo -e "${GREEN}✅ 调度器: 运行中${NC} (PID: $SCHEDULER_PID)"
    else
        echo -e "${RED}❌ 调度器: 未运行${NC}"
    fi
    
    echo ""
    echo "最近日志:"
    
    if [ -f "logs/scheduler.log" ]; then
        echo "调度器日志 (最后10行):"
        tail -10 logs/scheduler.log
    fi
}

# 本地模式日志
local_logs() {
    if [ "$1" == "-f" ] || [ "$1" == "--follow" ]; then
        log_info "实时跟踪日志（按 Ctrl+C 退出）..."
        tail -f logs/scheduler.log
    else
        cat logs/scheduler.log
    fi
}

# 本地模式同步
local_sync() {
    log_title "本地模式手动执行数据同步"
    
    check_python
    
    log_step "执行立即同步..."
    $PYTHON_CMD scripts/scheduler.py --sync-now
    
    log_info "✅ 数据同步完成"
}

# 本地模式测试
local_test() {
    log_title "本地模式连接测试"
    
    check_python
    
    $PYTHON_CMD scripts/scheduler.py --test
}

# 本地模式清理
local_clean() {
    log_title "清理本地资源"
    
    local_stop
    
    log_step "清理日志文件..."
    find logs -name "*.log" -mtime +7 -delete 2>/dev/null || true
    
    log_step "清理临时文件..."
    find . -name "*.pyc" -delete 2>/dev/null || true
    find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
    
    log_info "✅ 清理完成"
}

# 主函数
main() {
    local mode="$1"
    local command="$2"
    shift 2 || true
    
    case "$mode" in
        docker)
            case "$command" in
                start) docker_start "$@" ;;
                stop) docker_stop ;;
                restart) docker_stop && sleep 2 && docker_start "$@" ;;
                status) docker_status ;;
                logs) docker_logs "$@" ;;
                sync) docker_sync ;;
                test) check_docker && docker exec $($COMPOSE_CMD ps -q bjs-etl) python scripts/scheduler.py --test ;;
                build) docker_build "$@" ;;
                clean) docker_clean ;;
                *) log_error "未知的Docker命令: $command"; show_help; exit 1 ;;
            esac
            ;;
        local)
            case "$command" in
                start) local_start "$@" ;;
                stop) local_stop ;;
                restart) local_stop && sleep 2 && local_start "$@" ;;
                status) local_status ;;
                logs) local_logs "$@" ;;
                sync) local_sync ;;
                test) local_test ;;
                clean) local_clean ;;
                *) log_error "未知的本地命令: $command"; show_help; exit 1 ;;
            esac
            ;;
        help|-h|--help|"")
            show_help
            ;;
        *)
            log_error "未知的运行模式: $mode"
            show_help
            exit 1
            ;;
    esac
}

# 执行主函数
main "$@"
