# VirtuMate Live2D-LLM-Chat 项目文档

## 项目概述

VirtuMate 是一款智能语音对话 Live2D 桌宠应用，采用**IOCP架构**实现高性能异步调度。

### 核心特性
- **IOCP事件循环**: 基于Windows ProactorEventLoop实现高性能异步处理
- **插件化架构**: 模块化设计，易于扩展和定制
- **LangGraph Agent**: 智能体图引擎，支持工具调用和多轮对话
- **多模态交互**: 语音输入(ASR)、语音合成(TTS)、Live2D渲染、文本交互

### 技术栈
- Python 3.10+
- asyncio (IOCP/ProactorEventLoop)
- LangGraph Agent
- pywebview (前端)
- Chroma (RAG向量数据库)

---

## 架构概览

```
┌──────────────────────────────────────────────────────────────┐
│                    MainManager (main.py)                      │
│  统筹调度所有模块: ASR, TTS, LLM, Live2D, UI, 插件, Agent    │
├──────────────────────────────────────────────────────────────┤
│  IOCPScheduler (event_loop.py)                               │
│  • ProactorEventLoop (Windows IOCP)                          │
│  • 线程池执行同步代码                                         │
│  • 定时任务调度                                              │
│  • 异步任务管理                                              │
├──────────────────────────────────────────────────────────────┤
│  AsyncWrapper (async_wrapper.py)                             │
│  • 同步代码异步包装器                                        │
│  • 避免阻塞事件循环                                         │
│  • 装饰器支持                                                │
├──────────────────────────────────────────────────────────────┤
│  PluginRegistry (plugin_registry.py)                         │
│  • 插件自动发现与加载                                        │
│  • 后台任务注册与管理                                        │
│  • LangGraph工具收集与执行                                   │
│  • 事件广播                                                  │
├──────────────────────────────────────────────────────────────┤
│  PluginBase (plugin_base.py)                                 │
│  • 插件基类                                                  │
│  • 7个Hook生命周期方法 + 前端接口                            │
│  • IOCP后台任务Hook                                          │
│  • LangGraph工具Hook                                         │
└──────────────────────────────────────────────────────────────┘
```

---

## 核心模块详解

### 1. config.py - 配置管理

**位置**: `D:\Project\Visual Studio Code\VirtuMate\Live2D-LLM-Chat\config.py`

统一配置文件，支持：
- ASR/TTS/LLM 云端/本地模式切换
- MIMO API 配置
- VAD (Voice Activity Detection) 参数
- IOCP 调度器配置
- Live2D 模型路径

**关键配置项**:
```python
# IOCP配置
IOCP_MAX_WORKERS = 0  # 0=自动(CPU核心数*2)
IOCP_TASK_CHECK_INTERVAL = 1.0  # 后台任务检查间隔(秒)
ASYNC_WRAPPER_TIMEOUT = 30.0  # 异步包装器超时(秒)
```

---

### 2. main.py - 主程序

**位置**: `D:\Project\Visual Studio Code\VirtuMate\Live2D-LLM-Chat\main.py`

**核心类**: `MainManager`

**初始化流程** (5个阶段):
1. **阶段 0**: 项目基础信息打印
2. **阶段 1**: TTS API 初始化 (本地模式)
3. **阶段 2**: 核心AI模块初始化 (ASR/TTS/LLM/Live2D)
4. **阶段 3**: 插件系统 + WebUI前端窗口
5. **阶段 4**: LangGraph 智能体引擎
6. **阶段 5**: 运行时渲染线程启动

**主交互循环** (`run()`):
- 基于IOCP事件循环
- 用户输入在线程池中非阻塞等待
- VAD录音不阻塞事件循环
- 后台任务自动执行

**线程模型**:
- 主线程: pywebview前端事件循环
- 对话线程: IOCP对话循环线程
- Live2D线程: 守护线程运行渲染
- IOCP工作线程: 线程池执行同步代码

---

### 3. event_loop.py - IOCP事件循环调度器

**位置**: `D:\Project\Visual Studio Code\VirtuMate\Live2D-LLM-Chat\event_loop.py`

**核心类**: `IOCPScheduler`

**功能**:
- Windows上使用ProactorEventLoop (IOCP)
- Linux/macOS上使用SelectorEventLoop
- 支持定时任务调度
- 线程池执行同步代码
- 线程安全的任务管理

