"""
Agentic RAG Agent 模块
======================
从独立的 agentic_rag.py 适配而来，集成到 VirtuMate 插件系统。

包含 9 个 @tool 工具、SYSTEM_PROMPT 和 create_agent() 函数。
由 agentic_rag_plugin.py 在 on_startup 时注入 kb_controller，
在 on_execute_tool 时创建并运行 Agent。

使用方式：
    import agentic_rag_agent
    agentic_rag_agent.kb_controller = kb_instance
    agentic_rag_agent.knowledge_base_id = 0
    agent = agentic_rag_agent.create_agent(model=..., api_key=..., base_url=...)
    result = agent.invoke({"messages": [("user", question)]})
"""

from typing import List, Dict
import json
from log_config import get_logger

logger = get_logger(__name__)

# ===================== 模块级全局变量（由插件注入） =====================
kb_controller = None  # 延迟初始化，由 agentic_rag_plugin 在 on_startup 时注入
knowledge_base_id = 0

# ===================== 常量 =====================
RERANK_MIN_SCORE = 0.005
MAX_REFLECT_ROUNDS = 3


# ===================== P0: 查询改写/拆解 =====================
# 注意：以下 @tool 装饰器需要 langchain_core，延迟导入以避免启动时依赖
_tools_registered = False
rewrite_and_decompose = None
query_knowledge_base = None
keyword_search = None
rerank_results = None
get_file_summary = None
get_files_meta = None
read_file_chunks = None
list_files = None
reflect_on_answer = None
tools = []
SYSTEM_PROMPT = ""


