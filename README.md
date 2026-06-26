# VirtuMate - Live2D AI 桌面助手

基于 Live2D 数字人 + LLM 对话 + 语音交互的桌面 AI 助手，支持本地/云端混合部署。

## 功能特性

- **Live2D 数字人**：OpenGL 实时渲染，嘴型同步，眼神跟随
- **语音交互**：麦克风录音 → ASR 语音识别 → LLM 对话 → TTS 语音合成
- **多 TTS 引擎**：本地 Piper TTS / 云端 MiMo TTS / 本地 MOSS-TTS-Nano（支持声音克隆）
- **多 ASR 引擎**：本地 faster-whisper / 云端 MiMo ASR
- **LLM 对话**：云端 DeepSeek/MiMo API 或本地 LM Studio
- **插件系统**：情绪识别、定时提醒、知识库 RAG 检索、Agent 智能体

## 快速开始

### 环境要求

- Python >= 3.10
- Windows 10/11（Live2D 渲染依赖 OpenGL）
- 可选：NVIDIA GPU（CUDA 12.x，加速 ASR/LLM 推理）

### 安装

```bash
git clone <repo-url>
cd Live2D-LLM-Chat
pip install -r requirements.txt
```

### 配置

复制环境变量模板并填入 API Key：

```bash
cp .env.example .env
# 编辑 .env，填入 MIMO_API_KEY、LLM_CLOUD_API_KEY 等
```

### 启动

```bash
# 方式 1：一键启动（自动配置 HuggingFace 镜像）
run.bat

# 方式 2：直接运行
python main.py
```

启动后按提示选择 ASR / LLM / TTS 的部署模式（本地或云端）。

## TTS 引擎

| 模式 | 引擎 | 说明 |
|------|------|------|
| `local` | Piper TTS | 轻量本地 TTS，22kHz，单音色，CPU 友好 |
| `cloud` | MiMo-V2.5-TTS | 小米云端 TTS，多种音色，需 API Key |
| `moss` | MOSS-TTS-Nano | 本地 ONNX TTS，48kHz 立体声，支持声音克隆，20 种语言 |

在 `config.py` 中设置 `TTS_MODE` 切换，或启动时交互选择。

### MOSS-TTS-Nano 声音克隆

1. 准备一段 3~10 秒的参考音频（WAV/MP3/FLAC）
2. 放到 `TTS_env/prompt_audio/` 目录
3. 在 `config.py` 中设置：
   ```python
   TTS_MODE = "moss"
   MOSS_PROMPT_AUDIO_PATH = "TTS_env/prompt_audio/my_voice.wav"
   ```
4. 首次启动会自动下载 ONNX 模型到 MOSS-TTS-Nano 项目的 `models/` 目录

内置音色：Xiaoyu / Yuewen / Lingyu（中文女声），Junhao / Zhiming / Weiguo（中文男声），Trump / Ava / Adam 等英文音色，以及多个日语音色。

## 项目结构

```
├── main.py                 # 主入口，交互式部署模式选择
├── config.py               # 全局配置（ASR/LLM/TTS/Live2D 参数）
├── graph_engine.py         # LangGraph 对话引擎（图节点编排）
├── ASR.py                  # 语音识别管理器
├── LLM.py                  # 大语言模型管理器
├── TTS.py                  # 语音合成管理器（Piper/MiMo/MOSS 三模式）
├── Live2d_animation.py     # Live2D 渲染与嘴型同步
├── ui_shell.py             # pywebview 前端 UI
├── kb_controller.py        # 知识库控制器（Milvus + BGE-M3 向量检索）
├── infrastructure/
│   └── _bootstrap.py       # 启动引导（模型缓存重定向 + HF 镜像回退）
├── plugins/                # 插件目录
│   ├── emotion_rag_plugin.py    # 情绪 RAG 插件
│   ├── scheduler_plugin.py      # 定时提醒插件
│   ├── agentic_rag_plugin.py    # Agent 智能体 RAG 插件
│   └── chatbox_plugin.py        # 聊天框插件
├── TTS_env/                # TTS 工作目录（输出音频、模型缓存）
├── ASR_env/                # ASR 工作目录（录音文件）
├── Live2d_env/             # Live2D 模型文件
├── LLM_env/                # LLM 对话历史
├── .models/                # 模型缓存（HuggingFace/ModelScope/PyTorch）
└── logs/                   # 运行日志
```

## HuggingFace 镜像

国内用户自动使用 `hf-mirror.com` 镜像加速模型下载。镜像下载失败时自动回退到 `huggingface.co` 官方站。如需手动指定：

```bash
set HF_ENDPOINT=https://huggingface.co   # 使用官方站（需网络通畅）
set HF_ENDPOINT=https://hf-mirror.com    # 使用国内镜像
```

## 许可证

本项目仅供个人学习使用。依赖的第三方模型（Piper TTS、MOSS-TTS-Nano、faster-whisper 等）请遵循其各自的许可协议。
