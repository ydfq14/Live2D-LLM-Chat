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
        logger.info("[MemoryRAGFactory] 开始创建 MemoryRAG 实例")
        logger.info("[MemoryRAGFactory] 配置: persist_dir=%s, collection=%s", persist_dir, collection_name)

        if adapter is None:
            logger.info("[MemoryRAGFactory] 创建 ChromaAdapter...")
            try:
                adapter = ChromaAdapter(persist_dir=persist_dir, collection_name=collection_name)
                logger.info("[MemoryRAGFactory] ChromaAdapter 创建完成")
            except Exception as e:
                logger.error("[MemoryRAGFactory] ✗ ChromaAdapter 创建失败: %s", str(e))
                raise RuntimeError(
                    f"VectorStore adapter 创建失败: {str(e)}\n"
                    f"可能原因：\n"
                    f"  1. 网络不通，无法下载 sentence-transformers 模型\n"
                    f"  2. chromadb 库未安装或版本不兼容\n"
                    f"  3. 持久化目录权限问题\n"
                    f"解决方案：\n"
                    f"  - 设置环境变量: HF_ENDPOINT=https://hf-mirror.com（使用国内镜像）\n"
                    f"  - 手动下载模型到: ./models/sentence-transformers_all-MiniLM-L6-v2/\n"
                    f"  - 检查 chromadb 安装: pip install chromadb\n"
                    f"  - 检查目录权限: {persist_dir}"
                ) from e

        if not getattr(adapter, 'is_ready', False):
            logger.error("[MemoryRAGFactory] ✗ VectorStore adapter 未就绪")
            logger.error("[MemoryRAGFactory] adapter 类型: %s", adapter.__class__.__name__)
            logger.error("[MemoryRAGFactory] adapter.is_ready: %s", getattr(adapter, 'is_ready', None))
            raise RuntimeError(
                f"VectorStore adapter not ready: {adapter.__class__.__name__}\n"
                f"Adapter 状态: is_ready={getattr(adapter, 'is_ready', 'N/A')}\n"
                f"可能原因：\n"
                f"  1. 网络不通导致 sentence-transformers 模型下载失败\n"
                f"  2. 模型文件损坏或不完整\n"
                f"  3. ChromaDB 初始化过程中发生错误\n"
                f"解决方案：\n"
                f"  - 设置环境变量: HF_ENDPOINT=https://hf-mirror.com（使用国内镜像加速下载）\n"
                f"  - 手动下载模型: 访问 https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2\n"
                f"    下载后放到: ./models/sentence-transformers_all-MiniLM-L6-v2/\n"
                f"  - 检查网络连接和防火墙设置\n"
                f"  - 查看详细错误日志: logs/run.log"
            )

        logger.info("[MemoryRAGFactory] ✓ VectorStore adapter 就绪")

        if strategy is None:
            strategy = NeutralStrategy()
            logger.debug("[MemoryRAGFactory] 使用默认策略: NeutralStrategy")

        memory_rag = MemoryRAG(adapter=adapter, score_strategy=strategy)
        logger.info("[MemoryRAGFactory] ✓ MemoryRAG 实例创建成功")
        return memory_rag
