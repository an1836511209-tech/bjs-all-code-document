# MinIO 对象存储自动清理指南

本文档说明如何配置和使用MinIO对象存储的自动清理功能，用于自动删除过期的PDF高亮图片。

## 功能概述

PDF高亮图片上传到MinIO后，系统提供两种清理方式：

1. **MinIO生命周期策略**（推荐）- 由MinIO自动管理，无需额外代码
2. **定期清理任务** - 通过脚本或Celery定期执行清理

## 方式一：MinIO生命周期策略（推荐）

### 优点
- ✅ 完全自动化，无需额外的定时任务
- ✅ 由MinIO服务器端管理，性能最优
- ✅ 配置简单，一次设置永久生效
- ✅ 不占用应用服务器资源

### 设置方法

#### 1. 通过命令行设置（推荐）

```bash
# 设置7天后自动删除
python -m src.utils.minio_cleanup --setup 7

# 设置其他天数（例如3天）
python -m src.utils.minio_cleanup --setup 3
```

#### 2. 通过Python代码设置

```python
from src.utils.minio_cleanup import setup_auto_cleanup

# 设置7天后自动删除
setup_auto_cleanup(days=7)
```

#### 3. 在应用启动时自动设置

在 `src/main.py` 的启动事件中添加：

```python
from src.utils.minio_cleanup import MinIOCleanupService

@app.on_event("startup")
async def startup_event():
    """应用启动时的初始化"""
    # 初始化MinIO自动清理策略
    cleanup_service = MinIOCleanupService()
    cleanup_service.setup_auto_cleanup(days=7)
```

### 查看和管理生命周期策略

```bash
# 查看当前配置
python -m src.utils.minio_cleanup --status

# 移除生命周期策略
python -m src.utils.minio_cleanup --remove
```

## 方式二：定期清理任务

### 适用场景
- MinIO服务器不支持生命周期策略
- 需要更精细的控制（例如根据自定义元数据清理）
- 需要清理日志记录

### 手动执行清理

```bash
# 手动清理过期对象
python -m src.utils.minio_cleanup --cleanup
```

### 使用Cron定时执行

添加到crontab：

```bash
# 每天凌晨2点执行清理
0 2 * * * cd /path/to/project && python -m src.utils.minio_cleanup --cleanup >> /var/log/minio_cleanup.log 2>&1
```

### 使用Celery定时任务

在 `src/tasks/scheduled_tasks.py` 中添加：

```python
from celery import Celery
from celery.schedules import crontab
from src.utils.minio_cleanup import manual_cleanup

app = Celery('tasks')

@app.task
def cleanup_expired_minio_objects():
    """清理过期的MinIO对象"""
    manual_cleanup()

# 配置定时任务：每天凌晨2点执行
app.conf.beat_schedule = {
    'cleanup-expired-objects': {
        'task': 'tasks.scheduled_tasks.cleanup_expired_minio_objects',
        'schedule': crontab(hour=2, minute=0),
    },
}
```

## 工作原理

### 上传时的处理

当PDF高亮图片上传时：

```python
from src.utils.pdf_highlighter import highlight_pdf_page

# 上传图片并设置7天后过期
url = highlight_pdf_page(
    pdf_path="document.pdf",
    page_num=0,
    regions=[[100, 100, 300, 200]]
)
```

系统会自动：
1. 在对象元数据中添加 `expires-at` 字段（ISO格式的过期时间）
2. 在对象元数据中添加 `upload-time` 字段（上传时间）

### 清理机制

#### 生命周期策略（方式一）
- MinIO每天检查所有对象
- 自动删除创建时间超过指定天数的对象
- 只对 `highlights/*` 路径下的对象生效

#### 手动清理（方式二）
- 遍历所有对象，读取元数据
- 检查 `expires-at` 字段
- 删除已过期的对象

## 配置参数

在 `config/minio_config.py` 中可以配置：

```python
class MinIOConfig(BaseSettings):
    # 存储桶名称
    bucket_name: str = "pdf-highlights"
    
    # 文件路径前缀（生命周期策略只对此路径生效）
    file_prefix: str = "highlights"
    
    # MinIO服务器地址
    endpoint: str = "115.190.11.152:9000"
    
    # ... 其他配置
```

## 最佳实践

### 推荐配置

1. **使用MinIO生命周期策略**（方式一）
   - 设置7天自动删除
   - 在应用启动时自动配置
   - 定期检查配置状态

2. **日志监控**
   - 定期查看MinIO日志
   - 监控存储空间使用情况

3. **备份策略**
   - PDF高亮图片为临时文件，通常不需要备份
   - 如需备份，建议在过期前导出

### 性能优化

- 生命周期策略的清理是增量的，不会影响服务性能
- 手动清理在对象数量较多时可能需要较长时间
- 建议在业务低峰期执行手动清理

## 故障排查

### 问题：生命周期策略未生效

**可能原因：**
1. MinIO版本过低，不支持生命周期策略
2. 权限不足，无法设置生命周期策略
3. 配置错误

**解决方案：**
```bash
# 检查MinIO版本
mc version

# 验证配置
python -m src.utils.minio_cleanup --status

# 重新设置
python -m src.utils.minio_cleanup --setup 7
```

### 问题：手动清理失败

**可能原因：**
1. MinIO连接失败
2. 权限不足
3. 对象元数据格式错误

**解决方案：**
```bash
# 查看详细日志
python -m src.utils.minio_cleanup --cleanup

# 检查MinIO连接
python -c "from src.utils.minio_client import get_minio_client; client = get_minio_client(); print('连接成功')"
```

## API 文档

### MinIOClient 方法

```python
from src.utils.minio_client import get_minio_client

client = get_minio_client()

# 上传文件并设置过期时间
url = client.upload_bytes(
    data=image_bytes,
    content_type='image/png',
    expires_days=7  # 7天后过期
)

# 设置生命周期策略
client.set_bucket_lifecycle(days=7, prefix="highlights")

# 获取生命周期配置
lifecycle = client.get_bucket_lifecycle()

# 删除生命周期策略
client.delete_bucket_lifecycle()

# 手动清理过期对象
deleted = client.cleanup_expired_objects()

# 获取对象元数据
metadata = client.get_object_metadata(object_name)
```

### MinIOCleanupService 方法

```python
from src.utils.minio_cleanup import MinIOCleanupService

service = MinIOCleanupService()

# 设置自动清理
service.setup_auto_cleanup(days=7)

# 手动清理
deleted_count = service.manual_cleanup()

# 查看状态
status = service.get_lifecycle_status()

# 移除策略
service.remove_lifecycle()
```

## 环境变量配置

在 `.env` 文件中可以配置：

```env
# MinIO配置
MINIO_ENDPOINT=115.190.11.152:9000
MINIO_ACCESS_KEY=your_access_key
MINIO_SECRET_KEY=your_secret_key
MINIO_BUCKET=pdf-highlights
MINIO_FILE_PREFIX=highlights
MINIO_PUBLIC_URL=http://115.190.11.152:9000
```

## 总结

建议使用**MinIO生命周期策略**（方式一）：
- 在应用启动时自动设置
- 无需额外的定时任务
- 性能最优，维护成本最低

如果MinIO不支持生命周期策略，则使用**定期清理任务**（方式二）：
- 配置Celery或Cron定时任务
- 每天执行一次清理
- 注意监控清理日志

