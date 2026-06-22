"""
Agentic RAG 知识库插件 —— 基于 Milvus Lite + BGE-M3 + BM25 的本地知识库。

功能：
- 启动时初始化 Milvus 知识库控制器
- 注册 ask_knowledge_base 工具，内部运行完整 7 步 RAG 流程
- LLM 请求前注入知识库状态上下文
- 前端面板显示知识库信息

依赖：
  pip install pymilvus[model] sentence-transformers rank-bm25 jieba pypdf
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, List

from plugin_base import PluginBase
from log_config import get_logger

logger = get_logger("virtumate.agentic_rag")

# ═══════════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════════
DEFAULT_MILVUS_URI = "./plugins_data/agentic_rag/kb.db"
DEFAULT_COLLECTION = "kb_chunks"
DEFAULT_BM25_CACHE = "./plugins_data/agentic_rag/bm25_cache.pkl"
DEFAULT_KB_ID = 0

# Rerank 配置
RERANK_MIN_SCORE = 0.005
RERANK_K = 60  # RRF 常数


# ═══════════════════════════════════════════════════════════════════
# Agentic RAG 工具函数（7 步流程）
# ═══════════════════════════════════════════════════════════════════

def _rrf_fusion(semantic_results: list, keyword_results: list, top_n: int = 5) -> list:
    """RRF 融合排序。"""
    K = RERANK_K
    chunk_scores: Dict[str, float] = {}
    chunk_data: Dict[str, dict] = {}

    for rank, chunk in enumerate(semantic_results, 1):
        key = f"{chunk.get('fileId', '?')}_{chunk.get('chunkIndex', '?')}"
        chunk_scores[key] = chunk_scores.get(key, 0) + 1.0 / (K + rank)
        if key not in chunk_data:
            chunk_data[key] = chunk

    for rank, chunk in enumerate(keyword_results, 1):
        key = f"{chunk.get('fileId', '?')}_{chunk.get('chunkIndex', '?')}"
        chunk_scores[key] = chunk_scores.get(key, 0) + 1.0 / (K + rank)
        if key not in chunk_data:
            chunk_data[key] = chunk

    ranked = []
    for key, score in chunk_scores.items():
        if score < RERANK_MIN_SCORE:
            continue
        chunk = chunk_data[key]
        ranked.append({
            "fileId": chunk.get("fileId", "?"),
            "chunkIndex": chunk.get("chunkIndex", "?"),
            "content": chunk.get("content", ""),
            "combined_score": round(score, 4),
        })

    ranked.sort(key=lambda x: x["combined_score"], reverse=True)
    return ranked[:top_n]


def _run_agentic_rag(kb, kb_id: int, question: str) -> str:
    """运行完整 7 步 Agentic RAG 流程。"""
    try:
        import json as _json

        # ── Step 1: 查询改写（简化：直接用原始问题） ──
        logger.info("[RAG] Step 1: 查询分析 - '%s'", question[:50])

        # ── Step 2: 双通道检索 ──
        logger.info("[RAG] Step 2: 双通道检索")
        sem_result = kb.search(kb_id, question, top_k=10)
        kw_result = kb.keyword_search(kb_id, question, top_k=10)

        sem_chunks = _json.loads(sem_result) if sem_result else []
        kw_chunks = _json.loads(kw_result) if kw_result else []
        logger.info("[RAG]   语义: %d 结果, 关键词: %d 结果", len(sem_chunks), len(kw_chunks))

        # ── Step 3: RRF 融合 ──
        logger.info("[RAG] Step 3: RRF 融合排序")
        ranked = _rrf_fusion(sem_chunks, kw_chunks, top_n=5)
        logger.info("[RAG]   融合后保留 %d 个 chunk", len(ranked))

        if not ranked:
            return "知识库中未找到相关信息。请尝试换一种表述或提供更多细节。"

        # ── Step 4: 宏观定位（获取摘要） ──
        logger.info("[RAG] Step 4: 宏观定位")
        fids = list(set(c["fileId"] for c in ranked if c["fileId"] != "?"))
        summaries = {}
        for fid in fids:
            try:
                summary = kb.getFileSummary(kb_id, fid)
                if summary:
                    summaries[fid] = summary
            except Exception:
                pass

        # ── Step 5: 精读片段 ──
        logger.info("[RAG] Step 5: 精读片段")
        read_input = [{"fileId": c["fileId"], "chunkIndex": c["chunkIndex"]} for c in ranked[:3]]
        read_result = kb.readFileChunks(kb_id, read_input)
        chunks_read = _json.loads(read_result) if read_result else []
        logger.info("[RAG]   精读 %d 个片段", len(chunks_read))

        # ── Step 6: 自我反思（简化：检查是否有内容） ──
        logger.info("[RAG] Step 6: 自我反思")
        if not chunks_read:
            return "知识库中未找到相关信息。请尝试换一种表述。"

        # ── Step 7: 生成回答 ──
        logger.info("[RAG] Step 7: 生成回答")

        # 构建上下文
        context_parts = []
        for chunk in chunks_read:
            fid = chunk.get("fileId", "?")
            ci = chunk.get("chunkIndex", "?")
            content = chunk.get("content", "")
            context_parts.append(f"[文件{fid}-片段{ci}]\n{content}")

        context = "\n\n---\n\n".join(context_parts)

        # 构建引用
        refs = []
        for chunk in chunks_read:
            refs.append(f"fileId={chunk.get('fileId')}, chunkIndex={chunk.get('chunkIndex')}")

        answer = (
            f"根据知识库内容，以下是相关信息：\n\n"
            f"{context}\n\n"
            f"---\n"
            f"引用：{'; '.join(refs)}"
        )

        logger.info("[RAG] 流程完成，返回 %d 字符", len(answer))
        return answer

    except Exception as e:
        logger.error("[RAG] 执行失败: %s", e)
        return f"知识库查询失败: {e}"


# ═══════════════════════════════════════════════════════════════════
# 插件主类
# ═══════════════════════════════════════════════════════════════════

class AgenticRAGPlugin(PluginBase):
    """Agentic RAG 知识库插件。

    通过 Hook 机制实现：
    - on_startup: 初始化 Milvus 知识库控制器
    - on_register_tools: 注册 ask_knowledge_base 工具
    - on_execute_tool: 运行完整 7 步 RAG 流程
    - on_llm_context: 注入知识库状态
    - on_shutdown: 关闭连接
    """

    name = "agentic_rag"
    version = "1.0"

    def __init__(self) -> None:
        super().__init__()
        self._kb = None
        self._kb_id = DEFAULT_KB_ID
        self._file_count = 0
        self._chunk_count = 0

    # ================================================================
    # Hook 实现
    # ================================================================

    def on_startup(self, app) -> None:
        """初始化 Milvus 知识库控制器。"""
        super().on_startup(app)
        try:
            # 确保数据目录存在
            data_dir = self.get_data_dir()
            milvus_uri = os.path.join(data_dir, "kb.db")
            bm25_cache = os.path.join(data_dir, "bm25_cache.pkl")

            # 将项目根目录加入 sys.path，以便导入 kb_controller
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if project_root not in sys.path:
                sys.path.insert(0, project_root)

            from kb_controller import MilvusLiteKBController

            self._kb = MilvusLiteKBController(
                milvus_uri=milvus_uri,
                collection_name=DEFAULT_COLLECTION,
                bm25_cache_path=bm25_cache,
            )

            # 获取知识库状态
            self._update_stats()

            logger.info(
                "[agentic_rag] 插件就绪 — Milvus 知识库已连接\n"
                "  数据库: %s\n"
                "  文件数: %d | Chunk 数: %d",
                milvus_uri, self._file_count, self._chunk_count,
            )
        except Exception as e:
            logger.error("[agentic_rag] 初始化失败: %s", e)
            self._kb = None

    def on_register_tools(self) -> list[dict]:
        """注册 ask_knowledge_base 工具。"""
        if not self._kb:
            return []

        return [
            {
                "type": "function",
                "function": {
                    "name": "ask_knowledge_base",
                    "description": (
                        "查询本地知识库。当用户问题涉及文档、资料、学校信息、"
                        "产品说明等知识库中可能包含的内容时调用此工具。"
                        "内部会自动进行语义搜索、关键词搜索、结果融合、精读片段等多步处理。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "question": {
                                "type": "string",
                                "description": "用户的问题或查询内容",
                            },
                        },
                        "required": ["question"],
                    },
                },
            },
        ]

    def on_execute_tool(self, tool_name: str, tool_args: dict) -> str:
        """执行 ask_knowledge_base 工具。"""
        if tool_name != "ask_knowledge_base" or not self._kb:
            return ""

        question = tool_args.get("question", "")
        if not question:
            return "请提供查询问题。"

        logger.info("[agentic_rag] 收到查询: '%s'", question[:50])
        return _run_agentic_rag(self._kb, self._kb_id, question)

    def on_llm_context(self, user_input: str) -> str:
        """注入知识库状态信息到 system prompt。"""
        if not self._kb:
            return ""

        # 定期更新统计
        self._update_stats()

        if self._file_count == 0:
            return ""

        return (
            f"【知识库状态】当前知识库中有 {self._file_count} 个文件，"
            f"共 {self._chunk_count} 个文本片段。"
            f"如果用户的问题可能涉及知识库中的内容，请使用 ask_knowledge_base 工具查询。"
        )

    def on_shutdown(self) -> None:
        """关闭 Milvus 连接。"""
        if self._kb:
            try:
                self._kb.close()
                logger.info("[agentic_rag] Milvus 连接已关闭")
            except Exception as e:
                logger.warning("[agentic_rag] 关闭连接失败: %s", e)
            self._kb = None

    def get_frontend_html(self) -> str:
        """返回知识库状态面板。"""
        status = "已连接" if self._kb else "未连接"
        return f"""
        <div style="padding:12px; color:#eee; font-family:system-ui,sans-serif">
            <h3 style="color:#e94560; margin-bottom:12px">📚 知识库 (Agentic RAG)</h3>
            <p style="color:#aaa; font-size:13px">
                状态：{status}<br>
                文件数：{self._file_count}<br>
                片段数：{self._chunk_count}
            </p>
            <p style="color:#aaa; font-size:13px; margin-top:8px">
                工具：<code>ask_knowledge_base</code><br>
                流程：语义搜索 + BM25 → RRF 融合 → 精读 → 回答
            </p>
            <p style="color:#aaa; font-size:12px; margin-top:12px">
                向知识库中放入文档（txt/pdf/md），即可自动索引。
            </p>
        </div>
        """

    # ================================================================
    # 内部方法
    # ================================================================

    def _update_stats(self) -> None:
        """更新知识库统计信息。"""
        if not self._kb:
            return
        try:
            files = self._kb.listFilesPaginated(self._kb_id, page=1, pageSize=10000)
            self._file_count = len(files)
            self._chunk_count = sum(f.get("chunk_count", 0) for f in files)
        except Exception as e:
            logger.debug("[agentic_rag] 更新统计失败: %s", e)
