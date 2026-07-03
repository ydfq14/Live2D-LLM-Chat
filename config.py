import os
from pathlib import Path

# ============================================================
# 加载 .env 文件中的密钥（手动解析，零依赖，不引入 python-dotenv）
# 环境变量中已有的值不会被文件覆盖（setdefault 语义）
# ============================================================
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    with open(_env_path, "r", encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _key, _val = _line.split("=", 1)
                os.environ.setdefault(_key.strip(), _val.strip())

# ============================================================
# 自动设置 HuggingFace 镜像（国内加速）
# 如果用户没有设置 HF_ENDPOINT，自动使用镜像避免网络超时
# 镜像下载失败时会自动回退到 huggingface.co（参见 infrastructure/_bootstrap.py）
# ============================================================
if not os.environ.get("HF_ENDPOINT"):
    os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
    print(f"[Config] 已自动设置 HuggingFace 镜像: {os.environ['HF_ENDPOINT']}")
else:
    print(f"[Config] 使用用户设置的 HuggingFace 端点: {os.environ['HF_ENDPOINT']}")

class Config:
    # 项目根目录（动态获取，自动适配任何安装位置，无需手动修改）
    PROJECT_ROOT = str(Path(__file__).parent)

    # ==================== ASR（自动语音识别）配置 ====================
    ASR_MODE = "faster-whisper"  # "faster-whisper" or "cloud"
    ASR_AUDIO_INPUT = os.path.join(PROJECT_ROOT, "ASR_env/input_voice/voice.wav")

    # Faster-Whisper 配置（ASR_MODE = "faster-whisper" 时使用）
    ASR_WHISPER_MODEL_SIZE = "small"  # tiny, base, small, medium, large-v3
    ASR_WHISPER_DEVICE = "auto"       # cuda, cpu, auto（自动检测）
    ASR_WHISPER_COMPUTE_TYPE = "float16"  # float16, int8_float16, int8
    ASR_WHISPER_LANGUAGE = "zh"       # zh, en, auto（自动检测）

    # VAD（语音活动检测）参数 — 自动录音模式
    VAD_SILENCE_THRESHOLD = 500       # RMS 能量阈值，低于此值视为静音（0-32767 范围）
    VAD_SILENCE_TIMEOUT = 2.0         # 静音持续秒数，超时后结束录音
    VAD_MIN_SPEECH_DURATION = 0.3     # 最短有效语音时长（秒），短于此值的杂音将被忽略
    VAD_SPEECH_PADDING = 0.2          # 语音开始前保留的音频秒数，避免截断开头

    # ==================== TTS（文本转语音）配置 ====================
    TTS_MODE = "cloud"  # "local", "cloud", or "moss"; 本地 piper / 云端 MIMO / 本地 MOSS-TTS-Nano
    TTS_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "TTS_env/output_voice/")
    TTS_HISTORY_DIR = os.path.join(PROJECT_ROOT, "TTS_env/voice_history/")
    TTS_CLEANUP_MODE = "move"  # "delete" or "move"; 配置文件清理方式（delete: 删除 | move: 归档）

    # Piper TTS 本地配置 (TTS_MODE = "local" 时使用)
    # 中文模型: https://huggingface.co/rhasspy/piper-voices/tree/main/zh_CN/huayan/medium
    PIPER_MODEL_PATH = os.path.join(PROJECT_ROOT, "TTS_env/piper/zh_CN-huayan-medium.onnx")
    PIPER_SPEAKER_ID = 0            # 多说话人模型的 ID（单说话人为 0）
    PIPER_LENGTH_SCALE = 1.0        # 语速：<1.0 加快，>1.0 减慢
    PIPER_NOISE_SCALE = 0.667       # 表现力噪声（0.0-1.0）
    PIPER_NOISE_W = 0.8             # 时长噪声（0.0-1.0）
    PIPER_SAMPLE_RATE = 22050       # 采样率（模型默认）

    # ==================== 云端 MIMO API 配置 ====================
    # 前往 https://platform.xiaomimimo.com 注册获取 API Key
    MIMO_API_KEY = os.getenv("MIMO_API_KEY", "")
    MIMO_BASE_URL = "https://rainbowgate.top/v1"  # 按量付费；Token Plan 用 https://token-plan-cn.xiaomimimo.com/v1

    # ==================== Agentic RAG LLM 配置 ====================
    # 用于知识库智能检索的独立 LLM Agent（默认复用 MIMO 配置）
    AGENTIC_RAG_LLM_MODEL = os.getenv("AGENTIC_RAG_LLM_MODEL", "mimo-v2.5-pro")
    AGENTIC_RAG_LLM_BASE_URL = os.getenv("AGENTIC_RAG_LLM_BASE_URL", MIMO_BASE_URL)
    AGENTIC_RAG_LLM_API_KEY = os.getenv("AGENTIC_RAG_LLM_API_KEY", MIMO_API_KEY)

    # 云端 ASR（MiMo-V2.5-ASR）
    MIMO_ASR_MODEL = "mimo-v2.5-asr"
    MIMO_ASR_LANGUAGE = "auto"  # "auto" | "zh" | "en"

    # 云端 TTS（MiMo-V2.5-TTS）
    # 可用音色: 冰糖, 茉莉, 苏打, 白桦, Mia, Chloe, Milo, Dean, mimo_default
    MIMO_TTS_MODEL = "mimo-v2.5-tts"       # 预置音色；音色复刻用 mimo-v2.5-tts-voiceclone
    MIMO_TTS_VOICE = "冰糖"                 # 预置音色 ID
    MIMO_TTS_FORMAT = "wav"                 # wav | pcm16
    MIMO_TTS_STYLE = "语速适中、自然亲切"    # 自然语言风格描述（可选）

    # ==================== MOSS-TTS-Nano 本地 ONNX 配置 ====================
    # 前提：已在当前 Python 环境中 pip install -e /path/to/MOSS-TTS-Nano

    # ONNX 模型目录（None = 自动从 HuggingFace 下载）
    MOSS_MODEL_DIR = None  # str | None

    # ONNX 推理配置
    MOSS_CPU_THREADS = 4               # onnxruntime 线程数
    MOSS_EXECUTION_PROVIDER = "cpu"    # "cpu" 或 "cuda"
    MOSS_MAX_NEW_FRAMES = 375          # 最大生成帧数（控制最大音频长度）

    # 语音配置
    MOSS_VOICE = "Xiaoyu"              # 内置音色（Xiaoyu/Yuewen/Lingyu/Junhao/Zhiming/Weiguo 等）
    MOSS_PROMPT_AUDIO_PATH = os.path.join(PROJECT_ROOT, "TTS_env/prompt_audio/my_voice.wav")      # str | None; 自定义提示音频路径（覆盖内置音色）

    # ==================== LLM（大语言模型）配置 ====================
    LLM_MODE = "local"              # "local" or "cloud"

    # --- 云端 LLM（OpenAI 兼容协议，DeepSeek / MiMo / OpenAI / vLLM 等均可）---
    LLM_CLOUD_API_KEY = os.getenv("LLM_CLOUD_API_KEY", "")
    LLM_CLOUD_BASE_URL = "https://api.deepseek.com"
    LLM_CLOUD_MODEL_NAME = "deepseek-v4-flash"

    # --- 本地 LLM（LM Studio）---
    LOCAL_LLM_MODEL_NAME = "deepseek-r1-distill-qwen-1.5b"  # LM Studio 中加载的模型标识
    LOCAL_LLM_API_URL = "http://127.0.0.1:1234/v1/chat/completions"

    # --- 通用路径 ---
    LLM_TMP_DIR = os.path.join(PROJECT_ROOT, "TTS_env/tmp")
    LLM_CONVERSATION_HISTORY = os.path.join(PROJECT_ROOT, "LLM_env/conversation_history.txt")


    # Live2D 配置
    LIVE2D_MODEL_PATH = os.path.join(PROJECT_ROOT, "Live2d_env/pachirisu anime girl - top half.model3.json")

    # ==================== IOCP 配置 ====================
    # IOCP工作线程数（0=自动，通常为 CPU核心数 * 2）
    IOCP_MAX_WORKERS = int(os.getenv("IOCP_MAX_WORKERS", "0"))

    # 后台任务检查间隔（秒）
    # 影响日程提醒等后台任务的检查频率
    IOCP_TASK_CHECK_INTERVAL = float(os.getenv("IOCP_TASK_CHECK_INTERVAL", "1.0"))

    # 异步包装器配置
    # 同步代码（ASR/TTS/Live2D）在线程池中的超时时间（秒）
    ASYNC_WRAPPER_TIMEOUT = float(os.getenv("ASYNC_WRAPPER_TIMEOUT", "30.0"))

# 可用于打印检查配置
if __name__ == "__main__":
    for attr in dir(Config):
        if not attr.startswith("__"):
            print(f"{attr} = {getattr(Config, attr)}")
