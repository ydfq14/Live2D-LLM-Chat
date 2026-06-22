"""
IOCP 事件循环调度器
基于 Windows ProactorEventLoop 实现高性能异步调度

核心特性：
- Windows 上使用 ProactorEventLoop（IOCP）
- 支持定时任务调度
- 支持异步用户输入处理
- 线程安全的任务管理
- 自动资源清理
"""

import asyncio
import sys
import os
import threading
import time
from typing import Callable, Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from log_config import get_logger

logger = get_logger(__name__)


@dataclass
class ScheduledTask:
    """定时任务数据结构"""

    task_id: str
    interval: float  # 执行间隔（秒）
    callback: Callable
    description: str = ""
    last_run: float = 0
    enabled: bool = True
    run_count: int = 0
    created_at: float = field(default_factory=time.time)


class IOCPScheduler:
    """基于IOCP的事件调度器

    核心特性：
    - Windows 上使用 ProactorEventLoop（IOCP）
    - Linux/macOS 上使用 SelectorEventLoop
    - 支持定时任务调度
    - 线程池执行同步代码
    - 线程安全的任务管理
    """

    def __init__(self, max_workers: int = None):
        """
        初始化IOCP调度器

        Args:
            max_workers: 最大工作线程数（默认 CPU 核心数 * 2）
        """
        # 创建事件循环
        if sys.platform == "win32":
            # Windows: 使用 ProactorEventLoop（IOCP）
            self.loop = asyncio.ProactorEventLoop()
            logger.info("[IOCP] 初始化 ProactorEventLoop (Windows IOCP)")
        else:
            # Linux/macOS: 使用 SelectorEventLoop
            self.loop = asyncio.SelectorEventLoop()
            logger.info("[IOCP] 初始化 SelectorEventLoop (Unix)")

        asyncio.set_event_loop(self.loop)

        # 任务管理
        self.tasks: Dict[str, ScheduledTask] = {}
        self.task_futures: Dict[str, asyncio.Task] = {}

        # 线程池（用于同步代码）
        max_workers = max_workers or (os.cpu_count() * 2)
        self.executor = ThreadPoolExecutor(
            max_workers=max_workers, thread_name_prefix="IOCP-Worker"
        )

        # 状态
        self.running = False
        self._lock = threading.Lock()
        self._started = False

        logger.info(f"[IOCP] 调度器初始化完成，工作线程数: {max_workers}")

    def schedule_task(
        self,
        task_id: str,
        interval: float,
        callback: Callable,
        description: str = "",
        immediate: bool = False,
    ) -> bool:
        """
        调度定时任务

        Args:
            task_id: 任务唯一标识
            interval: 执行间隔（秒）
            callback: 回调函数（同步或异步）
            description: 任务描述
            immediate: 是否立即执行第一次

        Returns:
            是否成功添加
        """
        with self._lock:
            if task_id in self.tasks:
                logger.warning(f"[IOCP] 任务 {task_id} 已存在，将被覆盖")
                # 取消旧任务
                self._cancel_task(task_id)

            task = ScheduledTask(
                task_id=task_id,
                interval=interval,
                callback=callback,
                description=description,
                last_run=0 if immediate else time.time(),
            )

            self.tasks[task_id] = task

            # 如果事件循环已运行，立即启动任务
            if self._started and self.loop.is_running():
                # 使用 call_soon_threadsafe 确保线程安全
                self.loop.call_soon_threadsafe(self._start_task, task)
            elif self._started:
                # 事件循环已标记启动但还未运行，直接创建任务
                self._start_task(task)

            logger.info(f"[IOCP] 调度任务: {task_id} (间隔: {interval}s)")
            return True

    def _start_task(self, task: ScheduledTask):
        """启动单个任务的异步执行"""

        async def task_wrapper():
            while self.running and task.enabled:
                try:
                    # 等待到下一次执行时间
                    now = time.time()
                    wait_time = task.interval - (now - task.last_run)
                    if wait_time > 0:
                        await asyncio.sleep(wait_time)

                    # 执行回调
                    if asyncio.iscoroutinefunction(task.callback):
                        result = await task.callback()
                    else:
                        # 在线程池中执行同步代码
                        result = await self.loop.run_in_executor(
                            self.executor, task.callback
                        )

                    task.last_run = time.time()
                    task.run_count += 1

                    logger.debug(
                        f"[IOCP] 任务 {task.task_id} 执行完成 (第 {task.run_count} 次)"
                    )

                except asyncio.CancelledError:
                    logger.debug(f"[IOCP] 任务 {task.task_id} 被取消")
                    break
                except Exception as e:
                    logger.error(f"[IOCP] 任务 {task.task_id} 执行异常: {e}")
                    # 异常后短暂等待再重试
                    await asyncio.sleep(1)

        # 创建并保存Task
        async_task = self.loop.create_task(task_wrapper())
        self.task_futures[task.task_id] = async_task

    def _cancel_task(self, task_id: str):
        """取消任务"""
        if task_id in self.task_futures:
            self.task_futures[task_id].cancel()
            del self.task_futures[task_id]

    def remove_task(self, task_id: str) -> bool:
        """移除任务"""
        with self._lock:
            if task_id not in self.tasks:
                return False

            self._cancel_task(task_id)
            del self.tasks[task_id]

            logger.info(f"[IOCP] 移除任务: {task_id}")
            return True

    def enable_task(self, task_id: str) -> bool:
        """启用任务"""
        with self._lock:
            if task_id not in self.tasks:
                return False

            self.tasks[task_id].enabled = True
            logger.info(f"[IOCP] 启用任务: {task_id}")
            return True

    def disable_task(self, task_id: str) -> bool:
        """禁用任务"""
        with self._lock:
            if task_id not in self.tasks:
                return False

            self.tasks[task_id].enabled = False
            logger.info(f"[IOCP] 禁用任务: {task_id}")
            return True

    def start(self):
        """标记调度器为已启动状态（不真正启动任务）"""
        if self._started:
            logger.warning("[IOCP] 调度器已启动")
            return

        self.running = True
        self._started = True
        logger.info("[IOCP] 调度器已标记为启动状态")

    def _schedule_all_tasks(self):
        """在事件循环中调度所有任务（内部使用）"""
        for task in self.tasks.values():
            self._start_task(task)
        logger.info(f"[IOCP] 已调度 {len(self.tasks)} 个任务")

    def run_forever(self):
        """运行事件循环（阻塞）"""
        self.start()

        try:
            logger.info("[IOCP] 进入事件循环...")

            # 使用 call_soon 在事件循环开始后立即调度所有任务
            self.loop.call_soon(self._schedule_all_tasks)

            # 运行事件循环（阻塞）
            self.loop.run_forever()
        except KeyboardInterrupt:
            logger.info("[IOCP] 收到中断信号")
        finally:
            self._cleanup()

    def run_for(self, seconds: float):
        """运行事件循环指定秒数后自动停止（阻塞）

        Args:
            seconds: 运行时长（秒）
        """
        # 在事件循环中调度自动停止
        async def auto_stop():
            await asyncio.sleep(seconds)
            self.stop()

        self.loop.call_soon(lambda: asyncio.ensure_future(auto_stop()))
        self.run_forever()

    def run_until_complete(self, coro):
        """运行直到协程完成"""
        self.start()

        # 调度所有任务
        self._schedule_all_tasks()

        return self.loop.run_until_complete(coro)

    def stop(self):
        """停止事件循环"""
        if not self._started:
            return

        self.running = False

        # 取消所有任务
        for task_id in list(self.task_futures.keys()):
            self._cancel_task(task_id)

        # 停止事件循环
        self.loop.call_soon_threadsafe(self.loop.stop)

        logger.info("[IOCP] 事件循环已停止")

    def _cleanup(self):
        """清理资源"""
        logger.info("[IOCP] 开始清理资源...")

        # 等待所有任务完成
        for future in self.task_futures.values():
            if not future.done():
                future.cancel()

        # 关闭线程池
        self.executor.shutdown(wait=False)

        # 关闭事件循环
        if not self.loop.is_closed():
            self.loop.close()

        self._started = False
        logger.info("[IOCP] 资源已清理")

    def run_in_executor(self, func: Callable, *args):
        """在线程池中执行同步代码"""
        return self.loop.run_in_executor(self.executor, func, *args)

    def call_soon(self, callback: Callable, *args):
        """在事件循环中调用回调"""
        self.loop.call_soon(callback, *args)

    def call_later(self, delay: float, callback: Callable, *args):
        """延迟调用回调"""
        self.loop.call_later(delay, callback, *args)

    def get_task_status(self) -> Dict[str, dict]:
        """获取所有任务状态"""
        with self._lock:
            return {
                task_id: {
                    "interval": task.interval,
                    "description": task.description,
                    "enabled": task.enabled,
                    "last_run": task.last_run,
                    "run_count": task.run_count,
                    "created_at": task.created_at,
                }
                for task_id, task in self.tasks.items()
            }

    def get_stats(self) -> dict:
        """获取调度器统计信息"""
        return {
            "running": self.running,
            "started": self._started,
            "task_count": len(self.tasks),
            "active_tasks": len(self.task_futures),
            "platform": sys.platform,
            "loop_type": type(self.loop).__name__,
        }


