# Agentic RAG 实现对比分析报告

**分析日期**: 2026-06-22
**分析目的**: 对比真正的 Agentic RAG 与当前项目实现的差异

---

## 概述

发现项目中存在两个 Agentic RAG 实现：

1. **真正的 Agentic RAG** - 位于 `D:\Project\Visual Studio Code\agentic_rag\`
2. **当前项目实现** - 位于 `D:\Project\Visual Studio Code\VirtuMate\Live2D-LLM-Chat\plugins\`

两者存在**根本性差异**：真正的 Agentic RAG 使用 LLM 和 Agent 循环，而当前实现只是简单的脚本流程。

---

## 真正的 Agentic RAG 实现

### 文件位置

```
D:\Project\Visual Studio Code\agentic_rag\
├── agentic_rag.py          # 核心实现
├── kb_controller.py        # 知识库控制器
├── test_agentic_rag.py     # 测试文件
└── face_landmarker.task    # 人脸标记模型（无关）
```

### 核心技术栈

| 技术 | 用途 |
|------|------|
| **LangGraph** | ReAct Agent 框架 |
| **ChatOpenAI** | LLM 推理（MIMO v2.5-pro） |
| **@tool 装饰器** | 工具定义 |

### 关键特性

#### 1. LLM 参与查询改写

**工具**: `rewrite_and_decompose()`

**功能**:
- Agent 使用 LLM 分析用户问题
- 将复杂问题拆解为多个子查询
- 改写查询为知识库更容易匹配的形式

**代码** (agentic_rag.py 第34-64行):
```python
@tool("rewrite_and_decompose")
def rewrite_and_decompose(original_query: str) -> str:
    """将用户的原始问题拆解为多个子查询，并改写为知识库更容易匹配的形式。"""
    return (
        f"原始问题: {original_query}\n"
        "请将此问题拆解为 2-5 个子查询，每个子查询改写为知识库文档中"
        "可能出现的表述形式..."
    )
```

#### 2. LLM 进行自我反思

**工具**: `reflect_on_answer()`

**功能**:
- Agent 使用 LLM 评估答案质量
- 检查是否覆盖了所有子问题
- 判断是否需要补充搜索
- 最多回环 3 次

**代码** (agentic_rag.py 第340-390行):
```python
@tool("reflect_on_answer")
def reflect_on_answer(
    original_question: str,
    sub_queries: str,
    chunks_read: str,
    draft_answer: str,
) -> str:
    """反思当前草稿回答是否充分覆盖了用户问题的所有维度。"""
    return (
        f"=== 反思检查 ===\n"
        f"原始问题: {original_question}\n"
        "请逐一检查以下维度，判断回答是否充分：\n"
        "1. 每个子查询是否都有对应的证据片段支撑？\n"
        "2. 是否存在只有搜索结果但没有精读的遗漏片段？\n"
        "3. 草稿回答中是否包含了编造的、无引用来源的内容？\n"
        "4. 是否有子问题的证据互相矛盾需要进一步验证？\n"
    )
```

#### 3. Agent 循环决策

**创建 Agent** (agentic_rag.py 第453-486行):
```python
def create_agent(
    model: str = "mimo-v2.5-pro",
    temperature: float = 0,
    base_url: str = "https://token-plan-cn.xiaomimimo.com/v1",
    api_key: str = "tp-ckug325vqhsluif02yl4i3k69rx6qagqqdiomqj0adj26lxn",
):
    llm = ChatOpenAI(
        model=model,
        temperature=temperature,
        base_url=base_url,
        api_key=api_key,
    )
    return create_react_agent(
        llm,
        tools,
        prompt=SystemMessage(content=SYSTEM_PROMPT),
    )
```

**运行 Agent** (agentic_rag.py 第494-509行):
```python
def run(question: str, recursion_limit: int = 25, **agent_kwargs):
    _agent = create_agent(**agent_kwargs)
    result = _agent.invoke(
        {"messages": [("user", question)]},
        config={"recursion_limit": recursion_limit},
    )
    return result["messages"][-1].content
