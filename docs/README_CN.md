# VirtuMate Live2D-LLM-Chat
[US English](README.md) | [CN 中文](README_CN.md)

[![ASR](https://img.shields.io/badge/ASR-SenseVoice%2FMiMo-green.svg)](https://github.com/FunAudioLLM/SenseVoice)
[![LLM](https://img.shields.io/badge/LLM-GPT%2FDeepSeek%2FMiMo-red.svg)](https://openai.com/api/) 
[![TTS](https://img.shields.io/badge/TTS-CosyVoice%2FMiMo-orange.svg)](https://github.com/FunAudioLLM/CosyVoice)
[![Live2D](https://img.shields.io/badge/Live2D-v3-blue.svg)](https://github.com/Arkueid/live2d-py)
[![IOCP](https://img.shields.io/badge/IOCP-Architecture-blue.svg)](https://docs.python.org/3/library/asyncio-eventloop.html)

[![Python](https://img.shields.io/badge/Python-3.10+-yellow.svg)](https://www.python.org/downloads/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agent-purple.svg)](https://langchain-ai.github.io/langgraph/)

> **Live2D + ASR + LLM + TTS + IOCP** → 实时语音互动 | 本地部署 / 云端推理 | **IOCP异步架构 | 插件化系统 | LangGraph智能体**

---

## ✨ 1. 项目简介

**VirtuMate Live2D-LLM-Chat** 是一个基于**IOCP异步架构**的智能语音对话Live2D桌宠应用。采用**插件化设计**，支持**LangGraph智能体**，实现高性能异步调度和多模态交互。

### 核心特性

- **IOCP异步架构**: 基于Windows ProactorEventLoop实现高性能异步处理
- **插件化系统**: 模块化设计，易于扩展，支持5个功能插件
- **LangGraph Agent**: 智能体图引擎，支持工具调用和多轮对话
- **多模态交互**: 语音输入(ASR)、语音合成(TTS)、Live2D渲染、文本交互
- **后台任务**: 定时任务调度，不依赖用户输入

### 技术栈

| 组件 | 本地技术 | 云端技术 |
|------|---------|---------|
| ASR（语音识别） | SenseVoice | MiMo ASR |
| LLM（大语言模型） | LM Studio | OpenAI / DeepSeek / MiMo |
| TTS（文本转语音） | CosyVoice | MiMo TTS |
| Live2D 动画 | live2d-py + OpenGL | - |
| 架构 | IOCP异步 | - |
| 智能体 | LangGraph | - |

---

## 🏗️ 2. 架构设计

### IOCP异步架构

```
┌──────────────────────────────────────────────────────────────┐
│                    MainManager (main.py)                      │
│  统筹调度所有模块: ASR, TTS, LLM, Live2D, UI, 插件, Agent    │
├──────────────────────────────────────────────────────────────┤
│  IOCPScheduler (event_loop.py)                               │
│  • ProactorEventLoop (Windows IOCP)                          │
│  • 线程池执行同步代码                                         │
│  • 定时任务调度                                              │
├──────────────────────────────────────────────────────────────┤
│  AsyncWrapper (async_wrapper.py)                             │
│  • 同步代码异步包装器                                        │
│  • 避免阻塞事件循环                                         │
├──────────────────────────────────────────────────────────────┤
│  PluginRegistry (plugin_registry.py)                         │
│  • 插件自动发现与加载                                        │
│  • 后台任务注册与管理                                        │
│  • LangGraph工具收集与执行                                   │
├──────────────────────────────────────────────────────────────┤
│  PluginBase (plugin_base.py)                                 │
│  • 插件基类                                                  │
│  • 7个Hook生命周期方法                                       │
│  • IOCP后台任务Hook                                          │
│  • LangGraph工具Hook                                         │
└──────────────────────────────────────────────────────────────┘
```

### 线程模型

- **主线程**: pywebview前端事件循环
- **对话线程**: IOCP对话循环线程
- **Live2D线程**: 守护线程运行渲染
- **IOCP工作线程**: 线程池执行同步代码（ASR/TTS/Live2D）

---

## 🚀 3. 快速开始

### 3.1 环境要求

- **Python**: 3.10 或更高版本
- **操作系统**: Windows 10/11（推荐，支持IOCP）或 Linux
- **可选**: Miniconda（仅本地模式需要）

### 3.2 安装

```bash
# 克隆项目
git clone https://github.com/suzuran0y/Live2D-LLM-Chat.git
cd Live2D-LLM-Chat

# 创建虚拟环境（可选）
python -m venv venv
venv\Scripts\activate  # Windows
source venv/bin/activate  # Linux

# 安装依赖
pip install -r requirements.txt
```

### 3.3 配置

编辑 `config.py` 配置文件：

```python
class Config:
    # ASR模式: "local" 或 "cloud"
    ASR_MODE = "cloud"
    
    # TTS模式: "local" 或 "cloud"
    TTS_MODE = "cloud"
    
    # LLM模式: "local" 或 "cloud"
    LLM_MODE = "cloud"
    
    # MIMO API配置（云端模式）
    MIMO_API_KEY = "your_api_key"
    MIMO_BASE_URL = "https://api.xiaomimimo.com/v1"
    
    # LLM API配置
    LLM_CLOUD_API_KEY = "your_api_key"
    LLM_CLOUD_BASE_URL = "https://api.deepseek.com"
    LLM_CLOUD_MODEL_NAME = "deepseek-v4-flash"
```

### 3.4 运行

```bash
python main.py
```

**启动流程**:
1. 打印启动横幅
2. 初始化所有模块（ASR/TTS/LLM/Live2D）
3. 加载插件
4. 启动IOCP事件循环
5. 启动Live2D渲染线程
6. 进入主对话循环

**停止程序**: 关闭Live2D窗口或按 Ctrl+C

---

## 📦 4. 项目结构

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
├── ASR.py                          # ASR管理器
├── Live2d_animation.py             # Live2D管理器
├── ui_shell.py                     # UI前端管理器
├── log_config.py                   # 日志配置
├── .env                            # 环境变量
├── requirements.txt                # 依赖列表
├── README.md                       # 项目说明（英文）
├── README_CN.md                    # 项目说明（中文）
├── PROJECT_DOCUMENTATION.md        # 完整项目文档
├── IOCP_ARCHITECTURE.md            # IOCP架构文档
├── plugins/                        # 插件目录
│   ├── chatbox_plugin.py           # 聊天框插件
│   ├── emotion_rag_plugin.py       # 情绪分析RAG插件
│   ├── scheduler_plugin.py         # 日程管理插件
│   ├── agentic_rag_plugin.py       # Agentic RAG插件
│   └── demo_template_plugin.py     # 模板示例插件
├── test/                           # 测试目录
│   ├── test_iocp_basic.py          # IOCP基础测试
│   ├── test_plugin_iocp.py         # 插件系统测试
│   ├── test_main_iocp.py           # main.py验证
│   ├── test_scheduler_plugin.py    # 日程管理插件测试
│   ├── INTEGRATION_TEST_CHECKLIST.md  # 集成测试清单
│   └── TESTING_GUIDE.md            # 测试指南
├── plugins_data/                   # 插件数据目录
│   └── scheduler/
│       └── tasks.json
├── LLM_env/                        # LLM环境
├── TTS_env/                        # TTS环境
├── ASR_env/                        # ASR环境
├── Live2d_env/                     # Live2D环境
└── logs/                           # 日志目录
```

---

## 🔌 5. 插件系统

### 已有插件

1. **chatbox_plugin.py** - 聊天框插件
   - 提供文字输入界面
   - 记录对话消息

2. **emotion_rag_plugin.py** - 情绪分析RAG插件
   - 用户输入情感分析
   - Chroma记忆检索
   - 自适应规则学习

3. **scheduler_plugin.py** - 日程管理插件
   - 添加/查看/完成/删除任务
   - 后台定时提醒
   - LangGraph工具调用

4. **agentic_rag_plugin.py** - Agentic RAG插件
   - Agentic RAG检索
   - 工具调用支持

5. **demo_template_plugin.py** - 模板示例插件
   - 插件开发模板
   - 展示所有Hook用法

### 创建插件

```python
# my_plugin.py
from plugin_base import PluginBase

class MyPlugin(PluginBase):
    name = "my_plugin"
    version = "1.0"
    
    def on_startup(self, app):
        super().on_startup(app)
        # 插件初始化
    
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
    
    def on_register_tools(self):
        # 注册LangGraph工具
        return [...]
    
    def on_execute_tool(self, tool_name, tool_args):
        # 执行工具
        return ""
```

---

## ⚙️ 6. IOCP配置

### config.py 中的IOCP配置项

```python
class Config:
    # IOCP工作线程数（0=自动，CPU核心数*2）
    IOCP_MAX_WORKERS = 0
    
    # 后台任务检查间隔（秒）
    IOCP_TASK_CHECK_INTERVAL = 1.0
    
    # 异步包装器超时时间（秒）
    ASYNC_WRAPPER_TIMEOUT = 30.0
```

### 事件循环API

```python
from event_loop import get_scheduler, shutdown_scheduler

# 获取全局调度器
scheduler = get_scheduler()

# 调度任务
scheduler.schedule_task(
    task_id="my_task",
    interval=30,
    callback=my_callback,
    description="我的任务"
)

# 运行事件循环
scheduler.run_forever()

# 停止
scheduler.stop()
```

### 异步包装器API

```python
from async_wrapper import run_sync, async_wrap

# 方式1: 直接调用
result = await run_sync(sync_function, arg1, arg2)

# 方式2: 装饰器
@async_wrap
def sync_function(x, y):
    return x + y

result = await sync_function(1, 2)
```

---

## 🧪 7. 测试

### 运行测试

```bash
# 测试1: IOCP基础框架
python test/test_iocp_basic.py

# 测试2: 插件系统
python test/test_plugin_iocp.py

# 测试3: main.py结构
python test/test_main_iocp.py

# 测试4: 日程管理插件
python test/test_scheduler_plugin.py
```

### 测试覆盖

- **test_iocp_basic.py**: IOCP调度器、任务管理、异步包装器、线程安全性
- **test_plugin_iocp.py**: 插件基类、注册中心、后台任务、工具注册
- **test_main_iocp.py**: main.py语法、IOCP导入、配置联动
- **test_scheduler_plugin.py**: 日程管理、工具调用、数据持久化、前端HTML

---

## 📚 8. 文档

- **PROJECT_DOCUMENTATION.md** - 完整项目文档
  - 架构概览
  - 核心模块详解
  - 插件开发指南
  - API参考

- **IOCP_ARCHITECTURE.md** - IOCP架构文档
  - 事件循环模型
  - 线程安全
  - 异步包装器
  - 使用示例

- **test/INTEGRATION_TEST_CHECKLIST.md** - 集成测试清单
- **test/TESTING_GUIDE.md** - 测试指南

---

## 🛠️ 9. 开发指南

### 添加新插件

1. 在 `plugins/` 目录创建 `my_plugin.py`
2. 继承 `PluginBase`
3. 实现需要的Hook方法
4. 重启程序自动加载

### 添加后台任务

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

### 添加LangGraph工具

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

## 📊 10. 项目状态

**当前版本**: v2.0 (IOCP架构重构)
**最后更新**: 2026-06-22
**测试状态**: 28项测试（4个测试文件）
**文档状态**: 完整

### 已完成阶段

1. ✅ IOCP基础框架
2. ✅ 插件系统改造
3. ✅ 主程序重构
4. ✅ 日程管理插件
5. ✅ 集成测试清单
6. ✅ 项目文档编写

---

## 🤝 11. 贡献与鸣谢

本项目基于以下优秀的开源项目：

- [SenseVoice](https://github.com/FunAudioLLM/SenseVoice) - 语音识别
- [CosyVoice](https://github.com/FunAudioLLM/CosyVoice) - 语音合成
- [live2d-py](https://github.com/Arkueid/live2d-py) - Live2D渲染
- [LangGraph](https://langchain-ai.github.io/langgraph/) - 智能体引擎

**特此感谢原项目作者的贡献！**

---

## 📄 12. 许可证

本项目采用 [Apache-2.0 许可证](LICENSE)。

---

## 🔗 13. 相关链接

- **GitHub**: https://github.com/suzuran0y/Live2D-LLM-Chat
- **Issues**: https://github.com/suzuran0y/Live2D-LLM-Chat/issues
- **MiMo开放平台**: https://platform.xiaomimimo.com

---

*文档更新时间: 2026-06-22*
*版本: v2.0 (IOCP架构)*
