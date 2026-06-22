"""
memory_rag/__init__.py — 暴露公共接口。
"""
from __future__ import annotations

from plugins.memory_rag.memory_rag import MemoryRAG
from plugins.memory_rag.factory import MemoryRAGFactory
from plugins.memory_rag.facade import MemoryServiceFacade
from plugins.memory_rag.strategy import (
    ScoreStrategy,
    NeutralStrategy,
    EmotionPolarityStrategy,
    WeightedStrategy,
)

__all__ = [
    "MemoryRAG",
    "MemoryRAGFactory",
    "MemoryServiceFacade",
    "ScoreStrategy",
    "NeutralStrategy",
    "EmotionPolarityStrategy",
    "WeightedStrategy",
]
