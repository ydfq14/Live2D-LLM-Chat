"""
emotion_analysis/__init__.py — 暴露公共接口。
"""
from __future__ import annotations

from plugins.emotion_analysis.analyzer import EmotionAnalyzer
from plugins.emotion_analysis.functions import (
    keyword_emotion_fallback,
    analyze_emotion_with_llm,
    emotion_to_style,
)
from plugins.emotion_analysis.constants import (
    EMOTION_KEYWORDS,
    EMOTION_STYLE,
    NEGATIVE_EMOTIONS,
    POSITIVE_EMOTIONS,
    get_polarity_factor,
)

__all__ = [
    "EmotionAnalyzer",
    "keyword_emotion_fallback",
    "analyze_emotion_with_llm",
    "emotion_to_style",
    "EMOTION_KEYWORDS",
    "EMOTION_STYLE",
    "NEGATIVE_EMOTIONS",
    "POSITIVE_EMOTIONS",
    "get_polarity_factor",
]
