"""
阶段2测试文件：插件系统IOCP集成测试

测试内容：
1. PluginBase 新增接口
2. PluginRegistry IOCP模式
3. 后台任务注册与执行
4. 向后兼容性

使用方法：
    python test/test_plugin_iocp.py
"""

import sys
import os
import time

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from log_config import get_logger
from plugin_base import PluginBase
from plugin_registry import PluginRegistry
from event_loop import IOCPScheduler, reset_scheduler
from config import Config

logger = get_logger("test_plugin_iocp")


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


# ==================== 测试插件定义 ====================


class TestPlugin(PluginBase):
    """测试插件：实现后台任务注册"""
    name = "test_scheduler"
    version = "1.0"

    def __init__(self):
        super().__init__()
        self.check_count = 0
        self.reminders = []
        self.task_complete_called = False

    def on_startup(self, app):
        super().on_startup(app)

    def on_register_background_tasks(self):
        return [
            {
                "task_id": "check_reminders",
                "interval": 0.2,
                "callback": self._check_reminders,
                "description": "检查提醒",
                "immediate": True,
            }
        ]

    def _check_reminders(self):
        self.check_count += 1
        if self.check_count == 3:
            return "到时间了！"
        return None

    def on_task_complete(self, task_id, result):
        if result:
            self.task_complete_called = True
            self.reminders.append(result)


class LegacyPlugin(PluginBase):
    """传统插件：不实现IOCP接口，验证向后兼容"""
    name = "legacy"
    version = "1.0"

    def on_user_input(self, text):
        return None

    def on_tick(self, app):
        pass


class DummyApp:
    """模拟 MainManager"""
    pass


# ==================== 测试用例 ====================


def test_plugin_base_new_interfaces():
    """测试1: PluginBase 新增IOCP接口"""
    print_header("测试1: PluginBase 新增接口")

    plugin = PluginBase()

    # 检查新接口存在
    has_register = hasattr(plugin, "on_register_background_tasks")
    has_complete = hasattr(plugin, "on_task_complete")
    has_scheduler = hasattr(plugin, "get_scheduler")

    print_result("on_register_background_tasks 方法存在", has_register)
    print_result("on_task_complete 方法存在", has_complete)
    print_result("get_scheduler 方法存在", has_scheduler)

    # 检查默认实现
    tasks = plugin.on_register_background_tasks()
    print_result("默认返回空列表", tasks == [])

    result = plugin.on_task_complete("test", "result")
    print_result("默认返回None", result is None)

    return all([has_register, has_complete, has_scheduler, tasks == []])


def test_plugin_registry_iocp_mode():
    """测试2: PluginRegistry IOCP模式"""
    print_header("测试2: PluginRegistry IOCP模式")

    reset_scheduler()

    # 创建PluginRegistry
    registry = PluginRegistry()
    print_result("PluginRegistry创建", registry is not None)

    # 后台任务存储
    print_result("后台任务存储初始化", registry._background_tasks == {})

    return True


def test_background_task_registration():
    """测试3: 后台任务注册"""
    print_header("测试3: 后台任务注册")

    reset_scheduler()

    registry = PluginRegistry()

    # 手动注册测试插件
    plugin = TestPlugin()
    registry.register(plugin)

    app = DummyApp()
    registry.broadcast_on_startup(app)

    # 检查后台任务是否被收集
    tasks = registry.get_background_tasks()
    print_result("后台任务已收集", len(tasks) > 0, "任务数: %d" % len(tasks))

    if len(tasks) > 0:
        task_key = list(tasks.keys())[0]
        task_info = tasks[task_key]
        print_result("任务来源插件", task_info.get("plugin") == "test_scheduler")
        print_result("任务间隔", task_info.get("interval") == 0.2)

    return len(tasks) > 0


