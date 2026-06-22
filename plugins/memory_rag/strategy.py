"""
memory_rag/strategy.py — 策略模式：检索得分策略接口与实现。

定义 ScoreStrategy 抽象基类，允许调用方通过注入不同策略来影响检索排序权重。
"""
from __future__ import annotations

import abc
from typing import Any, Dict


class ScoreStrategy(abc.ABC):
    """检索得分策略接口。

    MemoryRAG.search() 在计算综合得分时调用此接口，
    将业务权重因子从向量存储层中解耦出来。
    """

    @abc.abstractmethod
    def calculate(self, metadata: Dict[str, Any]) -> float:
        """根据元数据计算业务权重因子。

        Args:
            metadata: 单条记忆的元数据字典（由 add_memory 时传入）

        Returns:
            权重因子（> 0），将被乘入检索综合得分
        """
        raise NotImplementedError


class NeutralStrategy(ScoreStrategy):
    """中性策略：不加权。适用于通用存储场景（如日程、偏好）。"""

    def calculate(self, metadata: Dict[str, Any]) -> float:
        return 1.0


class EmotionPolarityStrategy(ScoreStrategy):
    """情感极性策略：消极记忆降权，积极/中性记忆正常权重。

    适用于陪伴对话场景，避免消极历史过度影响当前回复。
    """

    _NEGATIVE = {"sad", "angry", "fearful", "anxious", "upset"}
    _POSITIVE = {"happy", "love"}

    def calculate(self, metadata: Dict[str, Any]) -> float:
        emotion = metadata.get("emotion", "neutral")
        if emotion in self._NEGATIVE:
            return 0.5
        return 1.0


class WeightedStrategy(ScoreStrategy):
    """自定义权重策略：直接从 metadata 中读取 'weight' 字段。"""

    def calculate(self, metadata: Dict[str, Any]) -> float:
        return float(metadata.get("weight", 1.0))
