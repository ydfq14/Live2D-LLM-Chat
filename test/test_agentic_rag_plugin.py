"""
Agentic RAG 插件集成测试

测试内容：
1. 插件自动加载
2. 知识库控制器初始化
3. 工具注册（ask_knowledge_base）
4. 工具执行（Mock Agent 模式）
5. Agent 执行失败回退测试
6. LLM 上下文注入
7. 前端 HTML 面板
8. 关闭清理

使用方法：
    python test/test_agentic_rag_plugin.py
"""

import sys
import os
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from log_config import get_logger
from plugin_registry import PluginRegistry
from event_loop import reset_scheduler

logger = get_logger("test_agentic_rag")


def print_header(title):
    logger.info("")
    logger.info("=" * 60)
    logger.info("  %s", title)
    logger.info("=" * 60)


def print_result(test_name, success, message=""):
    status = "✅ PASS" if success else "❌ FAIL"
    logger.info("%s | %s", status, test_name)
    if message:
        logger.info("       %s", message)


class DummyApp:
    pass


def get_agentic_rag_plugin():
    """获取已初始化的 agentic_rag 插件实例。"""
    reset_scheduler()
    registry = PluginRegistry()
    registry.scan_and_load()
    plugin = registry.get("agentic_rag")
    return plugin


# ==================== 测试1: 插件自动加载 ====================


def test_plugin_load():
    """测试1: 插件自动加载"""
    print_header("测试1: 插件自动加载")

    reset_scheduler()
    registry = PluginRegistry()
    loaded = registry.scan_and_load()

    print_result("agentic_rag 已加载", "agentic_rag" in loaded, f"已加载: {loaded}")

    plugin = registry.get("agentic_rag")
    print_result("插件实例获取", plugin is not None)
    print_result("插件名称", plugin.name == "agentic_rag")
    print_result("插件版本", plugin.version == "2.0")

    return "agentic_rag" in loaded


# ==================== 测试2: 知识库控制器初始化 ====================


def test_kb_initialization():
    """测试2: 知识库控制器初始化"""
    print_header("测试2: 知识库控制器初始化")

    plugin = get_agentic_rag_plugin()

    # Mock kb_controller 避免实际初始化 Milvus
    with patch("kb_controller.MilvusLiteKBController") as MockKB:
        mock_kb = MagicMock()
        mock_kb.listFilesPaginated.return_value = []
        MockKB.return_value = mock_kb

        plugin.on_startup(DummyApp())

        print_result("KB 控制器已初始化", plugin._kb is not None)
        print_result("Agent 模型已配置", len(plugin._agent_model) > 0, f"模型: {plugin._agent_model}")

    reset_scheduler()
    return plugin._kb is not None


# ==================== 测试3: 工具注册 ====================


def test_tool_registration():
    """测试3: 工具注册验证"""
    print_header("测试3: 工具注册验证")

    plugin = get_agentic_rag_plugin()

    # Mock KB 初始化
    with patch("kb_controller.MilvusLiteKBController") as MockKB:
        mock_kb = MagicMock()
        mock_kb.listFilesPaginated.return_value = [
            {"id": 1, "filename": "test.pdf", "chunk_count": 10, "status": "done"}
        ]
        MockKB.return_value = mock_kb
        plugin.on_startup(DummyApp())

    tools = plugin.on_register_tools()

    print_result("工具数量为1", len(tools) == 1, f"实际: {len(tools)}")

    if tools:
        tool = tools[0]
        func = tool.get("function", {})
        print_result("工具名称为 ask_knowledge_base", func.get("name") == "ask_knowledge_base")
        print_result("工具描述包含智能检索", "智能检索" in func.get("description", ""))
        params = func.get("parameters", {}).get("properties", {})
        print_result("工具参数包含 question", "question" in params)

    # KB 未初始化时应返回空
    plugin._kb = None
    empty_tools = plugin.on_register_tools()
    print_result("KB 未初始化时返回空工具", len(empty_tools) == 0)

    reset_scheduler()
    return len(tools) == 1


# ==================== 测试4: 工具执行（Mock Agent） ====================


def test_tool_execution_mock_agent():
    """测试4: 工具执行（Mock Agent 模式）"""
    print_header("测试4: 工具执行（Mock Agent 模式）")

    plugin = get_agentic_rag_plugin()

    # Mock KB 初始化
    with patch("kb_controller.MilvusLiteKBController") as MockKB:
        mock_kb = MagicMock()
        mock_kb.listFilesPaginated.return_value = []
        MockKB.return_value = mock_kb
        plugin.on_startup(DummyApp())

    # Mock Agent
    mock_agent = MagicMock()
    mock_message = MagicMock()
    mock_message.content = "这是 Agent 的合成答案：知识库中包含相关信息..."
    mock_agent.invoke.return_value = {"messages": [mock_message]}
    plugin._agent = mock_agent

    # 执行工具
    result = plugin.on_execute_tool("ask_knowledge_base", {"question": "什么是机器学习？"})

    print_result("Agent 执行返回结果", len(result) > 0, f"返回 {len(result)} 字符")
    print_result("结果包含 Agent 答案", "Agent" in result or "合成答案" in result, result[:80])
    print_result("Agent.invoke 被调用", mock_agent.invoke.called)

    # 未知工具返回空
    empty = plugin.on_execute_tool("unknown_tool", {})
    print_result("未知工具返回空", empty == "")

    reset_scheduler()
    return len(result) > 0


# ==================== 测试5: Agent 回退测试 ====================


