# IOCP 架构文档

## 概述

本项目采用 **IOCP (I/O Completion Ports)** 架构实现高性能异步调度。在Windows上使用 `ProactorEventLoop`，在Linux/macOS上使用 `SelectorEventLoop`。

---

## 核心组件

### 1. IOCPScheduler (event_loop.py)

**位置**: `D:\Project\Visual Studio Code\VirtuMate\Live2D-LLM-Chat\event_loop.py`

**功能**:
- 基于IOCP的事件循环调度器
- 支持定时任务调度
- 线程池执行同步代码
- 线程安全的任务管理

**API**:

```python
from event_loop import get_scheduler, shutdown_scheduler, reset_scheduler

# 获取全局调度器（单例）
scheduler = get_scheduler()

# 调度任务
scheduler.schedule_task(
    task_id="unique_id",
    interval=30,  # 执行间隔（秒）
    callback=my_callback,
    description="检查日程提醒",
    immediate=False  # 是否立即执行第一次
)

# 任务管理
scheduler.remove_task(task_id)
scheduler.enable_task(task_id)
scheduler.disable_task(task_id)

# 运行控制
scheduler.run_forever()  # 阻塞运行
scheduler.run_for(seconds)  # 运行指定秒数
scheduler.run_until_complete(coro)  # 运行直到协程完成
scheduler.stop()  # 停止事件循环

# 状态查询
scheduler.get_task_status()  # 获取所有任务状态
scheduler.get_stats()  # 获取调度器统计信息
```

**事件循环类型**:
- **Windows**: `ProactorEventLoop` (IOCP)
- **Linux/macOS**: `SelectorEventLoop`

**线程池**:
- 默认工作线程数: CPU核心数 × 2
- 用于执行同步阻塞代码（ASR/TTS/Live2D）
- 避免阻塞事件循环

---

### 2. AsyncWrapper (async_wrapper.py)

**位置**: `D:\Project\Visual Studio Code\VirtuMate\Live2D-LLM-Chat\async_wrapper.py`

**功能**:
- 将同步阻塞函数包装为异步函数
- 避免阻塞事件循环
- 支持装饰器语法
- 支持超时控制

**API**:

```python
from async_wrapper import (
    get_async_wrapper, 
    shutdown_async_wrapper, 
    reset_async_wrapper,
    run_sync,
    run_sync_with_timeout,
    async_wrap,
    async_wrap_with_timeout
)

# 获取全局包装器（单例）
wrapper = get_async_wrapper()

# 直接调用
result = await wrapper.run_sync(sync_function, arg1, arg2)
result = await wrapper.run_sync_with_timeout(func, timeout, *args, **kwargs)

# 装饰器
@wrapper.async_wrap
def sync_function(x, y):
    return x + y

@wrapper.async_wrap_with_timeout(timeout=5.0)
def slow_function():
    time.sleep(10)
    return "done"

# 便捷函数
result = await run_sync(func, *args, **kwargs)
result = await run_sync_with_timeout(func, timeout, *args, **kwargs)
```

**使用场景**:

```python
# 在IOCP事件循环中非阻塞执行同步代码
async def async_input_loop():
    # VAD录音（在线程池中非阻塞）
    recording_done = await run_sync(self.asr_manager.record_audio, user_wav)
    
    # ASR识别（在线程池中非阻塞）
    user_input = await run_sync(self.asr_manager.recognize_speech, user_wav)
    
    # LangGraph调用（在线程池中非阻塞）
    result = await run_sync(self.graph_engine.invoke, input_data)
```

---

## 事件循环模型

### Windows IOCP

```
┌──────────────────────────────────────────────────────────────┐
│                   ProactorEventLoop                          │
│  ┌────────────────────────────────────────────────────────┐  │
│  │              IOCP (I/O Completion Ports)               │  │
│  │   ┌──────────┐  ┌──────────┐  ┌──────────┐           │  │
│  │   │ I/O 1    │  │ I/O 2    │  │ I/O N    │           │  │
│  │   │ 完成端口  │  │ 完成端口  │  │ 完成端口  │           │  │
│  │   └──────────┘  └──────────┘  └──────────┘           │  │
│  └────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────┐  │
│  │              ThreadPoolExecutor                        │  │
│  │   ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐            │  │
│  │   │线程1 │  │线程2 │  │线程3 │  │线程N │            │  │
│  │   └──────┘  └──────┘  └──────┘  └──────┘            │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### Linux/macOS Selector

```
┌──────────────────────────────────────────────────────────────┐
│                   SelectorEventLoop                          │
│  ┌────────────────────────────────────────────────────────┐  │
│  │              epoll/kqueue/kevent                       │  │
│  │   ┌──────────┐  ┌──────────┐  ┌──────────┐           │  │
│  │   │ Socket 1 │  │ Socket 2 │  │ Socket N │           │  │
│  │   └──────────┘  └──────────┘  └──────────┘           │  │
│  └────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────┐  │
│  │              ThreadPoolExecutor                        │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

