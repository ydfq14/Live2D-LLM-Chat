# VirtuMate - Live2D AI 桌面助手

[US English](README.md) | [CN 中文](README_CN.md)

[![ASR](https://img.shields.io/badge/ASR-faster--whisper%2FMiMo-green.svg)](https://github.com/SYSTRAN/faster-whisper)
[![LLM](https://img.shields.io/badge/LLM-DeepSeek%2FMiMo%2FLM%20Studio-red.svg)](https://openai.com/api/)
[![TTS](https://img.shields.io/badge/TTS-Piper%2FMiMo%2FMOSS-orange.svg)](https://github.com/OpenMOSS/MOSS-TTS-Nano)
[![Live2D](https://img.shields.io/badge/Live2D-v3-blue.svg)](https://github.com/Arkueid/live2d-py)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agent-purple.svg)](https://langchain-ai.github.io/langgraph/)
[![Python](https://img.shields.io/badge/Python-3.10+-yellow.svg)](https://www.python.org/)

> **Live2D 数字人 + LLM 对话 + 语音交互** — 支持本地/云端混合部署，IOCP 异步架构，插件化设计，LangGraph 智能体引擎。

---

## 1. 功能特性

- **Live2D 数字人**：OpenGL 实时渲染，嘴型同步，眼神跟随鼠标
- **语音交互**：麦克风录音 → ASR 语音识别 → LLM 对话 → TTS 语音合成播报
- **多 TTS 引擎**：
  - `local` — Piper TTS，轻量本地引擎，CPU 即可运行
  - `cloud` — MiMo-V2.5-TTS，小米云端 TTS，多音色可选
  - `moss` — MOSS-TTS-Nano，本地 ONNX 引擎，48kHz 立体声，支持音色克隆
- **多 ASR 引擎**：本地 faster-whisper / 云端 MiMo ASR
- **多 LLM 后端**：云端 DeepSeek/MiMo API，或本地 LM Studio/Ollama
- **8 个功能插件**：情绪分析、日程提醒、知识库 RAG、Agent 智能体、自动关怀、面部表情识别、人设管理、助手工具
- **自动关怀**：主动推送关怀消息（情绪关怀/时段问候/空闲检测/久聊提醒）

---

## 2. 快速开始

### 2.1 环境要求

- Python >= 3.10
- Windows 10/11（Live2D 需要 OpenGL）
- 可选：NVIDIA GPU + CUDA 12.8（加速 ASR 推理 10-20x）

### 2.2 安装

```bash
git clone <仓库地址>
cd Live2D-LLM-Chat

# 推荐使用 conda 虚拟环境
conda create -n virtumate python=3.10 -y
conda activate virtumate

# 安装依赖
pip install -r requirements.txt
```

### 2.3 配置

**（1）API 密钥（.env 文件）**

```bash
cp .env.example .env
# 编辑 .env：
#   MIMO_API_KEY=你的小米MIMO密钥    （云端 ASR/TTS 需要）
#   LLM_CLOUD_API_KEY=你的DeepSeek密钥 （云端 LLM 需要）
```

**（2）运行模式（config.py）**

```python
# ASR 语音识别
ASR_MODE = "faster-whisper"   # "faster-whisper"（本地）或 "cloud"（云端）

# LLM 大语言模型
LLM_MODE = "local"            # "local"（LM Studio）或 "cloud"（DeepSeek/MiMo）

# TTS 语音合成
TTS_MODE = "cloud"            # "local"（Piper）、"cloud"（MiMo）或 "moss"（MOSS）
```

### 2.4 启动

```bash
python main.py
```

启动后按交互提示选择各模块的部署模式。使用 `--auto` 跳过交互，直接使用 `config.py` 的默认值。

---

## 3. TTS 引擎详解

| 模式 | 引擎 | 音频规格 | 音色 | 需联网 | 部署难度 |
|------|------|---------|------|:---:|:---:|
| `local` | Piper TTS | 22kHz 单声道 | 单一女声（花言） | 否 | 一键 |
| `cloud` | MiMo-V2.5-TTS | 24kHz | 冰糖/茉莉/苏打/白桦 等 8+ 音色 | 是 | 零 |
| `moss` | MOSS-TTS-Nano | 48kHz 立体声 | 20+ 内置音色 + 音色克隆 | 否（首次下载模型后） | 中等 |

### 3.1 MOSS-TTS-Nano 本地部署（支持音色克隆）

MOSS-TTS-Nano 是 OpenMOSS 团队开源的微型 TTS 模型（0.1B 参数），基于 ONNX Runtime 推理，纯 CPU 可跑。支持 20 种语言、48kHz 立体声输出，可通过一段参考音频克隆任意音色。

#### 第一步：克隆并安装 MOSS-TTS-Nano

```bash
# 克隆到任意目录（建议放在项目旁边）
git clone https://github.com/OpenMOSS/MOSS-TTS-Nano.git
cd MOSS-TTS-Nano

# 安装到当前 Python 环境
pip install -e .
```

执行 `pip install -e .` 后，MOSS 模块已注册到 Python 的 site-packages，后续 VirtuMate 可直接 `import onnx_tts_runtime`，**无需任何路径配置**。

#### 第二步：配置 VirtuMate

编辑 `config.py`：

```python
TTS_MODE = "moss"                       # 切换到 MOSS 模式
MOSS_VOICE = "Xiaoyu"                   # 内置音色名称
MOSS_CPU_THREADS = 4                    # ONNX Runtime 线程数（建议 = CPU 核心数）
MOSS_EXECUTION_PROVIDER = "cpu"         # "cpu" 或 "cuda"（需 onnxruntime-gpu）
MOSS_MAX_NEW_FRAMES = 375              # 最大生成长度（375 ≈ 30 秒音频）
```

#### 第三步：首次启动（自动下载模型）

```bash
python main.py
```

首次运行时 MOSS 会自动从 HuggingFace 下载 ONNX 模型（项目已配置 hf-mirror.com 国内镜像）：

| 模型 | 大小 | 说明 |
|------|------|------|
| `MOSS-TTS-Nano-100M-ONNX/` | 642 MB | TTS 核心模型（LLM 自回归生成音频 token） |
| `MOSS-Audio-Tokenizer-Nano-ONNX/` | 87 MB | 音频编解码器（参考音频编码 / 波形解码） |
| **合计** | **~730 MB** | 仅需下载一次 |

模型下载后存放在 MOSS 源码目录的 `models/` 子目录下。

#### 第四步（可选）：自定义音色克隆

1. 准备一段 3-10 秒的参考音频（WAV/MP3/FLAC 均可），要求说话人声音清晰
2. 放到 `TTS_env/prompt_audio/` 目录：
   ```bash
   cp 我的声音.wav TTS_env/prompt_audio/my_voice.wav
   ```
3. 在 `config.py` 中设置：
   ```python
   MOSS_PROMPT_AUDIO_PATH = "TTS_env/prompt_audio/my_voice.wav"
   ```
4. 重启程序。启动时会自动预编码参考音频并缓存，后续合成零额外开销。

#### MOSS 依赖清单

| 依赖 | 安装方式 |
|------|---------|
| MOSS-TTS-Nano 源码 | `git clone` + `pip install -e .` |
| onnxruntime | `pip install -r requirements.txt`（已包含） |
| sentencepiece | 随 `pip install -e .` 自动安装 |
| WeTextProcessing | 随 `pip install -e .` 自动安装 |
| torch + torchaudio | `pip install -r requirements.txt`（已包含，仅用于音频 I/O） |

#### 内置音色列表

中文女声：`Xiaoyu` / `Yuewen` / `Lingyu`
中文男声：`Junhao` / `Zhiming` / `Weiguo`
英文：`Trump` / `Ava` / `Adam` / `Mia` / `Chloe` / `Milo` / `Dean` 等
日语：多个日语音色

---

## 4. 插件系统（8 个插件）

所有插件存放在 `plugins/` 目录，程序启动时自动扫描加载，按字母序排列。

| 插件 | 文件名 | 功能 | 前端面板 |
|------|--------|------|:---:|
| **agentic_rag** | `agentic_rag_plugin.py` | 知识库 RAG 检索，Milvus + BGE-M3 向量搜索 | 有 |
| **assistant_tools** | `assistant_tools_plugin.py` | 工具函数集（时间/系统信息等），供 LangGraph 智能体调用 | 无 |
| **auto_care** | `auto_care_plugin.py` | 自动关怀：4 种场景主动消息推送（情绪/时段/空闲/久聊） | 有 |
| **chatbox** | `chatbox_plugin.py` | 聊天框 UI，消息显示与输入 | 有 |
| **emotion_rag** | `emotion_rag_plugin.py` | 用户情绪分析 + 情景记忆（Chroma 向量库） | 调试面板 |
| **fer** | `fer_plugin.py` | 摄像头实时面部表情识别 | 只读面板 |
| **personality** | `personality_plugin.py` | 角色人设选择与管理 | 有 |
| **scheduler** | `scheduler_plugin.py` | 定时日程提醒（语音播报 + Live2D 口型同步） | 有 |

### 自动关怀（auto_care）详解

自动检测以下 4 种场景并主动推送猫娘风格的关怀消息：

| 优先级 | 场景 | 触发条件 | 冷却策略 |
|:---:|------|---------|---------|
| 1 | 情绪关怀 | 检测到负面情绪（悲伤/愤怒/焦虑等） | 负面情绪时全局冷却缩至 10 分钟 |
| 2 | 时段问候 | 早/中/下午/晚/深夜 5 个时段 | 每天同时段仅触发一次 |
| 3 | 空闲检测 | 超过 5 分钟无交互 | 全局冷却（默认 30 分钟） |
| 4 | 久聊提醒 | 连续对话超过 20 轮 | 触发后重置轮次计数 |

消息通过 LLM 生成猫娘话术，直接 TTS 播报 + chatbox 气泡注入，不污染对话历史。

---

## 5. 项目结构

```
Live2D-LLM-Chat/
├── main.py                     # 主入口，交互式部署模式选择
├── config.py                   # 全局配置（ASR/LLM/TTS/Live2D 参数）
├── graph_engine.py             # LangGraph 对话引擎（9 节点图编排）
├── ASR.py                      # 语音识别管理器
├── LLM.py                      # 大语言模型管理器
├── TTS.py                      # 语音合成管理器（Piper/MiMo/MOSS 三模式）
├── Live2d_animation.py         # Live2D 渲染与嘴型同步
├── ui_shell.py                 # pywebview 前端 UI 壳
├── kb_controller.py            # 知识库控制器（Milvus + BGE-M3 向量检索）
├── plugin_base.py              # 插件基类（7 生命周期 Hook + IOCP + LangGraph Hook）
├── plugin_registry.py          # 插件注册中心（自动扫描 + 后台任务管理）
├── event_loop.py               # IOCP 异步事件循环调度器
├── infrastructure/
│   └── _bootstrap.py           # 启动引导（模型缓存重定向 + HF 镜像回退）
├── plugins/                    # 插件目录（自动发现加载）
│   ├── agentic_rag_plugin.py
│   ├── assistant_tools_plugin.py
│   ├── auto_care_plugin.py
│   ├── chatbox_plugin.py
│   ├── emotion_rag_plugin.py
│   ├── fer_plugin.py
│   ├── personality_plugin.py
│   └── scheduler_plugin.py
├── plugins_data/               # 插件运行时数据
│   ├── auto_care/
│   ├── scheduler/
│   └── agentic_rag/
├── TTS_env/                    # TTS 工作目录
│   ├── output_voice/           # 合成音频输出
│   ├── prompt_audio/           # MOSS 音色克隆参考音频
│   └── piper/                  # Piper TTS 模型缓存
├── ASR_env/                    # ASR 工作目录（录音文件）
├── Live2d_env/                 # Live2D 模型文件（.moc3 / .json / 贴图）
├── LLM_env/                    # LLM 对话历史
├── .models/                    # 模型缓存（HuggingFace / ModelScope / PyTorch / TF）
├── logs/                       # 运行日志
├── .gitignore
├── requirements.txt
├── README.md                   # 英文文档
└── README_CN.md                # 中文文档（本文件）
```

---

## 6. 架构概览

```
┌─────────────────────────────────────────────────────────┐
│                  MainManager (main.py)                   │
│   统筹调度: ASR / LLM / TTS / Live2D / UI / 插件 / Agent  │
├─────────────────────────────────────────────────────────┤
│  IOCP Scheduler (event_loop.py)                         │
│  - ProactorEventLoop (Windows IOCP)                       │
│  - 线程池执行同步任务（ASR / TTS / Live2D）               │
│  - 后台定时任务调度（插件关怀/提醒）                       │
├─────────────────────────────────────────────────────────┤
│  LangGraph Engine (graph_engine.py)                      │
│  - 9 节点对话图：用户输入 → 意图识别 → 上下文收集          │
│    → Agent 推理 ↔ 工具执行 → 响应 → TTS → Live2D → 收尾  │
├─────────────────────────────────────────────────────────┤
│  Plugin Registry (plugin_registry.py)                    │
│  - 自动扫描 plugins/*_plugin.py                         │
│  - 按字母序加载（顺序影响 Hook 执行）                     │
│  - 后台任务注册 + LangGraph 工具收集                      │
└─────────────────────────────────────────────────────────┘
```

**线程模型**：主线程（pywebview UI） + 对话线程（IOCP 异步循环） + Live2D 线程（OpenGL 渲染） + 钩子线程（鼠标跟踪）

---

## 7. 测试

```bash
# IOCP 基础框架测试
python test/test_iocp_basic.py

# 插件系统测试
python test/test_plugin_iocp.py

# 主程序结构验证
python test/test_main_iocp.py

# 日程管理插件测试
python test/test_scheduler_plugin.py
```

---

## 8. 常见问题

### Q: 需要 GPU 吗？

不需要。CPU 可以运行全部模块。有 NVIDIA GPU 时 faster-whisper 推理速度提升 10-20 倍。

### Q: 如何切换云端/本地模式？

编辑 `config.py` 中的 `ASR_MODE` / `LLM_MODE` / `TTS_MODE`，或启动时按交互提示选择。

### Q: MOSS-TTS-Nano 导入失败？

确保在 MOSS 源码目录执行过 `pip install -e .`。这会把 MOSS 注册到 Python 环境，之后任意位置都能 import。

### Q: MOSS 模型下载太慢？

项目已自动配置 hf-mirror.com 国内镜像。如果仍然很慢，可以手动从 HuggingFace 下载两个模型文件夹放到 MOSS 项目的 `models/` 目录。

### Q: MOSS 可以用 GPU 加速吗？

可以。安装 `onnxruntime-gpu`，然后将 `config.py` 中的 `MOSS_EXECUTION_PROVIDER` 改为 `"cuda"`。

### Q: HuggingFace 模型下载超时？

项目内置 `hf-mirror.com` 国内镜像，下载失败时自动回退到 `huggingface.co` 官方站。也可以手动设置：
```bash
set HF_ENDPOINT=https://hf-mirror.com    # 国内镜像
set HF_ENDPOINT=https://huggingface.co   # 官方站
```

### Q: PyTorch 默认 CPU 版本，需要 GPU 版怎么办？

参考 [GPU 加速配置](#)，卸载 CPU 版 PyTorch，根据你的 CUDA 版本安装对应版本：
```bash
pip uninstall torch torchvision torchaudio -y
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu128
```

---

## 9. 鸣谢

- [live2d-py](https://github.com/Arkueid/live2d-py) — Live2D 渲染引擎
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — 本地语音识别
- [Piper TTS](https://github.com/rhasspy/piper) — 轻量本地 TTS
- [MOSS-TTS-Nano](https://github.com/OpenMOSS/MOSS-TTS-Nano) — 高质量本地 TTS + 音色克隆
- [LangGraph](https://langchain-ai.github.io/langgraph/) — 智能体图引擎
- [MiMo 开放平台](https://platform.xiaomimimo.com) — 云端 ASR/TTS API

---

## 10. 许可证

[Apache-2.0](LICENSE)。第三方模型（Piper TTS、MOSS-TTS-Nano、faster-whisper 等）请遵循各自的许可协议。

---

*文档更新时间: 2026-07-03*
*版本: v2.1*
