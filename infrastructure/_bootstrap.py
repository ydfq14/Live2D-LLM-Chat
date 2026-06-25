"""
启动引导模块 — 必须在所有其他 import 之前加载。

核心职责：将 HuggingFace / ModelScope / PyTorch 的模型缓存目录
从默认的 C 盘用户目录重定向到项目本地的 .models/ 目录。

用法：在 main.py 最顶部 import infrastructure._bootstrap。
"""

import os
import sys

# 项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODELS_DIR = os.path.join(_PROJECT_ROOT, ".models")


def apply() -> None:
    """设置环境变量，将所有模型缓存重定向到项目 .models/ 目录。

    使用 setdefault 而非直接赋值，保留用户终端已设置的值。
    """
    # --- HuggingFace 镜像（国内加速，必须最先设置）---
    # 如果用户没有设置 HF_ENDPOINT，自动使用国内镜像避免网络超时
    os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

    # --- HuggingFace 缓存路径 ---
    os.environ.setdefault("HF_HOME", os.path.join(_MODELS_DIR, "huggingface"))
    os.environ.setdefault("HF_HUB_CACHE", os.path.join(_MODELS_DIR, "huggingface", "hub"))
    os.environ.setdefault("TRANSFORMERS_CACHE", os.path.join(_MODELS_DIR, "huggingface"))

    # --- ModelScope（FunASR 从 modelscope 下载 SenseVoice 等模型）---
    os.environ.setdefault("MODELSCOPE_CACHE", os.path.join(_MODELS_DIR, "modelscope"))

    # --- PyTorch ---
    os.environ.setdefault("TORCH_HOME", os.path.join(_MODELS_DIR, "torch"))

    # --- sentence-transformers（emotion_rag_plugin 的嵌入模型）---
    os.environ.setdefault("SENTENCE_TRANSFORMERS_HOME", os.path.join(_MODELS_DIR, "sentence_transformers"))

    # --- TensorFlow Hub（FER 面部情绪识别模型缓存，预留）---
    os.environ.setdefault("TFHUB_CACHE_DIR", os.path.join(_MODELS_DIR, "tfhub"))

    # --- 关键修复：强制 huggingface_hub 使用镜像端点 ---
    # 某些版本的 huggingface_hub 不会自动读取 HF_ENDPOINT 环境变量
    # 需要在导入 huggingface_hub 之前强制设置
    try:
        import huggingface_hub
        # 如果 huggingface_hub 已经导入，强制重新加载配置
        if hasattr(huggingface_hub, 'constants'):
            huggingface_hub.constants.HF_HUB_CACHE = os.environ.get('HF_HUB_CACHE', huggingface_hub.constants.HF_HUB_CACHE)
            huggingface_hub.constants.HF_ENDPOINT = os.environ.get('HF_ENDPOINT', huggingface_hub.constants.HF_ENDPOINT)
    except ImportError:
        # huggingface_hub 还未导入，稍后会在使用时读取环境变量
        pass


# 导入时自动生效
apply()


def verify_hf_endpoint():
    """验证 HuggingFace 端点配置是否生效。"""
    hf_endpoint = os.environ.get('HF_ENDPOINT')
    print(f"[Bootstrap] HuggingFace endpoint: {hf_endpoint}")

    if hf_endpoint and 'hf-mirror.com' in hf_endpoint:
        print("[Bootstrap] Using China mirror, network access will be accelerated")
    else:
        print("[Bootstrap] Using official site, China access may be slow")

    return hf_endpoint