---

## 线程安全

### 锁机制

```python
# 任务管理使用threading.Lock
self._lock = threading.Lock()

def schedule_task(self, task_id, interval, callback):
    with self._lock:
        if task_id in self.tasks:
            # 处理重复任务
            pass
        # 添加任务
```

### 跨线程调用

```python
# 使用loop.call_soon_threadsafe确保线程安全
if self._started and self.loop.is_running():
    self.loop.call_soon_threadsafe(self._start_task, task)

# 停止事件循环
self.loop.call_soon_threadsafe(self.loop.stop)
```

### 在线程池执行同步代码

```python
# 使用loop.run_in_executor在线程池中执行
result = await self.loop.run_in_executor(
    self.executor,  # ThreadPoolExecutor
    task.callback
)
```

---

## 定时任务调度

### 任务数据结构

```python
@dataclass
class ScheduledTask:
    task_id: str
    interval: float  # 执行间隔（秒）
    callback: Callable
    description: str = ""
    last_run: float = 0
    enabled: bool = True
    run_count: int = 0
    created_at: float = field(default_factory=time.time)
```

### 任务执行流程

```python
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
            
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"任务 {task.task_id} 执行异常: {e}")
            await asyncio.sleep(1)
```

---

## 插件后台任务集成

### 插件注册后台任务

```python
class SchedulerPlugin(PluginBase):
    def on_register_background_tasks(self):
        return [
            {
                "task_id": "check_reminders",
                "interval": 30,
                "callback": self._check_reminders,
                "description": "检查日程提醒",
                "immediate": True
            }
        ]
    
    def _check_reminders(self):
        # 检查是否有到期任务
        return "提醒消息" if 有到期任务 else None
    
    def on_task_complete(self, task_id, result):
        # 任务完成回调
        if result:
            self._pending_reminder = result
```

### PluginRegistry收集任务

```python
def _collect_background_tasks(self):
    for plugin in self.enabled_plugins:
        tasks = plugin.on_register_background_tasks()
        if not tasks:
            continue
        
        for task_def in tasks:
            task_id = f"{plugin.name}_{task_def['task_id']}"
            
            # 包装回调：执行完成后通知插件
            async def wrapped_callback(tid=task_id, cb=task_def["callback"], p=plugin):
                result = await cb()
                p.on_task_complete(tid, result)
                return result
            
            scheduler.schedule_task(
                task_id=task_id,
                interval=task_def["interval"],
                callback=wrapped_callback,
                description=task_def["description"],
                immediate=task_def.get("immediate", False)
            )
```

---

## 使用示例

### 示例1: 定时检查提醒

```python
class MyPlugin(PluginBase):
    name = "my_plugin"
    
    def on_register_background_tasks(self):
        return [
            {
                "task_id": "check_reminders",
                "interval": 60,  # 每60秒检查一次
                "callback": self._check_reminders,
                "description": "检查提醒",
                "immediate": True  # 立即执行第一次
            }
        ]
    
    def _check_reminders(self):
        # 检查逻辑
        if 需要提醒:
            return "提醒消息"
        return None
    
    def on_task_complete(self, task_id, result):
        if result:
            # 发送提醒
            self._send_notification(result)
```

### 示例2: 异步执行同步代码

```python
async def async_input_loop():
    # 录音（同步阻塞，在线程池中执行）
    recording_done = await run_sync(
        self.asr_manager.record_audio, 
        user_wav
    )
    
    # ASR识别（同步阻塞，在线程池中执行）
    user_input = await run_sync(
        self.asr_manager.recognize_speech, 
        user_wav
    )
    
    # LangGraph调用（同步阻塞，在线程池中执行）
    result = await run_sync(
        self.graph_engine.invoke, 
        input_data
    )
```

### 示例3: 带超时的异步调用

```python
from async_wrapper import run_sync_with_timeout

async def async_operation():
    try:
        # 5秒超时
        result = await run_sync_with_timeout(
            slow_function, 
            timeout=5.0, 
            arg1, 
            arg2
        )
        return result
    except asyncio.TimeoutError:
        logger.error("操作超时")
        return None
```

---

## 配置参数

### config.py 中的IOCP配置

