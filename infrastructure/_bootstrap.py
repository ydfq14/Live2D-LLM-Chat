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


def _patch_hf_hub_download_with_fallback():
    """
    Monkey-patch huggingface_hub 的 snapshot_download 和 hf_hub_download，
    使它们在镜像下载失败时自动回退到官方 Hub。
    """
    try:
        import huggingface_hub
        from huggingface_hub import hf_hub_download as _orig_hf_hub_download
        from huggingface_hub import snapshot_download as _orig_snapshot_download
        import functools
    except ImportError:
        return

    mirror_endpoint = "https://hf-mirror.com"
    official_endpoint = "https://huggingface.co"
    hf_endpoint = os.environ.get("HF_ENDPOINT", "")

    if mirror_endpoint not in hf_endpoint:
        return  # 未使用镜像，无需回退

    def _make_fallback(original_fn):
        @functools.wraps(original_fn)
        def wrapper(*args, **kwargs):
            try:
                return original_fn(*args, **kwargs)
            except Exception as e:
                err_str = str(e).lower()
                is_network_error = any(kw in err_str for kw in (
                    "does not seem to be on huggingface",
                    "connection", "timeout", "ssl", "distant resource",
                    "localentrynotfounderror",
                ))
                if not is_network_error:
                    raise

                import logging
                log = logging.getLogger(__name__)
                log.warning(
                    "HuggingFace 镜像 (%s) 下载失败，自动回退到官方 Hub...", mirror_endpoint
                )
                # 临时切换到官方端点
                old_endpoint = os.environ.get("HF_ENDPOINT")
                os.environ["HF_ENDPOINT"] = official_endpoint
                try:
                    huggingface_hub.constants.HF_ENDPOINT = official_endpoint
                except Exception:
                    pass
                log.info("HF_ENDPOINT 已切换为: %s (常量: %s)",
                         os.environ.get("HF_ENDPOINT"),
                         getattr(huggingface_hub.constants, "HF_ENDPOINT", "N/A"))
                try:
                    result = original_fn(*args, **kwargs)
                    log.info("官方 Hub 下载成功")
                    return result
                finally:
                    if old_endpoint:
                        os.environ["HF_ENDPOINT"] = old_endpoint
                    try:
                        huggingface_hub.constants.HF_ENDPOINT = old_endpoint or official_endpoint
                    except Exception:
                        pass
        return wrapper

    huggingface_hub.snapshot_download = _make_fallback(_orig_snapshot_download)
    huggingface_hub.hf_hub_download = _make_fallback(_orig_hf_hub_download)


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

    # --- 全局回退：镜像下载失败时自动切换到官方 Hub ---
    _patch_hf_hub_download_with_fallback()


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
