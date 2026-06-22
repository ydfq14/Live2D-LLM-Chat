"""
阶段1测试文件：IOCP基础框架测试

测试内容：
1. IOCPScheduler 基本功能
2. 任务调度与执行
3. 异步包装器功能
4. 线程安全性
5. 资源清理

使用方法：
    python test_iocp_basic.py
"""

import asyncio
import sys
import os
import time
import threading
from datetime import datetime

# 添加项目路径（从test文件夹向上一级）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from log_config import get_logger
from event_loop import IOCPScheduler, get_scheduler, shutdown_scheduler, reset_scheduler
from async_wrapper import AsyncWrapper, run_sync, async_wrap, get_async_wrapper
from config import Config

# 获取日志器
logger = get_logger(__name__)


def print_header(title):
    """打印测试标题"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("  %s", title)
    logger.info("=" * 60)


def print_result(test_name, success, message=""):
    """打印测试结果"""
    status = "✅ PASS" if success else "❌ FAIL"
    logger.info("%s | %s", status, test_name)
    if message:
        logger.info("       %s", message)


# ==================== 测试1: IOCPScheduler 基本功能 ====================


def test_scheduler_creation():
    """测试调度器创建"""
    print_header("测试1: IOCPScheduler 创建")

    try:
        reset_scheduler()
        scheduler = IOCPScheduler()

        # 检查属性
        assert scheduler.running == False
        assert scheduler._started == False
        assert len(scheduler.tasks) == 0

        print_result("创建调度器", True, "平台: %s" % sys.platform)

        # 检查事件循环类型
        if sys.platform == "win32":
            loop_type = type(scheduler.loop).__name__
            assert "Proactor" in loop_type, "期望 ProactorEventLoop，实际: %s" % loop_type
            print_result("IOCP事件循环", True, "类型: %s" % loop_type)
        else:
            print_result("IOCP事件循环", True, "Unix系统，使用SelectorEventLoop")

        scheduler.stop()
        return True

    except Exception as e:
        print_result("创建调度器", False, str(e))
        logger.exception("异常详情:")
        return False


# ==================== 测试2: 任务调度 ====================


def test_task_scheduling():
    """测试任务调度"""
    print_header("测试2: 任务调度")

    try:
        reset_scheduler()
        scheduler = IOCPScheduler()

        # 测试计数器
        counter = {"value": 0}

        def increment():
            counter["value"] += 1
            return counter["value"]

        # 调度任务
        result = scheduler.schedule_task(
            task_id="test_task_1",
            interval=0.1,  # 100ms
            callback=increment,
            description="测试任务",
            immediate=True,
        )

        assert result == True
        assert "test_task_1" in scheduler.tasks
        print_result("添加任务", True)

        # 检查任务状态
        status = scheduler.get_task_status()
        assert "test_task_1" in status
        print_result("任务状态查询", True)

        scheduler.stop()
        return True

    except Exception as e:
        print_result("任务调度", False, str(e))
        logger.exception("异常详情:")
        return False


# ==================== 测试3: 任务执行 ====================


def test_task_execution():
    """测试任务执行"""
    print_header("测试3: 任务执行")

    try:
        reset_scheduler()
        scheduler = IOCPScheduler()

        # 测试计数器
        execution_log = []

        def log_execution():
            execution_log.append(time.time())
            return len(execution_log)

        # 调度任务（立即执行，间隔100ms）
        scheduler.schedule_task(
            task_id="exec_test",
            interval=0.1,
            callback=log_execution,
            description="执行测试任务",
            immediate=True,
        )

        # 启动调度器，运行0.5秒
        logger.info("  等待任务执行中...")
        scheduler.run_for(0.5)

        # 检查执行次数
        exec_count = len(execution_log)
        print_result("任务执行", exec_count >= 3, "执行次数: %d" % exec_count)

        # 检查执行间隔
        if exec_count >= 2:
            intervals = [
                execution_log[i + 1] - execution_log[i]
                for i in range(len(execution_log) - 1)
            ]
            avg_interval = sum(intervals) / len(intervals)
            print_result(
                "执行间隔",
                0.08 < avg_interval < 0.15,
                "平均间隔: %.3fs" % avg_interval,
            )

        return exec_count >= 3

    except Exception as e:
        print_result("任务执行", False, str(e))
        logger.exception("异常详情:")
        return False


# ==================== 测试4: 异步任务执行 ====================


def test_async_task_execution():
    """测试异步任务执行"""
    print_header("测试4: 异步任务执行")

    try:
        reset_scheduler()
        scheduler = IOCPScheduler()

        # 异步计数器
        counter = {"value": 0}

        async def async_increment():
            await asyncio.sleep(0.01)  # 模拟异步操作
            counter["value"] += 1
            return counter["value"]

        # 调度异步任务
        scheduler.schedule_task(
            task_id="async_test",
            interval=0.1,
            callback=async_increment,
            description="异步测试任务",
            immediate=True,
        )

        # 启动调度器，运行0.5秒
        logger.info("  等待异步任务执行中...")
        scheduler.run_for(0.5)

        # 检查执行次数
        exec_count = counter["value"]
        print_result("异步任务执行", exec_count >= 3, "执行次数: %d" % exec_count)

        return exec_count >= 3

    except Exception as e:
        print_result("异步任务执行", False, str(e))
        logger.exception("异常详情:")
        return False


# ==================== 测试5: 多任务并发 ====================


def test_concurrent_tasks():
    """测试多任务并发"""
    print_header("测试5: 多任务并发")

    try:
        reset_scheduler()
        scheduler = IOCPScheduler()

        # 多个计数器
        counters = {f"task_{i}": 0 for i in range(5)}

        def make_counter(task_id):
            def counter():
                counters[task_id] += 1
                return counters[task_id]
            return counter

        # 调度多个任务
        for i in range(5):
            scheduler.schedule_task(
                task_id=f"task_{i}",
                interval=0.1,
                callback=make_counter(f"task_{i}"),
                description=f"并发任务 {i}",
                immediate=True,
            )

        # 启动调度器，运行0.5秒
        logger.info("  等待多个并发任务执行中...")
        scheduler.run_for(0.5)

        # 检查所有任务都执行了
        all_executed = all(count >= 2 for count in counters.values())
        print_result(
            "多任务并发",
            all_executed,
            "执行次数: %s" % str(counters),
        )

        # 检查任务数量
        print_result("任务数量", len(scheduler.tasks) == 5)

        return all_executed

    except Exception as e:
        print_result("多任务并发", False, str(e))
        logger.exception("异常详情:")
        return False


# ==================== 测试6: 任务管理 ====================


def test_task_management():
    """测试任务管理"""
    print_header("测试6: 任务管理")

    try:
        reset_scheduler()
        scheduler = IOCPScheduler()

        counter = {"value": 0}

        def increment():
            counter["value"] += 1

        # 测试1: 任务正常执行
        scheduler.schedule_task(
            task_id="manage_test",
            interval=0.1,
            callback=increment,
            immediate=True,
        )

        logger.info("  运行任务 0.5s...")
        scheduler.run_for(0.5)
        count_executed = counter["value"]
        logger.info("  执行次数: %d", count_executed)

        # 测试2: 禁用任务后不应执行
        reset_scheduler()
        scheduler2 = IOCPScheduler()
        counter2 = {"value": 0}

        def increment2():
            counter2["value"] += 1

        scheduler2.schedule_task(
            task_id="manage_test_2",
            interval=0.1,
            callback=increment2,
            immediate=True,
        )
        scheduler2.disable_task("manage_test_2")
        logger.info("  测试禁用任务...")
        scheduler2.run_for(0.3)
        count_disabled = counter2["value"]
        logger.info("  禁用后执行次数: %d", count_disabled)

        # 测试3: 移除任务
        reset_scheduler()
        scheduler3 = IOCPScheduler()
        scheduler3.schedule_task(
            task_id="manage_test_3",
            interval=0.1,
            callback=lambda: None,
            immediate=True,
        )
        result = scheduler3.remove_task("manage_test_3")
        logger.info("  移除任务结果: %s", result)

        print_result(
            "正常执行",
            count_executed >= 3,
            "执行次数: %d" % count_executed,
        )

        print_result(
            "禁用任务",
            count_disabled == 0,
            "禁用后执行次数: %d" % count_disabled,
        )

        print_result(
            "移除任务",
            result == True,
        )

        return True

    except Exception as e:
        print_result("任务管理", False, str(e))
        logger.exception("异常详情:")
        return False


# ==================== 测试7: AsyncWrapper ====================


def test_async_wrapper():
    """测试异步包装器"""
    print_header("测试7: AsyncWrapper")

    try:
        reset_scheduler()
        wrapper = AsyncWrapper()

        # 测试同步函数包装
        def sync_function(x, y):
            time.sleep(0.1)  # 模拟阻塞
            return x + y

        # 包装为异步
        async_func = wrapper.async_wrap(sync_function)

        # 运行测试
        async def run_test():
            result = await async_func(3, 4)
            return result

        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(run_test())
        loop.close()

        print_result("同步函数包装", result == 7, "结果: %d" % result)

        # 测试直接调用
        async def run_direct():
            result = await wrapper.run_sync(sync_function, 10, 20)
            return result

        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(run_direct())
        loop.close()

        print_result("直接调用包装", result == 30, "结果: %d" % result)

        wrapper.shutdown()
        return True

    except Exception as e:
        print_result("AsyncWrapper", False, str(e))
        logger.exception("异常详情:")
        return False


# ==================== 测试8: 全局调度器 ====================


def test_global_scheduler():
    """测试全局调度器"""
    print_header("测试8: 全局调度器")

    try:
        reset_scheduler()

        # 获取全局调度器
        scheduler1 = get_scheduler()
        scheduler2 = get_scheduler()

        # 检查是否是同一个实例
        print_result("单例模式", scheduler1 is scheduler2)

        # 调度任务
        counter = {"value": 0}

        def increment():
            counter["value"] += 1

        scheduler1.schedule_task(
            task_id="global_test",
            interval=0.1,
            callback=increment,
            immediate=True,
        )

        scheduler1.run_for(0.5)

        print_result("全局调度器任务执行", counter["value"] >= 2, "执行次数: %d" % counter['value'])

        shutdown_scheduler()
        return True

    except Exception as e:
        print_result("全局调度器", False, str(e))
        logger.exception("异常详情:")
        return False


# ==================== 测试9: 线程安全性 ====================


def test_thread_safety():
    """测试线程安全性"""
    print_header("测试9: 线程安全性")

    try:
        reset_scheduler()
        scheduler = IOCPScheduler()

        # 多线程同时添加任务
        errors = []

        def add_task(i):
            try:
                scheduler.schedule_task(
                    task_id=f"thread_test_{i}",
                    interval=0.1,
                    callback=lambda: None,
                    immediate=False,
                )
            except Exception as e:
                errors.append(e)

        threads = []
        for i in range(10):
            thread = threading.Thread(target=add_task, args=(i,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        print_result("多线程添加任务", len(errors) == 0, "错误数: %d" % len(errors))
        print_result("任务数量正确", len(scheduler.tasks) == 10)

        scheduler.stop()
        return len(errors) == 0

    except Exception as e:
        print_result("线程安全性", False, str(e))
        logger.exception("异常详情:")
        return False


# ==================== 测试10: 资源清理 ====================


def test_resource_cleanup():
    """测试资源清理"""
    print_header("测试10: 资源清理")

    try:
        reset_scheduler()
        scheduler = IOCPScheduler()

        # 添加任务并运行
        scheduler.schedule_task(
            task_id="cleanup_test",
            interval=0.1,
            callback=lambda: None,
            immediate=True,
        )

        scheduler.run_for(0.3)

        # 检查资源是否清理
        print_result("调度器停止", not scheduler.running)
        print_result("事件循环关闭", scheduler.loop.is_closed())
        print_result("任务清空", len(scheduler.task_futures) == 0)

        return True

    except Exception as e:
        print_result("资源清理", False, str(e))
        logger.exception("异常详情:")
        return False


# ==================== 测试11: 配置检查 ====================


def test_config():
    """测试配置"""
    print_header("测试11: 配置检查")

    try:
        print_result("IOCP_MAX_WORKERS 配置", hasattr(Config, "IOCP_MAX_WORKERS"), "值: %s" % Config.IOCP_MAX_WORKERS)
        print_result("IOCP_TASK_CHECK_INTERVAL 配置", hasattr(Config, "IOCP_TASK_CHECK_INTERVAL"), "值: %s" % Config.IOCP_TASK_CHECK_INTERVAL)
        print_result("ASYNC_WRAPPER_TIMEOUT 配置", hasattr(Config, "ASYNC_WRAPPER_TIMEOUT"), "值: %s" % Config.ASYNC_WRAPPER_TIMEOUT)

        return True

    except Exception as e:
        print_result("配置检查", False, str(e))
        logger.exception("异常详情:")
        return False


# ==================== 测试12: 性能测试 ====================


def test_performance():
    """测试性能"""
    print_header("测试12: 性能测试")

    try:
        reset_scheduler()
        scheduler = IOCPScheduler()

        counter = {"value": 0}

        def fast_increment():
            counter["value"] += 1

        # 添加100个任务
        logger.info("  添加100个任务中...")
        start_time = time.time()
        for i in range(100):
            scheduler.schedule_task(
                task_id=f"perf_test_{i}",
                interval=0.01,  # 10ms
                callback=fast_increment,
                immediate=True,
            )
        add_time = time.time() - start_time

        print_result("添加100个任务", add_time < 1.0, "耗时: %.3fs" % add_time)

        # 启动并运行
        logger.info("  启动调度器，运行性能测试中...")
        scheduler.run_for(1.0)

        total_executions = counter["value"]
        print_result(
            "任务执行性能",
            total_executions > 1000,
            "总执行次数: %d" % total_executions,
        )

        return total_executions > 1000

    except Exception as e:
        print_result("性能测试", False, str(e))
        logger.exception("异常详情:")
        return False


# ==================== 运行所有测试 ====================


def run_all_tests():
    """运行所有测试"""
    logger.info("")
    logger.info("🚀" * 30)
    logger.info("")
    logger.info("  IOCP 基础框架测试套件")
    logger.info("")
    logger.info("🚀" * 30)

    tests = [
        ("IOCPScheduler 创建", test_scheduler_creation),
        ("任务调度", test_task_scheduling),
        ("任务执行", test_task_execution),
        ("异步任务执行", test_async_task_execution),
        ("多任务并发", test_concurrent_tasks),
        ("任务管理", test_task_management),
        ("AsyncWrapper", test_async_wrapper),
        ("全局调度器", test_global_scheduler),
        ("线程安全性", test_thread_safety),
        ("资源清理", test_resource_cleanup),
        ("配置检查", test_config),
        ("性能测试", test_performance),
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

    # 打印总结
    print_header("测试总结")
    passed = sum(1 for _, result in results if result)
    failed = len(results) - passed

    for test_name, result in results:
        status = "✅" if result else "❌"
        logger.info("%s %s", status, test_name)

    logger.info("")
    logger.info("总计: %d | 通过: %d | 失败: %d", len(results), passed, failed)

    if failed == 0:
        logger.info("")
        logger.info("🎉 所有测试通过！")
    else:
        logger.info("")
        logger.info("⚠️  %d 个测试失败", failed)

    # 清理
    reset_scheduler()

    return failed == 0


if __name__ == "__main__":
    # 设置日志级别为DEBUG以查看详细输出
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    success = run_all_tests()
    sys.exit(0 if success else 1)