```python
class Config:
    # IOCP工作线程数（0=自动，CPU核心数*2）
    IOCP_MAX_WORKERS = int(os.getenv("IOCP_MAX_WORKERS", "0"))
    
    # 后台任务检查间隔（秒）
    IOCP_TASK_CHECK_INTERVAL = float(os.getenv("IOCP_TASK_CHECK_INTERVAL", "1.0"))
    
    # 异步包装器超时时间（秒）
    ASYNC_WRAPPER_TIMEOUT = float(os.getenv("ASYNC_WRAPPER_TIMEOUT", "30.0"))
```

### 环境变量

```env
# IOCP配置
IOCP_MAX_WORKERS=0
IOCP_TASK_CHECK_INTERVAL=1.0
ASYNC_WRAPPER_TIMEOUT=30.0
```

---

## 性能优化

### 1. 线程池大小

- 默认: CPU核心数 × 2
- 可通过 `IOCP_MAX_WORKERS` 环境变量调整
- 过大: 线程切换开销增加
- 过小: 任务排队等待时间增加

### 2. 任务间隔

- 合理设置任务间隔，避免过于频繁的执行
- 使用 `immediate=True` 时注意首次执行的时机

### 3. 超时控制

- 使用 `run_sync_with_timeout` 避免长时间阻塞
- 合理设置 `ASYNC_WRAPPER_TIMEOUT`

### 4. 资源清理

- 程序退出时调用 `shutdown_scheduler()`
- 确保所有任务正确取消

---

## 调试技巧

### 1. 查看调度器状态

```python
scheduler = get_scheduler()
stats = scheduler.get_stats()
print(stats)
# {
#     'running': True,
#     'started': True,
#     'task_count': 3,
#     'active_tasks': 3,
#     'platform': 'win32',
#     'loop_type': 'ProactorEventLoop'
# }
```

### 2. 查看任务状态

```python
task_status = scheduler.get_task_status()
print(task_status)
# {
#     'scheduler_check_reminders': {
#         'interval': 30,
#         'description': '检查日程提醒',
#         'enabled': True,
#         'last_run': 1234567890.0,
#         'run_count': 10,
#         'created_at': 1234567800.0
#     }
# }
```

### 3. 日志输出

```
[IOCP] 初始化 ProactorEventLoop (Windows IOCP)
[IOCP] 调度器初始化完成，工作线程数: 8
[IOCP] 调度任务: scheduler_check_reminders (间隔: 30s)
[IOCP] 任务 scheduler_check_reminders 执行完成 (第 1 次)
[AsyncWrapper] 初始化完成，工作线程数: 8
```

---

## 常见问题

### 1. 任务不执行

**原因**:
- 任务被禁用 (`enabled=False`)
- 任务ID重复
- 事件循环未启动

**解决**:
- 检查任务状态
- 确保任务ID唯一
- 确保调用 `run_forever()`

### 2. 线程安全问题

**原因**:
- 未使用锁保护共享资源
- 跨线程调用不安全

**解决**:
- 使用 `threading.Lock` 保护共享资源
- 使用 `loop.call_soon_threadsafe` 跨线程调用

### 3. 异步包装器超时

**原因**:
- 同步代码执行时间超过 `ASYNC_WRAPPER_TIMEOUT`

**解决**:
- 增加 `ASYNC_WRAPPER_TIMEOUT` 配置
- 优化同步代码性能

### 4. 资源泄漏

**原因**:
- 未正确清理资源
- 事件循环未关闭

**解决**:
- 程序退出时调用 `shutdown_scheduler()`
- 确保所有任务正确取消

---

## 最佳实践

### 1. 任务设计

- 任务应是独立的、无状态的
- 避免任务间相互依赖
- 合理设置任务间隔

### 2. 错误处理

- 任务回调应捕获所有异常
- 使用 try/except 包装任务逻辑
- 记录错误日志便于调试

### 3. 资源管理

- 及时释放不再需要的资源
- 使用 `asyncio.CancelledError` 处理任务取消
- 程序退出时清理所有资源

### 4. 性能优化

- 避免在事件循环中执行阻塞操作
- 使用线程池执行同步代码
- 合理设置线程池大小

---

## 参考资料

- [Python asyncio 文档](https://docs.python.org/3/library/asyncio.html)
- [ProactorEventLoop 文档](https://docs.python.org/3/library/asyncio-eventloop.html#asyncio.ProactorEventLoop)
- [ThreadPoolExecutor 文档](https://docs.python.org/3/library/concurrent.futures.html#threadpoolexecutor)

---

*文档版本: v2.0*
*最后更新: 2026-06-22*
