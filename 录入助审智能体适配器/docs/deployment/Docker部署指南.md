scp root@101.126.54.157:/tmp/bjs-luruzhushen.tar.bz2 .
autoagents@2023

# 北交所录入助审系统 - Docker部署指南

## 📋 目录

- [在线部署（推荐）](#在线部署推荐)
- [离线部署](#离线部署)
- [配置说明](#配置说明)
- [常见问题](#常见问题)

## 🚀 在线部署（推荐）

适用于可以访问互联网的服务器环境。

### 前置要求

- Docker 20.10+ 
- Docker Compose 2.0+ （可选）
- 8GB+ 内存
- 10GB+ 磁盘空间

### 快速部署

#### 方式1：使用 Docker Compose（推荐）

```bash
# 1. 克隆项目
git clone https://gitee.com/momomomom/bjs_luruzhushen.git
cd bjs_luruzhushen

# 2. 启动服务
docker-compose up -d

# 3. 查看日志
docker-compose logs -f

# 4. 访问服务
# http://localhost:8580/docs
```

#### 方式2：使用 Docker 命令

```bash
# 1. 构建镜像
docker build -t bjs-luruzhushen:latest .

# 2. 运行容器
docker run -d \
  --name bjs-luruzhushen-app \
  -p 8580:8580 \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/data/uploads:/app/data/uploads \
  -v $(pwd)/data/temp:/app/data/temp \
  -e DEBUG=false \
  -e LOG_LEVEL=INFO \
  --restart unless-stopped \
  bjs-luruzhushen:latest

# 3. 查看日志
docker logs -f bjs-luruzhushen-app

# 4. 访问服务
# http://localhost:8580/docs
```

## 📦 离线部署

适用于无法访问互联网的内网服务器环境。

### 步骤1：构建和导出镜像（在有网络的机器上）

#### Linux/Mac环境

```bash
# 1. 进入项目目录
cd bjs_luruzhushen

# 2. 执行构建和导出脚本
chmod +x scripts/docker_build_and_export.sh
./scripts/docker_build_and_export.sh

# 3. 导出文件位置
# docker-export/bjs-luruzhushen-latest.tar.gz
```

#### Windows环境

```powershell
# 1. 进入项目目录
cd bjs_luruzhushen

# 2. 执行PowerShell脚本
.\scripts\docker_build_and_export.ps1

# 3. 导出文件位置
# docker-export\bjs-luruzhushen-latest.zip
```

#### 手动构建和导出

```bash
# 1. 构建镜像
docker build -t bjs-luruzhushen:latest .

nohup docker build -t bjs-luruzhushen:latest . > build.log 2>&1 &

# 1. 先设置环境变量
export DOCKER_BUILDKIT=1

# 2. 后台运行构建
nohup docker build -t bjs-luruzhushen:latest . > build.log 2>&1 &

# 3. 查看进程
ps aux | grep docker

# 4. 实时查看构建日志
tail -f build.log

# 5. 按 Ctrl+C 退出日志查看（不会停止构建）

# 2. 导出镜像
mkdir -p docker-export
docker save -o docker-export/bjs-luruzhushen-latest.tar bjs-luruzhushen:latest

docker save bjs-luruzhushen:latest | bzip2 > bjs-luruzhushen.tar.bz2

# 3. 压缩（可选，减小文件大小）
cd docker-export
tar -czf bjs-luruzhushen-latest.tar.gz bjs-luruzhushen-latest.tar
```

### 步骤2：传输到目标服务器

```bash
# 使用scp传输
scp docker-export/bjs-luruzhushen-latest.tar.gz user@target-server:/path/to/deploy/

# 或使用其他传输方式（U盘、FTP等）
```

### 步骤3：在目标服务器上部署

#### 自动部署（推荐）

```bash
# 1. 解压项目文件
tar -xzf bjs-luruzhushen-latest.tar.gz
cd bjs_luruzhushen

# 2. 将镜像文件移动到当前目录
mv /path/to/bjs-luruzhushen-latest.tar.gz .

# 3. 执行部署脚本
chmod +x scripts/docker_deploy.sh
./scripts/docker_deploy.sh
```

#### 手动部署

```bash
# 1. 解压镜像（如果已压缩）
tar -xzf bjs-luruzhushen-latest.tar.gz

# 2. 加载镜像
docker load -i bjs-luruzhushen-latest.tar

# 3. 创建数据目录
mkdir -p logs data/uploads data/temp

# 4. 运行容器

# 开发环境启动（简化版）
docker run -d \
  --name bjs-luruzhushen-dev \
  -p 7580:8580 \
  -e ENV=dev \
  bjs-luruzhushen:latest

# 生产环境启动（简化版）
# 注意：不设置 MINIO_AUTO_CLEANUP_DAYS 时，默认 7 天后自动清理文件
docker run -d \
  --name bjs-luruzhushen-prod \
  -p 7580:8580 \
  -e ENV=prod \
  bjs-luruzhushen:latest

docker run -d \
  --name bjs-luruzhushen-prod \
  -p 7580:8580 \
  -e ENV=prod \
  -e LOG_LEVEL=DEBUG \
  bjs-luruzhushen:latest 

docker run -d \
  --name bjs-luruzhushen-prod-test \
  -p 7581:8580 \
  -e ENV=prod \
  bjs-luruzhushen:latest

# 生产环境启动（完整配置，推荐）
docker run -d \
  --name bjs-luruzhushen-app \
  -p 8580:8580 \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/data/uploads:/app/data/uploads \
  -v $(pwd)/data/temp:/app/data/temp \
  -e ENV=prod \
  -e HOST=0.0.0.0 \
  -e PORT=8580 \
  -e DEBUG=false \
  -e LOG_LEVEL=INFO \
  -e MINIO_AUTO_CLEANUP_DAYS=7 \
  --restart unless-stopped \
  bjs-luruzhushen:latest

# 5. 检查运行状态
docker ps | grep bjs-luruzhushen
docker logs -f bjs-luruzhushen-app

# 6. 健康检查
curl http://localhost:8580/health
```

## ⚙️ 配置说明

### 环境变量

| 变量名 | 说明 | 默认值 | 可选值 | 必需 |
|--------|------|--------|--------|------|
| `ENV` | **运行环境** | `dev` | `dev`, `prod` | **是** |
| `HOST` | 服务监听地址 | `0.0.0.0` | - | 否 |
| `PORT` | 服务端口 | `8580` | - | 否 |
| `DEBUG` | 调试模式 | `false` | `true`, `false` | 否 |
| `LOG_LEVEL` | 日志级别 | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` | 否 |
| `MINIO_AUTO_CLEANUP_DAYS` | MinIO自动清理天数 | `7` | - | 否 |

**MinIO 自动清理说明**：
- **不设置**：默认 7 天后自动删除高亮图片文件
- **设置为 N**：N 天后自动删除（如 `MINIO_AUTO_CLEANUP_DAYS=3` 表示 3 天）
- **设置为 0**：禁用自动清理（`MINIO_AUTO_CLEANUP_DAYS=0`）

**重要说明**：
- `ENV` 变量决定了所有服务的配置（LLM、Paddle、Tika、MinIO、Gotenberg）
- `dev` 使用开发环境服务地址
- `prod` 使用生产环境服务地址
- 详见 [环境配置说明](environment_config.md)

### 数据持久化

建议挂载以下目录以持久化数据：

| 容器路径 | 说明 | 推荐挂载 |
|----------|------|----------|
| `/app/logs` | 日志文件 | `./logs:/app/logs` |
| `/app/data/uploads` | 上传文件 | `./data/uploads:/app/data/uploads` |
| `/app/data/temp` | 临时文件 | `./data/temp:/app/data/temp` |

### 端口映射

默认映射端口：`8580:8580`

如需修改宿主机端口：
```bash
docker run -p 9000:8580 ...  # 使用9000端口访问
```

### 资源限制

生产环境建议设置资源限制：

```bash
docker run -d \
  --name bjs-luruzhushen-app \
  --memory="2g" \
  --cpus="2" \
  -p 8580:8580 \
  bjs-luruzhushen:latest
```

或在 docker-compose.yml 中：

```yaml
services:
  app:
    # ...
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '1'
          memory: 1G
```

### Docker Compose 完整示例

#### 开发环境 (docker-compose.dev.yml)

```yaml
version: '3.8'

services:
  app:
    image: bjs-luruzhushen:latest
    container_name: bjs-luruzhushen-dev
    ports:
      - "7580:8580"
    environment:
      - ENV=dev
      - HOST=0.0.0.0
      - PORT=8580
      - DEBUG=true
      - LOG_LEVEL=DEBUG
      - MINIO_AUTO_CLEANUP_DAYS=3
    volumes:
      - ./logs:/app/logs
      - ./data/uploads:/app/data/uploads
      - ./data/temp:/app/data/temp
    restart: unless-stopped
```

启动命令：
```bash
docker-compose -f docker-compose.dev.yml up -d
```

#### 生产环境 (docker-compose.prod.yml)

```yaml
version: '3.8'

services:
  app:
    image: bjs-luruzhushen:latest
    container_name: bjs-luruzhushen-prod
    ports:
      - "8580:8580"
    environment:
      - ENV=prod
      - HOST=0.0.0.0
      - PORT=8580
      - DEBUG=false
      - LOG_LEVEL=INFO
      - MINIO_AUTO_CLEANUP_DAYS=7
    volumes:
      - ./logs:/app/logs
      - ./data/uploads:/app/data/uploads
      - ./data/temp:/app/data/temp
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '1'
          memory: 1G
    restart: unless-stopped
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
```

启动命令：
```bash
docker-compose -f docker-compose.prod.yml up -d
```

## 🔧 容器管理

### 查看状态

```bash
# 查看运行中的容器
docker ps

# 查看所有容器（包括停止的）
docker ps -a

# 查看容器详细信息
docker inspect bjs-luruzhushen-app
```

### 查看日志

```bash
# 实时查看日志
docker logs -f bjs-luruzhushen-app

# 查看最近100行日志
docker logs --tail 100 bjs-luruzhushen-app

# 查看指定时间的日志
docker logs --since 30m bjs-luruzhushen-app
```

### 容器操作

```bash
# 停止容器
docker stop bjs-luruzhushen-app

# 启动容器
docker start bjs-luruzhushen-app

# 重启容器
docker restart bjs-luruzhushen-app

# 删除容器
docker rm -f bjs-luruzhushen-app
```

### 进入容器

```bash
# 进入容器Shell
docker exec -it bjs-luruzhushen-app /bin/bash

# 执行单个命令
docker exec bjs-luruzhushen-app ls -la /app
```

## 🔍 健康检查

### 手动检查

```bash
# 检查服务是否响应
curl http://localhost:8580/health

# 预期响应
{
  "status": "healthy",
  "service": "北交所录入助审系统",
  "version": "1.0.0",
  "timestamp": "2025-10-24T10:00:00Z"
}
```

### Docker健康检查

容器已内置健康检查，自动监控服务状态：

```bash
# 查看健康状态
docker ps --format "table {{.Names}}\t{{.Status}}"
```

## 🔄 更新部署

### 在线更新

```bash
# 1. 拉取最新代码
git pull

# 2. 重新构建并启动
docker-compose down
docker-compose up -d --build
```

### 离线更新

```bash
# 1. 停止旧容器
docker stop bjs-luruzhushen-app
docker rm bjs-luruzhushen-app

# 2. 删除旧镜像
docker rmi bjs-luruzhushen:latest

# 3. 加载新镜像
docker load -i bjs-luruzhushen-latest-new.tar

# 4. 启动新容器
docker run -d ...  # 使用相同的启动命令
```

## ❓ 常见问题

### 1. 容器启动失败

**问题**：容器无法启动或立即退出

**解决方案**：
```bash
# 查看容器日志
docker logs bjs-luruzhushen-app

# 检查端口占用
netstat -tulnp | grep 8580

# 检查Docker日志
sudo journalctl -u docker.service
```

### 2. 无法访问服务

**问题**：服务启动但无法访问

**检查项**：
- 防火墙设置：`sudo firewall-cmd --add-port=8580/tcp --permanent`
- 容器网络：`docker network inspect bridge`
- 端口映射：`docker port bjs-luruzhushen-app`

### 3. 内存不足

**问题**：图像处理时内存溢出

**解决方案**：
```bash
# 增加容器内存限制
docker run --memory="4g" ...

# 或修改 docker-compose.yml
deploy:
  resources:
    limits:
      memory: 4G
```

### 4. 日志文件过大

**问题**：日志占用过多磁盘空间

**解决方案**：
```bash
# 配置日志轮转
docker run -d \
  --log-driver json-file \
  --log-opt max-size=10m \
  --log-opt max-file=3 \
  ...
```

### 5. 镜像导入失败

**问题**：docker load 报错

**解决方案**：
```bash
# 检查文件完整性
md5sum bjs-luruzhushen-latest.tar

# 重新解压
tar -xzf bjs-luruzhushen-latest.tar.gz

# 检查磁盘空间
df -h
```

## 📊 性能优化

### 1. 多进程模式

默认启动4个工作进程，可通过修改Dockerfile调整：

```dockerfile
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8580", "--workers", "8"]
```

### 2. 使用Nginx反向代理

```nginx
upstream bjs_backend {
    server localhost:8580;
    server localhost:8581;
    server localhost:8582;
}

server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://bjs_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### 3. 数据库和缓存

如需添加数据库和Redis支持，修改 docker-compose.yml：

```yaml
services:
  app:
    # ...
    depends_on:
      - db
      - redis
    environment:
      - DATABASE_URL=postgresql://user:pass@db:5432/dbname
      - REDIS_URL=redis://redis:6379/0
  
  db:
    image: postgres:15-alpine
    # ...
  
  redis:
    image: redis:7-alpine
    # ...
```

## 📞 技术支持

如遇到问题，请提供以下信息：

```bash
# 系统信息
docker version
docker info

# 容器信息
docker ps -a
docker logs bjs-luruzhushen-app

# 镜像信息
docker images | grep bjs-luruzhushen
```

---

**文档版本**: v1.0.0  
**最后更新**: 2025-10-24

