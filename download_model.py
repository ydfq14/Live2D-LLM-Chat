"""
通过魔搭（ModelScope）下载 embedding 模型到本地。

运行方式（已激活 rgzn 环境）：
    python download_model.py

模型会下载到 ./models/sentence-transformers_all-MiniLM-L6-v2/
下载后 vector_store_adapter.py 会自动使用本地模型，无需网络。
"""
from __future__ import annotations

import os
import sys


def download_all_minilm() -> str:
    """使用魔搭下载 all-MiniLM-L6-v2 模型到本地。"""
    try:
        from modelscope import snapshot_download
    except ImportError:
        print("[ERROR] modelscope 未安装。请执行：pip install modelscope")
        sys.exit(1)

    model_dir = os.path.join(os.path.dirname(__file__), "models", "sentence-transformers_all-MiniLM-L6-v2")
    os.makedirs(os.path.dirname(model_dir), exist_ok=True)

    print("[INFO] 开始从魔搭下载 all-MiniLM-L6-v2...")
    print("[INFO] 目标目录:", model_dir)

    try:
        # 魔搭模型 ID：damo/nlp_corom_sentence-embedding_english-base
        # 或者使用社区镜像：sentence-transformers/all-MiniLM-L6-v2
        downloaded = snapshot_download(
            "sentence-transformers/all-MiniLM-L6-v2",
            cache_dir=model_dir,
            revision="master",
        )
        print("[INFO] 下载完成:", downloaded)
        return downloaded
    except Exception as e:
        print("[ERROR] 下载失败:", e)
        print("[HINT] 请检查网络连接，或尝试手动下载后放到", model_dir)
        raise


if __name__ == "__main__":
    download_all_minilm()
