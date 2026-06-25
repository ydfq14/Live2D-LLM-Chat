# 部署模式选择指南

## 使用方法

### 方式 1: 交互式选择（推荐）

直接运行 `main.py`，程序会显示交互式菜单让用户选择：

```bash
python main.py
```

程序启动后会显示：

```
============================================================
VirtuMate 部署模式选择
============================================================

请选择各模块的部署方式：
  1. 本地 (Local) - 使用本地模型，离线可用
  2. 云端 (Cloud) - 使用云端 API，需要网络

提示：直接按回车使用当前配置

------------------------------------------------------------
【ASR 语音识别】
  当前配置: faster-whisper
  选项:
    1. faster-whisper (本地)
    2. cloud (云端 MIMO)
    3. 使用当前配置 (回车)

请选择 ASR 模式 [1/2/3]: 1
  ✓ ASR 已设置为: faster-whisper (本地)

------------------------------------------------------------
【LLM 大语言模型】
  当前配置: local
  选项:
    1. local (本地 LM Studio/Ollama)
    2. cloud (云端 DeepSeek/MiMo)
    3. 使用当前配置 (回车)

请选择 LLM 模式 [1/2/3]: 2
  ✓ LLM 已设置为: cloud (云端)

------------------------------------------------------------
【TTS 语音合成】
  当前配置: cloud
  选项:
    1. local (本地 piper-tts)
    2. cloud (云端 MIMO)
    3. 使用当前配置 (回车)

请选择 TTS 模式 [1/2/3]: 1
  ✓ TTS 已设置为: local (本地)

============================================================
最终部署配置:
============================================================
  ASR: faster-whisper
  LLM: cloud
  TTS: local
============================================================
```

### 方式 2: 自动模式（跳过选择）

使用 `--auto` 参数跳过交互式选择，直接使用 `config.py` 中的默认配置：

```bash
python main.py --auto
```

输出：
```
使用 --auto 参数，跳过模式选择，使用默认配置
  ASR: faster-whisper
  LLM: local
  TTS: cloud
```

## 支持的组合

用户可以自由组合三个模块的部署方式：

| 场景 | ASR | LLM | TTS | 说明 |
|------|-----|-----|-----|------|
| 全本地 | faster-whisper | local | local | 离线可用，无需网络 |
| 全云端 | cloud | cloud | cloud | 无需本地模型，需要网络 |
| 混合 1 | faster-whisper | cloud | local | ASR/TTS 本地，LLM 云端 |
| 混合 2 | cloud | local | cloud | LLM 本地，ASR/TTS 云端 |
| 混合 3 | faster-whisper | local | cloud | ASR/LLM 本地，TTS 云端 |

## 配置说明

### ASR 模式
- **faster-whisper** (本地): 使用 faster-whisper 模型，支持 CPU/GPU
- **cloud** (云端): 使用 MIMO 云端 ASR API

### LLM 模式
- **local** (本地): 使用 LM Studio 或 Ollama
  - LM Studio: `http://127.0.0.1:1234/v1/chat/completions`
  - Ollama: `http://localhost:11434/v1/chat/completions`
- **cloud** (云端): 使用 DeepSeek 或 MiMo 云端 API

### TTS 模式
- **local** (本地): 使用 piper-tts，需要下载模型到 `TTS_env/piper/`
- **cloud** (云端): 使用 MIMO 云端 TTS API

## 修改默认配置

如果想永久修改默认配置，编辑 `config.py`：

```python
# ASR 配置
ASR_MODE = "faster-whisper"  # 或 "cloud"

# LLM 配置
LLM_MODE = "local"  # 或 "cloud"

# TTS 配置
TTS_MODE = "local"  # 或 "cloud"
```

## 注意事项

1. **本地模式需要预先安装依赖**：
   - ASR: `pip install faster-whisper`
   - LLM: 需要运行 LM Studio 或 Ollama 服务
   - TTS: `pip install piper-tts onnxruntime`，并下载模型

2. **云端模式需要配置 API Key**：
   - 在 `.env` 文件中设置 `MIMO_API_KEY` 和 `LLM_CLOUD_API_KEY`

3. **交互式选择仅在本次启动生效**，不会修改 `config.py` 文件

4. **使用 `--auto` 参数**可以跳过选择，适合自动化脚本或快速启动
