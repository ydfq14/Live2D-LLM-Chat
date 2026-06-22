"""
同步代码异步包装器
用于将现有的同步阻塞代码（ASR/TTS/Live2D）包装为异步调用

核心功能：
- 将同步函数包装为异步函数
- 在线程池中执行同步代码
- 避免阻塞事件循环
- 支持装饰器语法
"""

import asyncio
import os
import threading
from typing import Callable, TypeVar, Any, Optional
from functools import wraps
from concurrent.futures import ThreadPoolExecutor
from log_config import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


class AsyncWrapper:
    """异步包装器

    用于将同步阻塞函数包装为异步函数
    避免阻塞事件循环

    Usage:
        wrapper = AsyncWrapper()

        # 方式1: 直接调用
        result = await wrapper.run_sync(sync_function, arg1, arg2)

        # 方式2: 装饰器
        @wrapper.async_wrap
        def sync_function(x, y):
            return x + y

        result = await sync_function(1, 2)
    """

    def __init__(self, executor: ThreadPoolExecutor = None, max_workers: int = None):
        """
        初始化异步包装器

        Args:
            executor: 线程池执行器（可选）
            max_workers: 最大工作线程数（默认 CPU 核心数）
        """
        if executor:
            self.executor = executor
            self._owns_executor = False
        else:
            max_workers = max_workers or os.cpu_count()
            self.executor = ThreadPoolExecutor(
                max_workers=max_workers, thread_name_prefix="AsyncWrapper"
            )
            self._owns_executor = True

        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()

        logger.debug(f"[AsyncWrapper] 初始化完成，工作线程数: {self.executor._max_workers}")

    def get_loop(self) -> asyncio.AbstractEventLoop:
        """获取当前事件循环"""
        if self._loop is None or self._loop.is_closed():
            with self._lock:
                if self._loop is None or self._loop.is_closed():
                    try:
                        self._loop = asyncio.get_running_loop()
                    except RuntimeError:
                        self._loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(self._loop)
        return self._loop

    async def run_sync(self, func: Callable[..., T], *args, **kwargs) -> T:
        """
        在线程池中执行同步函数

        Args:
            func: 同步函数
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            函数返回值

        Example:
            async def main():
                wrapper = AsyncWrapper()

                # 执行同步阻塞函数
                result = await wrapper.run_sync(time.sleep, 1)
                print("完成")
        """
        loop = self.get_loop()

        # 包装带参数的函数
        def wrapper():
            return func(*args, **kwargs)

        # 在线程池中执行
        return await loop.run_in_executor(self.executor, wrapper)

    async def run_sync_with_timeout(
        self, func: Callable[..., T], timeout: float, *args, **kwargs
    ) -> T:
        """
        在线程池中执行同步函数（带超时）

        Args:
            func: 同步函数
            timeout: 超时时间（秒）
            *args: 位置参数
            **kwargs: 关键字参数

        Returns:
            函数返回值

        Raises:
            asyncio.TimeoutError: 超时异常
        """
        loop = self.get_loop()

        # 包装带参数的函数
        def wrapper():
            return func(*args, **kwargs)

        # 在线程池中执行，带超时
        return await asyncio.wait_for(
            loop.run_in_executor(self.executor, wrapper), timeout=timeout
        )

    def async_wrap(self, func: Callable[..., T]) -> Callable[..., asyncio.coroutine]:
        """
        装饰器：将同步函数包装为异步函数

        Args:
            func: 同步函数

        Returns:
            异步函数

        Example:
            wrapper = AsyncWrapper()

            @wrapper.async_wrap
            def sync_function(x, y):
                time.sleep(1)  # 模拟阻塞操作
                return x + y

            # 使用（自动变为异步）
            async def main():
                result = await sync_function(1, 2)
                print(result)  # 3
        """

        @wraps(func)
        async def async_func(*args, **kwargs):
            return await self.run_sync(func, *args, **kwargs)

        return async_func

    def async_wrap_with_timeout(self, timeout: float):
        """
        装饰器：将同步函数包装为异步函数（带超时）

        Args:
            timeout: 超时时间（秒）

        Returns:
            装饰器函数

        Example:
            wrapper = AsyncWrapper()

            @wrapper.async_wrap_with_timeout(timeout=5.0)
            def slow_function():
                time.sleep(10)  # 会超时
                return "done"

            async def main():
                try:
                    result = await slow_function()
                except asyncio.TimeoutError:
                    print("超时了")
        """

        def decorator(func: Callable[..., T]) -> Callable[..., asyncio.coroutine]:
            @wraps(func)
            async def async_func(*args, **kwargs):
                return await self.run_sync_with_timeout(func, timeout, *args, **kwargs)

            return async_func

        return decorator

    def shutdown(self, wait: bool = True):
        """关闭线程池"""
        if self._owns_executor:
            self.executor.shutdown(wait=wait)
            logger.debug("[AsyncWrapper] 线程池已关闭")


