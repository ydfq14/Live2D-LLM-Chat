"""
快速IOCP测试脚本

快速验证IOCP基础功能是否正常
"""

import sys
import os
import time

# 切换到项目根目录
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(project_root)
sys.path.insert(0, project_root)

from log_config import get_logger
from event_loop import IOCPScheduler, reset_scheduler
from config import Config

logger = get_logger("quick_test")


def quick_test():
    """快速测试"""
    logger.info("")
    logger.info("🚀 快速IOCP功能测试")
    logger.info("=" * 60)
    logger.info("")

    # 测试1: 创建调度器
    logger.info("📌 测试1: 创建IOCPScheduler...")
    try:
        reset_scheduler()
        scheduler = IOCPScheduler()
        logger.info("✅ 调度器创建成功")
        logger.info("   平台: %s", sys.platform)
        logger.info("   事件循环: %s", type(scheduler.loop).__name__)
    except Exception as e:
        logger.error("❌ 调度器创建失败: %s", str(e))
        return False

    # 测试2: 添加任务
    logger.info("")
    logger.info("📌 测试2: 添加定时任务...")
    try:
        counter = {"value": 0}

        def increment():
            counter["value"] += 1

        scheduler.schedule_task(
            task_id="quick_test",
            interval=0.1,
            callback=increment,
            description="快速测试任务",
            immediate=True,
        )
        logger.info("✅ 任务添加成功")
    except Exception as e:
        logger.error("❌ 任务添加失败: %s", str(e))
        return False

    # 测试3: 执行任务
    logger.info("")
    logger.info("📌 测试3: 执行任务（运行1秒）...")
    try:
        # 使用 run_for 让事件循环真正运行1秒
        scheduler.run_for(1.0)
        logger.info("   调度器已停止")

        exec_count = counter["value"]
        logger.info("✅ 任务执行成功")
        logger.info("   执行次数: %d", exec_count)

        if exec_count < 5:
            logger.warning("⚠️  执行次数较少，可能存在性能问题")
    except Exception as e:
        logger.error("❌ 任务执行失败: %s", str(e))
        return False

    # 测试4: 检查配置
    logger.info("")
    logger.info("📌 测试4: 检查配置...")
    try:
        logger.info("   IOCP_MAX_WORKERS: %s", Config.IOCP_MAX_WORKERS)
        logger.info("   IOCP_TASK_CHECK_INTERVAL: %s", Config.IOCP_TASK_CHECK_INTERVAL)
        logger.info("✅ 配置检查通过")
    except Exception as e:
        logger.error("❌ 配置检查失败: %s", str(e))
        return False

    # 测试5: 异步包装器
    logger.info("")
    logger.info("📌 测试5: 测试异步包装器...")
    try:
        from async_wrapper import AsyncWrapper

        wrapper = AsyncWrapper()

        def sync_func(x, y):
            time.sleep(0.1)
            return x + y

        async def test_async():
            result = await wrapper.run_sync(sync_func, 3, 4)
            return result

        import asyncio

        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(test_async())
        loop.close()

        if result == 7:
            logger.info("✅ 异步包装器工作正常")
        else:
            logger.error("❌ 异步包装器结果错误: %d (期望: 7)", result)
            return False

        wrapper.shutdown()
    except Exception as e:
        logger.error("❌ 异步包装器测试失败: %s", str(e))
        return False

    # 清理
    reset_scheduler()

    # 完成
    logger.info("")
    logger.info("=" * 60)
    logger.info("🎉 快速测试完成！所有核心功能正常")
    logger.info("=" * 60)
    logger.info("")

    return True


if __name__ == "__main__":
    import logging

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    success = quick_test()
    sys.exit(0 if success else 1)