def _register_tools():
    """延迟注册工具（首次调用时初始化，避免启动时导入 langchain）。"""
    global _tools_registered
    global rewrite_and_decompose, query_knowledge_base, keyword_search
    global rerank_results, get_file_summary, get_files_meta
    global read_file_chunks, list_files, reflect_on_answer
    global tools, SYSTEM_PROMPT

    if _tools_registered:
        return

    from langchain_core.tools import tool as langchain_tool

    # ---- rewrite_and_decompose ----
    @langchain_tool("rewrite_and_decompose")
    def _rewrite_and_decompose(original_query: str) -> str:
        """将用户的原始问题拆解为多个子查询，并改写为知识库更容易匹配的形式。

        输入：用户的原始问题（如 "对比 RAG 和 fine-tuning 的优缺点"）
        输出：JSON 格式的子查询列表，每个子查询包含：
          - sub_query: 改写后的搜索关键词
          - intent: 该子查询的检索意图

        使用场景：当用户的问题包含多个维度、或原问题措辞与知识库文档用语不一致时，
        先调用此工具拆解改写，再用子查询分别搜索。
        """
        return (
            f"原始问题: {original_query}\n"
            "请将此问题拆解为 2-5 个子查询，每个子查询改写为知识库文档中"
            "可能出现的表述形式（例如把口语化问题转为专业术语）。\n"
            "输出 JSON 数组格式：\n"
            '[{"sub_query": "...", "intent": "..."}]\n'
            "然后用每个 sub_query 分别调用 query_knowledge_base 和 keyword_search 进行搜索。"
        )

    # ---- query_knowledge_base ----
    @langchain_tool("query_knowledge_base")
    def _query_knowledge_base(query: str, top_k: int = 10) -> str:
        """语义搜索知识库。用向量相似度检索与 query 最相关的文本片段。

        参数：
          query: 搜索关键词（建议使用改写后的专业术语，而非口语化表述）
          top_k: 返回结果数量，默认 10

        返回：JSON 字符串，包含匹配的 chunk 信息（fileId, chunkIndex, content, score）。
        如果无结果，返回提示信息建议改写查询。
        """
        try:
            results = kb_controller.search(knowledge_base_id, query, top_k=top_k)
            if not results:
                return (
                    f"语义搜索 '{query}' 无结果。建议：\n"
                    "1. 用 rewrite_and_decompose 改写查询\n"
                    "2. 用 keyword_search 补充关键词检索\n"
                    "3. 用 list_files 浏览知识库内容"
                )
            return results
        except Exception as e:
            return f"搜索失败: {e}。请尝试简化查询或用 keyword_search 替代。"

    # ---- keyword_search ----
    @langchain_tool("keyword_search")
    def _keyword_search(query: str, top_k: int = 10) -> str:
        """BM25 关键词检索知识库。用精确关键词匹配检索文档片段。

        参数：
          query: 关键词搜索词（适合搜索专有名词、缩写、精确短语、编号等）
          top_k: 返回结果数量，默认 10

        返回：JSON 字符串，包含匹配的 chunk 信息（fileId, chunkIndex, content, bm25_score）。

        与 query_knowledge_base 的区别：
          - 语义搜索擅长理解含义（"优点" 能匹配 "benefits"）
          - 关键词搜索擅长精确匹配（"Section 3.2" 能精确命中）
          - 建议两者配合使用，结果会由 rerank_results 工具融合排序
        """
        try:
            results = kb_controller.keyword_search(knowledge_base_id, query, top_k=top_k)
            if not results:
                return f"关键词搜索 '{query}' 无结果。建议用 query_knowledge_base 语义搜索替代。"
            return results
        except Exception as e:
            return f"关键词搜索失败: {e}。请用 query_knowledge_base 语义搜索替代。"

    # ---- rerank_results ----
    @langchain_tool("rerank_results")
    def _rerank_results(
        query: str,
        semantic_results: str,
        keyword_results: str,
        top_n: int = 5,
    ) -> str:
        """对语义搜索和关键词搜索的结果做融合排序与过滤。

        参数：
          query: 原始用户问题（用于相关性判断）
          semantic_results: query_knowledge_base 的返回结果（JSON 字符串）
          keyword_results: keyword_search 的返回结果（JSON 字符串）
          top_n: 最终保留的高质量 chunk 数量，默认 5

        返回：排序后的高质量 chunk 列表（JSON），包含 fileId, chunkIndex, content, combined_score。
        低于相关性阈值的 chunk 会被过滤掉。
        """
        try:
            sem_chunks = []
            kw_chunks = []
            try:
                sem_chunks = json.loads(semantic_results) if semantic_results else []
            except json.JSONDecodeError:
                sem_chunks = []
            try:
                kw_chunks = json.loads(keyword_results) if keyword_results else []
            except json.JSONDecodeError:
                kw_chunks = []

            K = 60
            chunk_scores: Dict[str, float] = {}

            for rank, chunk in enumerate(sem_chunks, 1):
                key = f"{chunk.get('fileId', '?')}_{chunk.get('chunkIndex', '?')}"
                chunk_scores[key] = chunk_scores.get(key, 0) + 1.0 / (K + rank)
                chunk_scores[f"{key}_content"] = chunk.get("content", "")
                chunk_scores[f"{key}_fileId"] = chunk.get("fileId", "?")
                chunk_scores[f"{key}_chunkIndex"] = chunk.get("chunkIndex", "?")

            for rank, chunk in enumerate(kw_chunks, 1):
                key = f"{chunk.get('fileId', '?')}_{chunk.get('chunkIndex', '?')}"
                chunk_scores[key] = chunk_scores.get(key, 0) + 1.0 / (K + rank)
                if f"{key}_content" not in chunk_scores:
                    chunk_scores[f"{key}_content"] = chunk.get("content", "")
                    chunk_scores[f"{key}_fileId"] = chunk.get("fileId", "?")
                    chunk_scores[f"{key}_chunkIndex"] = chunk.get("chunkIndex", "?")

            ranked = []
            seen_keys = set()
            for key in sorted(chunk_scores.keys()):
                if key.endswith("_content") or key.endswith("_fileId") or key.endswith("_chunkIndex"):
                    continue
                if key in seen_keys:
                    continue
                seen_keys.add(key)
                score = chunk_scores[key]
                if score < RERANK_MIN_SCORE:
                    continue
                ranked.append({
                    "fileId": chunk_scores.get(f"{key}_fileId", "?"),
                    "chunkIndex": chunk_scores.get(f"{key}_chunkIndex", "?"),
                    "content": chunk_scores.get(f"{key}_content", ""),
                    "combined_score": round(score, 4),
                })

            ranked = sorted(ranked, key=lambda x: x["combined_score"], reverse=True)[:top_n]

            if not ranked:
                return (
                    "rerank 后无高质量结果。建议：\n"
                    "1. 用 rewrite_and_decompose 改写查询再搜索\n"
                    "2. 扩大 top_k 获取更多候选\n"
                    "3. 用 list_files 浏览知识库手动定位"
                )

            return json.dumps(ranked, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"rerank 失败: {e}。请直接从搜索结果中挑选最相关的 chunk 阅读。"

    # ---- get_file_summary ----
    @langchain_tool("get_file_summary")
    def _get_file_summary(file_id: int) -> str:
        """获取指定文档的摘要，用于宏观定位相关文档。

        参数：
          file_id: 文件 ID（从 list_files 或搜索结果中获取）

        返回：文档摘要文本，包含文档主题、核心论点、覆盖范围。
        """
        try:
            summary = kb_controller.getFileSummary(knowledge_base_id, file_id)
            if not summary:
                meta = kb_controller.getFilesMeta(knowledge_base_id, [file_id])
                if meta:
                    return f"无摘要，文件元数据：{meta}"
                return f"未找到文件 {file_id} 的摘要或元数据。"
            return summary
        except Exception as e:
            return f"获取摘要失败: {e}。请用 get_files_meta 获取文件元数据替代。"

    # ---- get_files_meta ----
    @langchain_tool("get_files_meta")
    def _get_files_meta(fileIds: List[int]) -> str:
        """获取知识库中指定文件的元数据（文件名、大小、类型、chunk 数量等）。

        参数：
          fileIds: 文件 ID 数组

        返回：JSON 字符串，每个文件的元数据。
        """
        try:
            if not fileIds:
                return "请提供文件 ID 数组。可以从搜索结果或 list_files 中获取。"
            results = kb_controller.getFilesMeta(knowledge_base_id, fileIds)
            if not results:
                return f"未找到文件 {fileIds} 的元数据。请检查 ID 是否正确。"
            return results
        except Exception as e:
            return f"获取元数据失败: {e}。请检查文件 ID 是否正确。"

    # ---- read_file_chunks ----
    @langchain_tool("read_file_chunks")
    def _read_file_chunks(chunks: List[Dict[str, int]]) -> str:
        """精读指定文件的文本片段。这是最终作答的依据，必须基于此工具的返回内容回答。

        参数：
          chunks: 要读取的片段数组，每项包含 fileId 和 chunkIndex。
            示例: [{"fileId": 5, "chunkIndex": 3}, {"fileId": 12, "chunkIndex": 7}]

        返回：片段的完整文本内容（JSON 字符串）。
        """
        try:
            if not chunks:
                return '请提供要读取的片段数组，格式：[{"fileId": int, "chunkIndex": int}]'
            for item in chunks:
                if "fileId" not in item or "chunkIndex" not in item:
                    return (
                        f"参数格式错误: {item}。每项需要 'fileId' 和 'chunkIndex'。\n"
                        '示例: [{"fileId": 5, "chunkIndex": 3}]'
                    )
            results = kb_controller.readFileChunks(knowledge_base_id, chunks)
            if not results:
                return f"未找到指定片段 {chunks}。请检查 fileId 和 chunkIndex 是否正确。"
            return results
        except Exception as e:
            return f"读取片段失败: {e}。请检查 fileId 和 chunkIndex 是否正确。"

    # ---- list_files ----
    @langchain_tool("list_files")
    def _list_files(page: int = 1, pageSize: int = 20) -> str:
        """浏览知识库中的文件列表，返回文件 ID、文件名、chunk 数量。

        参数：
          page: 页码，默认 1
          pageSize: 每页数量，默认 20

        返回：JSON 字符串，包含 id, filename, chunkCount。
        """
        try:
            files = kb_controller.listFilesPaginated(knowledge_base_id, page, pageSize)
            result = [
                {
                    "id": f["id"],
                    "filename": f["filename"],
                    "chunkCount": f.get("chunk_count", 0),
                }
                for f in files
                if f.get("status") == "done"
            ]
            if not result:
                return "知识库无可用文件，或当前页无内容。请检查 knowledge_base_id 是否正确。"
            return json.dumps(result, ensure_ascii=False, indent=2)
        except Exception as e:
            return f"浏览文件失败: {e}。请检查知识库 ID 是否正确。"

    # ---- reflect_on_answer ----
    @langchain_tool("reflect_on_answer")
    def _reflect_on_answer(
        original_question: str,
        sub_queries: str,
        chunks_read: str,
        draft_answer: str,
    ) -> str:
        """反思当前草稿回答是否充分覆盖了用户问题的所有维度。

        参数：
          original_question: 用户的原始问题
          sub_queries: 拆解出的子查询列表（JSON 字符串）
          chunks_read: 已读取的片段列表（JSON 字符串）
          draft_answer: 当前草稿回答内容

        返回：JSON 字符串，包含：
          - coverage_score: 覆盖度评分 (0-1)
          - missing_aspects: 未覆盖的子问题列表
          - suggestion: 改进建议（如需要补充搜索的查询词）
          - is_sufficient: 是否已经足够回答 (true/false)

        使用场景：在生成最终回答前，用此工具检查是否需要回环再搜索。
        如果 is_sufficient=false，根据 suggestion 回到搜索环节补充资料。
        """
        try:
            sub_list = json.loads(sub_queries) if sub_queries else []
            chunks_list = json.loads(chunks_read) if chunks_read else []
        except Exception:
            sub_list = []
            chunks_list = []

        return (
            f"=== 反思检查 ===\n"
            f"原始问题: {original_question}\n"
            f"子查询数量: {len(sub_list)}\n"
            f"已读片段数量: {len(chunks_list)}\n"
            f"草稿回答长度: {len(draft_answer)} 字符\n\n"
            "请逐一检查以下维度，判断回答是否充分：\n"
            "1. 每个子查询是否都有对应的证据片段支撑？\n"
            "2. 是否存在只有搜索结果但没有精读的遗漏片段？\n"
            "3. 草稿回答中是否包含了编造的、无引用来源的内容？\n"
            "4. 是否有子问题的证据互相矛盾需要进一步验证？\n\n"
            "输出 JSON：\n"
            '{"coverage_score": 0.0-1.0, "missing_aspects": [...], '
            '"suggestion": "...", "is_sufficient": true/false}\n\n'
            "如果 is_sufficient=false，请根据 suggestion 中的建议\n"
            "回到 query_knowledge_base / keyword_search 补充搜索，\n"
            "再用 read_file_chunks 精读新片段。\n"
            f"注意：最多回环 {MAX_REFLECT_ROUNDS} 次，避免无限循环。"
        )

    # ---- 注册到模块级变量 ----
    rewrite_and_decompose = _rewrite_and_decompose
    query_knowledge_base = _query_knowledge_base
    keyword_search = _keyword_search
    rerank_results = _rerank_results
    get_file_summary = _get_file_summary
    get_files_meta = _get_files_meta
    read_file_chunks = _read_file_chunks
    list_files = _list_files
    reflect_on_answer = _reflect_on_answer

    tools = [
        rewrite_and_decompose,
        query_knowledge_base,
        keyword_search,
        rerank_results,
        get_file_summary,
        get_files_meta,
        read_file_chunks,
        list_files,
        reflect_on_answer,
    ]

    SYSTEM_PROMPT = """你是一个 Agentic RAG 助手，严格基于知识库内容回答问题。

=== 工作流程（必须按顺序执行） ===

Step 1 - 查询分析与改写
  - 对于复杂问题（包含多个维度、对比、列举），先用 rewrite_and_decompose 拆解为子查询
  - 对于简单问题，可以直接搜索，但如果搜不到结果，回来改写再试

Step 2 - 双通道检索
  - 对每个子查询，同时调用 query_knowledge_base（语义搜索）和 keyword_search（关键词搜索）
  - 专有名词、缩写、精确短语优先用 keyword_search
  - 语义模糊的概念性问题优先用 query_knowledge_base

Step 3 - 结果融合与筛选
  - 将两路搜索结果交给 rerank_results 做融合排序
  - 从 rerank 返回的 top_n 结果中挑选 3-5 个最相关的 chunk

Step 4 - 宏观定位（可选）
  - 如果不确定某篇文档的整体方向，先用 get_file_summary 看摘要
  - 比盲目 read_file_chunks 更高效

Step 5 - 精读片段
  - 用 read_file_chunks 读取选定的片段，这是最终作答的唯一依据
  - 每次读取 3-5 个片段即可，不要贪多

Step 6 - 自我反思
  - 用 reflect_on_answer 检查回答是否覆盖了所有子问题
  - 如果不够充分，根据 suggestion 回到 Step 2 补充搜索
  - 最多回环 3 次

Step 7 - 生成回答
  - 基于精读的片段内容生成结构化回答
  - 回答末尾用"引用："列出实际读取的 fileId + chunkIndex
  - 对证据不足的部分标注"[证据不足]"并说明局限性
  - 对高置信部分标注"[充分证据]"

=== 约束 ===
- 不要编造知识库中不存在的内容
- 搜索次数不超过 3 轮（每轮含语义 + 关键词双通道）
- 每轮精读不超过 5 个片段
- 单次回答引用不超过 8 个片段
- 如果 3 轮检索后仍无法回答，坦诚告知并建议用户改进问题
"""

    _tools_registered = True
    logger.info("[agentic_rag_agent] 工具注册完成，共 %d 个工具", len(tools))


def create_agent(
    model: str,
    api_key: str,
    base_url: str,
    temperature: float = 0,
    max_retries: int = 3,
    recursion_limit: int = 25,
):
    """创建并返回 Agentic RAG Agent 实例。

    参数：
      model: LLM 模型名称
      api_key: API 密钥
      base_url: API 基地址
      temperature: 生成温度
      max_retries: API 重试次数
      recursion_limit: Agent 最大推理步骤数

    返回：LangGraph ReAct Agent 实例
    """
    _register_tools()

    from langchain_openai import ChatOpenAI
    from langchain_core.messages import SystemMessage
    from langgraph.prebuilt import create_react_agent

    llm = ChatOpenAI(
        model=model,
        temperature=temperature,
        max_retries=max_retries,
        base_url=base_url,
        api_key=api_key,
    )

    agent = create_react_agent(
        llm,
        tools,
        prompt=SystemMessage(content=SYSTEM_PROMPT),
    )

    logger.info("[agentic_rag_agent] Agent 已创建 (model=%s)", model)
    return agent