```

#### 4. 系统提示

**SYSTEM_PROMPT** (agentic_rag.py 第407-449行):
```python
SYSTEM_PROMPT = """你是一个 Agentic RAG 助手，严格基于知识库内容回答问题。

=== 工作流程（必须按顺序执行） ===

Step 1 - 查询分析与改写
Step 2 - 双通道检索
Step 3 - 结果融合与筛选
Step 4 - 宏观定位（可选）
Step 5 - 精读片段
Step 6 - 自我反思
Step 7 - 生成回答

=== 约束 ===
- 搜索次数不超过 3 轮
- 每轮精读不超过 5 个片段
- 单次回答引用不超过 8 个片段
"""
```

### 工具列表

| 工具名 | 功能 | 是否需要 LLM |
|--------|------|-------------|
| rewrite_and_decompose | 查询改写 | ✅ 是 |
| query_knowledge_base | 语义搜索 | ❌ 否 |
| keyword_search | 关键词搜索 | ❌ 否 |
| rerank_results | 结果融合 | ❌ 否 |
| get_file_summary | 文档摘要 | ❌ 否 |
| get_files_meta | 文件元数据 | ❌ 否 |
| read_file_chunks | 精读片段 | ❌ 否 |
| list_files | 浏览文件 | ❌ 否 |
| reflect_on_answer | 自我反思 | ✅ 是 |

---

## 当前项目实现

### 文件位置

```
D:\Project\Visual Studio Code\VirtuMate\Live2D-LLM-Chat\plugins\
├── agentic_rag_plugin.py   # 简单的 RAG（非 Agentic）
└── kb_controller.py        # 知识库控制器
```

### 问题分析

#### 1. 没有 LLM 参与

**代码** (agentic_rag_plugin.py 第76-155行):
```python
def _run_agentic_rag(kb, kb_id, question):
    # Step 1: 查询分析（简化：直接用原始问题）
    logger.info("[RAG] Step 1: 查询分析 - '%s'", question[:50])
    
    # Step 2: 双通道检索
    sem_result = kb.search(kb_id, question, top_k=10)
    kw_result = kb.keyword_search(kb_id, question, top_k=10)
    
    # Step 3: RRF 融合
    ranked = _rrf_fusion(sem_chunks, kw_chunks, top_n=5)
    
    # Step 4: 宏观定位
    # ...
    
    # Step 5: 精读片段
    # ...
    
    # Step 6: 自我反思（简化：检查是否有内容）
    if not chunks_read:
        return "知识库中未找到相关信息。"
    
    # Step 7: 生成回答（模板化）
    answer = (
        f"根据知识库内容，以下是相关信息：\n\n"
        f"{context}\n\n"
        f"---\n"
        f"引用：{'; '.join(refs)}"
    )
```

**问题**:
- ❌ 没有调用 LLM 进行查询改写
- ❌ 没有调用 LLM 进行自我反思
- ❌ 没有调用 LLM 生成答案
- ❌ 只是简单拼接上下文

#### 2. 没有自我反思

**代码** (agentic_rag_plugin.py 第120-123行):
```python
# Step 6: 自我反思（简化：检查是否有内容）
if not chunks_read:
    return "知识库中未找到相关信息。请尝试换一种表述。"
```

**问题**:
- ❌ 只检查是否有内容
- ❌ 没有评估答案质量
- ❌ 没有回环补充搜索

#### 3. 没有 Agent 循环

**代码** (agentic_rag_plugin.py):
```python
# 只是简单的函数调用，没有 Agent 循环
def _run_agentic_rag(kb, kb_id, question):
    # Step 1 -> Step 2 -> Step 3 -> ... -> Step 7
    # 没有回环，没有自主决策
