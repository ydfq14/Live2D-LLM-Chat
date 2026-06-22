"""
Agentic RAG 知识库插件 —— 基于 LangGraph ReAct Agent 的智能知识库检索。

功能：
- 启动时初始化 Milvus 知识库控制器 + 注入 Agent 模块
- 注册 ask_knowledge_base 工具，内部运行真正的 Agentic RAG Agent
- Agent 自主执行 7 步流程：查询改写 → 双通道检索 → RRF 融合 → 精读 → 反思 → 生成答案
- Agent 失败时自动回退到基础检索
- LLM 请求前注入知识库状态上下文
- 前端面板显示知识库和 Agent 信息

依赖：
  pip install pymilvus[model] sentence-transformers rank-bm25 jieba pypdf langchain-core langchain-openai langgraph
"""
from __future__ import annotations

import json
import os
import sys
from typing import Dict

from plugin_base import PluginBase
from log_config import get_logger

logger = get_logger("virtumate.agentic_rag")

# ═══════════════════════════════════════════════════════════════════
# 配置
# ═══════════════════════════════════════════════════════════════════
DEFAULT_COLLECTION = "kb_chunks"
DEFAULT_KB_ID = 0

# 回退用 RRF 配置
RERANK_MIN_SCORE = 0.005
RERANK_K = 60


# ═══════════════════════════════════════════════════════════════════
# 回退用基础 RAG 函数（Agent 失败时使用）
# ═══════════════════════════════════════════════════════════════════

def _rrf_fusion(semantic_results: list, keyword_results: list, top_n: int = 5) -> list:
    """RRF 融合排序（回退用）。"""
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


def _run_agentic_rag_basic(kb, kb_id: int, question: str) -> str:
    """基础 RAG 流程（无 LLM），Agent 失败时的回退方案。"""
    try:
        # 双通道检索
        sem_result = kb.search(kb_id, question, top_k=10)
        kw_result = kb.keyword_search(kb_id, question, top_k=10)

        sem_chunks = json.loads(sem_result) if sem_result else []
        kw_chunks = json.loads(kw_result) if kw_result else []

        # RRF 融合
        ranked = _rrf_fusion(sem_chunks, kw_chunks, top_n=5)

        if not ranked:
            return "知识库中未找到相关信息。请尝试换一种表述或提供更多细节。"

        # 精读片段
        read_input = [{"fileId": c["fileId"], "chunkIndex": c["chunkIndex"]} for c in ranked[:3]]
        read_result = kb.readFileChunks(kb_id, read_input)
        chunks_read = json.loads(read_result) if read_result else []

        if not chunks_read:
            return "知识库中未找到相关信息。请尝试换一种表述。"

        # 构建上下文
        context_parts = []
        for chunk in chunks_read:
            fid = chunk.get("fileId", "?")
            ci = chunk.get("chunkIndex", "?")
            content = chunk.get("content", "")
            context_parts.append(f"[文件{fid}-片段{ci}]\n{content}")

        context = "\n\n---\n\n".join(context_parts)
        refs = [f"fileId={c.get('fileId')}, chunkIndex={c.get('chunkIndex')}" for c in chunks_read]

        return (
            f"根据知识库内容，以下是相关信息：\n\n"
            f"{context}\n\n"
            f"---\n"
            f"引用：{'; '.join(refs)}"
        )
    except Exception as e:
        logger.error("[agentic_rag] 基础检索失败: %s", e)
        return f"知识库查询失败: {e}"


# ═══════════════════════════════════════════════════════════════════
# 插件主类
# ═══════════════════════════════════════════════════════════════════

