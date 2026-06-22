"""
阶段3测试文件：main.py IOCP集成验证

测试内容：
1. main.py 模块导入（语法检查）
2. IOCP 条件导入
3. MainManager 新增方法
4. 配置联动

注意：main.py 依赖完整的运行环境（Live2D、ASR、TTS等），
无法在单元测试中完整运行。本测试验证结构正确性。
"""

import sys
import os
import ast

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from log_config import get_logger

logger = get_logger("test_main_iocp")


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


# ==================== 测试用例 ====================


def test_main_syntax():
    """测试1: main.py 语法正确性"""
    print_header("测试1: main.py 语法检查")

    main_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "main.py"
    )

    try:
        with open(main_path, "r", encoding="utf-8") as f:
            source = f.read()
        ast.parse(source)
        print_result("语法检查", True, "main.py 无语法错误")
        return True
    except SyntaxError as e:
        print_result("语法检查", False, "行 %d: %s" % (e.lineno, e.msg))
        return False


def test_main_has_iocp_methods():
    """测试2: main.py 包含IOCP相关代码"""
    print_header("测试2: IOCP代码存在性检查")

    main_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "main.py"
    )

    with open(main_path, "r", encoding="utf-8") as f:
        source = f.read()

    checks = [
        ("IOCP事件循环导入", "from event_loop import" in source),
        ("异步包装器导入", "from async_wrapper import" in source),
        ("asyncio导入", "import asyncio" in source),
        ("run方法(IOCP)", "def run(self):" in source),
        ("_async_input_loop方法", "async def _async_input_loop(self):" in source),
        ("_cleanup方法", "def _cleanup(self):" in source),
        ("asyncio.sleep调用", "await asyncio.sleep" in source),
        ("run_sync调用", "await run_sync" in source),
        ("IOCP调度器使用", "scheduler = get_scheduler()" in source),
    ]

    all_pass = True
    for name, result in checks:
        print_result(name, result)
        if not result:
            all_pass = False

    return all_pass


def test_config_iocp_settings():
    """测试3: 配置文件IOCP设置"""
    print_header("测试3: 配置文件IOCP设置")

    from config import Config

    checks = [
        ("IOCP_MAX_WORKERS 存在", hasattr(Config, "IOCP_MAX_WORKERS")),
        ("IOCP_TASK_CHECK_INTERVAL 存在", hasattr(Config, "IOCP_TASK_CHECK_INTERVAL")),
        ("ASYNC_WRAPPER_TIMEOUT 存在", hasattr(Config, "ASYNC_WRAPPER_TIMEOUT")),
    ]

    all_pass = True
    for name, result in checks:
        print_result(name, result)
        if not result:
            all_pass = False

    return all_pass


def test_iocp_imports_available():
    """测试4: IOCP模块可导入"""
    print_header("测试4: IOCP模块可导入")

    checks = []
    try:
        from event_loop import IOCPScheduler, get_scheduler, shutdown_scheduler
        checks.append(("event_loop 模块", True))
    except ImportError as e:
        checks.append(("event_loop 模块", False))

    try:
        from async_wrapper import AsyncWrapper, run_sync
        checks.append(("async_wrapper 模块", True))
    except ImportError as e:
        checks.append(("async_wrapper 模块", False))

    try:
        from plugin_base import PluginBase
        has_tasks = hasattr(PluginBase, "on_register_background_tasks")
        has_complete = hasattr(PluginBase, "on_task_complete")
        has_scheduler = hasattr(PluginBase, "get_scheduler")
        checks.append(("PluginBase IOCP接口", all([has_tasks, has_complete, has_scheduler])))
    except Exception as e:
        checks.append(("PluginBase IOCP接口", False))

    try:
        from plugin_registry import PluginRegistry
        r = PluginRegistry()
        checks.append(("PluginRegistry初始化", r is not None))
    except Exception as e:
        checks.append(("PluginRegistry初始化", False))

    all_pass = True
    for name, result in checks:
        print_result(name, result)
        if not result:
            all_pass = False

    return all_pass


def test_backward_compatibility():
    """测试5: 向后兼容性"""
    print_header("测试5: 向后兼容性")

    try:
        from plugin_registry import PluginRegistry
        registry = PluginRegistry()
        tasks = registry.get_background_tasks()
        print_result("PluginRegistry初始化正常", True)
        print_result("后台任务存储初始化为空", len(tasks) == 0)
        return True
    except Exception as e:
        print_result("向后兼容性", False, str(e))
        return False


# ==================== 运行所有测试 ====================


def run_all_tests():
    logger.info("")
    logger.info("🚀" * 30)
    logger.info("  main.py IOCP 集成验证")
    logger.info("🚀" * 30)

    tests = [
        ("main.py 语法检查", test_main_syntax),
        ("IOCP代码存在性", test_main_has_iocp_methods),
        ("配置文件IOCP设置", test_config_iocp_settings),
        ("IOCP模块可导入", test_iocp_imports_available),
        ("向后兼容性", test_backward_compatibility),
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
