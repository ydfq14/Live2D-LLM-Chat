"""
验证IOCP任务执行是否正常
"""

import asyncio
import sys
import os
import time

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from log_config import get_logger
from event_loop import IOCPScheduler, reset_scheduler

logger = get_logger("verify_fix")


def verify_task_execution():
    """验证任务执行"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("  验证IOCP任务执行修复")
    logger.info("=" * 60)
    logger.info("")

    # 测试1: 基本任务执行
    logger.info("📌 测试1: 基本任务执行...")
    reset_scheduler()
    scheduler = IOCPScheduler()

    counter = {"value": 0}

    def increment():
        counter["value"] += 1
        logger.info(f"   ✅ 任务执行! 计数: {counter['value']}")
        return counter["value"]

    # 添加任务（立即执行，间隔200ms）
    scheduler.schedule_task(
        task_id="verify_task",
        interval=0.2,
        callback=increment,
        description="验证任务",
        immediate=True,
    )

    # 运行事件循环1秒
    logger.info("   启动事件循环，运行1秒...")
    logger.info("")

    # 创建一个异步函数来停止事件循环
    async def stop_after_delay():
        await asyncio.sleep(1.0)
        scheduler.stop()

    # 在事件循环中运行停止函数
    scheduler.loop.create_task(stop_after_delay())

    # 运行事件循环
    scheduler.run_forever()

    # 检查结果
    exec_count = counter["value"]
    logger.info("")
    logger.info("📊 测试结果:")
    logger.info("   执行次数: %d", exec_count)

    if exec_count > 0:
        logger.info("   ✅ 任务执行正常!")
        logger.info("   平均间隔: %.3fs", 1.0 / exec_count if exec_count > 0 else 0)
        return True
    else:
        logger.error("   ❌ 任务未执行!")
        return False


def verify_multiple_tasks():
    """验证多任务执行"""
    logger.info("")
    logger.info("=" * 60)
    logger.info("  验证多任务并发执行")
    logger.info("=" * 60)
    logger.info("")

    reset_scheduler()
    scheduler = IOCPScheduler()

    counters = {f"task_{i}": 0 for i in range(3)}

    def make_counter(task_id):
        def counter():
            counters[task_id] += 1
            return counters[task_id]
        return counter

    # 添加3个任务
    for i in range(3):
        scheduler.schedule_task(
            task_id=f"task_{i}",
            interval=0.3,
            callback=make_counter(f"task_{i}"),
            description=f"任务 {i}",
            immediate=True,
        )

    logger.info("   已添加3个任务，启动事件循环...")

    # 运行1.5秒
    async def stop_after_delay():
        await asyncio.sleep(1.5)
        scheduler.stop()

    scheduler.loop.create_task(stop_after_delay())
    scheduler.run_forever()

    logger.info("")
    logger.info("📊 测试结果:")
    logger.info("   任务0执行次数: %d", counters["task_0"])
    logger.info("   任务1执行次数: %d", counters["task_1"])
    logger.info("   任务2执行次数: %d", counters["task_2"])

    all_executed = all(count >= 2 for count in counters.values())

    if all_executed:
        logger.info("   ✅ 所有任务执行正常!")
        return True
    else:
        logger.error("   ❌ 部分任务未执行!")
        return False


if __name__ == "__main__":
    import logging

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    logger.info("🚀 开始验证IOCP任务执行修复...")

    # 运行测试
    test1_result = verify_task_execution()
    test2_result = verify_multiple_tasks()

    # 总结
    logger.info("")
    logger.info("=" * 60)
    if test1_result and test2_result:
        logger.info("🎉 所有验证通过！IOCP任务执行正常!")
    else:
        logger.error("❌ 验证失败，需要进一步调试")
    logger.info("=" * 60)

    sys.exit(0 if (test1_result and test2_result) else 1)