**API**:
```python
# 全局单例
scheduler = get_scheduler()
shutdown_scheduler()
reset_scheduler()

# 任务调度
scheduler.schedule_task(
    task_id="unique_id",
    interval=30,  # 秒
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
scheduler.stop()  # 停止事件循环
```

---

### 4. async_wrapper.py - 同步代码异步包装器

**位置**: `D:\Project\Visual Studio Code\VirtuMate\Live2D-LLM-Chat\async_wrapper.py`

**核心类**: `AsyncWrapper`

**功能**:
- 将同步阻塞函数包装为异步函数
- 避免阻塞事件循环
- 支持装饰器语法
- 支持超时控制

**API**:
```python
# 全局单例
wrapper = get_async_wrapper()
shutdown_async_wrapper()
reset_async_wrapper()

# 直接调用
result = await wrapper.run_sync(sync_function, arg1, arg2)
result = await wrapper.run_sync_with_timeout(func, timeout, *args)

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

**使用示例**:
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

### 5. plugin_base.py - 插件基类

**位置**: `D:\Project\Visual Studio Code\VirtuMate\Live2D-LLM-Chat\plugin_base.py`

**核心类**: `PluginBase`

**类属性** (子类必须覆写):
- `name`: 插件唯一名称
- `version`: 插件版本号

**Hook生命周期方法** (按调用顺序):
1. `on_startup(app)`: 程序启动时调用
2. `on_user_input(text)`: 用户输入时调用
3. `on_llm_context(user_input)`: LLM请求前调用，注入上下文
4. `on_llm_response(text)`: LLM返回后调用
5. `on_before_tts(text)`: TTS合成前调用
6. `on_tick(app)`: 主循环每轮对话末尾调用
7. `on_shutdown()`: 程序退出时调用

**IOCP后台任务Hook**:
- `on_register_background_tasks()`: 注册后台定时任务
- `on_task_complete(task_id, result)`: 任务完成回调

**LangGraph工具Hook**:
- `on_register_tools()`: 注册OpenAI格式工具定义
- `on_execute_tool(tool_name, tool_args)`: 执行工具

**内置工具**:
- `get_data_dir()`: 获取插件数据目录
- `get_scheduler()`: 获取IOCP调度器实例

---

### 6. plugin_registry.py - 插件注册中心

**位置**: `D:\Project\Visual Studio Code\VirtuMate\Live2D-LLM-Chat\plugin_registry.py`

**核心类**: `PluginRegistry`

**功能**:
- 自动扫描 `plugins/` 目录
- 动态加载所有 `*_plugin.py` 文件
- 插件注册、卸载、启用、禁用管理
- 事件广播（单个插件出错不中断）
- 后台任务注册与管理
- LangGraph工具收集与执行

**API**:
```python
# 初始化
registry = PluginRegistry()
loaded = registry.scan_and_load()

# 插件管理
registry.register(plugin)
registry.unregister(name)
registry.enable(name)
registry.disable(name)

# 查询
registry.plugins  # 所有插件
registry.enabled_plugins  # 启用的插件
registry.plugin_names  # 插件名称列表
registry.get(name)  # 获取单个插件

# 事件广播
registry.broadcast("on_user_input", text)
registry.broadcast_on_startup(app)
registry.broadcast_on_shutdown()

# IOCP后台任务
registry._collect_background_tasks()  # 收集所有插件的后台任务
registry.get_background_tasks()  # 获取已注册的任务

# LangGraph工具
tools = registry.collect_tools()  # 收集所有工具
result = registry.execute_tool(tool_name, tool_args)  # 执行工具
```

**插件加载日志**:
```
[插件] 扫描目录: D:\...\plugins
[插件] 发现 5 个候选文件: ['agentic_rag_plugin.py', 'chatbox_plugin.py', ...]
  [OK] agentic_rag v1.0  (Hook: on_llm_context, on_register_tools, on_execute_tool)
  [OK] scheduler v1.0  (Hook: on_llm_context, on_register_tools, on_execute_tool, ...)
