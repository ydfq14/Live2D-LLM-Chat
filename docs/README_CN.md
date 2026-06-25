# VirtuMate Live2D-LLM-Chat
[US English](README.md) | [CN 中文](README_CN.md)

[![ASR](https://img.shields.io/badge/ASR-faster--whisper%2FMiMo-green.svg)](https://github.com/SYSTRAN/faster-whisper)
[![LLM](https://img.shields.io/badge/LLM-GPT%2FDeepSeek%2FMiMo-red.svg)](https://openai.com/api/) 
[![TTS](https://img.shields.io/badge/TTS-piper--tts%2FMiMo-orange.svg)](https://github.com/rhasspy/piper)
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
| ASR（语音识别） | faster-whisper | MiMo ASR |
| LLM（大语言模型） | LM Studio / Ollama | OpenAI / DeepSeek / MiMo |
| TTS（文本转语音） | piper-tts | MiMo TTS |
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
- **推荐**: Miniconda 或 Anaconda（用于创建虚拟环境，本地模式需要）

### 3.2 安装

```bash
# 克隆项目
git clone https://github.com/suzuran0y/Live2D-LLM-Chat.git
cd Live2D-LLM-Chat

# 创建 conda 虚拟环境（推荐）
conda create -n virtumate python=3.10 -y
conda activate virtumate

# 安装依赖
pip install -r requirements.txt
```

### 3.3 GPU 加速配置（推荐）

> **⚠️ 重要提示**：PyTorch 默认安装的是 **CPU 版本**！
> 如果你有 NVIDIA GPU，强烈建议安装 CUDA 版本以获得 **10-20 倍加速**。

#### 步骤 1: 检查 GPU 和 CUDA 版本

```bash
nvidia-smi
```

查看输出中的 `CUDA Version`（例如 11.8 或 12.4）

#### 步骤 2: 在 Conda 虚拟环境中卸载 CPU 版本的 PyTorch

```bash
# 确保在正确的 conda 环境中
conda activate virtumate

# 卸载 CPU 版本
pip uninstall torch torchvision torchaudio -y
```

#### 步骤 3: 安装 CUDA 版本的 PyTorch

根据你的 CUDA 版本选择：

**CUDA 11.8（推荐，兼容性最好）：**
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
```

**CUDA 12.4：**
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
```

**CUDA 12.1：**
```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

**使用国内镜像加速下载（可选，下载更快）：**
```bash
# 清华镜像
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118 -i https://pypi.tuna.tsinghua.edu.cn/simple

# 阿里云镜像
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118 -i https://mirrors.aliyun.com/pypi/simple/
```

#### 步骤 4: 验证 GPU 安装

```bash
python -c "
import torch
print('PyTorch version:', torch.__version__)
print('CUDA available:', torch.cuda.is_available())
if torch.cuda.is_available():
    print('CUDA version:', torch.version.cuda)
    print('GPU:', torch.cuda.get_device_name(0))
    print('GPU memory:', round(torch.cuda.get_device_properties(0).total_memory / 1024**3, 1), 'GB')
else:
    print('CUDA not available - using CPU')
"
```

**预期输出（GPU 可用时）：**
```
PyTorch version: 2.6.0+cu118
CUDA available: True
CUDA version: 11.8
GPU: NVIDIA GeForce RTX 3060
GPU memory: 6.0 GB
```

#### GPU 性能对比

| 设备 | ASR 模型 | 速度 | 内存占用 |
|------|---------|------|---------|
| **RTX 3060 (GPU)** | small | ~10-20x 实时 | ~2GB |
| CPU | small | ~2-3x 实时 | ~1GB |
| **RTX 3060 (GPU)** | medium | ~5-10x 实时 | ~4GB |
| CPU | medium | ~1-2x 实时 | ~2GB |

### 3.4 配置和运行

#### 配置

本项目需要配置两个文件：

**1. 配置 API 密钥（.env 文件）**

在项目根目录创建 `.env` 文件，存储真实的 API Key：

```bash
# MIMO API Key（ASR + TTS 云端模式）
# 前往 https://platform.xiaomimimo.com 注册获取
MIMO_API_KEY=your_mimo_api_key

# DeepSeek API Key（LLM 云端模式）
# 前往 https://platform.deepseek.com 注册获取
LLM_CLOUD_API_KEY=your_deepseek_api_key
```

> **注意**: `.env` 文件已被 `.gitignore` 排除，不会提交到 git。请勿将真实 API Key 提交到版本控制系统。

**2. 配置运行模式（config.py 文件）**

编辑 `config.py` 配置文件，选择本地或云端模式：

```python
class Config:
    # 项目根目录（自动获取，无需手动修改）
    PROJECT_ROOT = str(Path(__file__).parent)

    # ==================== ASR（语音识别）配置 ====================
    ASR_MODE = "faster-whisper"  # "faster-whisper"（本地） 或 "cloud"（云端 MIMO）
    
    # Faster-Whisper 配置（本地模式）
    ASR_WHISPER_MODEL_SIZE = "small"        # tiny, base, small, medium, large-v3
    ASR_WHISPER_DEVICE = "auto"             # cuda, cpu, auto
    ASR_WHISPER_COMPUTE_TYPE = "float16"    # float16, int8_float16, int8
    ASR_WHISPER_LANGUAGE = "zh"             # zh, en, auto

    # VAD（语音活动检测）参数
    VAD_SILENCE_THRESHOLD = 500     # RMS 能量阈值（0-32767）
    VAD_SILENCE_TIMEOUT = 2.0       # 静音超时秒数
    VAD_MIN_SPEECH_DURATION = 0.3   # 最短有效语音时长（秒）

    # ==================== TTS（语音合成）配置 ====================
    TTS_MODE = "cloud"  # "local"（本地 piper-tts） 或 "cloud"（云端 MIMO）
    
    # Piper TTS 配置（本地模式）
    PIPER_MODEL_PATH = os.path.join(PROJECT_ROOT, "TTS_env/piper/zh_CN-huayan-medium.onnx")
    PIPER_LENGTH_SCALE = 1.0    # 语速：<1.0 加快，>1.0 减慢
    PIPER_NOISE_SCALE = 0.667   # 表现力噪声（0.0-1.0）

    # ==================== MIMO 云端配置 ====================
    MIMO_API_KEY = os.getenv("MIMO_API_KEY", "")  # 从 .env 文件读取
    MIMO_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
    
    # 云端 ASR（MiMo-V2.5-ASR）
    MIMO_ASR_MODEL = "mimo-v2.5-asr"
    MIMO_ASR_LANGUAGE = "auto"  # "auto" | "zh" | "en"
    
    # 云端 TTS（MiMo-V2.5-TTS）
    MIMO_TTS_MODEL = "mimo-v2.5-tts"
    MIMO_TTS_VOICE = "冰糖"  # 可用音色: 冰糖, 茉莉, 苏打, 白桦, Mia, Chloe, Milo, Dean

    # ==================== LLM（大语言模型）配置 ====================
    LLM_MODE = "local"  # "local"（LM Studio） 或 "cloud"（DeepSeek / OpenAI）
    
    # 云端 LLM
    LLM_CLOUD_API_KEY = os.getenv("LLM_CLOUD_API_KEY", "")  # 从 .env 文件读取
    LLM_CLOUD_BASE_URL = "https://api.deepseek.com"
    LLM_CLOUD_MODEL_NAME = "deepseek-v4-flash"
    
    # 本地 LLM（LM Studio）
    LOCAL_LLM_MODEL_NAME = "qwen2.5-7b-instruct"
    LOCAL_LLM_API_URL = "http://127.0.0.1:1234/v1/chat/completions"

    # ==================== Live2D 配置 ====================
    LIVE2D_MODEL_PATH = os.path.join(PROJECT_ROOT, "Live2d_env/pachirisu anime girl - top half.model3.json")

    # ==================== IOCP 配置 ====================
    IOCP_MAX_WORKERS = 0    # 工作线程数（0=自动，CPU核心数 * 2）
    IOCP_TASK_CHECK_INTERVAL = 1.0   # 后台任务检查间隔（秒）
    ASYNC_WRAPPER_TIMEOUT = 30.0     # 异步包装器超时时间（秒）
```

> **完整配置说明**: 详见 `config.py` 文件中的注释，包含更多高级配置选项。

#### 运行

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

## ❓ 11. 常见问题（FAQ）

### Q: 为什么 PyTorch 默认安装的是 CPU 版本？

A: PyTorch 官方为了兼容性，默认提供 CPU 版本。GPU 版本需要根据用户的 CUDA 版本手动安装，避免因版本不匹配导致安装失败。详见 [GPU 加速配置](#33-gpu-加速配置推荐) 部分。

### Q: 如何确定我的 CUDA 版本？

A: 运行以下命令查看：
```bash
nvidia-smi
```
查看输出中的 `CUDA Version`。如果未安装 NVIDIA 驱动，请先从 [NVIDIA 官网](https://www.nvidia.com/drivers) 下载安装。

### Q: 安装 CUDA 版本 PyTorch 后仍然显示 CUDA 不可用？

A: 检查以下几点：
1. **NVIDIA 驱动是否安装**：`nvidia-smi` 应该能正常显示 GPU 信息
2. **是否在正确的 conda 环境中**：`conda activate virtumate`
3. **PyTorch 版本是否正确**：`python -c "import torch; print(torch.__version__)"` 应该显示 `+cu118` 或 `+cu124`
4. **CUDA 版本是否匹配**：确保 PyTorch CUDA 版本与你的 NVIDIA 驱动 CUDA 版本兼容

### Q: 可以同时使用 GPU 和 CPU 模式吗？

A: 可以！项目会自动检测 GPU 是否可用。如果 GPU 不可用，会自动降级到 CPU 模式。日志中会显示：
```
ASR 初始化: faster-whisper, model=small, device=auto
  最终配置: device=cuda, compute_type=float16  ← GPU 模式
```
或
```
  CPU 模式不支持 float16，自动切换到 float32  ← CPU 模式
```

### Q: HuggingFace 模型下载超时？

A: 项目已内置国内镜像配置（hf-mirror.com）。如果仍然超时，可以：
1. 使用代理
2. 手动下载模型
3. 选择云端模式（不需要本地模型）

### Q: 如何更新依赖？

A: 
```bash
pip install -r requirements.txt --upgrade
```

### Q: 使用本地模式时，模型会自动下载吗？

A: 是的！本地模式的模型会自动下载：

- **faster-whisper 模型**：首次使用时自动从 HuggingFace 下载到 `.models/` 目录
- **piper-tts 模型**：首次使用本地 TTS 时自动下载到 `TTS_env/piper/` 目录
- **下载加速**：项目已配置 HuggingFace 国内镜像（hf-mirror.com），下载速度快

> **提示**: 如果自动下载失败（网络问题），程序会提示手动下载的地址和方法。

### Q: PyTorch CUDA 版本下载很慢？

A: 使用国内镜像加速：
```bash
# 清华镜像
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118 -i https://pypi.tuna.tsinghua.edu.cn/simple

# 阿里云镜像
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118 -i https://mirrors.aliyun.com/pypi/simple/
```

### Q: conda 环境中应该使用哪个 Python 版本？

A: 推荐使用 **Python 3.10** 或 **3.11**，兼容性最好。Python 3.12/3.13 也可以，但某些依赖可能还不完全支持。

```bash
# 推荐
conda create -n virtumate python=3.10 -y

# 或者
conda create -n virtumate python=3.11 -y
```

### Q: faster-whisper 和 piper-tts 是什么？

A: 
- **faster-whisper**: OpenAI Whisper 的优化版本，用于语音识别（ASR），支持 GPU 加速
- **piper-tts**: 本地离线语音合成引擎，基于 ONNX 推理，无需 GPU

---

## 🤝 12. 贡献与鸣谢

本项目基于以下优秀的开源项目：

- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) - 语音识别（ASR）
- [piper-tts](https://github.com/rhasspy/piper) - 语音合成（TTS）
- [live2d-py](https://github.com/Arkueid/live2d-py) - Live2D渲染
- [LangGraph](https://langchain-ai.github.io/langgraph/) - 智能体引擎
- [PyTorch](https://pytorch.org/) - 深度学习框架
- [HuggingFace](https://huggingface.co/) - 模型库和工具

**特此感谢原项目作者的贡献！**

---

## 📄 13. 许可证

本项目采用 [Apache-2.0 许可证](LICENSE)。

---

## 🔗 14. 相关链接

- **GitHub**: https://github.com/suzuran0y/Live2D-LLM-Chat
- **Issues**: https://github.com/suzuran0y/Live2D-LLM-Chat/issues
- **MiMo开放平台**: https://platform.xiaomimimo.com

---

*文档更新时间: 2026-06-25*
*版本: v2.0 (IOCP架构)*
