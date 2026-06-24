"""
memory_rag/facade.py — 门面模式：为其他模块提供一键式 RAG 接口。

其他模块（日程管理、主动关怀）无需了解 MemoryRAG、VectorStore、ScoreStrategy 等内部类，
只需通过 MemoryServiceFacade 即可使用语义存储与检索。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    from log_config import get_logger
except ImportError:
    import logging
    get_logger = logging.getLogger
from plugins.memory_rag.factory import MemoryRAGFactory
from plugins.memory_rag.strategy import NeutralStrategy

logger = get_logger("memory_rag.facade")


class MemoryServiceFacade:
    """RAG 记忆服务门面。

    为其他业务模块提供简化的 store/recall 接口，自动处理命名空间隔离。

    示例：
        schedule = MemoryServiceFacade(namespace="schedule")
        schedule.store("明天下午3点开会", tags={"topic": "meeting", "time": "15:00"})
        results = schedule.recall("明天的会议", tag_filter={"topic": "meeting"})
    """

    def __init__(self, namespace: str = "default"):
        """
        Args:
            namespace: 命名空间（自动映射为独立的 collection_name，防止数据污染）
        """
        self.namespace = namespace
        self._rag = MemoryRAGFactory.create(
            persist_dir="./plugins_data/memory",
            collection_name=f"ns_{namespace}",
            strategy=NeutralStrategy(),
        )
        logger.info("[Facade] 命名空间 '%s' 已初始化", namespace)

    def store(self, content: str, tags: Optional[Dict[str, Any]] = None) -> str:
        """存储内容。

        Args:
            content: 文本内容
            tags: 任意标签（如 {"topic": "meeting", "priority": "high"}）

        Returns:
            memory_id: 唯一标识
        """
        metadata = tags or {}
        return self._rag.add_memory(content, metadata=metadata)

    def recall(self, query: str, tag_filter: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """语义检索。

        Args:
            query: 查询文本
            tag_filter: 标签过滤条件

        Returns:
            检索结果列表
        """
        return self._rag.search(query, filters=tag_filter)

    def recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近存储的内容。"""
        return self._rag.get_recent(limit=limit)
