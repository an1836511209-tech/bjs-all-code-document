"""
北交所录入助审系统主应用

FastAPI 主应用入口，提供信息披露智能录入和助审服务
"""

import os
import sys
import argparse
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Request, status, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger
from pydantic import BaseModel, ValidationError

from src.api.v1 import api_router
from src.api.v1.endpoints.rule_config_web import router as rule_config_web_router
from src.core.logging import setup_logging
from config.env_config import set_current_env, get_current_env, is_extraction_cache_enabled, set_extraction_cache_enabled


class HealthResponse(BaseModel):
    """健康检查响应模型"""
    status: str
    service: str
    version: str
    timestamp: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 初始化日志系统
    debug = os.getenv("DEBUG", "false").lower() == "true"
    log_level = os.getenv("LOG_LEVEL")
    
    # 如果没有设置 LOG_LEVEL，根据环境自动判断
    if log_level is None:
        current_env = get_current_env()
        log_level = "DEBUG" if current_env == "dev" else "INFO"
    else:
        log_level = log_level.upper()
    
    setup_logging(debug=debug, log_level=log_level)
    
    # 获取当前环境
    current_env = get_current_env()
    env_name = "开发环境" if current_env == "dev" else "生产环境"
    cache_enabled = is_extraction_cache_enabled()
    
    # 启动时执行
    logger.info("🚀 北交所录入助审系统启动中...")
    logger.info(f"🌍 运行环境: {env_name} ({current_env})")
    logger.info(f"🔧 配置信息: LOG_LEVEL={log_level}, EXTRACTION_CACHE={cache_enabled}")
    
    # 初始化HTTP客户端单例
    try:
        from src.services.paddle.client import get_paddle_client
        from src.services.mineru.client import get_mineru_client
        from src.services.tika.client import get_tika_client
        from src.services.gotenberg.client import get_gotenberg_client
        
        # 预创建客户端单例
        get_paddle_client(current_env)
        get_mineru_client(current_env)
        get_tika_client(current_env)
        get_gotenberg_client(current_env)
        logger.info("✅ HTTP客户端单例初始化完成")
    except Exception as e:
        logger.warning(f"HTTP客户端初始化失败（系统将继续运行）: {str(e)}")
    
    # 初始化API限流器
    try:
        from src.api.v1.middleware.rate_limiter import init_rate_limiter
        init_rate_limiter()
    except Exception as e:
        logger.warning(f"API限流器初始化失败（系统将继续运行）: {str(e)}")
    
    # 打印服务配置信息
    try:
        from config.llm_config import LLMConfig
        from config.paddle_config import get_paddle_config
        from config.tika_config import get_tika_config
        from config.minio_config import get_minio_config
        from config.gotenberg_config import get_gotenberg_config
        
        logger.info("📡 服务配置信息:")
        
        # LLM 配置
        extraction_agent = LLMConfig.get_extraction_agent_config()
        logger.info(f"  - LLM服务: {extraction_agent.base_url}")
        
        # Paddle 配置
        paddle_config = get_paddle_config(current_env)
        logger.info(f"  - Paddle OCR: {paddle_config['api']['ocr_vl']['base_url']}")
        
        # Tika 配置
        tika_config = get_tika_config(current_env)
        logger.info(f"  - Tika服务: {tika_config['server_url']}")
        
        # MinIO 配置
        minio_config = get_minio_config(current_env)
        logger.info(f"  - MinIO存储: {minio_config['endpoint']}")
        
        # Gotenberg 配置
        gotenberg_config = get_gotenberg_config(current_env)
        logger.info(f"  - Gotenberg服务: {gotenberg_config['server_url']}")
        
    except Exception as e:
        logger.warning(f"获取服务配置信息失败: {str(e)}")
    
    # 初始化MinIO对象存储
    try:
        from src.utils.minio.init import initialize_minio
        auto_cleanup_days = int(os.getenv("MINIO_AUTO_CLEANUP_DAYS", "7"))
        initialize_minio(auto_cleanup_days=auto_cleanup_days)
    except Exception as e:
        logger.warning(f"MinIO初始化失败（系统将继续运行）: {str(e)}")
    
    # 启动磁盘缓存定期清理任务
    try:
        from src.services.storage.cache_service import get_disk_cache
        disk_cache = get_disk_cache()
        disk_cache.start_cleanup_task()
        logger.info("✅ 磁盘缓存定期清理任务已启动")
    except Exception as e:
        logger.warning(f"磁盘缓存清理任务启动失败（系统将继续运行）: {str(e)}")
    
    # 初始化Redis连接
    try:
        from src.services.redis.client import get_redis_client
        redis_client = get_redis_client()
        logger.info("✅ Redis连接已建立")
    except Exception as e:
        logger.error(f"❌ Redis连接失败: {e}")
        raise
    
    # 启动任务取消订阅器
    try:
        from src.services.redis.task_cancel_subscriber import get_task_cancel_subscriber
        subscriber = get_task_cancel_subscriber()
        await subscriber.start()
        logger.info("✅ 任务取消订阅器已启动")
    except Exception as e:
        logger.warning(f"任务取消订阅器启动失败（系统将继续运行）: {e}")
    
    # 启动任务存储定期清理任务（改为90天）
    try:
        from src.services.task_store import get_task_store
        task_store = get_task_store()
        task_store.start_cleanup_task(interval_days=1, max_age_days=90)
        logger.info("✅ 任务存储定期清理任务已启动（每天清理，保留90天）")
    except Exception as e:
        logger.warning(f"任务存储清理任务启动失败（系统将继续运行）: {str(e)}")
    
    # 预初始化质量检测进程池（可选，首次使用时也会自动初始化）
    try:
        from src.utils.process_pool import ProcessPoolManager
        from config.api_config import QUALITY_CHECK_MAX_WORKERS
        executor = ProcessPoolManager.get_executor()
        logger.info(f"✅ 质量检测进程池已初始化，worker 数量: {ProcessPoolManager.get_max_workers()}")
    except Exception as e:
        logger.warning(f"质量检测进程池初始化失败（首次使用时会自动重试）: {str(e)}")
    
    logger.info("📋 已加载功能模块：")
    logger.info("  - 文件质量检测 ✅")
    logger.info("  - 规则配置管理 ✅")
    logger.info("  - PDF高亮标注 ✅")
    logger.info("  - MinIO对象存储 ✅")
    logger.info("  - 磁盘缓存管理 ✅")
    logger.info("  - Redis分布式存储 ✅")
    logger.info("  - 任务取消通知 ✅")
    logger.info("  - 字段信息提取 ✅")
    logger.info("  - 规则审核 ✅")
    logger.info("✅ 系统启动完成")
    
    yield
    
    # 关闭时执行
    logger.info("👋 北交所录入助审系统正在关闭...")
    
    # 关闭HTTP客户端
    try:
        from src.services.paddle.client import close_paddle_client
        from src.services.mineru.client import close_mineru_client
        from src.services.tika.client import close_tika_client
        from src.services.gotenberg.client import close_gotenberg_client
        from src.services.llm.client import close_all_llm_clients
        
        await close_paddle_client()
        await close_mineru_client()
        await close_tika_client()
        await close_gotenberg_client()
        await close_all_llm_clients()
        logger.info("✅ HTTP客户端已关闭")
    except Exception as e:
        logger.warning(f"关闭HTTP客户端失败: {str(e)}")
    
    # 停止磁盘缓存清理任务
    try:
        from src.services.storage.cache_service import get_disk_cache
        disk_cache = get_disk_cache()
        disk_cache.stop_cleanup_task()
    except Exception as e:
        logger.warning(f"停止磁盘缓存清理任务失败: {str(e)}")
    
    # 停止任务存储清理任务
    try:
        from src.services.task_store import get_task_store
        task_store = get_task_store()
        task_store.stop_cleanup_task()
    except Exception as e:
        logger.warning(f"停止任务存储清理任务失败: {str(e)}")
    
    # 关闭质量检测进程池
    try:
        from src.utils.process_pool import ProcessPoolManager
        if ProcessPoolManager.is_initialized():
            ProcessPoolManager.shutdown(wait=True)
            logger.info("✅ 质量检测进程池已关闭")
    except Exception as e:
        logger.warning(f"关闭质量检测进程池失败: {str(e)}")
    
    logger.info("✅ 系统已安全关闭")


