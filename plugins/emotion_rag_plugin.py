"""
情绪分析与 RAG 记忆插件 —— 组合层（重构后瘦实现）。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
重构说明：
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
本文件从 1076 行瘦身到 ~200 行，职责从"实现所有逻辑"变为"组合各模块"。

已迁移的模块：
├─ 情感分析函数/常量 → plugins/emotion_analysis/
├─ 通用向量记忆存储 → plugins/memory_rag/
├─ 时序事件记忆     → plugins/memory_rag/episodic_memory.py
└─ FER 面部情绪     → plugins/fer_plugin.py

保留的内容：
├─ UserRulesManager（自适应规则学习，独立业务逻辑）
├─ EmotionRAGPlugin（PluginBase Hook 组合层）
└─ 向后兼容的导出符号（旧 import 路径仍可用）

设计模式：
├─ 依赖注入：MemoryRAG / EmotionAnalyzer / SafetyRAG 通过构造函数注入
├─ 策略模式：检索得分由 EmotionPolarityStrategy 注入
├─ 工厂模式：MemoryRAGFactory 创建适配器+策略组合
├─ 门面模式：MemoryServiceFacade 供其他模块使用
└─ 观察者模式：事件广播（预留）
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional

from plugin_base import PluginBase
from log_config import get_logger

logger = get_logger("virtumate.emotion_rag_plugin")


# ═══════════════════════════════════════════════════════════════════
# 向后兼容导出（旧 import 路径仍可用）
# ═══════════════════════════════════════════════════════════════════

from plugins.emotion_analysis.constants import (
    EMOTION_KEYWORDS as _EMOTION_KEYWORDS,
    EMOTION_STYLE as _EMOTION_STYLE,
    NEGATIVE_EMOTIONS as _NEGATIVE_EMOTIONS,
    POSITIVE_EMOTIONS as _POSITIVE_EMOTIONS,
    get_polarity_factor,
)
from plugins.emotion_analysis.functions import (
    keyword_emotion_fallback as _keyword_emotion_fallback,
    analyze_emotion_with_llm as _analyze_emotion_from_text,
    emotion_to_style as _emotion_to_style,
)
from plugins.memory_rag.episodic_memory import EpisodicMemory
from plugins.memory_rag.factory import MemoryRAGFactory
from plugins.memory_rag.strategy import EmotionPolarityStrategy

try:
    from plugins.fer_plugin import FERAnalyzer
except ImportError:
    # 降级：如果 fer_plugin 不存在，提供本地兼容定义
    class FERAnalyzer:
        def __init__(self) -> None:
            self.detector = None
        def analyze_from_camera(self) -> Dict[str, Any]:
            return {"emotion": "neutral", "confidence": 0.5, "available": False}


# ═══════════════════════════════════════════════════════════════════
# 向后兼容 MemoryRAG 包装器（保留旧构造函数和旧 API）
# ═══════════════════════════════════════════════════════════════════

class MemoryRAG:
    """向后兼容的 MemoryRAG 包装器。

    旧构造函数签名：MemoryRAG(persist_dir, collection_name, adapter)
    旧 add_memory 签名：add_memory(content, emotion, weight)

    内部通过 MemoryRAGFactory + EmotionPolarityStrategy 委托给新实现。
    """

    def __init__(
        self,
        persist_dir: str = "./plugins_data/memory",
        collection_name: str = "user_memories",
        adapter: Optional[Any] = None,
    ):
        if adapter is not None:
            self._rag = MemoryRAGFactory.create(adapter=adapter, strategy=EmotionPolarityStrategy())
        else:
            self._rag = MemoryRAGFactory.create(
                persist_dir=persist_dir,
                collection_name=collection_name,
                strategy=EmotionPolarityStrategy(),
            )

    # ── 旧 API 兼容 ──

    def add_memory(self, content: str, emotion_or_metadata: Any = None, weight: float = 1.0) -> str:
        """兼容旧 add_memory(content, emotion, weight) 和新的 add_memory(content, metadata)。"""
        if isinstance(emotion_or_metadata, dict):
            metadata = dict(emotion_or_metadata)
        elif isinstance(emotion_or_metadata, str):
            metadata = {"emotion": emotion_or_metadata, "weight": weight}
        else:
            metadata = {"weight": weight}
        return self._rag.add_memory(content, metadata=metadata)

    def search(self, query: str, n_results: int = 5, emotion_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """兼容旧 search(query, n_results, emotion_filter)。"""
        filters = {"emotion": emotion_filter} if emotion_filter else None
        results = self._rag.search(query, n_results=n_results, filters=filters)
        # 将新格式（metadata 字典）映射回旧格式（扁平字段）
        mapped = []
        for r in results:
            meta = r.get("metadata", {})
            mapped.append({
                "id": r.get("id", ""),
                "content": r.get("content", ""),
                "emotion": meta.get("emotion", "neutral"),
                "weight": meta.get("weight", 1.0),
                "timestamp": meta.get("timestamp", 0),
                "similarity": r.get("similarity", 0),
            })
        return mapped

    def update_weight(self, memory_id: str, delta: float) -> None:
        return self._rag.update_weight(memory_id, delta)

    def forget(self, memory_id: str) -> None:
        return self._rag.forget(memory_id)

    def get_recent_conversations(self, limit: int = 10) -> List[Dict[str, Any]]:
        """兼容旧 get_recent_conversations(limit)。"""
        results = self._rag.get_recent(limit=limit)
        mapped = []
        for r in results:
            meta = r.get("metadata", {})
            mapped.append({
                "id": r.get("id", ""),
                "content": r.get("content", ""),
                "emotion": meta.get("emotion", "neutral"),
                "weight": meta.get("weight", 1.0),
                "timestamp": meta.get("timestamp", 0),
            })
        return mapped

    # 暴露底层实例（供高级使用）
    @property
    def _inner(self):
        return self._rag


# ═══════════════════════════════════════════════════════════════════
# 用户规则管理器（保留，自适应规则学习）
# ═══════════════════════════════════════════════════════════════════

class UserRulesManager:
    """管理用户自适应检索规则。

    规则文件：plugins_data/emotion_rag/user_rules.json
    """

    DEFAULT_RULES = {
        "trigger_words": [
            "上次", "之前", "记得", "说过", "聊过", "提过", "以前", "曾经",
            "earlier", "before", "last time", "remember", "mentioned", "talked about",
        ],
        "skip_patterns": [
            "你好", "在吗", "哈喽", "hi", "hello", "hey", "早安", "午安", "晚安",
            "good morning", "good afternoon", "good evening", "good night",
        ],
        "learned_words": [],
        "llm_fallback_remaining": 0,
        "learning_inputs": [],
        "version": 1,
    }

    def __init__(self, data_dir: str = "./plugins_data/emotion_rag") -> None:
        self.data_dir = data_dir
        self.rules_file = os.path.join(data_dir, "user_rules.json")
        self.rules: Dict[str, Any] = {}
        self._load_rules()

    def _load_rules(self) -> None:
        os.makedirs(self.data_dir, exist_ok=True)
        if os.path.exists(self.rules_file):
            try:
                with open(self.rules_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                self.rules = {**self.DEFAULT_RULES, **loaded}
                logger.info("[规则] 已加载: %d 触发词, %d 学习词",
                            len(self.rules["trigger_words"]), len(self.rules.get("learned_words", [])))
            except Exception as e:
                logger.warning("[规则] 加载失败: %s，使用默认", e)
                self.rules = dict(self.DEFAULT_RULES)
        else:
            self.rules = dict(self.DEFAULT_RULES)
            self._save_rules()
            logger.info("[规则] 创建默认: %s", self.rules_file)

    def _save_rules(self) -> None:
        try:
            with open(self.rules_file, "w", encoding="utf-8") as f:
                json.dump(self.rules, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("[规则] 保存失败: %s", e)

    def decide_retrieval(self, text: str) -> tuple[bool, str]:
        if not text:
            return False, "skip"
        text_lower = text.lower().strip()
        all_words = self.rules.get("trigger_words", []) + self.rules.get("learned_words", [])
        skip_patterns = self.rules.get("skip_patterns", [])

        if len(text_lower) <= 6:
            for pattern in skip_patterns:
                if pattern.lower() in text_lower:
                    return False, "skip"

        for word in all_words:
            if word.lower() in text_lower:
                return True, "rule"

        remaining = self.rules.get("llm_fallback_remaining", 0)
        if remaining > 0:
            return True, "llm"

        return True, "default"

    def record_learning_input(self, text: str, llm_decision: bool) -> None:
        inputs = self.rules.get("learning_inputs", [])
        inputs.append({"text": text, "need_retrieval": llm_decision, "timestamp": time.time()})
        self.rules["learning_inputs"] = inputs
        remaining = self.rules.get("llm_fallback_remaining", 0)
        if remaining > 0:
            self.rules["llm_fallback_remaining"] = remaining - 1
        if remaining <= 1 and len(inputs) >= 2:
            self._try_learn_new_rules()
        self._save_rules()

    def start_learning_mode(self, missed_text: str) -> None:
        self.rules["llm_fallback_remaining"] = 5
        inputs = self.rules.get("learning_inputs", [])
        inputs.append({"text": missed_text, "need_retrieval": True, "timestamp": time.time(), "missed": True})
        self.rules["learning_inputs"] = inputs
        self._save_rules()
        logger.info("[规则] 学习模式启动: '%s'，后续5次用 LLM 判断", missed_text[:30])

    def _try_learn_new_rules(self) -> None:
        inputs = self.rules.get("learning_inputs", [])
        if not inputs:
            return
        need_retrieval_texts = [r["text"] for r in inputs if r.get("need_retrieval", False)]
        if len(need_retrieval_texts) < 2:
            return
        from collections import Counter
        all_words = []
        for text in need_retrieval_texts:
            for i in range(len(text) - 1):
                word = text[i:i+2]
                if len(word) >= 2 and word.strip():
                    all_words.append(word)
        counter = Counter(all_words)
        existing = set(self.rules.get("trigger_words", []) + self.rules.get("learned_words", []))
        new_candidates = []
        for word, count in counter.most_common(5):
            if word not in existing and count >= 2:
                new_candidates.append(word)
        if new_candidates:
            learned = self.rules.get("learned_words", [])
            for word in new_candidates:
                if word not in learned:
                    learned.append(word)
            self.rules["learned_words"] = learned
            logger.info("[规则] 自动学习新触发词: %s", new_candidates)
        self.rules["learning_inputs"] = []

    def is_in_learning_mode(self) -> bool:
        return self.rules.get("llm_fallback_remaining", 0) > 0

    def get_stats(self) -> Dict[str, Any]:
        return {
            "trigger_words": len(self.rules.get("trigger_words", [])),
            "learned_words": len(self.rules.get("learned_words", [])),
            "learning_mode": self.is_in_learning_mode(),
            "remaining": self.rules.get("llm_fallback_remaining", 0),
        }


# ═══════════════════════════════════════════════════════════════════
# 插件主类（组合层）
# ═══════════════════════════════════════════════════════════════════

class EmotionRAGPlugin(PluginBase):
    """情绪分析与 RAG 记忆插件（重构后组合层）。

    通过 Hook 机制实现，所有具体逻辑委托给独立模块：
    - 情感分析 → EmotionAnalyzer（plugins/emotion_analysis/）
    - 向量记忆 → MemoryRAG（plugins/memory_rag/，通过兼容包装器）
    - 时序记忆 → EpisodicMemory（plugins/memory_rag/）
    - 安全拦截 → SafetyRAG（safety_rag/）
    """

    name = "emotion_rag"
    version = "3.0"  # 重构版本

    def __init__(self) -> None:
        super().__init__()
        self.memory_rag: MemoryRAG | None = None
        self.rules_manager: UserRulesManager | None = None
        self.episodic_memory: EpisodicMemory | None = None
        self._character_knowledge: str = ""
        self.safety_rag: Any | None = None
        self._safety_intercepted: bool = False
        self._last_user_input: str | None = None
        self._last_emotion: Dict[str, Any] | None = None
        self._last_reply: str | None = None
        self._last_retrieval_mode: str = ""
        self._last_need_retrieval: bool = False
        self._fer_data_path: str = "./plugins_data/fer_emotion.json"
        self._last_face_emotion: Dict[str, Any] | None = None

    # ================================================================
    # Hook 实现
    # ================================================================

    def on_startup(self, app) -> None:
        super().on_startup(app)
        # ── MemoryRAG 独立初始化（失败时不影响其他组件）──
        try:
            self.memory_rag = MemoryRAG(persist_dir="./plugins_data/memory")
            logger.info("[emotion_rag] MemoryRAG 已初始化")
        except Exception as e:
            logger.warning("[emotion_rag] MemoryRAG 初始化失败: %s。记忆检索功能不可用。", e)
            self.memory_rag = None

        try:
            self.rules_manager = UserRulesManager(data_dir="./plugins_data/emotion_rag")
            self.episodic_memory = EpisodicMemory(db_path="./plugins_data/emotion_rag/episodic.db")
            try:
                from safety_rag.safety_rag import SafetyRAG
                self.safety_rag = SafetyRAG()
            except Exception as e:
                logger.warning("[emotion_rag] SafetyRAG 加载失败: %s", e)
                self.safety_rag = None
            self._load_character_knowledge()
            stats = self.rules_manager.get_stats()
            logger.info(
                "[emotion_rag] 插件就绪 v%s — 组合层 | 触发词:%d | 学习词:%d | SafetyRAG:%s | MemoryRAG:%s",
                self.version,
                stats["trigger_words"], stats["learned_words"],
                "已启用" if self.safety_rag else "未启用",
                "已启用" if self.memory_rag else "未启用",
            )
        except Exception as e:
            logger.error("[emotion_rag] 初始化失败: %s", e)

    def _load_character_knowledge(self) -> None:
        kb_path = "./knowledge_base/character_script.md"
        if os.path.exists(kb_path):
            try:
                with open(kb_path, "r", encoding="utf-8") as f:
                    self._character_knowledge = f.read()
                logger.info("[知识库] 角色剧本已加载: %d 字符", len(self._character_knowledge))
            except Exception as e:
                logger.warning("[知识库] 加载失败: %s", e)
        else:
            logger.info("[知识库] 角色剧本未找到: %s（可选）", kb_path)

    def on_user_input(self, text: str) -> str | None:
        self._last_user_input = text
        self._safety_intercepted = False

        # ── 安全拦截 ──
        if self.safety_rag:
            safety_result = self.safety_rag.check_input(text)
            risk_level = safety_result.get("risk_level", "safe")
            if risk_level == "high":
                self._safety_intercepted = True
                if self.episodic_memory:
                    self.episodic_memory.add_event(
                        event_type="care_triggered",
                        content=f"高危拦截: {safety_result.get('risk_type', '')} | 输入: {text[:50]}",
                        emotion="fearful",
                        weight=1.0,
                    )
                return safety_result.get("response", "这个话题我不能讨论。")
            elif risk_level in ("medium", "low"):
                logger.warning("[SafetyRAG] 风险标记: level=%s", risk_level)

        # ── FER 数据读取 ──
        self._read_fer_emotion()

        # ── 情感分析（委托给新模块）──
        self._last_emotion = _keyword_emotion_fallback(text)
        logger.info(
            "[emotion_rag] 关键词情感 fallback: %s (%.2f)",
            self._last_emotion.get("emotion", "neutral"),
            self._last_emotion.get("confidence", 0.5),
        )
        return None

    def _read_fer_emotion(self) -> None:
        try:
            if os.path.exists(self._fer_data_path):
                with open(self._fer_data_path, "r", encoding="utf-8") as f:
                    self._last_face_emotion = json.load(f)
        except Exception as e:
            logger.debug("[emotion_rag] FER 数据读取失败: %s", e)
            self._last_face_emotion = None

    def on_llm_context(self, user_input: str) -> str:
        if not self.memory_rag or not self._last_user_input:
            return ""

        # ── 1. LLM 情感分析（覆盖关键词 fallback）──
        try:
            if self.app and hasattr(self.app, "llm_manager"):
                llm_result = _analyze_emotion_from_text(self._last_user_input, self.app.llm_manager)
                if llm_result.get("confidence", 0) > 0.5:
                    self._last_emotion = llm_result
                    logger.info(
                        "[emotion_rag] LLM 情感分析: %s (%.2f)",
                        llm_result.get("emotion", "neutral"),
                        llm_result.get("confidence", 0.5),
                    )
        except Exception as e:
            logger.warning("[emotion_rag] LLM 情感分析失败: %s", e)

        emotion = self._last_emotion or {}
        parts: list[str] = []

        # ── 2. 情绪信息 ──
        if emotion.get("emotion", "neutral") != "neutral":
            parts.append(f"【当前用户情绪】{emotion['emotion']}（{emotion.get('confidence', 0):.2f}）")
            if emotion.get("cause"):
                parts.append(f"【情绪原因】{emotion['cause']}")

        # ── 3. 自适应检索决策 ──
        need_retrieval = False
        mode = "default"
        if self.rules_manager:
            need_retrieval, mode = self.rules_manager.decide_retrieval(self._last_user_input)
            self._last_retrieval_mode = mode
            self._last_need_retrieval = need_retrieval

            if mode == "default":
                self.rules_manager.start_learning_mode(self._last_user_input)
                parts.append(
                    "【系统提示】刚才可能漏检了相关记忆，本次已启用智能检索模式。"
                    "如果回复不够全面，请告诉我。"
                )
                try:
                    if self.app and hasattr(self.app, "llm_manager"):
                        need_retrieval = self._llm_decide_retrieval(self._last_user_input, self.app.llm_manager)
                        mode = "llm"
                        self._last_need_retrieval = need_retrieval
                except Exception as e:
                    logger.warning("[emotion_rag] LLM 检索判断失败: %s", e)
                    need_retrieval = True

            elif mode == "llm":
                try:
                    if self.app and hasattr(self.app, "llm_manager"):
                        need_retrieval = self._llm_decide_retrieval(self._last_user_input, self.app.llm_manager)
                        self._last_need_retrieval = need_retrieval
                        self.rules_manager.record_learning_input(self._last_user_input, need_retrieval)
                except Exception as e:
                    logger.warning("[emotion_rag] LLM 检索判断失败: %s", e)
                    need_retrieval = True

        logger.info("[emotion_rag] 检索决策: %s (模式=%s)", need_retrieval, mode)

        # ── 4. 记忆检索 ──
        if need_retrieval:
            memory_items: list[dict[str, Any]] = []
            try:
                emotion_filter = emotion.get("emotion") if emotion.get("emotion") != "neutral" else None
                memories = self.memory_rag.search(
                    query=self._last_user_input,
                    n_results=5,
                    emotion_filter=emotion_filter,
                )
                recent = self.memory_rag.get_recent_conversations(limit=5)

                seen_content: set[str] = set()
                for m in memories:
                    if m["content"] not in seen_content:
                        memory_items.append(m)
                        seen_content.add(m["content"])
                for m in recent:
                    if m["content"] not in seen_content:
                        memory_items.append(m)
                        seen_content.add(m["content"])

                # 多跳检索
                if len(memory_items) < 2 and memories:
                    hop_query = memories[0]["content"]
                    hop_results = self.memory_rag.search(query=hop_query, n_results=3)
                    for m in hop_results:
                        if m["content"] not in seen_content:
                            memory_items.append(m)
                            seen_content.add(m["content"])
                    logger.info("[emotion_rag] 多跳检索: 补充 %d 条", len(hop_results))

                memory_items = memory_items[:8]
                logger.info("[emotion_rag] 检索到 %d 条记忆", len(memory_items))
            except Exception as e:
                logger.warning("[emotion_rag] 记忆检索失败: %s", e)

            if memory_items:
                lines = [f"- [{m.get('emotion', 'neutral')}] {m['content']}" for m in memory_items[:3]]
                parts.append("【相关记忆】\n" + "\n".join(lines))
        else:
            logger.info("[emotion_rag] 跳过检索")

        # ── 5. 回复风格 ──
        style = _emotion_to_style(emotion.get("emotion", ""))
        if style:
            parts.append(f"【回复风格】{style}")

        # ── 6. 角色剧本知识库 ──
        if self._character_knowledge:
            kb_lines = self._character_knowledge.splitlines()
            relevant_lines = []
            for line in kb_lines:
                line_stripped = line.strip()
                if not line_stripped or line_stripped.startswith("#"):
                    continue
                if any(kw in line_stripped for kw in [emotion.get("emotion", ""), "情绪", "回应", "风格"]):
                    relevant_lines.append(line_stripped)
            if relevant_lines:
                parts.append(f"【角色剧本参考】\n" + "\n".join(relevant_lines[:5]))

        extra_context = "\n\n".join(parts)
        if extra_context:
            logger.info("[emotion_rag] 注入上下文 (%d 字符)", len(extra_context))
        return extra_context

    def _llm_decide_retrieval(self, text: str, llm: Any) -> bool:
        prompt = (
            "判断下面的用户输入是否需要检索历史记忆才能给出好的回复。\n"
            '只返回 JSON 格式：{"need_retrieval": true/false, "reason": "简要原因"}\n\n'
            f"用户输入：{text}\n\nJSON："
        )
        try:
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
                need = data.get("need_retrieval", True)
                reason = data.get("reason", "")
                logger.info("[emotion_rag] LLM 检索判断: %s (%s)", need, reason)
                return bool(need)
        except Exception as e:
            logger.warning("[emotion_rag] LLM 检索判断解析失败: %s", e)
        return True

    def on_llm_response(self, text: str) -> str | None:
        self._last_reply = text

        if self._safety_intercepted:
            logger.info("[SafetyGuard] 本轮被安全拦截，跳过记忆存储")
            self._clear_round_cache()
            return None

        if not self.memory_rag or not self._last_user_input:
            self._clear_round_cache()
            return None

        try:
            emotion_label = self._last_emotion.get("emotion", "neutral") if self._last_emotion else "neutral"

            if emotion_label in _NEGATIVE_EMOTIONS:
                user_weight = 0.5
            elif emotion_label in _POSITIVE_EMOTIONS:
                user_weight = 1.5
            else:
                user_weight = 1.0

            self.memory_rag.add_memory(
                content=self._last_user_input,
                emotion_or_metadata=emotion_label,
                weight=user_weight,
            )
            if text:
                self.memory_rag.add_memory(content=text, emotion_or_metadata="neutral", weight=0.7)

            logger.info(
                "[emotion_rag] 记忆入库: 用户[%s] (情感=%s 权重=%.1f) + 回复[%s]",
                self._last_user_input[:30], emotion_label, user_weight, text[:30],
            )

            if self.episodic_memory:
                try:
                    self.episodic_memory.add_event(
                        event_type="user_input",
                        content=self._last_user_input[:100],
                        emotion=emotion_label,
                        weight=user_weight,
                    )
                    if text:
                        self.episodic_memory.add_event(
                            event_type="llm_response",
                            content=text[:100],
                            emotion="neutral",
                            weight=0.7,
                        )
                except Exception as e:
                    logger.warning("[emotion_rag] Episodic 记录失败: %s", e)
        except Exception as e:
            logger.warning("[emotion_rag] 记忆入库失败: %s", e)

        self._clear_round_cache()
        return None

    def _clear_round_cache(self) -> None:
        self._last_user_input = None
        self._last_emotion = None
        self._last_reply = None
        self._last_retrieval_mode = ""
        self._last_need_retrieval = False
        self._safety_intercepted = False
        self._last_face_emotion = None

    def on_tick(self, app) -> None:
        self._tick_count = getattr(self, "_tick_count", 0) + 1
        if self._tick_count % 10 == 0:
            self._read_fer_emotion()
            if self._last_face_emotion and self._last_face_emotion.get("available"):
                logger.info(
                    "[FER] 面部情绪: %s (%.2f) 来源=%s",
                    self._last_face_emotion.get("emotion", "neutral"),
                    self._last_face_emotion.get("confidence", 0.5),
                    self._last_face_emotion.get("source", "—"),
                )

    def on_before_tts(self, text: str) -> str | None:
        cleaned = re.sub(r"【.*?】", "", text)
        cleaned = cleaned.strip()
        if cleaned != text:
            logger.info("[emotion_rag] TTS 文本清理: %d -> %d 字符", len(text), len(cleaned))
            return cleaned
        return None

    def on_shutdown(self) -> None:
        if self.memory_rag:
            self.memory_rag = None
        logger.info("[emotion_rag] 插件已关闭。")

    def get_frontend_html(self) -> str:
        return r"""
        <div style="padding:12px; color:#eee; font-family:system-ui,sans-serif">
            <h3 style="color:#e94560; margin-bottom:12px">[情绪与记忆]</h3>
            <p style="color:#aaa; font-size:13px">
                此插件通过 Hook 机制工作：<br>
                · on_user_input → 关键词情感分析<br>
                · on_llm_context → LLM 零样本 + 自适应检索决策<br>
                · on_llm_response → 对话入库<br>
            </p>
            <p style="color:#aaa; font-size:13px; margin-top:8px">
                <b>自适应规则学习</b>：<br>
                预设规则未命中 → 启动 LLM 学习模式（5次）→ 自动提取特征词 → 更新用户规则<br>
                规则文件：plugins_data/emotion_rag/user_rules.json（用户可手动编辑）
            </p>
            <p style="color:#aaa; font-size:13px; margin-top:8px">
                <b>重构后架构</b>：<br>
                情感分析 → plugins/emotion_analysis/<br>
                向量记忆 → plugins/memory_rag/<br>
                安全拦截 → safety_rag/<br>
                零改动 GraphEngine，纯插件实现。
            </p>
        </div>
        """
