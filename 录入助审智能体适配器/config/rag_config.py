"""
RAG (检索增强生成) 配置

配置 RAG 检索的参数，包括 Embedding 和 Rerank 服务
开发和生产环境共用相同参数，仅 API 地址不同
"""

from pydantic import BaseModel, Field
from typing import Optional


class EmbeddingConfig(BaseModel):
    """Embedding 服务配置"""
    enabled: bool = Field(default=True, description="是否启用 Embedding")
    base_url: str = Field(default="", description="Embedding API 地址")
    model: str = Field(default="Qwen3-Embedding-0.6B", description="Embedding 模型名称")
    timeout: int = Field(default=30, description="请求超时时间（秒）")
    batch_size: int = Field(default=32, description="批量处理大小")
    max_input_length: int = Field(default=8000, description="单个文本最大输入长度（字符），超过会截断")


class RerankConfig(BaseModel):
    """Rerank 服务配置"""
    enabled: bool = Field(default=True, description="是否启用 Rerank")
    base_url: str = Field(default="", description="Rerank API 地址")
    model: str = Field(default="Qwen3-Reranker-0.6B", description="Rerank 模型名称")
    timeout: int = Field(default=30, description="请求超时时间（秒）")
    top_n: int = Field(default=10, description="Rerank 后返回的最大结果数")
    min_relevance_score: float = Field(default=0.1, description="最小相关性分数阈值")
    max_doc_length: int = Field(default=8000, description="单个文档最大长度（字符），超过会截断")


# ============================================================
# RAG 核心配置（修改这里的值会同时影响 dev 和 prod 环境）
# ============================================================

# 是否启用 RAG
RAG_ENABLED = True

# 触发 RAG 的内容长度阈值（字符数）
RAG_MAX_LENGTH = 40000

# 初步检索返回的候选数量（用于 Embedding 召回）
RAG_TOP_K = 40

# Rerank 后最终选择的切片数
RAG_FINAL_TOP_K = 20

# 命中切片的上下文窗口大小（前后各取多少个切片）
# 设为 0 表示不扩展上下文，只返回精确命中的切片
RAG_WINDOW_SIZE = 0

# 当检索无结果时，取前 N 页作为兜底
RAG_FALLBACK_PAGES = 20

# 当 Embedding 服务不可用时，是否降级使用 BM25
RAG_USE_BM25_FALLBACK = True

# BM25 检索返回的最相关切片数
RAG_BM25_TOP_K = 20

# 最小切片长度（字符），过短的切片会被合并到相邻切片
RAG_CHUNK_MIN_LENGTH = 50

# 最大切片长度（字符），超过会被拆分
RAG_CHUNK_MAX_LENGTH = 2000

# 是否合并跨页表格为一个切片
RAG_MERGE_CROSS_PAGE_TABLES = True

# 是否保留上下文标记（页码、文件名等）用于溯源
RAG_PRESERVE_CONTEXT_MARKERS = True


# ============================================================
# API 地址配置（开发和生产环境不同）
# ============================================================

# 开发环境 API 地址（空字符串表示不可用，会降级到 BM25）
DEV_EMBEDDING_URL = "http://10.224.98.172/v1/embeddings"
DEV_RERANK_URL = "http://10.224.98.172/v1/rerank"

# 生产环境 API 地址
PROD_EMBEDDING_URL = "http://10.224.98.172/v1/embeddings"
PROD_RERANK_URL = "http://10.224.98.172/v1/rerank"


class RAGConfig(BaseModel):
    """RAG 配置（自动从上方常量读取）"""
    
    enabled: bool = Field(default=RAG_ENABLED, description="是否启用 RAG 功能")
    max_length: int = Field(default=RAG_MAX_LENGTH, description="触发 RAG 的内容长度阈值（字符数）")
    top_k: int = Field(default=RAG_TOP_K, description="初步检索返回的候选数量")
    final_top_k: int = Field(default=RAG_FINAL_TOP_K, description="Rerank 后最终选择的切片数")
    window_size: int = Field(default=RAG_WINDOW_SIZE, description="命中切片的上下文窗口大小")
    fallback_pages: int = Field(default=RAG_FALLBACK_PAGES, description="当检索无结果时的兜底页数")
    use_bm25_fallback: bool = Field(default=RAG_USE_BM25_FALLBACK, description="是否降级使用 BM25")
    bm25_top_k: int = Field(default=RAG_BM25_TOP_K, description="BM25 检索返回的切片数")
    chunk_min_length: int = Field(default=RAG_CHUNK_MIN_LENGTH, description="最小切片长度")
    chunk_max_length: int = Field(default=RAG_CHUNK_MAX_LENGTH, description="最大切片长度")
    merge_cross_page_tables: bool = Field(default=RAG_MERGE_CROSS_PAGE_TABLES, description="是否合并跨页表格")
    preserve_context_markers: bool = Field(default=RAG_PRESERVE_CONTEXT_MARKERS, description="是否保留上下文标记")
    
    # Embedding 和 Rerank 配置
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    rerank: RerankConfig = Field(default_factory=RerankConfig)


def get_rag_config(env: str = None) -> RAGConfig:
    """
    获取 RAG 配置
    
    Args:
        env: 环境名称 ('dev' 或 'prod')，默认从全局配置获取
        
    Returns:
        RAGConfig: RAG 配置对象
    """
    if env is None:
        from config.env_config import get_current_env
        env = get_current_env()
    
    # 根据环境选择 API 地址
    if env == "prod":
        embedding_url = PROD_EMBEDDING_URL
        rerank_url = PROD_RERANK_URL
    else:
        embedding_url = DEV_EMBEDDING_URL
        rerank_url = DEV_RERANK_URL
    
    # 创建配置对象（参数从上方常量读取）
    return RAGConfig(
        embedding=EmbeddingConfig(
            enabled=True,
            base_url=embedding_url,
        ),
        rerank=RerankConfig(
            enabled=False,  # 暂停使用 rerank，使用 embedding 的 topk 逻辑
            base_url=rerank_url,
        )
    )
