"""
通过魔搭（ModelScope）精确下载 embedding 模型到本地。
只下载 sentence-transformers 运行所需的必要文件（约 90MB），
避免 snapshot_download 拉取全仓库所有格式（PyTorch + ONNX + OpenVINO + TF + Rust ≈ 900MB+）。

运行方式（已激活 rgzn 环境）：
    python download_model.py

模型会下载到 ./models/sentence-transformers_all-MiniLM-L6-v2/
下载后 vector_store_adapter.py 会自动使用本地模型，无需网络。
"""
from __future__ import annotations

import os
import sys


def download_all_minilm() -> str:
    """使用 modelscope 精确下载 all-MiniLM-L6-v2 必要文件到本地。"""
    try:
        from modelscope import snapshot_download
    except ImportError:
        print("[ERROR] modelscope 未安装。请执行：pip install modelscope")
        sys.exit(1)

    model_dir = os.path.join(
        os.path.dirname(__file__),
        "models",
        "sentence-transformers_all-MiniLM-L6-v2",
    )
    os.makedirs(model_dir, exist_ok=True)

    print("[INFO] 开始从魔搭精确下载 all-MiniLM-L6-v2 必要文件...")
    print("[INFO] 目标目录:", model_dir)
    print("[INFO] 排除 ONNX / OpenVINO / TF / Rust 等多余格式，仅保留核心文件...")

    # 排除所有非 sentence-transformers 运行必需的格式
    # 全仓库可达 900MB+，排除后仅剩约 90MB
    ignore_patterns = [
        "onnx/**",           # ONNX 多版本（model.onnx, O1, O2, O3, O4, qint8...）
        "openvino/**",       # OpenVINO 格式
        "*.onnx",            # 根目录 ONNX 文件
        "tf_model.h5",       # TensorFlow
        "rust_model.ot",     # Rust 格式
    ]

    try:
        downloaded = snapshot_download(
            "sentence-transformers/all-MiniLM-L6-v2",
            cache_dir=model_dir,
            revision="master",
            ignore_patterns=ignore_patterns,
        )
        print("[INFO] 下载完成:", downloaded)
        return downloaded
    except Exception as e:
        print("[ERROR] 下载失败:", e)
        print("[HINT] 请检查网络连接，或尝试手动下载后放到", model_dir)
        raise


if __name__ == "__main__":
    download_all_minilm()
