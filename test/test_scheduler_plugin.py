"""
阶段4测试文件：日程管理插件测试

测试内容：
1. 插件加载
2. 任务CRUD（添加/查看/完成/删除）
3. 后台提醒检查
4. LangGraph工具注册与执行
5. LLM上下文注入
6. 前端HTML
"""

import sys
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from log_config import get_logger
from plugin_registry import PluginRegistry
from event_loop import IOCPScheduler, reset_scheduler

logger = get_logger("test_scheduler")


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


def get_scheduler_plugin():
    """获取已初始化的scheduler插件实例（干净状态）"""
    reset_scheduler()
    registry = PluginRegistry()
    registry.scan_and_load()
    plugin = registry.get("scheduler")
    # 先初始化 _data_dir
    plugin._data_dir = Path(plugin.get_data_dir())
    # 删除残留的任务文件，保证测试隔离
    tasks_file = plugin._data_dir / "tasks.json"
    if tasks_file.exists():
        tasks_file.unlink()
    # 初始化插件（会加载空数据）
    plugin.on_startup(DummyApp())
    return plugin


# ==================== 测试用例 ====================


def test_plugin_load():
    """测试1: 插件自动加载"""
    print_header("测试1: 插件自动加载")

    registry = PluginRegistry()
    loaded = registry.scan_and_load()

    print_result("scheduler插件已加载", "scheduler" in loaded, "已加载: %s" % loaded)

    plugin = registry.get("scheduler")
    print_result("插件实例获取", plugin is not None)

    if plugin:
        print_result("插件名称", plugin.name == "scheduler")
        print_result("插件版本", plugin.version == "1.0")

    return "scheduler" in loaded and plugin is not None