# ==================== 全局包装器 ====================

_wrapper: Optional[AsyncWrapper] = None
_wrapper_lock = threading.Lock()


def get_async_wrapper() -> AsyncWrapper:
    """获取全局异步包装器（线程安全的单例）"""
    global _wrapper

    if _wrapper is None:
        with _wrapper_lock:
            if _wrapper is None:
                _wrapper = AsyncWrapper()

    return _wrapper


def shutdown_async_wrapper():
    """关闭全局异步包装器"""
    global _wrapper

    with _wrapper_lock:
        if _wrapper:
            _wrapper.shutdown()
            _wrapper = None
            logger.info("[AsyncWrapper] 全局包装器已关闭")


def reset_async_wrapper():
    """重置全局异步包装器（用于测试）"""
    global _wrapper

    with _wrapper_lock:
        if _wrapper:
            _wrapper.shutdown()
        _wrapper = None


# ==================== 便捷函数 ====================


async def run_sync(func: Callable[..., T], *args, **kwargs) -> T:
    """
    便捷函数：运行同步函数

    Args:
        func: 同步函数
        *args: 位置参数
        **kwargs: 关键字参数

    Returns:
        函数返回值

    Example:
        import time

        async def main():
            # 非阻塞地执行同步阻塞函数
            await run_sync(time.sleep, 1)
            print("完成")
    """
    return await get_async_wrapper().run_sync(func, *args, **kwargs)


async def run_sync_with_timeout(
    func: Callable[..., T], timeout: float, *args, **kwargs
) -> T:
    """
    便捷函数：运行同步函数（带超时）

    Args:
        func: 同步函数
        timeout: 超时时间（秒）
        *args: 位置参数
        **kwargs: 关键字参数

    Returns:
        函数返回值

    Raises:
        asyncio.TimeoutError: 超时异常
    """
    return await get_async_wrapper().run_sync_with_timeout(
        func, timeout, *args, **kwargs
    )


def async_wrap(func: Callable[..., T]) -> Callable[..., asyncio.coroutine]:
    """
    便捷装饰器：包装同步函数为异步

    Args:
        func: 同步函数

    Returns:
        异步函数

    Example:
        @async_wrap
        def sync_function(x, y):
            time.sleep(1)
            return x + y

        async def main():
            result = await sync_function(1, 2)
    """
    return get_async_wrapper().async_wrap(func)


def async_wrap_with_timeout(timeout: float):
    """
    便捷装饰器：包装同步函数为异步（带超时）

    Args:
        timeout: 超时时间（秒）

    Returns:
        装饰器函数

    Example:
        @async_wrap_with_timeout(timeout=5.0)
        def slow_function():
            time.sleep(10)
            return "done"

        async def main():
            try:
                result = await slow_function()
            except asyncio.TimeoutError:
                print("超时")
    """
    return get_async_wrapper().async_wrap_with_timeout(timeout)


# ==================== 工具函数 ====================


async def gather_sync(*funcs: Callable, max_workers: int = None) -> list:
    """
    并行执行多个同步函数

    Args:
        *funcs: 同步函数列表
        max_workers: 最大并发数（可选）

    Returns:
        结果列表

    Example:
        async def main():
            results = await gather_sync(
                lambda: time.sleep(1),
                lambda: time.sleep(2),
                lambda: time.sleep(3)
            )
    """
    wrapper = AsyncWrapper(max_workers=max_workers)
    tasks = [wrapper.run_sync(func) for func in funcs]
    return await asyncio.gather(*tasks)


async def run_in_thread(func: Callable[..., T], *args, **kwargs) -> T:
    """
    在单独线程中执行函数（不使用线程池）

    Args:
        func: 函数
        *args: 位置参数
        **kwargs: 关键字参数

    Returns:
        函数返回值
    """
    result = None
    exception = None

    def target():
        nonlocal result, exception
        try:
            result = func(*args, **kwargs)
        except Exception as e:
            exception = e

    thread = threading.Thread(target=target)
    thread.start()

    # 等待线程完成
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, thread.join)

    if exception:
        raise exception

    return result
