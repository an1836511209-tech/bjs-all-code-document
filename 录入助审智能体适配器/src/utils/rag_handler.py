"""
RAG (检索增强生成) 处理类

用于处理超长文档，通过检索相关切片来减少输入上下文

支持两种检索模式：
1. Embedding + Rerank（推荐，更精准）
2. BM25（降级方案，当 Embedding 服务不可用时使用）
"""

import json
import logging
import asyncio
import httpx
from typing import List, Dict, Any, Set, Tuple, Optional
from dataclasses import dataclass, field

from config.rag_config import get_rag_config, RAGConfig

# 尝试导入 BM25 依赖（作为降级方案）
try:
    import jieba
    from rank_bm25 import BM25Okapi
    HAS_BM25_DEPS = True
except ImportError:
    HAS_BM25_DEPS = False

logger = logging.getLogger(__name__)


@dataclass
class Chunk:
    """文档切片"""
    chunk_id: str                    # 切片唯一标识
    text: str                        # 切片文本内容
    page_idx: int                    # 所在页码（全局）
    file_idx: int                    # 所在文件索引
    block_indices: List[int]         # 包含的 layout_block 索引
    chunk_type: str = "text"         # 切片类型：text, table, seal
    bbox: Optional[List[float]] = None  # 切片的边界框（用于溯源）
    is_cross_page: bool = False      # 是否跨页
    cross_page_range: Optional[Tuple[int, int]] = None  # 跨页范围 (start_page, end_page)
    metadata: Dict[str, Any] = field(default_factory=dict)  # 额外元数据


@dataclass
class RetrievalResult:
    """检索结果"""
    chunk: Chunk
    score: float
    rank: int


class EmbeddingClient:
    """Embedding 服务客户端"""
    
    def __init__(self, config: 'RAGConfig'):
        self.config = config.embedding
        self.enabled = config.embedding.enabled and bool(config.embedding.base_url)
        
    async def get_embeddings(self, texts: List[str]) -> Optional[List[List[float]]]:
        """
        获取文本的 Embedding 向量
        
        Args:
            texts: 文本列表
            
        Returns:
            Embedding 向量列表，失败返回 None
        """
        if not self.enabled:
            return None
            
        try:
            # 截断过长的文本
            truncated_texts = [
                text[:self.config.max_input_length] if len(text) > self.config.max_input_length else text
                for text in texts
            ]
            
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.post(
                    self.config.base_url,
                    json={
                        "model": self.config.model,
                        "input": truncated_texts
                    }
                )
                response.raise_for_status()
                result = response.json()
                
                # 解析响应
                embeddings = []
                for item in result.get("data", []):
                    embeddings.append(item.get("embedding", []))
                
                return embeddings if len(embeddings) == len(texts) else None
                
        except Exception as e:
            logger.warning(f"Embedding 服务调用失败: {e}")
            return None
    
    async def get_embedding(self, text: str) -> Optional[List[float]]:
        """获取单个文本的 Embedding"""
        result = await self.get_embeddings([text])
        return result[0] if result else None


class RerankClient:
    """Rerank 服务客户端"""
    
    def __init__(self, config: 'RAGConfig'):
        self.config = config.rerank
        self.enabled = config.rerank.enabled and bool(config.rerank.base_url)
        
    async def rerank(
        self, 
        query: str, 
        documents: List[str],
        top_n: Optional[int] = None
    ) -> Optional[List[Dict[str, Any]]]:
        """
        对文档进行重排序
        
        Args:
            query: 查询文本
            documents: 文档列表
            top_n: 返回的最大结果数
            
        Returns:
            重排序结果列表，按相关性降序排列
        """
        if not self.enabled:
            return None
            
        try:
            # 截断过长的文档
            truncated_docs = [
                doc[:self.config.max_doc_length] if len(doc) > self.config.max_doc_length else doc
                for doc in documents
            ]
            
            async with httpx.AsyncClient(timeout=self.config.timeout) as client:
                response = await client.post(
                    self.config.base_url,
                    json={
                        "model": self.config.model,
                        "query": query,
                        "documents": truncated_docs
                    }
                )
                response.raise_for_status()
                result = response.json()
                
                # 解析响应
                results = result.get("results", [])
                
                # 过滤低分结果
                filtered_results = [
                    r for r in results 
                    if r.get("relevance_score", 0) >= self.config.min_relevance_score
                ]
                
                # 限制返回数量
                top_n = top_n or self.config.top_n
                return filtered_results[:top_n]
                
        except Exception as e:
            logger.warning(f"Rerank 服务调用失败: {e}")
            return None