def test_add_task():
    """测试2: 添加任务"""
    print_header("测试2: 添加任务")

    plugin = get_scheduler_plugin()

    # 添加任务
    now = datetime.now()
    future = (now + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    result = plugin._add_task("测试会议", future, "项目周会")
    print_result("添加任务返回成功", "已添加" in result, result)

    # 检查任务存储
    tasks = plugin._tasks
    print_result("任务已存储", len(tasks) == 1)

    if tasks:
        task = list(tasks.values())[0]
        print_result("任务标题正确", task.title == "测试会议")
        print_result("任务状态为pending", task.status == "pending")
        print_result("任务描述正确", task.description == "项目周会")

    # 添加第二个任务
    result2 = plugin._add_task("学习Python", future)
    print_result("添加第二个任务", len(plugin._tasks) == 2)

    reset_scheduler()
    return len(plugin._tasks) == 2


def test_list_tasks():
    """测试3: 查看任务"""
    print_header("测试3: 查看任务")

    plugin = get_scheduler_plugin()

    # 添加今天和明天的任务
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    today_task_time = now.replace(hour=23, minute=59).strftime("%Y-%m-%d %H:%M")
    plugin._add_task("今天任务A", today_task_time)
    plugin._add_task("今天任务B", today_task_time)

    # 查看今天的任务
    result = plugin._list_tasks(today)
    print_result("查看今天任务", "今天任务A" in result, result[:100])

    # 查看明天的任务（应该为空）
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    result2 = plugin._list_tasks(tomorrow)
    print_result("明天无任务", "没有待办" in result2)

    # 查看所有任务
    result3 = plugin._list_tasks()
    print_result("默认查看今天", "今天任务" in result3)

    reset_scheduler()
    return True


def test_complete_task():
    """测试4: 完成任务"""
    print_header("测试4: 完成任务")

    plugin = get_scheduler_plugin()

    future = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    result = plugin._add_task("待完成任务", future)
    task_id = list(plugin._tasks.keys())[0]

    # 完成任务
    complete_result = plugin._complete_task(task_id)
    print_result("完成任务返回成功", "已完成" in complete_result, complete_result)

    task = plugin._tasks[task_id]
    print_result("任务状态变为completed", task.status == "completed")
    print_result("完成时间已记录", task.completed_at is not None)

    # 不存在的任务
    result2 = plugin._complete_task("nonexistent")
    print_result("不存在的任务返回提示", "未找到" in result2)

    reset_scheduler()
    return task.status == "completed"


def test_delete_task():
    """测试5: 删除任务"""
    print_header("测试5: 删除任务")

    plugin = get_scheduler_plugin()

    future = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    plugin._add_task("待删除任务", future)
    task_id = list(plugin._tasks.keys())[0]
    count_before = len(plugin._tasks)

    # 删除任务
    result = plugin._delete_task(task_id)
    print_result("删除任务返回成功", "已删除" in result, result)
    print_result("任务数量减少", len(plugin._tasks) == count_before - 1)

    # 不存在的任务
    result2 = plugin._delete_task("nonexistent")
    print_result("不存在的任务返回提示", "未找到" in result2)

    reset_scheduler()
    return len(plugin._tasks) == count_before - 1


def test_reminder_check():
    """测试6: 后台提醒检查"""
    print_header("测试6: 后台提醒检查")

    plugin = get_scheduler_plugin()

    # 添加一个"现在"的任务（1分钟内）
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M")
    plugin._add_task("立即提醒测试", now_str)

    # 手动触发检查
    reminder = plugin._check_reminders()
    print_result("触发提醒", reminder is not None, "提醒内容: %s" % reminder)
    print_result("提醒包含任务名", reminder is not None and "立即提醒测试" in reminder)

    # 标记已发送后不再提醒
    reminder2 = plugin._check_reminders()
    print_result("不再重复提醒", reminder2 is None)

    reset_scheduler()
    return reminder is not None


def test_expired_task():
    """测试7: 过期任务标记"""
    print_header("测试7: 过期任务标记")

    plugin = get_scheduler_plugin()

    # 添加一个已过期的任务（2小时前）
    past = (datetime.now() - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
    plugin._add_task("过期任务", past)
    task_id = list(plugin._tasks.keys())[0]

    # 触发检查
    plugin._check_reminders()

    task = plugin._tasks[task_id]
    print_result("过期任务标记为missed", task.status == "missed")

    reset_scheduler()
    return task.status == "missed"


def test_tool_registration():
    """测试8: LangGraph工具注册"""
    print_header("测试8: LangGraph工具注册")

    plugin = get_scheduler_plugin()

    tools = plugin.on_register_tools()
    print_result("工具数量为4", len(tools) == 4)

    tool_names = [t["function"]["name"] for t in tools]
    print_result("add_task工具", "add_task" in tool_names)
    print_result("list_tasks工具", "list_tasks" in tool_names)
    print_result("complete_task工具", "complete_task" in tool_names)
    print_result("delete_task工具", "delete_task" in tool_names)

    reset_scheduler()
    return len(tools) == 4


def test_tool_execution():
    """测试9: 工具执行"""
    print_header("测试9: 工具执行")

    plugin = get_scheduler_plugin()

    future = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")

    # 通过工具接口添加任务
    result = plugin.on_execute_tool("add_task", {
        "title": "工具添加的任务",
        "datetime": future,
        "description": "通过LangGraph工具添加",
    })
    print_result("工具添加任务", "已添加" in result, result[:80])

    # 通过工具接口查看任务
    today = datetime.now().strftime("%Y-%m-%d")
    result2 = plugin.on_execute_tool("list_tasks", {"date": today})
    print_result("工具查看任务", "工具添加的任务" in result2)

    # 完成任务
    task_id = list(plugin._tasks.keys())[0]
    result3 = plugin.on_execute_tool("complete_task", {"task_id": task_id})
    print_result("工具完成任务", "已完成" in result3)

    # 未知工具
    result4 = plugin.on_execute_tool("unknown_tool", {})
    print_result("未知工具返回空", result4 == "")

    reset_scheduler()
    return "已添加" in result


def test_llm_context():
    """测试10: LLM上下文注入"""
    print_header("测试10: LLM上下文注入")

    plugin = get_scheduler_plugin()

    # 无任务时返回空
    ctx = plugin.on_llm_context("你好")
    print_result("无任务时返回空", ctx == "")

    # 添加今天任务
    now = datetime.now()
    today_time = now.replace(hour=23, minute=58).strftime("%Y-%m-%d %H:%M")
    plugin._add_task("下午开会", today_time)

    ctx = plugin.on_llm_context("今天有什么安排")
    print_result("有任务时注入上下文", "日程提醒" in ctx, ctx[:100])
    print_result("上下文包含任务名", "下午开会" in ctx)

    reset_scheduler()
    return "日程提醒" in ctx


def test_persistence():
    """测试11: 数据持久化"""
    print_header("测试11: 数据持久化")

    plugin = get_scheduler_plugin()

    future = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    plugin._add_task("持久化测试任务", future)
    task_id = list(plugin._tasks.keys())[0]

    # 保存
    plugin._save_tasks()

    # 重新加载
    plugin._tasks = {}
    plugin._load_tasks()

    print_result("任务重新加载成功", task_id in plugin._tasks)

    success = task_id in plugin._tasks
    if task_id in plugin._tasks:
        task = plugin._tasks[task_id]
        print_result("任务标题保留", task.title == "持久化测试任务")
        print_result("任务状态保留", task.status == "pending")

    # 清理
    plugin._tasks = {}
    plugin._save_tasks()

    reset_scheduler()
    return success


def test_frontend_html():
    """测试12: 前端HTML"""
    print_header("测试12: 前端HTML")

    plugin = get_scheduler_plugin()

    html = plugin.get_frontend_html()
    print_result("HTML非空", len(html) > 0)
    print_result("包含scheduler-wrap", "scheduler-wrap" in html)
    print_result("包含JavaScript", "schRefresh" in html)
    print_result("包含添加功能", "schAdd" in html)

    reset_scheduler()
    return len(html) > 0


# ==================== 运行所有测试 ====================


def run_all_tests():
    logger.info("")
    logger.info("🚀" * 30)
    logger.info("  日程管理插件测试")
    logger.info("🚀" * 30)

    tests = [
        ("插件自动加载", test_plugin_load),
        ("添加任务", test_add_task),
        ("查看任务", test_list_tasks),
        ("完成任务", test_complete_task),
        ("删除任务", test_delete_task),
        ("后台提醒检查", test_reminder_check),
        ("过期任务标记", test_expired_task),
        ("LangGraph工具注册", test_tool_registration),
        ("工具执行", test_tool_execution),
        ("LLM上下文注入", test_llm_context),
        ("数据持久化", test_persistence),
        ("前端HTML", test_frontend_html),
    ]

    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            logger.error("❌ 测试 %s 异常: %s", test_name, str(e))
            logger.exception("异常详情:")
            results.append((test_name, False))

    print_header("测试总结")
    passed = sum(1 for _, r in results if r)
    failed = len(results) - passed

    for name, r in results:
        logger.info("%s %s", "✅" if r else "❌", name)

    logger.info("")
    logger.info("总计: %d | 通过: %d | 失败: %d", len(results), passed, failed)

    if failed == 0:
        logger.info("🎉 所有测试通过！")
    else:
        logger.info("⚠️  %d 个测试失败", failed)

    reset_scheduler()
    return failed == 0


if __name__ == "__main__":
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    success = run_all_tests()
    sys.exit(0 if success else 1)
