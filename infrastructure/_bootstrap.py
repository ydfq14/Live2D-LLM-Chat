"""
启动引导模块 — 必须在所有其他 import 之前加载。

核心职责：将 HuggingFace / ModelScope / PyTorch 的模型缓存目录
从默认的 C 盘用户目录重定向到项目本地的 .models/ 目录。

用法：在 main.py 最顶部 import infrastructure._bootstrap。
"""

import os

# 项目根目录
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_MODELS_DIR = os.path.join(_PROJECT_ROOT, ".models")


def apply() -> None:
    """设置环境变量，将所有模型缓存重定向到项目 .models/ 目录。

    使用 setdefault 而非直接赋值，保留用户终端已设置的值。
    """
    # --- HuggingFace ---
    os.environ.setdefault("HF_HOME", os.path.join(_MODELS_DIR, "huggingface"))
    os.environ.setdefault("HF_HUB_CACHE", os.path.join(_MODELS_DIR, "huggingface", "hub"))
    os.environ.setdefault("TRANSFORMERS_CACHE", os.path.join(_MODELS_DIR, "huggingface"))

    # --- ModelScope（FunASR 从 modelscope 下载 SenseVoice 等模型）---
    os.environ.setdefault("MODELSCOPE_CACHE", os.path.join(_MODELS_DIR, "modelscope"))

    # --- PyTorch ---
    os.environ.setdefault("TORCH_HOME", os.path.join(_MODELS_DIR, "torch"))


# 导入时自动生效
apply()