```

**问题**:
- ❌ 只是简单的脚本流程
- ❌ 没有自主决策能力
- ❌ 没有多轮推理

---

## 功能对比表

| 功能 | 真正的 Agentic RAG | 当前实现 | 差异 |
|------|-------------------|---------|------|
| **LLM 参与查询改写** | ✅ 是 | ❌ 否 | 缺少 LLM |
| **LLM 自我反思** | ✅ 是 | ❌ 否 | 缺少 LLM |
| **LLM 生成答案** | ✅ 是 | ❌ 否 | 缺少 LLM |
| **Agent 循环决策** | ✅ 是 | ❌ 否 | 缺少 Agent |
| **工具调用** | 9 个工具 | 4 个工具 | 缺少工具 |
| **多轮推理** | ✅ 是 | ❌ 否 | 缺少推理 |
| **回环机制** | ✅ 最多3次 | ❌ 无 | 缺少回环 |
| **系统提示** | ✅ 是 | ❌ 否 | 缺少提示 |

---

## 关键差异分析

### 1. 架构差异

**真正的 Agentic RAG**:
```
用户问题
    ↓
Agent (LangGraph ReAct)
    ↓
LLM 推理
    ↓
工具调用
    ↓
LLM 反思
    ↓
最终答案
```

**当前实现**:
```
用户问题
    ↓
脚本流程
    ↓
模板化答案
```

### 2. 智能程度差异

**真正的 Agentic RAG**:
- ✅ LLM 分析问题意图
- ✅ LLM 改写查询
- ✅ LLM 评估答案质量
- ✅ LLM 生成最终答案
- ✅ Agent 自主决策

**当前实现**:
- ❌ 没有 LLM 参与
- ❌ 只是简单脚本
- ❌ 模板化答案
- ❌ 没有智能决策

### 3. 工具使用差异

**真正的 Agentic RAG** (9个工具):
- rewrite_and_decompose - 查询改写
- query_knowledge_base - 语义搜索
- keyword_search - 关键词搜索
- rerank_results - 结果融合
- get_file_summary - 文档摘要
- get_files_meta - 文件元数据
- read_file_chunks - 精读片段
- list_files - 浏览文件
- reflect_on_answer - 自我反思

**当前实现** (4个工具):
- add_task - 添加任务
- list_tasks - 查看任务
- complete_task - 完成任务
- delete_task - 删除任务

---

## 结论

### 真正的 Agentic RAG

✅ **使用 LangGraph** 创建 ReAct Agent
✅ **使用 ChatOpenAI (MIMO)** 作为 LLM
✅ **Agent 自主决策**调用工具
✅ **LLM 参与**查询改写、自我反思、答案生成
✅ **支持多轮推理**和回环机制
✅ **有系统提示**指导工作流程

### 当前项目实现

❌ **没有使用 LLM**
❌ **没有 Agent 循环**
❌ **只是简单的脚本流程**
❌ **文件名具有误导性**

### 建议

1. **整合真正的 Agentic RAG** - 将 `D:\Project\Visual Studio Code\agentic_rag\agentic_rag.py` 整合到项目中
2. **重命名当前实现** - 将 `agentic_rag_plugin.py` 改为 `simple_rag_plugin.py` 或 `basic_rag_plugin.py`
3. **更新文档** - 明确说明两种实现的区别

---

## 技术建议

### 如何整合真正的 Agentic RAG

1. **复制文件**:
   - 将 `agentic_rag.py` 复制到 `plugins/` 目录
   - 重命名为 `agentic_rag_plugin.py`

2. **修改插件接口**:
   - 适配 PluginBase 接口
   - 实现 on_register_tools() 和 on_execute_tool()

3. **配置 LLM**:
   - 使用项目的 LLM 配置
   - 确保 MIMO API 密钥正确

4. **测试验证**:
   - 运行测试确保功能正常
   - 验证 Agent 循环和回环机制

---

## 参考文件

- **真正的 Agentic RAG**: `D:\Project\Visual Studio Code\agentic_rag\agentic_rag.py`
- **当前项目实现**: `D:\Project\Visual Studio Code\VirtuMate\Live2D-LLM-Chat\plugins\agentic_rag_plugin.py`
- **知识库控制器**: `kb_controller.py`

---

**报告版本**: v1.0
**分析日期**: 2026-06-22
**结论**: 真正的 Agentic RAG 需要 LLM 和 Agent 循环，当前实现只是简单的 RAG
