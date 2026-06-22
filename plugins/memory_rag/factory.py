"""
memory_rag/factory.py — 工厂模式：统一创建 MemoryRAG 实例。

调用方无需关心底层适配器和策略细节，通过配置即可创建不同用途的 MemoryRAG。
"""
from __future__ import annotations

from typing import Optional

from plugins.vector_store_adapter import ChromaAdapter, VectorStore
from plugins.memory_rag.memory_rag import MemoryRAG
from plugins.memory_rag.strategy import ScoreStrategy, NeutralStrategy


class MemoryRAGFactory:
    """MemoryRAG 工厂。

    创建带不同配置（适配器、策略、命名空间）的 MemoryRAG 实例。
    """

    @staticmethod
    def create(
        persist_dir: str = "./plugins_data/memory",
        collection_name: str = "user_memories",
        adapter: Optional[VectorStore] = None,
        strategy: Optional[ScoreStrategy] = None,
    ) -> MemoryRAG:
        """创建 MemoryRAG 实例。

        Args:
            persist_dir: 持久化目录（adapter 为 None 时用于创建 ChromaAdapter）
            collection_name: 集合名称（命名空间隔离）
            adapter: 自定义 VectorStore 适配器（None 则创建 ChromaAdapter）
            strategy: 检索得分策略（None 则使用 NeutralStrategy）

        Returns:
            MemoryRAG 实例
        """
        if adapter is None:
            adapter = ChromaAdapter(persist_dir=persist_dir, collection_name=collection_name)

        if not getattr(adapter, 'is_ready', False):
            raise RuntimeError(
                f"VectorStore adapter not ready: {adapter.__class__.__name__}. "
                f"可能原因：网络不通导致 sentence-transformers 模型下载失败。"
                f"解决方案：设置 HF_ENDPOINT=https://hf-mirror.com，或手动下载模型。"
            )

        if strategy is None:
            strategy = NeutralStrategy()

        return MemoryRAG(adapter=adapter, score_strategy=strategy)