[插件] 扫描完成: 成功加载 5/5 个
```

---

## 插件开发指南

### 插件目录结构

```
plugins/
├── __init__.py
├── chatbox_plugin.py
├── emotion_rag_plugin.py
├── scheduler_plugin.py
├── agentic_rag_plugin.py
└── demo_template_plugin.py
```

### 创建插件示例

```python
# my_plugin.py
from plugin_base import PluginBase
from log_config import get_logger

logger = get_logger(__name__)

class MyPlugin(PluginBase):
    name = "my_plugin"
    version = "1.0"

    def on_startup(self, app):
        super().on_startup(app)
        logger.info("[my_plugin] 已启动")

    def on_user_input(self, text):
        # 处理用户输入
        return None  # 返回None表示不修改

    def on_llm_context(self, user_input):
        # 返回要注入到LLM的额外上下文
        return "【我的插件】一些上下文信息"

    def on_register_tools(self):
        # 注册LangGraph工具
        return [
            {
                "type": "function",
                "function": {
                    "name": "my_tool",
                    "description": "我的工具",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "param1": {"type": "string", "description": "参数1"}
                        },
                        "required": ["param1"]
                    }
                }
            }
        ]

    def on_execute_tool(self, tool_name, tool_args):
        if tool_name == "my_tool":
            return self._my_tool(**tool_args)
        return ""

    def _my_tool(self, param1):
        return f"工具执行结果: {param1}"

    def on_register_background_tasks(self):
        # 注册后台任务
        return [
            {
                "task_id": "check_status",
                "interval": 60,
                "callback": self._check_status,
                "description": "检查状态"
            }
        ]

    def _check_status(self):
        # 后台任务回调
        logger.info("[my_plugin] 检查状态...")
        return None

    def get_frontend_html(self):
        # 返回前端HTML
        return """
        <div style="padding: 12px;">
            <h3>我的插件</h3>
            <p>插件内容...</p>
        </div>
        """
```

---

## 已有插件说明

### 1. chatbox_plugin.py - 聊天框插件

**功能**:
- 提供文字输入界面
- 记录对话消息
- 前端轮询展示

**Hook实现**:
- `on_user_input`: 记录用户消息
- `on_llm_response`: 记录AI回复
- `get_frontend_html`: 聊天界面

---

### 2. emotion_rag_plugin.py - 情绪分析与RAG记忆插件

**功能**:
- 用户输入时进行关键词情感分析
- LLM请求前进行零样本情感分析
- 自适应检索决策
- Chroma记忆检索
- 规则学习与更新

**Hook实现**:
- `on_user_input`: 关键词情感分析
- `on_llm_context`: 零样本情感分析 + 记忆检索 + 构建上下文
- `on_llm_response`: 存储对话到Chroma记忆库

---

### 3. scheduler_plugin.py - 日程管理插件

**功能**:
- 添加/查看/完成/删除日程任务
- 后台定时检查到期任务
- 自动提醒
- LangGraph工具调用支持

**Hook实现**:
- `on_startup`: 加载任务数据
- `on_register_background_tasks`: 注册检查提醒任务
- `on_task_complete`: 处理提醒
- `on_llm_context`: 注入待办任务信息
- `on_register_tools`: 注册add_task/list_tasks/complete_task/delete_task工具
- `on_execute_tool`: 执行工具
- `get_frontend_html`: 日程界面

**数据持久化**:
- 任务存储: `plugins_data/scheduler/tasks.json`
- 自动加载/保存

---

### 4. agentic_rag_plugin.py - Agentic RAG插件

**功能**:
- Agentic RAG检索
- 工具调用支持
- LLM上下文注入

---

### 5. demo_template_plugin.py - 演示模板插件

**功能**:
- 插件开发模板
- 展示所有Hook的用法

---

## IOCP架构详解

### 事件循环模型

```
┌──────────────────────────────────────────────────────────────┐
│                   IOCPScheduler                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │         ProactorEventLoop (Windows IOCP)               │  │
│  │   ┌──────────┐  ┌──────────┐  ┌──────────┐           │  │
│  │   │ Task 1   │  │ Task 2   │  │ Task N   │           │  │
│  │   │ 30s间隔  │  │ 60s间隔  │  │ ...      │           │  │
│  │   └──────────┘  └──────────┘  └──────────┘           │  │
│  └────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────┐  │
│  │         ThreadPoolExecutor (IOCP-Worker)               │  │
│  │   ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐            │  │
│  │   │线程1 │  │线程2 │  │线程3 │  │线程N │            │  │
│  │   └──────┘  └──────┘  └──────┘  └──────┘            │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