# 创建FastAPI应用实例
app = FastAPI(
    title="北交所录入助审系统API",
    description="""
    北交所信息披露智能录入和助审系统接口文档
    
    ## 主要功能模块
    - 文件质量检测：支持PDF和图片的清晰度、分辨率、遮挡检测
    - 字段信息提取：从多种文档中提取结构化信息
    - 规则审核：基于配置规则进行智能审核
    - 任务管理：长时间运行任务的查询和管理
    - 规则配置管理：提取和审核规则的配置管理
    
    ## 技术特点
    - RESTful API设计
    - 支持SSE流式响应
    - 统一的响应格式
    - 完善的错误处理
    - JWT身份认证（开发中）
    
    ## 当前版本功能
    - ✅ 文件质量检测API
    - ✅ 字段提取API
    - ✅ 规则审核API
    """,
    version="1.0.0",
    contact={
        "name": "API支持团队"
    },
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# CORS中间件配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 生产环境应限制具体域名
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 北交所 API 统一管控平台 — 服务提供方适配（仅 /api/platform 前缀）
# Starlette 后 add_middleware 的中间件更靠外（更靠近客户端）；位于 CORS 外侧以便统一改写纳入范围的响应。
from src.platform_gw.middleware import PlatformGwMiddleware  # noqa: E402

app.add_middleware(PlatformGwMiddleware)

# 挂载静态文件目录（Bootstrap等）
app.mount("/static", StaticFiles(directory="src/templates"), name="static")


# Pydantic验证错误处理器
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """处理请求参数验证错误"""
    logger.warning(f"请求参数验证失败: {str(exc)}")
    
    # 转换Pydantic错误为统一格式
    error_details = []
    for error in exc.errors():
        field_path = " -> ".join(str(loc) for loc in error["loc"][1:])  # 跳过'body'
        error_details.append({
            "field": field_path,
            "message": error["msg"]
        })
    
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "code": 400,
            "message": "Bad Request",
            "error": {
                "error_code": "VALIDATION_ERROR",
                "error_message": "请求参数验证失败",
                "details": error_details
            },
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    )


