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

class Config:
    # 项目根目录（动态获取，自动适配任何安装位置，无需手动修改）
    PROJECT_ROOT = str(Path(__file__).parent)

    # ==================== ASR（自动语音识别）配置 ====================
    ASR_MODE = "cloud"  # "local" or "cloud" ; 本地 SenseVoice 或云端 MIMO
    ASR_MODEL_DIR = os.path.join(PROJECT_ROOT, "ASR_env/SenseVoice/models/SenseVoiceSmall")
    ASR_AUDIO_INPUT = os.path.join(PROJECT_ROOT, "ASR_env/input_voice/voice.wav")

    # VAD（语音活动检测）参数 — 自动录音模式
    VAD_SILENCE_THRESHOLD = 500       # RMS 能量阈值，低于此值视为静音（0-32767 范围）
    VAD_SILENCE_TIMEOUT = 2.0         # 静音持续秒数，超时后结束录音
    VAD_MIN_SPEECH_DURATION = 0.3     # 最短有效语音时长（秒），短于此值的杂音将被忽略
    VAD_SPEECH_PADDING = 0.2          # 语音开始前保留的音频秒数，避免截断开头

    # ==================== TTS（文本转语音）配置 ====================
    TTS_MODE = "cloud"  # "local" or "cloud" ; 本地 CosyVoice 或云端 MIMO
    TTS_API_URL = "http://localhost:8000/" # 该地址为cosyvoice模型自动分配地址，无出错时不改动
    TTS_OUTPUT_DIR = os.path.join(PROJECT_ROOT, "TTS_env/output_voice/")
    TTS_HISTORY_DIR = os.path.join(PROJECT_ROOT, "TTS_env/voice_history/")
    TTS_PROMPT_TEXT = os.path.join(PROJECT_ROOT, "TTS_env/voice_training_sample/text_taiyuan.txt")
    TTS_PROMPT_WAV = os.path.join(PROJECT_ROOT, "TTS_env/voice_training_sample/taiyuan.mp3")

    # ==================== 云端 MIMO API 配置 ====================
    # 前往 https://platform.xiaomimimo.com 注册获取 API Key
    MIMO_API_KEY = os.getenv("MIMO_API_KEY", "")
    MIMO_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"  # 按量付费；Token Plan 用 https://token-plan-cn.xiaomimimo.com/v1

    # 云端 ASR（MiMo-V2.5-ASR）
    MIMO_ASR_MODEL = "mimo-v2.5-asr"
    MIMO_ASR_LANGUAGE = "auto"  # "auto" | "zh" | "en"

    # 云端 TTS（MiMo-V2.5-TTS）
    # 可用音色: 冰糖, 茉莉, 苏打, 白桦, Mia, Chloe, Milo, Dean, mimo_default
    MIMO_TTS_MODEL = "mimo-v2.5-tts"       # 预置音色；音色复刻用 mimo-v2.5-tts-voiceclone
    MIMO_TTS_VOICE = "冰糖"                 # 预置音色 ID
    MIMO_TTS_FORMAT = "wav"                 # wav | pcm16
    MIMO_TTS_STYLE = "语速适中、自然亲切"    # 自然语言风格描述（可选）

    # ==================== TTS API 相关（仅本地模式使用） ====================
    # Miniconda 安装路径（本地 TTS 模式需要，云端模式无需设置）
    # 如果 TTS_MODE = "local"，请修改为你的实际 Miniconda 安装路径
    MINICONDA_PATH = "D:/ProgramFiles/miniconda"  # 例如："C:/Users/你的用户名/miniconda3" 或 "D:/ProgramFiles/miniconda3"
    WEBUI_PYTHON = os.path.join(MINICONDA_PATH, "python.exe") if MINICONDA_PATH else ""
    WEBUI_SCRIPT = os.path.join(PROJECT_ROOT, "TTS_env/CosyVoice/webui.py")
    CLEANUP_MODE = "move"  # "delete" or "move"; 配置文件清理方式（delete: 删除 | move: 归档）
    SHOW_WINDOW = True

    # ==================== LLM（大语言模型）配置 ====================
    LLM_MODE = "cloud"              # "local" or "cloud"

    # --- 云端 LLM（OpenAI 兼容协议，DeepSeek / MiMo / OpenAI / vLLM 等均可）---
    LLM_CLOUD_API_KEY = os.getenv("LLM_CLOUD_API_KEY", "")
    LLM_CLOUD_BASE_URL = "https://api.deepseek.com"
    LLM_CLOUD_MODEL_NAME = "deepseek-v4-flash"

    # --- 本地 LLM（LM Studio）---
    LOCAL_LLM_MODEL_NAME = ""
    LOCAL_LLM_API_URL = "http://127.0.0.1:1234/v1/chat/completions"

    # --- 通用路径 ---
    LLM_TMP_DIR = os.path.join(PROJECT_ROOT, "TTS_env/tmp")
    LLM_CONVERSATION_HISTORY = os.path.join(PROJECT_ROOT, "LLM_env/conversation_history.txt")


    # Live2D 配置
    LIVE2D_MODEL_PATH = os.path.join(PROJECT_ROOT, "Live2d_env/pachirisu anime girl - top half.model3.json")

    # WebUI 相关配置
    WEBUI_SAVE_DIR = os.path.join(PROJECT_ROOT, "TTS_env/output_voice/")
    WEBUI_HISTORY_DIR = os.path.join(PROJECT_ROOT, "TTS_env/voice_history/")
    WEBUI_MODEL_DIR = os.path.join(PROJECT_ROOT, "TTS_env/CosyVoice/pretrained_models/CosyVoice2-0.5B")

# 可用于打印检查配置
if __name__ == "__main__":
    for attr in dir(Config):
        if not attr.startswith("__"):
            print(f"{attr} = {getattr(Config, attr)}")
