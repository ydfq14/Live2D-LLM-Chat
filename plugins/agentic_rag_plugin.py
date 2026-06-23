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

    # ==================================================================
    #  文件上传 API（供前端调用）
    # ==================================================================

    def upload_file(self, file_path: str, summary: str = "") -> str:
        """上传并索引文件到知识库。

        Args:
            file_path: 文件路径
            summary: 文件摘要（可选）

        Returns:
            JSON 格式的处理结果
        """
        logger.info("[agentic_rag] 开始文件上传流程: %s", file_path)

        if not self._kb:
            logger.error("[agentic_rag] 上传失败: 知识库未初始化")
            return json.dumps({"success": False, "error": "知识库未初始化"})

        try:
            from kb_controller import IngestionPipeline
            import os

            # 检查文件是否存在
            if not os.path.exists(file_path):
                logger.error("[agentic_rag] 上传失败: 文件不存在 - %s", file_path)
                return json.dumps({"success": False, "error": f"文件不存在: {file_path}"})

            logger.info("[agentic_rag] 文件存在检查通过: %s", file_path)

            # 获取文件信息
            file_size = os.path.getsize(file_path)
            file_ext = os.path.splitext(file_path)[1].lower()
            filename = os.path.basename(file_path)
            logger.info("[agentic_rag] 文件信息: 名称=%s, 大小=%d bytes, 类型=%s", filename, file_size, file_ext)

            # 检查文件类型
            supported_types = {'.txt', '.md', '.pdf', '.json', '.csv'}
            if file_ext not in supported_types:
                logger.error("[agentic_rag] 上传失败: 不支持的文件类型 %s", file_ext)
                return json.dumps({
                    "success": False,
                    "error": f"不支持的文件类型: {file_ext}，支持: {', '.join(supported_types)}"
                })

            logger.info("[agentic_rag] 文件类型检查通过: %s", file_ext)

            # 检查文件是否为空
            if file_size == 0:
                logger.error("[agentic_rag] 上传失败: 文件为空")
                return json.dumps({"success": False, "error": "文件内容为空"})

            # 创建 IngestionPipeline 并摄入文件
            logger.info("[agentic_rag] 创建 IngestionPipeline...")
            pipeline = IngestionPipeline(self._kb)

            logger.info("[agentic_rag] 开始摄入文件到知识库...")
            file_id = pipeline.ingest_file(file_path, summary=summary)

            if file_id > 0:
                # 更新统计
                self._update_stats()
                logger.info("[agentic_rag] ✓ 文件上传成功: %s (ID=%d)", filename, file_id)
                logger.info("[agentic_rag] 当前知识库统计: 文件数=%d, 片段数=%d", self._file_count, self._chunk_count)
                return json.dumps({
                    "success": True,
                    "file_id": file_id,
                    "filename": filename,
                    "message": f"文件已成功索引，ID={file_id}"
                })
            else:
                logger.error("[agentic_rag] 上传失败: 文件索引失败，返回 ID=%d", file_id)
                return json.dumps({"success": False, "error": "文件索引失败，可能是文件内容为空"})

        except Exception as e:
            logger.error("[agentic_rag] 文件上传异常: %s", str(e), exc_info=True)
            return json.dumps({"success": False, "error": str(e)})

    def get_file_list(self) -> str:
        """获取知识库文件列表（供前端显示）。"""
        logger.info("[agentic_rag] 获取文件列表请求")

        if not self._kb:
            logger.warning("[agentic_rag] 获取文件列表失败: 知识库未初始化")
            return json.dumps({"files": [], "error": "知识库未初始化"})

        try:
            files = self._kb.listFilesPaginated(self._kb_id, page=1, pageSize=100)
            logger.debug("[agentic_rag] 从数据库获取到 %d 个文件", len(files))

            file_list = [
                {
                    "id": f.get("id"),
                    "filename": f.get("filename", "未知"),
                    "chunk_count": f.get("chunk_count", 0),
                    "status": f.get("status", "unknown")
                }
                for f in files
                if f.get("status") == "done"
            ]

            logger.info("[agentic_rag] 返回 %d 个已完成文件（过滤掉非 done 状态）", len(file_list))
            return json.dumps({"files": file_list})
        except Exception as e:
            logger.error("[agentic_rag] 获取文件列表失败: %s", str(e), exc_info=True)
            return json.dumps({"files": [], "error": str(e)})

    def delete_file(self, file_id: str) -> str:
        """从知识库删除指定文件。

        Args:
            file_id: 文件 ID（字符串，前端传入）

        Returns:
            JSON 格式的处理结果
        """
        logger.info("[agentic_rag] 收到删除文件请求: file_id=%s", file_id)

        if not self._kb:
            logger.error("[agentic_rag] 删除失败: 知识库未初始化")
            return json.dumps({"success": False, "error": "知识库未初始化"})

        try:
            fid = int(file_id)
            logger.info("[agentic_rag] 转换文件 ID: %s -> %d", file_id, fid)

            # 获取文件信息（用于日志）
            logger.debug("[agentic_rag] 查询文件列表以查找目标文件...")
            files = self._kb.listFilesPaginated(self._kb_id, page=1, pageSize=10000)
            target_file = next((f for f in files if f.get("id") == fid), None)

            if not target_file:
                logger.error("[agentic_rag] 删除失败: 文件 ID=%d 不存在", fid)
                return json.dumps({"success": False, "error": f"文件 ID={fid} 不存在"})

            filename = target_file.get("filename", "未知")
            logger.info("[agentic_rag] 找到目标文件: %s (ID=%d)", filename, fid)

            # 删除文件
            logger.info("[agentic_rag] 开始删除文件...")
            self._kb.delete_file(fid)
            logger.info("[agentic_rag] 文件已从数据库删除")

            # 更新统计
            self._update_stats()

            logger.info("[agentic_rag] ✓ 文件删除成功: %s (ID=%d)", filename, fid)
            logger.info("[agentic_rag] 当前知识库统计: 文件数=%d, 片段数=%d", self._file_count, self._chunk_count)
            return json.dumps({
                "success": True,
                "message": f"文件 '{filename}' 已删除",
                "file_id": fid
            })

        except ValueError:
            logger.error("[agentic_rag] 删除失败: 无效的文件 ID 格式 - %s", file_id)
            return json.dumps({"success": False, "error": f"无效的文件 ID: {file_id}"})
        except Exception as e:
            logger.error("[agentic_rag] 删除文件异常: %s", str(e), exc_info=True)
            return json.dumps({"success": False, "error": str(e)})

    def get_frontend_html(self) -> str:
        """返回知识库状态面板（含文件上传功能）。"""
        status = "已连接" if self._kb else "未连接"
        agent_status = "已缓存" if self._agent else "待创建"
        return f"""
        <style>
            .kb-section {{ margin-bottom: 16px; padding-bottom: 12px; border-bottom: 1px solid rgba(255,255,255,0.1); }}
            .kb-btn {{
                padding: 8px 16px; border: none; border-radius: 6px;
                background: #e94560; color: #fff; font-size: 12px;
                cursor: pointer; transition: background 0.2s;
            }}
            .kb-btn:hover {{ background: #c73e54; }}
            .kb-btn:disabled {{ background: #555; cursor: not-allowed; }}
            .kb-file-list {{ max-height: 200px; overflow-y: auto; margin-top: 8px; }}
            .kb-file-item {{
                display: flex; justify-content: space-between; align-items: center;
                padding: 6px 8px; background: rgba(255,255,255,0.05);
                border-radius: 4px; margin-bottom: 4px; font-size: 12px;
            }}
            .kb-file-name {{ color: #eee; flex: 1; }}
            .kb-file-chunks {{ color: #888; font-size: 11px; margin-right: 8px; }}
            .kb-file-delete {{
                padding: 2px 8px; border: 1px solid #e94560; border-radius: 4px;
                background: transparent; color: #e94560; font-size: 11px;
                cursor: pointer; transition: all 0.2s;
            }}
            .kb-file-delete:hover {{ background: #e94560; color: #fff; }}
            .kb-upload-area {{
                border: 2px dashed rgba(255,255,255,0.2); border-radius: 8px;
                padding: 20px; text-align: center; margin-top: 12px;
                cursor: pointer; transition: border-color 0.2s;
            }}
            .kb-upload-area:hover {{ border-color: #e94560; }}
            .kb-upload-area.dragover {{ border-color: #e94560; background: rgba(233,69,96,0.1); }}
            #kbFileInput {{ display: none; }}
        </style>

        <div style="padding:12px; color:#eee; font-family:system-ui,sans-serif">
            <h3 style="color:#e94560; margin-bottom:12px">📚 知识库 (Agentic RAG)</h3>

            <div class="kb-section">
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
            </div>

            <div class="kb-section">
                <button class="kb-btn" onclick="kbRefreshFiles()">🔄 刷新文件列表</button>
                <div id="kbFileList" class="kb-file-list">
                    <p style="color:#555; font-size:12px">点击刷新加载文件列表</p>
                </div>
            </div>

            <div class="kb-section">
                <p style="color:#aaa; font-size:12px; margin-bottom:8px">上传文件到知识库</p>
                <div class="kb-upload-area" id="kbUploadArea" onclick="kbSelectAndUpload()">
                    <p style="color:#888; font-size:13px; margin:0">📁 点击此处选择文件</p>
                    <p style="color:#555; font-size:11px; margin:4px 0 0 0">
                        <strong>支持的格式：</strong>.txt .md .pdf .json .csv<br>
                        <span style="color:#e94560">其他格式将被拒绝</span>
                    </p>
                </div>
                <div id="kbUploadStatus" style="margin-top:8px; font-size:12px; color:#aaa"></div>
            </div>
        </div>

        <script>
            // 刷新文件列表
            function kbRefreshFiles() {{
                console.log('[agentic_rag] 刷新文件列表...');
                pywebview.api.call_plugin('agentic_rag', 'get_file_list').then(function(raw) {{
                    console.log('[agentic_rag] 收到文件列表响应:', raw);
                    var data = JSON.parse(raw);
                    var el = document.getElementById('kbFileList');
                    if (data.error) {{
                        console.error('[agentic_rag] 获取文件列表失败:', data.error);
                        el.innerHTML = '<p style="color:#e94560; font-size:12px">' + data.error + '</p>';
                        return;
                    }}
                    if (!data.files || data.files.length === 0) {{
                        console.log('[agentic_rag] 知识库暂无文件');
                        el.innerHTML = '<p style="color:#555; font-size:12px">知识库暂无文件</p>';
                        return;
                    }}
                    console.log('[agentic_rag] 加载 ' + data.files.length + ' 个文件');
                    var html = '';
                    for (var i = 0; i < data.files.length; i++) {{
                        var f = data.files[i];
                        html += '<div class="kb-file-item">';
                        html += '<span class="kb-file-name">📄 ' + f.filename + '</span>';
                        html += '<span class="kb-file-chunks">' + f.chunk_count + ' 片段</span>';
                        html += '<button class="kb-file-delete" onclick="kbDeleteFile(' + f.id + ', \'' + f.filename.replace(/'/g, "\\'") + '\')">删除</button>';
                        html += '</div>';
                    }}
                    el.innerHTML = html;
                    console.log('[agentic_rag] ✓ 文件列表刷新完成');
                }}).catch(function(e) {{
                    console.error('[agentic_rag] 刷新文件列表异常:', e);
                }});
            }}

            // 删除文件
            function kbDeleteFile(fileId, filename) {{
                console.log('[agentic_rag] 删除文件请求:', fileId, filename);
                if (!confirm('确定要删除文件 "' + filename + '" 吗？\\n删除后无法恢复。')) {{
                    console.log('[agentic_rag] 用户取消删除');
                    return;
                }}

                var statusEl = document.getElementById('kbUploadStatus');
                statusEl.innerHTML = '⏳ 正在删除: ' + filename + '...';
                statusEl.style.color = '#aaa';

                console.log('[agentic_rag] 调用后端删除 API, fileId:', fileId);
                pywebview.api.call_plugin('agentic_rag', 'delete_file', String(fileId)).then(function(raw) {{
                    console.log('[agentic_rag] 收到删除响应:', raw);
                    var data = JSON.parse(raw);
                    if (data.success) {{
                        console.log('[agentic_rag] ✓ 文件删除成功:', data);
                        statusEl.innerHTML = '✅ ' + data.message;
                        statusEl.style.color = '#4a9';
                        kbRefreshFiles();  // 刷新文件列表
                    }} else {{
                        console.error('[agentic_rag] ✗ 文件删除失败:', data.error);
                        statusEl.innerHTML = '❌ ' + data.error;
                        statusEl.style.color = '#e94560';
                    }}
                }}).catch(function(e) {{
                    console.error('[agentic_rag] 删除过程异常:', e);
                    statusEl.innerHTML = '❌ 删除失败: ' + e.message;
                    statusEl.style.color = '#e94560';
                }});
            }}

            // 选择并上传文件（直接调用 pywebview API）
            function kbSelectAndUpload() {{
                console.log('[agentic_rag] 开始文件选择流程');
                var statusEl = document.getElementById('kbUploadStatus');
                statusEl.innerHTML = '⏳ 正在打开文件选择对话框...';
                statusEl.style.color = '#aaa';

                // 支持的文件格式列表
                var supportedExtensions = ['.txt', '.md', '.pdf', '.json', '.csv'];

                // 直接调用 pywebview 的文件选择 API
                pywebview.api.select_file().then(function(filePath) {{
                    if (!filePath) {{
                        console.log('[agentic_rag] 用户取消文件选择');
                        statusEl.innerHTML = '❌ 未选择文件';
                        statusEl.style.color = '#e94560';
                        return;
                    }}

                    var filename = filePath.split('\\').pop().split('/').pop();
                    console.log('[agentic_rag] 用户选择文件:', filePath, '文件名:', filename);

                    // 获取文件扩展名（小写）
                    var lastDotIndex = filename.lastIndexOf('.');
                    var fileExtension = lastDotIndex > 0 ? filename.substring(lastDotIndex).toLowerCase() : '';

                    console.log('[agentic_rag] 文件扩展名:', fileExtension);

                    // 前端验证文件类型
                    if (!fileExtension || supportedExtensions.indexOf(fileExtension) === -1) {{
                        console.error('[agentic_rag] ✗ 不支持的文件格式:', fileExtension);
                        var supportedFormats = supportedExtensions.join(', ');
                        statusEl.innerHTML = '❌ 不支持的文件格式: ' + (fileExtension || '无扩展名') + '<br>支持的格式: ' + supportedFormats;
                        statusEl.style.color = '#e94560';
                        return;
                    }}

                    console.log('[agentic_rag] ✓ 文件格式验证通过:', fileExtension);
                    statusEl.innerHTML = '⏳ 正在上传: ' + filename + '...';
                    statusEl.style.color = '#aaa';

                    console.log('[agentic_rag] 调用后端上传 API...');
                    return pywebview.api.call_plugin('agentic_rag', 'upload_file', filePath, '');
                }}).then(function(raw) {{
                    if (!raw) {{
                        console.log('[agentic_rag] 上传 API 返回空结果');
                        return;
                    }}
                    console.log('[agentic_rag] 收到后端响应:', raw);
                    var data = JSON.parse(raw);
                    if (data.success) {{
                        console.log('[agentic_rag] ✓ 文件上传成功:', data);
                        statusEl.innerHTML = '✅ ' + data.message;
                        statusEl.style.color = '#4a9';
                        kbRefreshFiles();  // 刷新文件列表
                    }} else {{
                        console.error('[agentic_rag] ✗ 文件上传失败:', data.error);
                        statusEl.innerHTML = '❌ ' + data.error;
                        statusEl.style.color = '#e94560';
                    }}
                }}).catch(function(e) {{
                    console.error('[agentic_rag] 上传过程异常:', e);
                    statusEl.innerHTML = '❌ 上传失败: ' + e.message;
                    statusEl.style.color = '#e94560';
                }});
            }}

            // 拖拽上传
            var uploadArea = document.getElementById('kbUploadArea');
            uploadArea.addEventListener('dragover', function(e) {{
                e.preventDefault();
                uploadArea.classList.add('dragover');
            }});
            uploadArea.addEventListener('dragleave', function(e) {{
                uploadArea.classList.remove('dragover');
            }});
            uploadArea.addEventListener('drop', function(e) {{
                e.preventDefault();
                uploadArea.classList.remove('dragover');
                // 拖拽时也直接调用文件选择对话框
                kbSelectAndUpload();
            }});

            // 初始加载文件列表
            kbRefreshFiles();
        </script>
        """

    # ================================================================
    # 内部方法
    # ================================================================

    def _update_stats(self) -> None:
        """更新知识库统计信息。"""
        if not self._kb:
            logger.debug("[agentic_rag] 更新统计跳过: 知识库未初始化")
            return

        try:
            logger.debug("[agentic_rag] 开始更新知识库统计...")
            files = self._kb.listFilesPaginated(self._kb_id, page=1, pageSize=10000)
            old_file_count = self._file_count
            old_chunk_count = self._chunk_count

            self._file_count = len(files)
            self._chunk_count = sum(f.get("chunk_count", 0) for f in files)

            if old_file_count != self._file_count or old_chunk_count != self._chunk_count:
                logger.info("[agentic_rag] 统计已更新: 文件数 %d->%d, 片段数 %d->%d",
                           old_file_count, self._file_count, old_chunk_count, self._chunk_count)
            else:
                logger.debug("[agentic_rag] 统计未变化: 文件数=%d, 片段数=%d", self._file_count, self._chunk_count)
        except Exception as e:
            logger.warning("[agentic_rag] 更新统计失败: %s", str(e))