def test_tool_execution_fallback():
    """测试5: Agent 执行失败回退到基础检索"""
    print_header("测试5: Agent 执行失败回退测试")

    plugin = get_agentic_rag_plugin()

    # Mock KB 初始化
    with patch("kb_controller.MilvusLiteKBController") as MockKB:
        mock_kb = MagicMock()
        mock_kb.listFilesPaginated.return_value = []
        mock_kb.search.return_value = '[{"fileId": 1, "chunkIndex": 0, "content": "测试内容", "score": 0.9}]'
        mock_kb.keyword_search.return_value = None
        mock_kb.readFileChunks.return_value = '[{"fileId": 1, "chunkIndex": 0, "content": "测试内容"}]'
        MockKB.return_value = mock_kb
        plugin.on_startup(DummyApp())

    # 模拟 Agent 创建失败
    plugin._agent = None
    with patch("plugins.agentic_rag_agent.create_agent", side_effect=Exception("Agent 创建失败")):
        result = plugin.on_execute_tool("ask_knowledge_base", {"question": "测试问题"})

    print_result("回退返回结果", len(result) > 0, f"返回 {len(result)} 字符")
    print_result("结果包含基础检索内容", "相关信息" in result or "知识库" in result or "测试内容" in result, result[:80])

    reset_scheduler()
    return len(result) > 0


# ==================== 测试6: LLM 上下文注入 ====================


def test_llm_context():
    """测试6: LLM 上下文注入"""
    print_header("测试6: LLM 上下文注入")

    plugin = get_agentic_rag_plugin()

    # 未初始化时返回空
    ctx = plugin.on_llm_context("你好")
    print_result("未初始化时返回空", ctx == "")

    # Mock KB 初始化
    with patch("kb_controller.MilvusLiteKBController") as MockKB:
        mock_kb = MagicMock()
        mock_kb.listFilesPaginated.return_value = [
            {"id": 1, "filename": "test.pdf", "chunk_count": 10, "status": "done"},
            {"id": 2, "filename": "guide.md", "chunk_count": 5, "status": "done"},
        ]
        MockKB.return_value = mock_kb
        plugin.on_startup(DummyApp())

    ctx = plugin.on_llm_context("什么是知识库？")
    print_result("有文件时注入上下文", "知识库状态" in ctx, ctx[:100])
    print_result("上下文包含文件数", "2 个文件" in ctx)
    print_result("上下文包含 Agent 信息", "智能检索 Agent" in ctx)

    # 空知识库返回空
    plugin._file_count = 0
    ctx = plugin.on_llm_context("你好")
    print_result("空知识库返回空", ctx == "")

    reset_scheduler()
    return "知识库状态" in ctx or plugin._file_count == 0


# ==================== 测试7: 前端 HTML ====================


def test_frontend_html():
    """测试7: 前端 HTML 面板"""
    print_header("测试7: 前端 HTML 面板")

    plugin = get_agentic_rag_plugin()

    html = plugin.get_frontend_html()
    print_result("HTML 非空", len(html) > 0)
    print_result("包含知识库标题", "知识库" in html)
    print_result("包含 Agentic RAG", "Agentic RAG" in html)
    print_result("包含 Agent 模型信息", "Agent" in html)

    reset_scheduler()
    return len(html) > 0


# ==================== 测试8: 关闭清理 ====================


def test_shutdown():
    """测试8: 关闭清理"""
    print_header("测试8: 关闭清理")

    plugin = get_agentic_rag_plugin()

    # Mock KB 初始化
    with patch("kb_controller.MilvusLiteKBController") as MockKB:
        mock_kb = MagicMock()
        mock_kb.listFilesPaginated.return_value = []
        MockKB.return_value = mock_kb
        plugin.on_startup(DummyApp())

    # 设置一个 mock agent
    plugin._agent = MagicMock()

    print_result("关闭前 KB 存在", plugin._kb is not None)
    print_result("关闭前 Agent 存在", plugin._agent is not None)

    plugin.on_shutdown()

    print_result("关闭后 KB 为 None", plugin._kb is None)
    print_result("关闭后 Agent 为 None", plugin._agent is None)

    reset_scheduler()
    return plugin._kb is None and plugin._agent is None


# ==================== 运行所有测试 ====================


def run_all_tests():
    logger.info("")
    logger.info("🚀" * 30)
    logger.info("  Agentic RAG 插件测试")
    logger.info("🚀" * 30)

    tests = [
        ("插件自动加载", test_plugin_load),
        ("知识库控制器初始化", test_kb_initialization),
        ("工具注册验证", test_tool_registration),
        ("工具执行（Mock Agent）", test_tool_execution_mock_agent),
        ("Agent 回退测试", test_tool_execution_fallback),
        ("LLM 上下文注入", test_llm_context),
        ("前端 HTML 面板", test_frontend_html),
        ("关闭清理", test_shutdown),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            success = test_func()
            results.append((test_name, success))
        except Exception as e:
            logger.error("❌ FAIL | %s | 异常: %s", test_name, e)
            import traceback
            traceback.print_exc()
            results.append((test_name, False))

    # 测试总结
    print_header("测试总结")

    passed = 0
    for name, success in results:
        status = "✅" if success else "❌"
        logger.info("%s %s", status, name)
        if success:
            passed += 1

    logger.info("")
    logger.info("总计: %d | 通过: %d | 失败: %d", len(results), passed, len(results) - passed)

    if passed == len(results):
        logger.info("🎉 全部测试通过！")
    else:
        logger.info("⚠️  %d 个测试失败", len(results) - passed)

    return passed == len(results)


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
