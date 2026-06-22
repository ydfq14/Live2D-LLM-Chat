"""
memory_rag/memory_rag.py — 通用向量记忆存储（与情感分析完全解耦）。

职责：
- 提供通用的 add_memory / search / update / delete / get_recent 接口
- 通过 ScoreStrategy 注入业务权重，自身不感知任何业务语义
- metadata 完全由调用方决定，不限于 emotion

依赖：plugins.vector_store_adapter.VectorStore
"""
from __future__ import annotations

import os
import time
import uuid
from typing import Any, Dict, List, Optional

from log_config import get_logger
from plugins.vector_store_adapter import ChromaAdapter, VectorStore

logger = get_logger("memory_rag")


class MemoryRAG:
    """通用向量记忆存储。

    与情感分析完全解耦：
    - metadata 中的字段由调用方决定，不限于 emotion
    - 检索得分通过 score_strategy 计算，默认不加权

    Args:
        adapter: VectorStore 适配器实例（如 ChromaAdapter）
        score_strategy: 检索得分策略（可选，默认 NeutralStrategy）
    """

    def __init__(
        self,
        adapter: VectorStore,
        score_strategy: Optional[Any] = None,
    ):
        self.store = adapter
        self.score_strategy = score_strategy

    def _ensure_ready(self) -> None:
        if not self.store or not self.store.is_ready:
            raise RuntimeError("MemoryRAG 未初始化（向量库适配器未就绪）")

    # ────────────────────────────────────────────
    # 增
    # ────────────────────────────────────────────

    def add_memory(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """添加记忆。metadata 完全由调用方决定。

        Args:
            content: 文本内容
            metadata: 任意元数据字典，如
                      {"emotion": "happy", "topic": "travel", "weight": 1.5}

        Returns:
            memory_id: 唯一标识
        """
        self._ensure_ready()
        memory_id = str(uuid.uuid4())
        meta = metadata or {}
        meta["timestamp"] = time.time()

        try:
            self.store.add(ids=[memory_id], documents=[content], metadatas=[meta])
            logger.info("Memory added: id=%s meta=%s", memory_id[:8], meta)
        except Exception as e:
            logger.exception("Failed to add memory: %s", e)
            raise
        return memory_id

    # ────────────────────────────────────────────
    # 查
    # ────────────────────────────────────────────

    def search(
        self,
        query: str,
        n_results: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """语义检索。

        综合得分 = similarity × time_decay × score_strategy(metadata)

        Args:
            query: 查询文本
            n_results: 返回数量
            filters: 元数据过滤条件，如 {"topic": "travel"}

        Returns:
            [{"id": str, "content": str, "metadata": dict, "similarity": float}, ...]
        """
        self._ensure_ready()
        try:
            raw_results = self.store.query(query, n_results=n_results * 2, filters=filters)
        except Exception as e:
            logger.exception("Memory search failed: %s", e)
            return []

        now = time.time()
        parsed: List[Dict[str, Any]] = []
        for r in raw_results:
            dist = r.get("distance", 1.0)
            similarity = 1.0 - float(dist)
            meta = r.get("metadata", {})
            timestamp = float(meta.get("timestamp", 0))
            weight = float(meta.get("weight", 1.0))
            age_hours = (now - timestamp) / 3600
            time_decay = max(0.3, 1.0 - (age_hours / (24 * 7)))

            # 业务权重：由策略对象注入
            business_weight = 1.0
            if self.score_strategy is not None:
                try:
                    business_weight = self.score_strategy.calculate(meta)
                except Exception as e:
                    logger.debug("ScoreStrategy failed: %s, fallback=1.0", e)

            score = similarity * weight * time_decay * business_weight
            parsed.append({
                "id": r.get("id", ""),
                "content": r.get("content", ""),
                "metadata": meta,
                "similarity": round(score, 4),
            })
        parsed.sort(key=lambda x: x["similarity"], reverse=True)
        return parsed[:n_results]

    # ────────────────────────────────────────────
    # 改
    # ────────────────────────────────────────────

    def update_weight(self, memory_id: str, delta: float) -> None:
        """调整 metadata 中的 weight 字段。"""
        self._ensure_ready()
        try:
            result = self.store.get(memory_id)
            if not result:
                logger.warning("Memory not found: %s", memory_id[:8])
                return
            meta = result.get("metadata", {})
            current = float(meta.get("weight", 1.0))
            meta["weight"] = max(0.1, current + delta)
            self.store.update_metadata(memory_id, meta)
            logger.info("Weight updated: %s %.2f → %.2f", memory_id[:8], current, meta["weight"])
        except Exception as e:
            logger.exception("Failed to update weight: %s", e)

    # ────────────────────────────────────────────
    # 删
    # ────────────────────────────────────────────

    def forget(self, memory_id: str) -> None:
        self._ensure_ready()
        try:
            self.store.delete(ids=[memory_id])
            logger.info("Memory deleted: %s", memory_id[:8])
        except Exception as e:
            logger.exception("Failed to delete memory: %s", e)

    # ────────────────────────────────────────────
    # 最近
    # ────────────────────────────────────────────

    def get_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        """按时间倒序获取最近记忆。"""
        self._ensure_ready()
        try:
            raw_results = self.store.get_recent(limit=limit * 3)
        except Exception as e:
            logger.exception("Failed to get recent: %s", e)
            return []
        parsed = []
        for r in raw_results:
            meta = r.get("metadata", {})
            parsed.append({
                "id": r.get("id", ""),
                "content": r.get("content", ""),
                "metadata": meta,
                "timestamp": meta.get("timestamp", 0),
            })
        parsed.sort(key=lambda x: x["timestamp"], reverse=True)
        return parsed[:limit]