class RagHandler:
    """
    RAG (检索增强生成) 处理类
    
    用于处理超长文档，通过检索相关切片来减少输入上下文
    
    检索流程：
    1. 文档切片（考虑表格跨页、上下文完整性）
    2. Embedding 召回（或 BM25 降级）
    3. Rerank 精排
    4. 上下文窗口扩展
    5. 生成输出
    """
    
    def __init__(self, config: Optional[RAGConfig] = None):
        """
        初始化 RAG 处理器
        
        Args:
            config: RAG 配置对象，如果不提供则从配置文件读取
        """
        self.config = config or get_rag_config()
        
        # 初始化客户端
        self.embedding_client = EmbeddingClient(self.config)
        self.rerank_client = RerankClient(self.config)
        
        # 兼容旧接口
        self.max_length = self.config.max_length
        
        if not HAS_BM25_DEPS and not self.embedding_client.enabled:
            logger.warning(
                "RAG 功能受限：Embedding 服务未配置，且缺少 BM25 依赖 (jieba, rank_bm25)。"
                "请配置 Embedding 服务或运行 `pip install jieba rank_bm25` 安装 BM25 依赖。"
            )
            
    @staticmethod
    def _safe_get(obj: Any, key: str, default: Any = None) -> Any:
        """安全获取对象属性或字典值"""
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    def should_use_rag(self, content_length: int) -> bool:
        """判断是否需要使用 RAG"""
        if not self.config.enabled:
            return False
        if not self.embedding_client.enabled and not HAS_BM25_DEPS:
            return False
        return content_length > self.max_length
    
    async def get_relevant_content(
        self, 
        parse_results: List[Any], 
        query: str,
        top_k: Optional[int] = None
    ) -> Tuple[str, str]:
        """
        获取相关的文档内容（Markdown 和 Middle JSON）
        """
        if not parse_results:
            logger.warning("get_relevant_content: parse_results 为空")
            return "", "[]"
            
        # 调试日志：检查输入数据结构
        try:
            if isinstance(parse_results, list) and len(parse_results) > 0:
                first_item = parse_results[0]
                logger.info(f"RAG 输入 parse_results: 长度={len(parse_results)}, 首元素类型={type(first_item)}")
                if isinstance(first_item, dict):
                    logger.info(f"首元素 keys: {list(first_item.keys())}")
                    if 'pages' in first_item:
                        pages = first_item['pages']
                        logger.info(f"首元素 pages 类型: {type(pages)}, 长度={len(pages) if isinstance(pages, list) else 'N/A'}")
                else:
                    logger.info(f"首元素 dir: {[d for d in dir(first_item) if not d.startswith('_')][:10]}...")
        except Exception as e:
            logger.error(f"打印调试日志失败: {e}")
        
        final_top_k = top_k or self.config.final_top_k
        
        # 1. 文档切片
        chunks = self._create_chunks(parse_results)
        if not chunks:
            return "", "[]"
        
        logger.info(f"RAG 切片完成: {len(chunks)} 个切片")
        
        # 2. 检索
        retrieval_results = await self._retrieve(chunks, query)
        
        if not retrieval_results:
            # 兜底：返回前 N 页
            logger.warning(f"RAG 检索无结果，使用前 {self.config.fallback_pages} 页兜底")
            return self._generate_fallback_output(parse_results)
        
        logger.info(f"RAG 检索返回 {len(retrieval_results)} 个结果，配置 final_top_k={final_top_k}, window_size={self.config.window_size}")
        
        # 3. 扩展上下文窗口（window_size=0 时不扩展，只返回命中的切片）
        selected_chunks = self._expand_context(chunks, retrieval_results, final_top_k)
        
        logger.info(f"RAG 最终选择 {len(selected_chunks)}/{len(chunks)} 个切片（检索 {len(retrieval_results)} -> 扩展后 {len(selected_chunks)}）")
        
        # 4. 生成输出
        md_output, middle_json = self._generate_outputs(selected_chunks, parse_results)
        logger.info(f"RAG 输出 markdown 长度: {len(md_output)} 字符")
        
        # 5. 兜底机制：如果输出超过阈值，逐步减少切片数量
        if len(md_output) > self.config.max_length:
            logger.warning(f"RAG 输出超过阈值 ({len(md_output)} > {self.config.max_length})，启动兜底机制逐步减少切片")
            # 从后往前逐步减少切片，直到低于阈值
            for i in range(len(selected_chunks) - 1, 0, -1):
                reduced_chunks = selected_chunks[:i]
                logger.debug(f"尝试减少到 {i} 个切片")
                
                md_output, middle_json = self._generate_outputs(reduced_chunks, parse_results)
                
                if len(md_output) <= self.config.max_length:
                    logger.info(f"兜底成功：减少到 {i} 个切片后，长度: {len(md_output)} 字符")
                    break
            else:
                # 即使只保留 1 个切片仍然超过阈值，直接截断
                logger.warning(f"无法通过减少切片降低长度，直接截断到 {self.config.max_length} 字符")
                md_output = md_output[:self.config.max_length]
                middle_json = "[]"  # 截断后 middle_json 可能不准确，清空
        
        return md_output, middle_json
    
    def _create_chunks(self, parse_results: List[Any]) -> List[Chunk]:
        """
        创建文档切片
        
        切片策略：
        1. 以 layout_block 为基本单位
        2. 合并过短的相邻块
        3. 拆分过长的块
        4. 特殊处理表格（保持完整，处理跨页）
        5. 保留印章等特殊内容
        """
        chunks = []
        global_page_idx = 0
        chunk_id = 0
        
        # 先检测跨页表格
        cross_page_tables = self._detect_cross_page_tables(parse_results) if self.config.merge_cross_page_tables else {}
        
        for file_idx, result in enumerate(parse_results):
            pages = self._safe_get(result, 'pages')
            if not pages:
                logger.warning(f"_create_chunks: 文件 {file_idx} 没有 pages 属性或为空")
                continue
            
            logger.debug(f"_create_chunks: 处理文件 {file_idx}, 共 {len(pages) if isinstance(pages, list) else 0} 页")
            
            file_start_page = global_page_idx
            pending_text = ""
            pending_blocks = []
            pending_page_idx = global_page_idx
            
            for page in pages:
                page_num = self._safe_get(page, 'page_num', 0)
                current_page_idx = file_start_page + page_num
                
                # 检查是否是跨页表格的一部分
                if current_page_idx in cross_page_tables:
                    table_info = cross_page_tables[current_page_idx]
                    if table_info['is_continuation']:
                        # 跳过续页，已在首页处理
                        continue
                
                layout_blocks = self._safe_get(page, 'layout_blocks', [])
                
                for block_idx, block in enumerate(layout_blocks):
                    category_type = self._safe_get(block, 'category_type', 'text')
                    block_text = self._extract_block_text(block)
                    bbox = self._extract_bbox(block)
                    
                    # 处理表格
                    if category_type == 'table':
                        # 先保存之前累积的文本
                        if pending_text.strip():
                            chunks.append(Chunk(
                                chunk_id=f"chunk_{chunk_id}",
                                text=pending_text.strip(),
                                page_idx=pending_page_idx,
                                file_idx=file_idx,
                                block_indices=pending_blocks.copy(),
                                chunk_type="text",
                                bbox=None
                            ))
                            chunk_id += 1
                            pending_text = ""
                            pending_blocks = []
                        
                        # 检查是否是跨页表格的首页
                        if current_page_idx in cross_page_tables and not cross_page_tables[current_page_idx]['is_continuation']:
                            # 合并跨页表格
                            merged_text, end_page = self._merge_cross_page_table(
                                parse_results, file_idx, current_page_idx, cross_page_tables
                            )
                            chunks.append(Chunk(
                                chunk_id=f"chunk_{chunk_id}",
                                text=merged_text,
                                page_idx=current_page_idx,
                                file_idx=file_idx,
                                block_indices=[block_idx],
                                chunk_type="table",
                                bbox=bbox,
                                is_cross_page=True,
                                cross_page_range=(current_page_idx, end_page)
                            ))
                        else:
                            # 普通表格
                            chunks.append(Chunk(
                                chunk_id=f"chunk_{chunk_id}",
                                text=block_text,
                                page_idx=current_page_idx,
                                file_idx=file_idx,
                                block_indices=[block_idx],
                                chunk_type="table",
                                bbox=bbox
                            ))
                        chunk_id += 1
                        continue
                    
                    # 处理印章
                    if category_type == 'seal':
                        # 先保存之前累积的文本
                        if pending_text.strip():
                            chunks.append(Chunk(
                                chunk_id=f"chunk_{chunk_id}",
                                text=pending_text.strip(),
                                page_idx=pending_page_idx,
                                file_idx=file_idx,
                                block_indices=pending_blocks.copy(),
                                chunk_type="text",
                                bbox=None
                            ))
                            chunk_id += 1
                            pending_text = ""
                            pending_blocks = []
                        
                        # 印章单独成块
                        chunks.append(Chunk(
                            chunk_id=f"chunk_{chunk_id}",
                            text=f"[印章: {block_text}]",
                            page_idx=current_page_idx,
                            file_idx=file_idx,
                            block_indices=[block_idx],
                            chunk_type="seal",
                            bbox=bbox
                        ))
                        chunk_id += 1
                        continue
                    
                    # 普通文本：累积
                    if not block_text.strip():
                        continue
                    
                    # 检查是否需要拆分（过长）
                    if len(pending_text) + len(block_text) > self.config.chunk_max_length:
                        # 保存当前累积
                        if pending_text.strip():
                            chunks.append(Chunk(
                                chunk_id=f"chunk_{chunk_id}",
                                text=pending_text.strip(),
                                page_idx=pending_page_idx,
                                file_idx=file_idx,
                                block_indices=pending_blocks.copy(),
                                chunk_type="text",
                                bbox=None
                            ))
                            chunk_id += 1
                        pending_text = block_text + "\n"
                        pending_blocks = [block_idx]
                        pending_page_idx = current_page_idx
                    else:
                        pending_text += block_text + "\n"
                        pending_blocks.append(block_idx)
                        if not pending_blocks:
                            pending_page_idx = current_page_idx
                
                global_page_idx = current_page_idx + 1
            
            # 保存文件末尾的累积文本
            if pending_text.strip() and len(pending_text.strip()) >= self.config.chunk_min_length:
                chunks.append(Chunk(
                    chunk_id=f"chunk_{chunk_id}",
                    text=pending_text.strip(),
                    page_idx=pending_page_idx,
                    file_idx=file_idx,
                    block_indices=pending_blocks.copy(),
                    chunk_type="text",
                    bbox=None
                ))
                chunk_id += 1
            elif pending_text.strip() and chunks:
                # 过短的文本合并到上一个切片
                chunks[-1].text += "\n" + pending_text.strip()
        
        return chunks
    
    def _detect_cross_page_tables(self, parse_results: List[Any]) -> Dict[int, Dict]:
        """
        检测跨页表格
        
        Returns:
            Dict: {page_idx: {'is_continuation': bool, 'start_page': int, 'end_page': int}}
        """
        cross_page_info = {}
        global_page_idx = 0
        
        for file_idx, result in enumerate(parse_results):
            pages = self._safe_get(result, 'pages')
            if not pages:
                continue
            
            file_start_page = global_page_idx
            prev_had_table = False
            table_start_page = None
            
            for page in pages:
                page_num = self._safe_get(page, 'page_num', 0)
                current_page_idx = file_start_page + page_num
                
                layout_blocks = self._safe_get(page, 'layout_blocks', [])
                has_table = any(
                    self._safe_get(block, 'category_type', '') == 'table' 
                    for block in layout_blocks
                )
                
                # 检查是否有跨页标记
                has_continuation = any(
                    self._safe_get(block, 'is_continuation', False) 
                    for block in layout_blocks
                )
                
                if has_table:
                    if has_continuation and prev_had_table:
                        # 这是跨页表格的续页
                        cross_page_info[current_page_idx] = {
                            'is_continuation': True,
                            'start_page': table_start_page,
                            'end_page': current_page_idx
                        }
                        # 更新首页的 end_page
                        if table_start_page in cross_page_info:
                            cross_page_info[table_start_page]['end_page'] = current_page_idx
                    else:
                        # 表格首页
                        table_start_page = current_page_idx
                        cross_page_info[current_page_idx] = {
                            'is_continuation': False,
                            'start_page': current_page_idx,
                            'end_page': current_page_idx
                        }
                    prev_had_table = True
                else:
                    prev_had_table = False
                    table_start_page = None
                
                global_page_idx = current_page_idx + 1
        
        return cross_page_info
    
    def _merge_cross_page_table(
        self, 
        parse_results: List[Any], 
        file_idx: int, 
        start_page: int,
        cross_page_info: Dict
    ) -> Tuple[str, int]:
        """合并跨页表格内容"""
        if start_page not in cross_page_info:
            return "", start_page
        
        info = cross_page_info[start_page]
        end_page = info['end_page']
        
        texts = []
        result = parse_results[file_idx]
        pages = self._safe_get(result, 'pages', [])
        
        for page in pages:
            page_num = self._safe_get(page, 'page_num', 0)
            # 计算全局页码
            global_page = page_num
            for i in range(file_idx):
                prev_pages = self._safe_get(parse_results[i], 'pages')
                if prev_pages:
                    global_page += len(prev_pages)
            
            if global_page < start_page or global_page > end_page:
                continue
            
            layout_blocks = self._safe_get(page, 'layout_blocks', [])
            for block in layout_blocks:
                if self._safe_get(block, 'category_type', '') == 'table':
                    text = self._extract_block_text(block)
                    if text:
                        texts.append(text)
        
        return "\n".join(texts), end_page
    
    async def _retrieve(self, chunks: List[Chunk], query: str) -> List[RetrievalResult]:
        """
        检索相关切片
        
        优先使用 Embedding + Rerank，失败则降级到 BM25
        """
        # 尝试 Embedding + Rerank
        if self.embedding_client.enabled:
            results = await self._retrieve_with_embedding(chunks, query)
            if results:
                return results
            logger.warning("Embedding 检索失败，尝试 BM25 降级")
        
        # BM25 降级
        if self.config.use_bm25_fallback and HAS_BM25_DEPS:
            return self._retrieve_with_bm25(chunks, query)
        
        return []
    
    async def _retrieve_with_embedding(
        self, 
        chunks: List[Chunk], 
        query: str
    ) -> List[RetrievalResult]:
        """使用 Embedding + Rerank 检索"""
        try:
            # 1. 获取 query 和所有 chunk 的 embedding
            texts = [query] + [c.text for c in chunks]
            embeddings = await self.embedding_client.get_embeddings(texts)
            
            if not embeddings or len(embeddings) != len(texts):
                return []
            
            query_embedding = embeddings[0]
            chunk_embeddings = embeddings[1:]
            
            # 2. 计算余弦相似度
            similarities = []
            for i, chunk_emb in enumerate(chunk_embeddings):
                sim = self._cosine_similarity(query_embedding, chunk_emb)
                similarities.append((i, sim))
            
            # 3. 取 Top K 候选
            similarities.sort(key=lambda x: x[1], reverse=True)
            top_k_indices = [idx for idx, _ in similarities[:self.config.top_k]]
            
            # 4. Rerank
            if self.rerank_client.enabled:
                candidate_texts = [chunks[i].text for i in top_k_indices]
                logger.info(f"Rerank 输入: {len(candidate_texts)} 个候选，期望返回 top_n={self.config.final_top_k}")
                
                rerank_results = await self.rerank_client.rerank(
                    query, 
                    candidate_texts,
                    top_n=self.config.final_top_k  # 传入 final_top_k 作为 top_n
                )
                
                if rerank_results:
                    results = []
                    for rank, r in enumerate(rerank_results):
                        original_idx = top_k_indices[r['index']]
                        results.append(RetrievalResult(
                            chunk=chunks[original_idx],
                            score=r['relevance_score'],
                            rank=rank
                        ))
                    logger.info(f"Rerank 成功，返回 {len(results)} 个结果（期望 {self.config.final_top_k}）")
                    return results
                else:
                    # Rerank 失败，降级使用 Embedding 相似度
                    logger.warning(f"Rerank 失败，降级使用 Embedding 相似度取前 {self.config.final_top_k} 个结果")
            
            # Rerank 不可用或失败，直接使用 Embedding 相似度（按得分取前 final_top_k 个）
            results = []
            for rank, (idx, score) in enumerate(similarities[:self.config.final_top_k]):
                results.append(RetrievalResult(
                    chunk=chunks[idx],
                    score=score,
                    rank=rank
                ))
            logger.info(f"使用 Embedding 相似度，返回 {len(results)} 个结果（得分: {[f'{r.score:.3f}' for r in results]}）")
            return results
            
        except Exception as e:
            logger.error(f"Embedding 检索异常: {e}", exc_info=True)
            return []
    
    def _retrieve_with_bm25(self, chunks: List[Chunk], query: str) -> List[RetrievalResult]:
        """使用 BM25 检索（降级方案）"""
        try:
            # 分词
            corpus = [list(jieba.cut(c.text)) for c in chunks]
            tokenized_query = list(jieba.cut(query))
            
            # BM25 检索
            bm25 = BM25Okapi(corpus)
            scores = bm25.get_scores(tokenized_query)
            
            # 排序
            indexed_scores = list(enumerate(scores))
            indexed_scores.sort(key=lambda x: x[1], reverse=True)
            
            # 取 Top K
            results = []
            for rank, (idx, score) in enumerate(indexed_scores[:self.config.bm25_top_k]):
                if score > 0:
                    results.append(RetrievalResult(
                        chunk=chunks[idx],
                        score=score,
                        rank=rank
                    ))
            
            return results
            
        except Exception as e:
            logger.error(f"BM25 检索异常: {e}", exc_info=True)
            return []
    
    def _expand_context(
        self, 
        chunks: List[Chunk], 
        results: List[RetrievalResult],
        final_top_k: int
    ) -> List[Chunk]:
        """
        扩展上下文窗口
        
        对命中的 chunk 扩展前后窗口，增加上下文信息。
        限制扩展在同一文件内，避免跨文件混淆。
        
        注意：跨页 chunk 不需要特殊处理，因为 chunks 列表是按文档顺序排列的，
        扩展窗口获取的是文档顺序上的相邻内容，这比页面边界更重要。
        """
        # 预构建索引映射，O(1) 查找
        chunk_id_to_idx = {c.chunk_id: i for i, c in enumerate(chunks)}
        
        selected_indices = set()
        
        # 按分数排序，取 top k
        sorted_results = sorted(results, key=lambda x: x.score, reverse=True)[:final_top_k]
        logger.debug(f"_expand_context: 输入 {len(results)} 个检索结果，取 top {final_top_k}，window_size={self.config.window_size}")
        
        for result in sorted_results:
            chunk_idx = chunk_id_to_idx.get(result.chunk.chunk_id)
            if chunk_idx is None:
                continue
            
            current_file_idx = result.chunk.file_idx
            
            # 扩展窗口，但限制在同一文件内
            start = max(0, chunk_idx - self.config.window_size)
            end = min(len(chunks), chunk_idx + self.config.window_size + 1)
            
            for i in range(start, end):
                # 只扩展同一文件的 chunk
                if chunks[i].file_idx == current_file_idx:
                    selected_indices.add(i)
        
        # 按原始顺序返回
        sorted_indices = sorted(selected_indices)
        return [chunks[i] for i in sorted_indices]
    
    def _generate_outputs(
        self, 
        chunks: List[Chunk], 
        parse_results: List[Any]
    ) -> Tuple[str, str]:
        """生成 Markdown 和 Middle JSON 输出"""
        md_parts = []
        middle_data = []
        
        current_file_idx = -1
        current_page_idx = -1
        
        # 统计涉及的页面数
        unique_pages = set()
        for chunk in chunks:
            unique_pages.add((chunk.file_idx, chunk.page_idx))
        logger.info(f"RAG 选中的 {len(chunks)} 个切片分布在 {len(unique_pages)} 个不同页面")
        
        for chunk in chunks:
            # 添加文件/页面标记（用于溯源）
            if self.config.preserve_context_markers:
                if chunk.file_idx != current_file_idx:
                    file_name = self._safe_get(parse_results[chunk.file_idx], 'file_name', f'文件{chunk.file_idx+1}')
                    md_parts.append(f"\n# === {file_name} ===\n")
                    current_file_idx = chunk.file_idx
                    current_page_idx = -1
                
                if chunk.page_idx != current_page_idx:
                    md_parts.append(f"\n## [Page {chunk.page_idx + 1}]\n")
                    current_page_idx = chunk.page_idx
            
            # 添加切片内容
            if chunk.chunk_type == "table":
                md_parts.append(f"\n[表格]\n{chunk.text}\n[/表格]\n")
            elif chunk.chunk_type == "seal":
                md_parts.append(f"\n{chunk.text}\n")
            else:
                md_parts.append(f"\n{chunk.text}\n")
            
            # 构建 Middle JSON（用于溯源）
            page_data = self._construct_middle_data(chunk, parse_results)
            if page_data:
                middle_data.append(page_data)
        
        return "\n".join(md_parts), json.dumps(middle_data, ensure_ascii=False)
    
    def _generate_fallback_output(self, parse_results: List[Any]) -> Tuple[str, str]:
        """生成兜底输出（前 N 页）"""
        md_parts = []
        middle_data = []
        
        pages_collected = 0
        global_page_idx = 0
        
        for file_idx, result in enumerate(parse_results):
            if pages_collected >= self.config.fallback_pages:
                break
                
            pages = self._safe_get(result, 'pages')
            if not pages:
                logger.warning(f"_generate_fallback_output: 文件 {file_idx} 没有 pages 属性或为空")
                continue
            
            file_name = self._safe_get(result, 'file_name', f'文件{file_idx+1}')
            md_parts.append(f"\n# === {file_name} ===\n")
            
            for page in pages:
                if pages_collected >= self.config.fallback_pages:
                    break
                
                page_num = self._safe_get(page, 'page_num', 0)
                md_parts.append(f"\n## [Page {page_num + 1}]\n")
                
                # 重建页面内容
                page_md = self._reconstruct_page_markdown(page)
                md_parts.append(page_md)
                
                # Middle JSON
                page_data = self._construct_middle_page(page, global_page_idx)
                middle_data.append(page_data)
                
                pages_collected += 1
                global_page_idx += 1
        
        return "\n".join(md_parts), json.dumps(middle_data, ensure_ascii=False)
    
    def _construct_middle_data(self, chunk: Chunk, parse_results: List[Any]) -> Optional[Dict]:
        """为单个切片构建 middle json 数据"""
        try:
            result = parse_results[chunk.file_idx]
            pages = self._safe_get(result, 'pages')
            if not pages:
                return None
            
            # 找到对应的页面
            target_page = None
            for page in pages:
                page_num = self._safe_get(page, 'page_num', 0)
                # 计算全局页码
                global_page = page_num
                for i in range(chunk.file_idx):
                    prev_pages = self._safe_get(parse_results[i], 'pages')
                    if prev_pages:
                        global_page += len(prev_pages)
                
                if global_page == chunk.page_idx:
                    target_page = page
                    break
            
            if not target_page:
                return None
            
            return self._construct_middle_page(target_page, chunk.page_idx)
            
        except Exception as e:
            logger.warning(f"构建 middle data 失败: {e}")
            return None
    
    def _construct_middle_page(self, page: Any, global_page_idx: int) -> Dict:
        """构造单页 middle json 数据"""
        layout_dets = []
        
        layout_blocks = self._safe_get(page, 'layout_blocks')
        if layout_blocks:
            for block in layout_blocks:
                bbox = self._extract_bbox(block)
                
                # 构建 lines
                lines_data = []
                lines = self._safe_get(block, 'lines')
                if lines:
                    for line in lines:
                        line_bbox = [0, 0, 0, 0]
                        lb = self._safe_get(line, 'bbox')
                        if lb:
                            if isinstance(lb, (list, tuple)) and len(lb) == 4:
                                line_bbox = list(lb)
                        
                        spans_data = []
                        spans = self._safe_get(line, 'spans')
                        if spans:
                            for span in spans:
                                span_text = self._safe_get(span, 'text', '')
                                if span_text:
                                    span_bbox = [0, 0, 0, 0]
                                    sb = self._safe_get(span, 'bbox')
                                    if sb:
                                        if isinstance(sb, (list, tuple)) and len(sb) == 4:
                                            span_bbox = list(sb)
                                    
                                    spans_data.append({
                                        "bbox": span_bbox,
                                        "content": span_text,
                                        "type": self._safe_get(span, 'type', 'text')
                                    })
                        
                        if spans_data:
                            lines_data.append({
                                "bbox": line_bbox,
                                "spans": spans_data
                            })
                
                layout_dets.append({
                    "bbox": bbox,
                    "text": self._safe_get(block, 'text', ''),
                    "category_type": self._safe_get(block, 'category_type', 'text'),
                    "lines": lines_data
                })
        
        return {
            "page_idx": global_page_idx,
            "layout_dets": layout_dets
        }
    
    def _reconstruct_page_markdown(self, page: Any) -> str:
        """重建单页 Markdown"""
        lines = []
        contents = self._safe_get(page, 'contents')
        if contents:
            for content in contents:
                text = self._safe_get(content, 'text', '')
                type_ = self._safe_get(content, 'type', 'text')
                
                if not text:
                    continue
                
                if type_ in ['title', 'header']:
                    lines.append(f"### {text}")
                elif type_ == 'list':
                    lines.append(f"- {text}")
                elif type_ == 'table':
                    table_body = self._safe_get(content, 'table_body', '')
                    lines.append(table_body if table_body else text)
                elif type_ == 'seal':
                    lines.append(f"[印章: {text}]")
                else:
                    lines.append(text)
        
        return "\n\n".join(lines)
    
    def _extract_block_text(self, block: Any) -> str:
        """提取 block 的文本内容"""
        # 优先从 lines/spans 提取
        lines = self._safe_get(block, 'lines', [])
        if lines:
            text_parts = []
            for line in lines:
                spans = self._safe_get(line, 'spans', [])
                for span in spans:
                    span_text = self._safe_get(span, 'text', '')
                    if span_text:
                        text_parts.append(span_text)
            if text_parts:
                return ' '.join(text_parts)
        
        # 降级：从 text 属性提取
        return self._safe_get(block, 'text', '') or ''
    
    def _extract_bbox(self, block: Any) -> List[float]:
        """提取 block 的 bbox"""
        bbox = self._safe_get(block, 'bbox')
        
        if bbox is None:
            return [0, 0, 0, 0]
        
        if hasattr(bbox, 'x0'):
            return [bbox.x0, bbox.y0, bbox.x1, bbox.y1]
        
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            return list(bbox[:4])
            
        if isinstance(bbox, dict):
            # 兼容字典格式的 bbox (可能是 {'x0': ..., ...} 或 [x0, y0, x1, y1])
            if 'x0' in bbox:
                return [bbox['x0'], bbox['y0'], bbox['x1'], bbox['y1']]
        
        return [0, 0, 0, 0]
    
    @staticmethod
    def _cosine_similarity(vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        if not vec1 or not vec2 or len(vec1) != len(vec2):
            return 0.0
        
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = sum(a * a for a in vec1) ** 0.5
        norm2 = sum(b * b for b in vec2) ** 0.5
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