### 线程安全

- 使用`threading.Lock`保护任务管理
- 使用`loop.call_soon_threadsafe`跨线程调用
- 使用`loop.run_in_executor`在线程池执行同步代码

### 异步包装器

```python
# 同步代码（阻塞）
def sync_function():
    time.sleep(1)  # 阻塞1秒
    return "result"

# 异步包装后
async def async_function():
    result = await run_sync(sync_function)  # 不阻塞事件循环
    return result
```

---

## 测试文件

### test_iocp_basic.py - IOCP基础框架测试

**测试内容**:
1. IOCPScheduler基本功能
2. 任务调度与执行
3. 异步包装器功能
4. 线程安全性
5. 资源清理

**运行**:
```bash
python test/test_iocp_basic.py
```

---

### test_plugin_iocp.py - 插件系统IOCP集成测试

**测试内容**:
1. PluginBase新增接口
2. PluginRegistry IOCP模式
3. 后台任务注册与执行
4. 向后兼容性

**运行**:
```bash
python test/test_plugin_iocp.py
```

---

### test_main_iocp.py - main.py IOCP集成验证

**测试内容**:
1. main.py模块导入（语法检查）
2. IOCP条件导入
3. MainManager新增方法
4. 配置联动

**运行**:
```bash
python test/test_main_iocp.py
```

---

### test_scheduler_plugin.py - 日程管理插件测试

**测试内容** (12项):
1. 插件自动加载
2. 添加任务
3. 查看任务
4. 完成任务
5. 删除任务
6. 后台提醒检查
7. 过期任务标记
8. LangGraph工具注册
9. 工具执行
10. LLM上下文注入
11. 数据持久化
12. 前端HTML

**运行**:
```bash
python test/test_scheduler_plugin.py
```

---

## 项目目录结构

```
Live2D-LLM-Chat/
├── main.py                          # 主程序
├── config.py                        # 配置文件
├── plugin_base.py                   # 插件基类
├── plugin_registry.py               # 插件注册中心
├── event_loop.py                    # IOCP事件循环调度器
├── async_wrapper.py                 # 同步代码异步包装器
├── graph_engine.py                  # LangGraph智能体图引擎
├── LLM.py                          # LLM管理器
├── TTS.py                          # TTS管理器
├── TTS_api.py                      # TTS API管理器
├── ASR.py                          # ASR管理器
├── Live2d_animation.py             # Live2D管理器
├── ui_shell.py                     # UI前端管理器
├── log_config.py                   # 日志配置
├── .env                            # 环境变量
├── requirements.txt                # 依赖列表
├── README.md                       # 项目说明
├── IOCP_ARCHITECTURE.md            # IOCP架构文档
├── plugins/                        # 插件目录
│   ├── __init__.py
│   ├── chatbox_plugin.py
│   ├── emotion_rag_plugin.py
│   ├── scheduler_plugin.py
│   ├── agentic_rag_plugin.py
│   └── demo_template_plugin.py
├── test/                           # 测试目录
│   ├── test_iocp_basic.py
│   ├── test_plugin_iocp.py
│   ├── test_main_iocp.py
│   └── test_scheduler_plugin.py
├── plugins_data/                   # 插件数据目录
│   └── scheduler/
│       └── tasks.json
├── LLM_env/                        # LLM环境
│   └── conversation_history.txt
├── TTS_env/                        # TTS环境
│   ├── output_voice/
│   ├── voice_history/
│   └── tmp/
├── ASR_env/                        # ASR环境
│   └── input_voice/
├── Live2d_env/                     # Live2D环境
│   └── *.model3.json
└── logs/                           # 日志目录
    └── run.log
```

---

## 启动与运行

### 环境准备

```bash
# 安装依赖
pip install -r requirements.txt

# 配置环境变量
# 编辑 .env 文件，配置API密钥等
```

### 启动程序

```bash
python main.py
```

**启动流程**:
1. 打印启动横幅
2. 初始化所有模块
3. 加载插件
4. 启动IOCP事件循环
5. 启动Live2D渲染线程
6. 进入主对话循环

### 停止程序

- 关闭Live2D窗口
- 或按Ctrl+C

---

## 配置说明