def test_background_task_execution():
    """测试4: 后台任务执行"""
    print_header("测试4: 后台任务执行")

    reset_scheduler()

    registry = PluginRegistry()
    plugin = TestPlugin()
    registry.register(plugin)

    app = DummyApp()
    registry.broadcast_on_startup(app)

    # 运行调度器1秒
    scheduler = registry.get_background_tasks()
    from event_loop import get_scheduler
    sched = get_scheduler()
    sched.run_for(1.0)

    # 检查任务是否执行了
    print_result("任务执行次数 >= 3", plugin.check_count >= 3, "执行次数: %d" % plugin.check_count)
    print_result("任务完成回调触发", plugin.task_complete_called, "提醒: %s" % str(plugin.reminders))

    reset_scheduler()
    return plugin.check_count >= 3


def test_backward_compatibility():
    """测试5: 向后兼容性"""
    print_header("测试5: 向后兼容性")

    reset_scheduler()

    # 现在总是收集后台任务（摒弃传统模式）
    registry = PluginRegistry()
    plugin = TestPlugin()
    registry.register(plugin)

    app = DummyApp()
    registry.broadcast_on_startup(app)

    tasks = registry.get_background_tasks()
    print_result("总是收集后台任务", len(tasks) > 0)

    # LegacyPlugin 不实现IOCP接口，也应该正常工作
    legacy = LegacyPlugin()
    registry.register(legacy)

    # 检查 Hook 检测
    hooks = []
    for hook in ("on_register_background_tasks", "on_task_complete"):
        base_method = getattr(PluginBase, hook)
        override = getattr(type(legacy), hook)
        if override is not base_method:
            hooks.append(hook)
    print_result("LegacyPlugin 不覆写IOCP Hook", len(hooks) == 0)

    reset_scheduler()
    return len(tasks) > 0


def test_multiple_plugins_tasks():
    """测试6: 多插件后台任务"""
    print_header("测试6: 多插件后台任务")

    reset_scheduler()

    registry = PluginRegistry()

    class PluginA(PluginBase):
        name = "plugin_a"
        version = "1.0"
        def __init__(self):
            super().__init__()
            self.count = 0
        def on_register_background_tasks(self):
            return [{"task_id": "task_a", "interval": 0.2, "callback": lambda: self._inc(), "immediate": True}]
        def _inc(self):
            self.count += 1

    class PluginB(PluginBase):
        name = "plugin_b"
        version = "1.0"
        def __init__(self):
            super().__init__()
            self.count = 0
        def on_register_background_tasks(self):
            return [{"task_id": "task_b", "interval": 0.3, "callback": lambda: self._inc(), "immediate": True}]
        def _inc(self):
            self.count += 1

    a = PluginA()
    b = PluginB()
    registry.register(a)
    registry.register(b)

    app = DummyApp()
    registry.broadcast_on_startup(app)

    tasks = registry.get_background_tasks()
    print_result("两个插件都注册了任务", len(tasks) == 2, "任务数: %d" % len(tasks))

    from event_loop import get_scheduler
    sched = get_scheduler()
    sched.run_for(1.0)

    print_result("PluginA 任务执行", a.count >= 2, "执行次数: %d" % a.count)
    print_result("PluginB 任务执行", b.count >= 2, "执行次数: %d" % b.count)

    reset_scheduler()
    return a.count >= 2 and b.count >= 2


def test_empty_plugin_tasks():
    """测试7: 无后台任务的插件"""
    print_header("测试7: 无后台任务的插件")

    reset_scheduler()

    registry = PluginRegistry()
    legacy = LegacyPlugin()
    registry.register(legacy)

    app = DummyApp()
    registry.broadcast_on_startup(app)

    tasks = registry.get_background_tasks()
    print_result("无后台任务时为空", len(tasks) == 0)

    reset_scheduler()
    return len(tasks) == 0


# ==================== 运行所有测试 ====================


def run_all_tests():
    logger.info("")
    logger.info("🚀" * 30)
    logger.info("  插件系统 IOCP 集成测试")
    logger.info("🚀" * 30)

    tests = [
        ("PluginBase 新增接口", test_plugin_base_new_interfaces),
        ("PluginRegistry IOCP模式", test_plugin_registry_iocp_mode),
        ("后台任务注册", test_background_task_registration),
        ("后台任务执行", test_background_task_execution),
        ("向后兼容性", test_backward_compatibility),
        ("多插件后台任务", test_multiple_plugins_tasks),
        ("无后台任务插件", test_empty_plugin_tasks),
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
