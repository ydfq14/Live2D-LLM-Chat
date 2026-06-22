"""
emotion_analysis/functions.py — 纯情感分析函数（从 emotion_rag_plugin.py 迁移）。

包含：关键词 fallback、LLM 零样本分析、风格映射。

不依赖任何 RAG/插件类，可独立使用。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict

from log_config import get_logger
from plugins.emotion_analysis.constants import EMOTION_KEYWORDS, EMOTION_STYLE, get_polarity_factor

logger = get_logger("emotion_analysis.functions")


def keyword_emotion_fallback(text: str) -> Dict[str, Any]:
    """关键词情绪检测作为 fallback。

    按优先级：upset > love > sad > angry > happy > fearful > anxious

    Args:
        text: 用户输入文本

    Returns:
        {"emotion": str, "confidence": float, "cause": str}
    """
    if not text:
        return {"emotion": "neutral", "confidence": 0.5, "cause": ""}

    text_lower = text.lower()
    # 去空格版本：处理 "我 很 开 心" → "我很开心" 场景
    text_no_space = text_lower.replace(" ", "").replace("　", "")
    for emotion, words in EMOTION_KEYWORDS.items():
        for word in words:
            if word in text_lower or word in text_no_space:
                confidence_map = {
                    "love": 0.6, "upset": 0.65, "sad": 0.7, "angry": 0.7,
                    "happy": 0.7, "fearful": 0.6, "anxious": 0.6,
                    "surprised": 0.65, "disgusted": 0.65,
                }
                return {
                    "emotion": emotion,
                    "confidence": confidence_map.get(emotion, 0.6),
                    "cause": word,
                }
    return {"emotion": "neutral", "confidence": 0.5, "cause": ""}


def analyze_emotion_with_llm(text: str, llm: Any) -> Dict[str, Any]:
    """LLM 零样本情绪分析。

    Args:
        text: 用户输入文本
        llm: LLM 管理器（需有 chat_with_tools 或 chat 方法）

    Returns:
        {"emotion": str, "confidence": float, "cause": str}
        失败时返回 neutral
    """
    if not text or not llm:
        return {"emotion": "neutral", "confidence": 0.5, "cause": ""}

    try:
        prompt = (
            "分析下面这句话的情绪。只返回JSON格式："
            '{"emotion": "情绪标签", "confidence": 0~1之间的置信度, "cause": "引起情绪的关键词"}\n'
            "情绪标签可选：love, upset, sad, angry, happy, fearful, anxious, surprised, disgusted, neutral\n\n"
            f"文本：{text}\n\nJSON："
        )

        if hasattr(llm, "chat_with_tools"):
            result = llm.chat_with_tools([{"role": "user", "content": prompt}], tools=[])
            content = result.get("content", "")
        elif hasattr(llm, "chat"):
            result = llm.chat([{"role": "user", "content": prompt}])
            content = result if isinstance(result, str) else str(result)
        else:
            content = str(llm)

        json_match = re.search(r'\{.*?\}', content, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            emotion = data.get("emotion", "neutral").lower().strip()
            confidence = float(data.get("confidence", 0.5))
            cause = data.get("cause", "")
            valid = set(EMOTION_KEYWORDS.keys()) | {"neutral", "surprised", "disgusted"}
            if emotion not in valid:
                emotion = "neutral"
            return {"emotion": emotion, "confidence": min(confidence, 1.0), "cause": cause}

    except Exception as e:
        logger.warning("LLM emotion analysis failed: %s", e)

    return {"emotion": "neutral", "confidence": 0.5, "cause": ""}


def emotion_to_style(emotion: str) -> str:
    """将情绪标签转换为回复风格提示。

    Args:
        emotion: 情绪标签

    Returns:
        风格提示字符串（空字符串表示 neutral）
    """
    if not emotion or emotion == "neutral":
        return ""
    info = EMOTION_STYLE.get(emotion)
    if not info:
        return ""
    return f"语调：{info['tone']}\n风格：{info['style']}"
