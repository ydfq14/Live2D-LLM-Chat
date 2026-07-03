# VirtuMate - Live2D AI Desktop Companion

[![ASR](https://img.shields.io/badge/ASR-faster--whisper%2FMiMo-green.svg)](https://github.com/SYSTRAN/faster-whisper)
[![LLM](https://img.shields.io/badge/LLM-DeepSeek%2FMiMo%2FLM%20Studio-red.svg)](https://openai.com/api/)
[![TTS](https://img.shields.io/badge/TTS-Piper%2FMiMo%2FMOSS-orange.svg)](https://github.com/rhasspy/piper)
[![Live2D](https://img.shields.io/badge/Live2D-v3-blue.svg)](https://github.com/Arkueid/live2d-py)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agent-purple.svg)](https://langchain-ai.github.io/langgraph/)
[![Python](https://img.shields.io/badge/Python-3.10+-yellow.svg)](https://www.python.org/)

> Live2D digital human + LLM conversation + voice interaction, with IOCP async architecture and plugin system. Supports local/cloud hybrid deployment.

---

## Features

- **Live2D Digital Human**: OpenGL real-time rendering, lip-sync, eye tracking
- **Voice Interaction**: Mic recording -> ASR -> LLM -> TTS voice output
- **Multi TTS Engine**: Piper (lightweight local) / MiMo (cloud) / MOSS-TTS-Nano (local, voice cloning)
- **Multi ASR Engine**: faster-whisper (local) / MiMo ASR (cloud)
- **LLM Backend**: DeepSeek/MiMo API (cloud) or LM Studio/Ollama (local)
- **Plugin System**: Emotion analysis, scheduler, RAG knowledge base, agentic intelligence, auto care, face emotion recognition, personality management
- **Auto Care**: Proactive care messages (emotion-based, period greetings, idle detection, long-chat reminder)

---

## Quick Start

### Prerequisites

- Python >= 3.10
- Windows 10/11 (Live2D requires OpenGL)
- Optional: NVIDIA GPU with CUDA 12.x (for faster ASR/LLM inference)

### Installation

```bash
git clone <repo-url>
cd Live2D-LLM-Chat
pip install -r requirements.txt
```

### Configuration

```bash
cp .env.example .env
# Edit .env with your API keys (MIMO_API_KEY, LLM_CLOUD_API_KEY, etc.)
```

Edit `config.py` to choose your preferred modes:

```python
ASR_MODE = "faster-whisper"   # or "cloud"
LLM_MODE = "local"            # or "cloud"
TTS_MODE = "cloud"            # "local", "cloud", or "moss"
```

### Launch

```bash
python main.py
```

Follow the interactive prompts to select deployment mode for each module. Use `--auto` to skip prompts and use `config.py` defaults.

---

## TTS Engines

| Mode | Engine | Audio | Voice | Network |
|------|--------|-------|-------|:---:|
| `local` | Piper TTS | 22kHz mono | Single (huayan female) | No |
| `cloud` | MiMo-V2.5-TTS | 24kHz | 8+ built-in voices | Yes |
| `moss` | MOSS-TTS-Nano | 48kHz stereo | 20+ voices, voice cloning | No (after model download) |

Set `TTS_MODE` in `config.py` or choose interactively on startup.

### MOSS-TTS-Nano Setup (Local, Voice Cloning)

MOSS-TTS-Nano is an open-source ONNX-based TTS engine (100M params) that runs entirely on CPU with 48kHz stereo output. It supports voice cloning from a reference audio clip.

#### Step 1: Clone and Install MOSS-TTS-Nano

```bash
# Clone to any directory
git clone https://github.com/OpenMOSS/MOSS-TTS-Nano.git
cd MOSS-TTS-Nano

# Install dependencies and register the package
pip install -e .
```

This makes MOSS importable from anywhere via Python's standard import system. No path configuration needed.

#### Step 2: Configure VirtuMate

Edit `config.py`:

```python
TTS_MODE = "moss"
MOSS_VOICE = "Xiaoyu"          # Built-in voice name
MOSS_CPU_THREADS = 4           # ONNX Runtime thread count
MOSS_EXECUTION_PROVIDER = "cpu"  # "cpu" or "cuda"
MOSS_MAX_NEW_FRAMES = 375      # Max audio length (~30 seconds)
```

#### Step 3: First Launch (Model Download)

```bash
python main.py
```

On first run, MOSS automatically downloads ~730 MB of ONNX models from HuggingFace (mirrored via hf-mirror.com for China users):

- `MOSS-TTS-Nano-100M-ONNX/` (642 MB) — LLM for audio token generation
- `MOSS-Audio-Tokenizer-Nano-ONNX/` (87 MB) — Audio codec (encode/decode)

#### Step 4 (Optional): Custom Voice Cloning

1. Prepare a 3-10 second WAV/MP3/FLAC reference clip of the target voice
2. Place it in `TTS_env/prompt_audio/my_voice.wav`
3. Set in `config.py`:
   ```python
   MOSS_PROMPT_AUDIO_PATH = "TTS_env/prompt_audio/my_voice.wav"
   ```
4. Restart — the reference audio is pre-encoded at startup and cached for zero-overhead reuse

#### MOSS Requirements Summary

| Dependency | Install via |
|------------|-------------|
| MOSS-TTS-Nano | `git clone` + `pip install -e .` |
| onnxruntime | `pip install -r requirements.txt` (included) |
| sentencepiece | `pip install -e .` (installed as MOSS dependency) |
| WeTextProcessing | `pip install -e .` (installed as MOSS dependency) |
| torch + torchaudio | `pip install -r requirements.txt` (included, for audio I/O) |

---

## Plugins (8 total)

| Plugin | Description | Frontend |
|--------|-------------|:---:|
| `chatbox` | Chat UI, message display, input box | Yes |
| `emotion_rag` | User emotion analysis, episodic memory via Chroma | Debug view |
| `scheduler` | Time-based reminders with voice output | Yes |
| `agentic_rag` | Knowledge base retrieval (Milvus + BGE-M3 embedding) | Yes |
| `personality` | Character persona selection and management | Yes |
| `fer` | Real-time facial expression recognition via webcam | Read-only |
| `auto_care` | Proactive care messages (emotion/period/idle/long-chat) | Yes |
| `assistant_tools` | Utility tools (time, system info, etc.) for LangGraph | No |

All plugins are auto-discovered from `plugins/` directory. See `plugin_base.py` for the hook API.

---

## Architecture

```
MainManager (main.py)
  ├── ASR Manager (faster-whisper / MiMo)
  ├── LLM Manager (DeepSeek / LM Studio)
  ├── TTS Manager (Piper / MiMo / MOSS)
  ├── Live2D Manager (OpenGL + lip-sync)
  ├── UI Shell (pywebview + HTML/JS)
  └── Plugin Registry
        ├── IOCP Scheduler (background tasks, 60s interval)
        └── LangGraph Engine (9-node conversation graph)
```

**Thread Model**: Main thread (pywebview UI) + Conversation thread (IOCP async loop) + Live2D thread (OpenGL rendering) + Hook thread (mouse tracking)

---

## Project Structure

```
Live2D-LLM-Chat/
├── main.py                  # Entry point, interactive deployment mode selection
├── config.py                # Global configuration
├── graph_engine.py          # LangGraph conversation graph engine
├── ASR.py                   # Speech recognition manager
├── LLM.py                   # Large language model manager
├── TTS.py                   # TTS manager (Piper/MiMo/MOSS triple-mode)
├── Live2d_animation.py      # Live2D rendering + lip-sync
├── ui_shell.py              # pywebview frontend UI
├── kb_controller.py         # Knowledge base controller (Milvus + BGE-M3)
├── infrastructure/
│   └── _bootstrap.py        # Bootstrap: model cache redirect + HF mirror fallback
├── plugins/                 # Plugin directory (auto-discovered)
│   ├── chatbox_plugin.py
│   ├── emotion_rag_plugin.py
│   ├── scheduler_plugin.py
│   ├── agentic_rag_plugin.py
│   ├── personality_plugin.py
│   ├── fer_plugin.py
│   ├── auto_care_plugin.py
│   └── assistant_tools_plugin.py
├── plugins_data/            # Plugin runtime data (auto_care/, scheduler/, etc.)
├── TTS_env/                 # TTS workspace (output audio, model cache, prompt audio)
├── ASR_env/                 # ASR workspace (recording files)
├── Live2d_env/              # Live2D model files (.moc3, .json, etc.)
├── LLM_env/                 # LLM conversation history
├── .models/                 # Model cache (HuggingFace/ModelScope/PyTorch/TF)
└── logs/                    # Application logs
```

---

## HuggingFace Mirror

For China users, `hf-mirror.com` is automatically used to accelerate model downloads. Falls back to `huggingface.co` if the mirror fails. To override:

```bash
set HF_ENDPOINT=https://huggingface.co    # Official site
set HF_ENDPOINT=https://hf-mirror.com     # China mirror (default)
```

---

## FAQ

**Q: What GPU is needed?**

A: optional. CPU works for all modules. NVIDIA GPU (CUDA 12.8) accelerates faster-whisper ASR significantly (10-20x). TTS and LLM mode selection is independent.

**Q: How to switch between cloud and local mode?**

A: Edit `config.py` (ASR_MODE / LLM_MODE / TTS_MODE) or use the interactive prompts on startup.

**Q: MOSS-TTS-Nano fails to import?**

A: Make sure you ran `pip install -e .` inside the cloned MOSS-TTS-Nano directory. This registers the package globally.

**Q: MOSS model download is slow?**

A: The project auto-uses hf-mirror.com. If still slow, manually download the two model folders from HuggingFace to the MOSS project's `models/` directory.

**Q: Can I use MOSS with GPU?**

A: Change `MOSS_EXECUTION_PROVIDER` to `"cuda"` in `config.py`. Requires `onnxruntime-gpu`.

---

## Credits

- [live2d-py](https://github.com/Arkueid/live2d-py) — Live2D rendering
- [faster-whisper](https://github.com/SYSTRAN/faster-whisper) — Local ASR
- [Piper TTS](https://github.com/rhasspy/piper) — Lightweight local TTS
- [MOSS-TTS-Nano](https://github.com/OpenMOSS/MOSS-TTS-Nano) — High-quality local TTS with voice cloning
- [LangGraph](https://langchain-ai.github.io/langgraph/) — Agent engine
- [MiMo Platform](https://platform.xiaomimimo.com) — Cloud ASR/TTS API

---

## License

[Apache-2.0](LICENSE). Third-party models (Piper TTS, MOSS-TTS-Nano, faster-whisper, etc.) follow their respective licenses.
