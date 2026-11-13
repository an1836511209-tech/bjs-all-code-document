# 北交所数据同步程序 - 简化版Docker镜像
FROM python:3.10-slim

LABEL maintainer="dev-team" \
      description="北交所数据ETL系统" \
      version="2.0.0"

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    TZ=Asia/Shanghai

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    # MySQL客户端开发库
    default-libmysqlclient-dev \
    # 编译工具
    gcc \
    g++ \
    pkg-config \
    # 网络工具（调试用）
    curl \
    wget \
    # 时区数据
    tzdata \
    # 清理
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 设置时区
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 创建应用目录
WORKDIR /app

# 创建非root用户
RUN useradd -m -u 1000 etl && \
    mkdir -p /app/logs /app/exports /app/config && \
    chown -R etl:etl /app

# 复制requirements文件并安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip install --no-cache-dir -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 复制应用代码
COPY . .

# 确保脚本有执行权限
RUN chmod +x scripts/*.py && \
    chown -R etl:etl /app

# 创建健康检查脚本
RUN echo '#!/bin/bash' > /app/healthcheck.sh && \
    echo '# 健康检查脚本' >> /app/healthcheck.sh && \
    echo '' >> /app/healthcheck.sh && \
    echo '# 检查调度器进程' >> /app/healthcheck.sh && \
    echo 'if ! pgrep -f "scheduler.py" > /dev/null; then' >> /app/healthcheck.sh && \
    echo '    echo "调度器未运行"' >> /app/healthcheck.sh && \
    echo '    exit 1' >> /app/healthcheck.sh && \
    echo 'fi' >> /app/healthcheck.sh && \
    echo '' >> /app/healthcheck.sh && \
    echo '# 检查数据库连接' >> /app/healthcheck.sh && \
    echo 'if ! python scripts/scheduler.py --test > /dev/null 2>&1; then' >> /app/healthcheck.sh && \
    echo '    echo "数据库连接失败"' >> /app/healthcheck.sh && \
    echo '    exit 1' >> /app/healthcheck.sh && \
    echo 'fi' >> /app/healthcheck.sh && \
    echo '' >> /app/healthcheck.sh && \
    echo 'echo "健康检查通过"' >> /app/healthcheck.sh && \
    echo 'exit 0' >> /app/healthcheck.sh

RUN chmod +x /app/healthcheck.sh

# 创建启动脚本
RUN echo '#!/bin/bash' > /app/docker-entrypoint.sh && \
    echo 'set -e' >> /app/docker-entrypoint.sh && \
    echo '' >> /app/docker-entrypoint.sh && \
    echo 'echo "========================================"' >> /app/docker-entrypoint.sh && \
    echo 'echo "北交所数据ETL系统启动"' >> /app/docker-entrypoint.sh && \
    echo 'echo "========================================"' >> /app/docker-entrypoint.sh && \
    echo '' >> /app/docker-entrypoint.sh && \
    echo '# 检查配置文件' >> /app/docker-entrypoint.sh && \
    echo 'if [ ! -f "/app/config/config.yaml" ]; then' >> /app/docker-entrypoint.sh && \
    echo '    echo "错误: 配置文件不存在"' >> /app/docker-entrypoint.sh && \
    echo '    exit 1' >> /app/docker-entrypoint.sh && \
    echo 'fi' >> /app/docker-entrypoint.sh && \
    echo '' >> /app/docker-entrypoint.sh && \
    echo '# 创建必要目录' >> /app/docker-entrypoint.sh && \
    echo 'mkdir -p /app/logs /app/exports' >> /app/docker-entrypoint.sh && \
    echo '' >> /app/docker-entrypoint.sh && \
    echo '# 设置文件权限' >> /app/docker-entrypoint.sh && \
    echo 'chown -R etl:etl /app/logs /app/exports' >> /app/docker-entrypoint.sh && \
    echo '' >> /app/docker-entrypoint.sh && \
    echo 'echo "配置文件检查通过，启动调度器..."' >> /app/docker-entrypoint.sh && \
    echo '' >> /app/docker-entrypoint.sh && \
    echo '# 切换到etl用户并启动调度器' >> /app/docker-entrypoint.sh && \
    echo 'exec su etl -c "python scripts/scheduler.py"' >> /app/docker-entrypoint.sh

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
