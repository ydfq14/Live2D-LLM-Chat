"""
emotion_analysis/analyzer.py — 情感分析器类（封装双引擎）。

职责：
- 封装关键词 fallback + LLM 零样本分析双引擎
- 提供统一接口：analyze(text) -> {"emotion", "confidence", "cause"}
- 提供风格映射和极性因子查询

可独立使用，不依赖任何 RAG/插件。
"""
from __future__ import annotations

from typing import Any, Dict, Optional

from log_config import get_logger
from plugins.emotion_analysis.constants import get_polarity_factor
from plugins.emotion_analysis.functions import (
    keyword_emotion_fallback,
    analyze_emotion_with_llm,
    emotion_to_style,
)

logger = get_logger("emotion_analysis")


class EmotionAnalyzer:
    """情感分析器。

    封装关键词 + LLM 双引擎分析，调用方可通过配置选择是否使用 LLM。

    Args:
        llm: LLM 管理器（可选，没有则只使用关键词 fallback）
        llm_confidence_threshold: LLM 结果最低置信度，低于此值 fallback 到关键词
    """

    def __init__(
        self,
        llm: Optional[Any] = None,
        llm_confidence_threshold: float = 0.5,
    ):
        self.llm = llm
        self.llm_threshold = llm_confidence_threshold

    def analyze(self, text: str, use_llm: bool = True) -> Dict[str, Any]:
        """分析文本情感。

        策略：
        1. 如果 use_llm=True 且 llm 可用，先用 LLM 分析
        2. 如果 LLM 结果置信度低于阈值，fallback 到关键词匹配
        3. 返回统一格式

        Args:
            text: 用户输入文本
            use_llm: 是否尝试 LLM 分析

        Returns:
            {"emotion": str, "confidence": float, "cause": str}
        """
        if not text:
            return {"emotion": "neutral", "confidence": 0.5, "cause": ""}

        # 先关键词 fallback（保底）
        fallback_result = keyword_emotion_fallback(text)

        if use_llm and self.llm is not None:
            try:
                llm_result = analyze_emotion_with_llm(text, self.llm)
                if llm_result.get("confidence", 0) >= self.llm_threshold:
                    logger.info(
                        "[EmotionAnalyzer] LLM: %s (%.2f)",
                        llm_result["emotion"], llm_result["confidence"],
                    )
                    return llm_result
                else:
                    logger.info(
                        "[EmotionAnalyzer] LLM 置信度低 (%.2f)，fallback 到关键词",
                        llm_result.get("confidence", 0),
                    )
            except Exception as e:
                logger.warning("[EmotionAnalyzer] LLM 分析失败: %s", e)

        return fallback_result

    def get_style(self, emotion: str) -> str:
        """获取情感对应的回复风格提示。"""
        return emotion_to_style(emotion)

    def get_polarity(self, emotion: str) -> float:
        """获取情感极性权重因子。"""
        return get_polarity_factor(emotion)