class AgenticRAGPlugin(PluginBase):
    """Agentic RAG 知识库插件（基于 LangGraph ReAct Agent）。

    通过 Hook 机制实现：
    - on_startup: 初始化 Milvus 知识库控制器 + 注入 Agent 模块
    - on_register_tools: 注册 ask_knowledge_base 工具
    - on_execute_tool: 运行真正的 Agentic RAG Agent（失败回退到基础检索）
    - on_llm_context: 注入知识库状态
    - on_shutdown: 关闭连接
    """

    name = "agentic_rag"
    version = "2.0"

    def __init__(self) -> None:
        super().__init__()
        self._kb = None
        self._kb_id = DEFAULT_KB_ID
        self._file_count = 0
        self._chunk_count = 0
        self._agent = None  # 缓存的 Agent 实例
        self._agent_model = ""
        self._agent_base_url = ""
        self._agent_api_key = ""

    # ================================================================
    # Hook 实现
    # ================================================================

    def on_startup(self, app) -> None:
        """初始化 Milvus 知识库控制器 + 注入 Agent 模块。"""
        super().on_startup(app)
        try:
            # 确保数据目录存在
            data_dir = self.get_data_dir()
            milvus_uri = os.path.join(data_dir, "kb.db")
            bm25_cache = os.path.join(data_dir, "bm25_cache.pkl")

            # 将项目根目录加入 sys.path
            project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            if project_root not in sys.path:
                sys.path.insert(0, project_root)

            from kb_controller import MilvusLiteKBController

            self._kb = MilvusLiteKBController(
                milvus_uri=milvus_uri,
                collection_name=DEFAULT_COLLECTION,
                bm25_cache_path=bm25_cache,
            )

            # 注入 kb_controller 到 Agent 模块
            from config import Config
            from plugins import agentic_rag_agent
            agentic_rag_agent.kb_controller = self._kb
            agentic_rag_agent.knowledge_base_id = self._kb_id

            # 读取 Agent LLM 配置
            self._agent_model = os.getenv("AGENTIC_RAG_LLM_MODEL", Config.AGENTIC_RAG_LLM_MODEL)
            self._agent_base_url = os.getenv("AGENTIC_RAG_LLM_BASE_URL", Config.AGENTIC_RAG_LLM_BASE_URL)
            self._agent_api_key = os.getenv("AGENTIC_RAG_LLM_API_KEY", Config.AGENTIC_RAG_LLM_API_KEY)

            # 获取知识库状态
            self._update_stats()

            logger.info(
                "[agentic_rag] 插件就绪 — Milvus 知识库已连接\n"
                "  数据库: %s\n"
                "  文件数: %d | Chunk 数: %d\n"
                "  Agent 模型: %s",
                milvus_uri, self._file_count, self._chunk_count,
                self._agent_model,
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
                        "内部使用独立的智能检索 Agent，支持多步推理、查询改写、"
                        "双通道检索、RRF 融合、自我反思等高级检索流程。"
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
        """执行 ask_knowledge_base 工具（Agent 模式，失败回退到基础检索）。"""
        if tool_name != "ask_knowledge_base" or not self._kb:
            return ""

        question = tool_args.get("question", "")
        if not question:
            return "请提供查询问题。"

        logger.info("[agentic_rag] 收到查询: '%s'", question[:80])

        # 尝试使用真正的 Agentic RAG Agent
        try:
            from plugins import agentic_rag_agent

            # 检查 Agent 模块是否已初始化
            if agentic_rag_agent.kb_controller is None:
                logger.warning("[agentic_rag] Agent 模块未初始化，回退到基础检索")
                return _run_agentic_rag_basic(self._kb, self._kb_id, question)

            # 创建或复用 Agent
            if self._agent is None:
                self._agent = agentic_rag_agent.create_agent(
                    model=self._agent_model,
                    api_key=self._agent_api_key,
                    base_url=self._agent_base_url,
                )

            # 运行 Agent
            logger.info("[agentic_rag] 启动 Agent 推理...")
            result = self._agent.invoke(
                {"messages": [("user", question)]},
                config={"recursion_limit": 25},
            )
            answer = result["messages"][-1].content

            logger.info("[agentic_rag] Agent 完成，返回 %d 字符", len(answer))
            return answer

        except ImportError as e:
            logger.error("[agentic_rag] Agent 模块导入失败: %s，回退到基础检索", e)
            return _run_agentic_rag_basic(self._kb, self._kb_id, question)
        except Exception as e:
            logger.error("[agentic_rag] Agent 执行失败: %s，回退到基础检索", e)
            self._agent = None  # 清空缓存，下次重新创建
            return _run_agentic_rag_basic(self._kb, self._kb_id, question)

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
            f"知识库查询使用独立的智能检索 Agent (model: {self._agent_model})，"
            f"支持多步推理、双通道检索、自我反思。"
            f"如果用户的问题可能涉及知识库中的内容，请使用 ask_knowledge_base 工具查询。"
        )

    def on_shutdown(self) -> None:
        """关闭 Milvus 连接，清理 Agent。"""
        self._agent = None
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
        agent_status = "已缓存" if self._agent else "待创建"
        return f"""
        <div style="padding:12px; color:#eee; font-family:system-ui,sans-serif">
            <h3 style="color:#e94560; margin-bottom:12px">📚 知识库 (Agentic RAG)</h3>
            <p style="color:#aaa; font-size:13px">
                知识库状态：{status}<br>
                文件数：{self._file_count}<br>
                片段数：{self._chunk_count}
            </p>
            <p style="color:#aaa; font-size:13px; margin-top:8px">
                工具：<code>ask_knowledge_base</code><br>
                Agent 模型：{self._agent_model}<br>
                Agent 状态：{agent_status}
            </p>
            <p style="color:#aaa; font-size:13px; margin-top:8px">
                流程：查询改写 → 双通道检索 → RRF 融合 → 精读 → 自我反思 → 生成答案
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
