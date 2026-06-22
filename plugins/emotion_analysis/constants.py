"""
emotion_analysis/constants.py — 情感分析常量（从 emotion_rag_plugin.py 迁移）。

包含：情绪词库、风格映射、极性分类。
"""
from __future__ import annotations

from typing import Dict, List


# ────────────────────────────────────────────
# 情绪词库（中文 + 英文触发词）
# ────────────────────────────────────────────

EMOTION_KEYWORDS: Dict[str, List[str]] = {
    "love": ["爱", "喜欢", "想念", "想你了", "爱你", "喜欢上", "love", "miss you", "like you", "cute", "可爱"],
    "upset": ["怪怪的", "不对劲", "烦闷", "烦躁", "upset", "郁闷", "低沉", "不太舒服", "不舒服", "别扭"],
    "sad": ["难过", "伤心", "悲伤", "不开心", "失落", "sad", "cry", "哭", "想哭", "好难过"],
    "angry": ["生气", "愤怒", "气死", "烦", "angry", "mad", "烦死了", "火大", "气炸了", "恼火"],
    "happy": ["开心", "高兴", "快乐", "棒", "好开心", "happy", "哈哈", "嘻嘻", "太棒了", "喜悦"],
    "fearful": ["害怕", "恐惧", "担心", "慌", "scared", "afraid", "worried", "好怕", "吓人", "恐怖"],
    "anxious": ["焦虑", "紧张", "不安", "anxious", "nervous", "压力", "着急", "忐忑", "焦虑不安"],
    "surprised": ["惊讶", "震惊", "surprise", "surprised", "吓我一跳", "意想不到", "出乎意料", "amazing", "wow"],
    "disgusted": ["恶心", "厌恶", "disgust", "disgusted", "反感", "讨厌", "嫌弃", "作呕", "反胃"],
}


# ────────────────────────────────────────────
# 情绪 → 回复风格映射
# ────────────────────────────────────────────

EMOTION_STYLE: Dict[str, Dict[str, str]] = {
    "happy": {"tone": "活泼、喜悦", "style": "可以开玩笑，一起分享快乐"},
    "sad": {"tone": "温柔、包容", "style": "低调、安静地陪伴，不要强行鼓励"},
    "angry": {"tone": "冷静、理解", "style": "先认同感受，不急着分析对错"},
    "surprised": {"tone": "好奇、兴奋", "style": "可以一起表达惊讶和好奇"},
    "fearful": {"tone": "安心、镇定", "style": "温柔地安抚，传递安全感"},
    "disgusted": {"tone": "理解、认同", "style": "表示理解并倾听原因"},
    "neutral": {"tone": "自然、轻松", "style": "日常聊天，保持轻松氛围"},
    "anxious": {"tone": "稳定、安心", "style": "先安抚情绪，再温和分析"},
    "love": {"tone": "温暖、甜蜜", "style": "温暖回应，一起分享美好感受"},
    "upset": {"tone": "温柔、体谅", "style": "先倾听，不要急着分析原因，表示你注意到了ta的不对劲"},
}


# ────────────────────────────────────────────
# 情感极性分类
# ────────────────────────────────────────────

NEGATIVE_EMOTIONS = {"sad", "angry", "fearful", "anxious", "upset"}
POSITIVE_EMOTIONS = {"happy", "love"}


def get_polarity_factor(emotion: str) -> float:
    """返回情感极性权重因子。

    Args:
        emotion: 情感标签

    Returns:
        消极情绪 0.5，积极/中性 1.0
    """
    if emotion in NEGATIVE_EMOTIONS:
        return 0.5
    return 1.0