# ==================== 全局调度器 ====================

_scheduler: Optional[IOCPScheduler] = None
_scheduler_lock = threading.Lock()


def get_scheduler() -> IOCPScheduler:
    """获取全局调度器实例（线程安全的单例）"""
    global _scheduler

    if _scheduler is None:
        with _scheduler_lock:
            if _scheduler is None:
                _scheduler = IOCPScheduler()

    return _scheduler


def shutdown_scheduler():
    """关闭全局调度器"""
    global _scheduler

    with _scheduler_lock:
        if _scheduler:
            _scheduler.stop()
            _scheduler = None
            logger.info("[IOCP] 全局调度器已关闭")


def reset_scheduler():
    """重置全局调度器（用于测试）"""
    global _scheduler

    with _scheduler_lock:
        if _scheduler:
            _scheduler.stop()
        _scheduler = None


# ==================== 便捷函数 ====================


def schedule_task(
    task_id: str,
    interval: float,
    callback: Callable,
    description: str = "",
    immediate: bool = False,
) -> bool:
    """便捷函数：调度任务"""
    return get_scheduler().schedule_task(
        task_id=task_id,
        interval=interval,
        callback=callback,
        description=description,
        immediate=immediate,
    )


def remove_task(task_id: str) -> bool:
    """便捷函数：移除任务"""
    return get_scheduler().remove_task(task_id)


def get_task_status() -> Dict[str, dict]:
    """便捷函数：获取任务状态"""
    return get_scheduler().get_task_status()