### 环境变量 (.env)

```env
# MIMO API密钥
MIMO_API_KEY=your_api_key

# LLM API密钥
LLM_CLOUD_API_KEY=your_api_key
```

### config.py 配置项

**ASR配置**:
```python
ASR_MODE = "cloud"  # "local" or "cloud"
ASR_MODEL_DIR = "..."  # 本地模型路径
```

**TTS配置**:
```python
TTS_MODE = "cloud"  # "local" or "cloud"
TTS_API_URL = "http://localhost:8000/"  # 本地TTS API
```

**LLM配置**:
```python
LLM_MODE = "cloud"  # "local" or "cloud"
LLM_CLOUD_API_KEY = "..."
LLM_CLOUD_BASE_URL = "https://api.deepseek.com"
LLM_CLOUD_MODEL_NAME = "deepseek-v4-flash"
```

**IOCP配置**:
```python
IOCP_MAX_WORKERS = 0  # 0=自动(CPU核心数*2)
IOCP_TASK_CHECK_INTERVAL = 1.0  # 后台任务检查间隔(秒)
ASYNC_WRAPPER_TIMEOUT = 30.0  # 异步包装器超时(秒)
```

---

## 调试与日志

### 日志配置

**日志文件**: `logs/run.log`
**控制台输出**: 实时打印
**日志级别**: INFO (可在log_config.py中修改)

### 调试技巧

**1. 查看插件加载日志**:
```
[插件] 扫描目录: D:\...\plugins
[插件] 发现 5 个候选文件: [...]
  [OK] scheduler v1.0  (Hook: ...)
[插件] 扫描完成: 成功加载 5/5 个
```

**2. 查看IOCP任务调度日志**:
```
[IOCP] 调度任务: scheduler_check_reminders (间隔: 30s)
[IOCP] 任务 scheduler_check_reminders 执行完成 (第 1 次)
```

**3. 查看异步包装器日志**:
```
[AsyncWrapper] 初始化完成，工作线程数: 8
[AsyncWrapper] 线程池已关闭
```

---

## 常见问题

### 1. 插件加载失败

**原因**: 插件文件命名不符合 `*_plugin.py` 规范

**解决**: 确保插件文件以 `_plugin.py` 结尾

### 2. 后台任务不执行

**原因**: 任务ID重复或任务被禁用

**解决**: 检查任务ID唯一性，确保任务enabled=True

### 3. 异步包装器超时

**原因**: 同步代码执行时间超过ASYNC_WRAPPER_TIMEOUT

**解决**: 增加ASYNC_WRAPPER_TIMEOUT配置或优化同步代码

### 4. 数据持久化失败

**原因**: plugins_data目录权限问题

**解决**: 确保程序有写入权限

---

## 扩展开发

### 添加新插件

1. 在 `plugins/` 目录创建 `my_plugin.py`
2. 继承 `PluginBase`
3. 实现需要的Hook方法
4. 重启程序自动加载

### 添加新的后台任务

在插件中实现 `on_register_background_tasks()`:
```python
def on_register_background_tasks(self):
    return [
        {
            "task_id": "my_task",
            "interval": 60,
            "callback": self._my_callback,
            "description": "我的后台任务"
        }
    ]
```

### 添加新的LangGraph工具

在插件中实现 `on_register_tools()` 和 `on_execute_tool()`:
```python
def on_register_tools(self):
    return [
        {
            "type": "function",
            "function": {
                "name": "my_tool",
                "description": "工具描述",
                "parameters": {...}
            }
        }
    ]

def on_execute_tool(self, tool_name, tool_args):
    if tool_name == "my_tool":
        return self._execute_my_tool(**tool_args)
    return ""
```

---

## 版本历史

**v1.0** (初始版本)
- 基础功能实现
- 插件系统

**v2.0** (IOCP架构重构)
- IOCP事件循环
- 异步包装器
- 后台任务系统
- LangGraph工具支持

---

## 相关文档

- `README.md`: 项目简介
- `IOCP_ARCHITECTURE.md`: IOCP架构详细说明
- `requirements.txt`: 依赖列表

---

## 项目状态

**当前版本**: v2.0
**最后更新**: 2026-06-22
**测试状态**: 11/12 通过
**待完成**: 集成测试、文档编写

---

*文档生成时间: 2026-06-22*