# HTTPException处理器
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """处理HTTP异常"""
    logger.warning(f"HTTP异常: {exc.status_code} - {str(exc.detail)}")
    
    # 如果detail已经是我们的统一格式，直接使用
    if isinstance(exc.detail, dict) and "error_code" in exc.detail:
        error_info = {
            "error_code": exc.detail.get("error_code", "HTTP_ERROR"),
            "error_message": exc.detail.get("error_message", str(exc.detail))
        }
        if "trace_id" in exc.detail:
            error_info["trace_id"] = exc.detail["trace_id"]
    else:
        # 否则转换为统一格式
        error_info = {
            "error_code": "HTTP_ERROR",
            "error_message": str(exc.detail)
        }
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code,
            "message": "Error" if exc.status_code >= 500 else "Bad Request",
            "error": error_info,
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    )


# 全局异常处理器
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理"""
    logger.error(f"未处理的异常: {str(exc)}", exc_info=True)
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "code": 500,
            "message": "Internal Server Error",
            "error": {
                "error_code": "INTERNAL_ERROR",
                "error_message": "服务器内部错误，请稍后重试"
            },
            "timestamp": datetime.utcnow().isoformat() + "Z"
        }
    )


# 根路径健康检查
@app.get(
    "/",
    response_model=HealthResponse,
    summary="系统健康检查",
    description="检查系统是否正常运行"
)
async def root():
    """根路径健康检查"""
    return HealthResponse(
        status="healthy",
        service="北交所录入助审系统",
        version="1.0.0",
        timestamp=datetime.utcnow().isoformat() + "Z"
    )


@app.get(
    "/health",
    response_model=HealthResponse,
    summary="详细健康检查", 
    description="获取系统健康状态详细信息"
)
async def health_check():
    """详细健康检查"""
    return HealthResponse(
        status="healthy",
        service="北交所录入助审系统",
        version="1.0.0", 
        timestamp=datetime.utcnow().isoformat() + "Z"
    )


# 注册API路由
app.include_router(api_router)
# 注册Web界面路由
app.include_router(rule_config_web_router)

# 注册平台接入路由（复用业务 endpoint，隔离前缀）
from config.platform_gw_config import PLATFORM_GW_ENABLED  # noqa: E402

if PLATFORM_GW_ENABLED:
    from src.platform_gw.router import build_platform_router  # noqa: E402

    app.include_router(build_platform_router())


# 启动配置
if __name__ == "__main__":
    import uvicorn
    
    # 解析命令行参数
    parser = argparse.ArgumentParser(description='北交所录入助审系统')
    parser.add_argument(
        '--env',
        type=str,
        choices=['dev', 'prod'],
        default=os.getenv('ENV', 'dev'),
        help='运行环境 (dev: 开发环境, prod: 生产环境)'
    )
    parser.add_argument(
        '--host',
        type=str,
        default=os.getenv("HOST", "0.0.0.0"),
        help='服务器主机地址'
    )
    parser.add_argument(
        '--port',
        type=int,
        default=int(os.getenv("PORT", "8580")),
        help='服务器端口'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        default=os.getenv("DEBUG", "false").lower() == "true",
        help='是否启用调试模式'
    )
    parser.add_argument(
        '--no-cache',
        action='store_true',
        help='禁用提取结果缓存复用（强制重新计算）'
    )
    
    args = parser.parse_args()
    
    # 设置环境变量（在 lifespan 初始化前设置，这样日志系统才能读取到）
    if args.debug:
        os.environ["DEBUG"] = "true"
        os.environ["LOG_LEVEL"] = "DEBUG"
    
    # 设置环境
    set_current_env(args.env)
    
    # 设置缓存状态（如果传了 --no-cache，则禁用提取缓存）
    set_extraction_cache_enabled(not args.no_cache)
    
    # 显示启动信息
    env_name = "开发环境" if args.env == "dev" else "生产环境"
    cache_status = "禁用" if args.no_cache else "启用"
    debug_status = "DEBUG" if args.debug else "INFO"
    print(f"🌍 运行环境: {env_name} ({args.env})")
    print(f"🔧 日志级别: {debug_status}")
    print(f"💾 提取缓存复用: {cache_status}")
    print(f"🌐 启动服务器: http://{args.host}:{args.port}")
    print(f"📚 API文档: http://{args.host}:{args.port}/docs")
    
    uvicorn.run(
        "src.main:app",
        host=args.host,
        port=args.port,
        reload=args.debug,
        log_level="info" if not args.debug else "debug"
    )
