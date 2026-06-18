"""
情绪分析与 RAG 记忆插件 —— 纯插件实现，零改动 GraphEngine。

功能：
- 启动时初始化 Chroma 向量记忆库 + 用户自适应规则
- 用户输入时：关键词情感 fallback（快速），缓存到插件状态
- LLM 请求前：LLM 零样本情感分析 + 自适应检索决策 + Chroma 记忆检索 + 构建上下文
- LLM 回复后：将本轮对话存入 Chroma 记忆库
- 自适应规则学习：规则未命中时触发 LLM 判断 + 道歉 + 学习模式，自动更新规则

此插件不修改任何根目录文件，不依赖 LangGraph 内部节点，
完全通过 PluginBase 的 Hook 机制工作。
"""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from plugin_base import PluginBase
from log_config import get_logger

logger = get_logger("virtumate.emotion_rag_plugin")

# ═══════════════════════════════════════════════════════════════════
# 情绪词库（中文 + 英文触发词）
# ═══════════════════════════════════════════════════════════════════
_EMOTION_KEYWORDS: Dict[str, list[str]] = {
    "love": ["爱", "喜欢", "想念", "想你了", "爱你", "喜欢上", "love", "miss you", "like you", "cute", "可爱"],
    "upset": ["怪怪的", "不对劲", "烦闷", "烦躁", "upset", "郁闷", "低沉", "不太舒服", "不舒服", "别扭"],
    "sad": ["难过", "伤心", "悲伤", "不开心", "失落", "sad", "cry", "哭", "想哭", "好难过"],
    "angry": ["生气", "愤怒", "气死", "烦", "angry", "mad", "烦死了", "火大", "气炸了", "恼火"],
    "happy": ["开心", "高兴", "快乐", "棒", "好开心", "happy", "哈哈", "嘻嘻", "太棒了", "喜悦"],
    "fearful": ["害怕", "恐惧", "担心", "慌", "scared", "afraid", "worried", "好怕", "吓人", "恐怖"],
    "anxious": ["焦虑", "紧张", "不安", "anxious", "nervous", "压力", "着急", "忐忑", "焦虑不安"],
}

# ═══════════════════════════════════════════════════════════════════
# 情绪 → 回复风格映射
# ═══════════════════════════════════════════════════════════════════
_EMOTION_STYLE: Dict[str, Dict[str, str]] = {
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

# ═══════════════════════════════════════════════════════════════════
# 情感极性分类（Phase 2：情感极性遗忘）
# ═══════════════════════════════════════════════════════════════════
_NEGATIVE_EMOTIONS = {"sad", "angry", "fearful", "anxious", "upset"}
_POSITIVE_EMOTIONS = {"happy", "love"}

# ═══════════════════════════════════════════════════════════════════
# 情感分析函数（纯函数，不依赖任何类）
# ═══════════════════════════════════════════════════════════════════

def _keyword_emotion_fallback(text: str) -> Dict[str, Any]:
    """关键词情绪检测作为 fallback。
    按优先级：upset > love > sad > angry > happy > fearful > anxious
    """
    text_lower = text.lower()
    for emotion, words in _EMOTION_KEYWORDS.items():
        for word in words:
            if word in text_lower:
                confidence_map = {
                    "love": 0.6, "upset": 0.65, "sad": 0.7, "angry": 0.7,
                    "happy": 0.7, "fearful": 0.6, "anxious": 0.6,
                }
                return {
                    "emotion": emotion,
                    "confidence": confidence_map.get(emotion, 0.6),
                    "cause": word,
                }
    return {"emotion": "neutral", "confidence": 0.5, "cause": ""}


def _analyze_emotion_from_text(text: str, llm: Any) -> Dict[str, Any]:
    """LLM 零样本情绪分析 + 关键词 fallback。"""
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
            emotion_value = data.get("emotion", "neutral").lower().strip()
            confidence = float(data.get("confidence", 0.5))
            cause = data.get("cause", "")
            valid_emotions = set(_EMOTION_KEYWORDS.keys()) | {"neutral", "surprised", "disgusted"}
            if emotion_value not in valid_emotions:
                emotion_value = "neutral"
            return {"emotion": emotion_value, "confidence": min(confidence, 1.0), "cause": cause}

    except Exception as e:
        logger.warning("LLM emotion analysis failed: %s", e)

    return _keyword_emotion_fallback(text)


def _emotion_to_style(emotion: str) -> str:
    """将情绪标签转换为回复风格提示。"""
    if not emotion or emotion == "neutral":
        return ""
    info = _EMOTION_STYLE.get(emotion)
    if not info:
        return ""
    return f"语调：{info['tone']}\n风格：{info['style']}"


# ═══════════════════════════════════════════════════════════════════
# 用户规则管理器（自适应规则学习）
# ═══════════════════════════════════════════════════════════════════

class UserRulesManager:
    """管理用户自适应检索规则。

    规则文件：plugins_data/emotion_rag/user_rules.json
    结构：
    {
        "trigger_words": ["上次", "之前", ...],      # 检索触发词
        "skip_patterns": ["你好", "hi", ...],        # 跳过检索模式
        "learned_words": ["自定义触发词", ...],      # 从 LLM 学习到的词
        "llm_fallback_remaining": 0,                  # 剩余 LLM 判断次数
        "learning_inputs": [],                          # 学习模式中的输入记录
        "version": 1
    }
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
        """加载用户规则文件，不存在则创建默认规则。"""
        os.makedirs(self.data_dir, exist_ok=True)
        if os.path.exists(self.rules_file):
            try:
                with open(self.rules_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                # 合并默认规则（处理新增字段）
                self.rules = {**self.DEFAULT_RULES, **loaded}
                logger.info("[规则] 已加载用户规则: %d 触发词, %d 学习词",
                            len(self.rules["trigger_words"]), len(self.rules.get("learned_words", [])))
            except Exception as e:
                logger.warning("[规则] 加载规则失败: %s，使用默认规则", e)
                self.rules = dict(self.DEFAULT_RULES)
        else:
            self.rules = dict(self.DEFAULT_RULES)
            self._save_rules()
            logger.info("[规则] 创建默认规则文件: %s", self.rules_file)

    def _save_rules(self) -> None:
        """保存用户规则到文件。"""
        try:
            with open(self.rules_file, "w", encoding="utf-8") as f:
                json.dump(self.rules, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error("[规则] 保存规则失败: %s", e)

    def decide_retrieval(self, text: str) -> tuple[bool, str]:
        """判断是否需要检索记忆。

        Returns:
            (need_retrieval, mode)
            mode: "rule" | "llm" | "default" | "skip"
        """
        if not text:
            return False, "skip"

        text_lower = text.lower().strip()
        all_words = (
            self.rules.get("trigger_words", [])
            + self.rules.get("learned_words", [])
        )
        skip_patterns = self.rules.get("skip_patterns", [])

        # 1. 短问候语跳过检索
        if len(text_lower) <= 6:
            for pattern in skip_patterns:
                if pattern.lower() in text_lower:
                    return False, "skip"

        # 2. 规则命中 → 需要检索
        for word in all_words:
            if word.lower() in text_lower:
                return True, "rule"

        # 3. 规则未命中 → 检查是否处于学习模式
        remaining = self.rules.get("llm_fallback_remaining", 0)
        if remaining > 0:
            return True, "llm"

        # 4. 默认：需要检索（宁可多检，不可漏检）
        return True, "default"

    def record_learning_input(self, text: str, llm_decision: bool) -> None:
        """记录学习模式中的输入和 LLM 判断结果。"""
        inputs = self.rules.get("learning_inputs", [])
        inputs.append({"text": text, "need_retrieval": llm_decision, "timestamp": time.time()})
        self.rules["learning_inputs"] = inputs

        # 减少剩余次数
        remaining = self.rules.get("llm_fallback_remaining", 0)
        if remaining > 0:
            self.rules["llm_fallback_remaining"] = remaining - 1

        # 如果学习模式结束，尝试自动更新规则
        if remaining <= 1 and len(inputs) >= 2:
            self._try_learn_new_rules()

        self._save_rules()

    def start_learning_mode(self, missed_text: str) -> None:
        """启动学习模式：规则未命中时调用。"""
        self.rules["llm_fallback_remaining"] = 5
        # 记录这次未命中的输入
        inputs = self.rules.get("learning_inputs", [])
        inputs.append({"text": missed_text, "need_retrieval": True, "timestamp": time.time(), "missed": True})
        self.rules["learning_inputs"] = inputs
        self._save_rules()
        logger.info("[规则] 启动学习模式 — 规则未命中: '%s'，后续5次用 LLM 判断", missed_text[:30])

    def _try_learn_new_rules(self) -> None:
        """尝试从学习记录中自动发现新规则。"""
        inputs = self.rules.get("learning_inputs", [])
        if not inputs:
            return

        # 收集所有在学习模式中被 LLM 判断为"需要检索"的输入
        need_retrieval_texts = [r["text"] for r in inputs if r.get("need_retrieval", False)]
        if len(need_retrieval_texts) < 2:
            return

        # 简单启发式：提取这些文本中的高频词（长度 >= 2）
        from collections import Counter
        all_words = []
        for text in need_retrieval_texts:
            # 中文分词简化版：按字/词提取
            for i in range(len(text) - 1):
                word = text[i:i+2]
                if len(word) >= 2 and word.strip():
                    all_words.append(word)

        counter = Counter(all_words)
        # 排除已在规则中的词
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

        # 清空学习记录（已吸收）
        self.rules["learning_inputs"] = []

    def is_in_learning_mode(self) -> bool:
        """检查是否处于学习模式。"""
        return self.rules.get("llm_fallback_remaining", 0) > 0

    def get_stats(self) -> Dict[str, Any]:
        """返回规则统计信息。"""
        return {
            "trigger_words": len(self.rules.get("trigger_words", [])),
            "learned_words": len(self.rules.get("learned_words", [])),
            "learning_mode": self.is_in_learning_mode(),
            "remaining": self.rules.get("llm_fallback_remaining", 0),
        }


# ═══════════════════════════════════════════════════════════════════
# MemoryRAG 类（Chroma 向量记忆）
# ═══════════════════════════════════════════════════════════════════

class MemoryRAG:
    """Chroma-based vector memory for conversation history.

    每个记忆存储：content + embedding + metadata(emotion, weight, timestamp)
    """

    def __init__(self, persist_dir: str = "./plugins_data/memory", collection_name: str = "user_memories"):
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self.client = None
        self.collection = None
        self._embedding_fn = None
        self._init_chroma()

    def _init_chroma(self) -> None:
        """Initialise Chroma persistent client and collection."""
        try:
            import sqlite3
            if sqlite3.sqlite_version < "3.35.0":
                try:
                    import pysqlite3 as sqlite3
                    import chromadb
                    import sys
                    sys.modules['sqlite3'] = sqlite3
                except ImportError:
                    pass
            import chromadb
            os.makedirs(self.persist_dir, exist_ok=True)
            self.client = chromadb.PersistentClient(path=self.persist_dir)
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
            logger.info("Chroma ready: persist_dir=%s collection=%s", self.persist_dir, self.collection_name)
        except ImportError as e:
            logger.error("chromadb not installed: pip install chromadb\n  %s", e)
            self.client = None
            self.collection = None
        except RuntimeError as e:
            if "sqlite3" in str(e).lower():
                logger.error("SQLite3 version too old. Please upgrade sqlite3 >= 3.35.0\n  %s", e)
            self.client = None
            self.collection = None

    def _ensure_ready(self) -> None:
        """确保 Chroma 已就绪，否则抛出异常。"""
        if self.client is None or self.collection is None:
            raise RuntimeError("MemoryRAG 未初始化（chromadb 未安装或初始化失败）。请运行 pip install chromadb")

    def _get_embedding(self, text: str) -> List[float]:
        """Compute embedding using sentence-transformers (all-MiniLM-L6-v2)."""
        if self._embedding_fn is not None:
            return self._embedding_fn(text)
        try:
            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer("all-MiniLM-L6-v2", local_files_only=True)
            self._embedding_fn = lambda t: model.encode(t).tolist()
            return self._embedding_fn(text)
        except ImportError:
            raise ImportError("sentence-transformers is required. pip install sentence-transformers")
        except Exception as e:
            logger.error("Embedding failed: %s", e)
            raise

    def add_memory(self, content: str, emotion: str = "neutral", weight: float = 1.0) -> str:
        """Add a memory entry to the vector store."""
        memory_id = str(uuid.uuid4())
        embedding = self._get_embedding(content)
        timestamp = time.time()
        metadata: Dict[str, Any] = {"emotion": emotion, "weight": weight, "timestamp": timestamp}
        try:
            self.collection.add(ids=[memory_id], embeddings=[embedding], metadatas=[metadata], documents=[content])
            logger.info("Memory added: id=%s emotion=%s len=%d", memory_id[:8], emotion, len(content))
        except Exception as e:
            logger.exception("Failed to add memory: %s", e)
            raise
        return memory_id

    def search(self, query: str, n_results: int = 5, emotion_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Search memories by semantic similarity with time decay and weight."""
        query_embedding = self._get_embedding(query)
        where_filter: Optional[Dict[str, Any]] = None
        if emotion_filter:
            where_filter = {"emotion": emotion_filter}
        try:
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=n_results * 2,
                where=where_filter,
                include=["documents", "metadatas", "distances"],
            )
        except Exception as e:
            logger.exception("Memory search failed: %s", e)
            return []

        now = time.time()
        parsed: List[Dict[str, Any]] = []
        ids_raw = results.get("ids", [[]])[0]
        docs_raw = results.get("documents", [[]])[0]
        meta_raw = results.get("metadatas", [[]])[0]
        dists_raw = results.get("distances", [[]])[0]

        for idx, doc in enumerate(docs_raw):
            if idx >= len(ids_raw):
                break
            meta = meta_raw[idx] if idx < len(meta_raw) else {}
            dist = dists_raw[idx] if idx < len(dists_raw) else 1.0
            similarity = 1.0 - float(dist)
            timestamp = float(meta.get("timestamp", 0))
            weight = float(meta.get("weight", 1.0))
            age_hours = (now - timestamp) / 3600
            time_decay = max(0.3, 1.0 - (age_hours / (24 * 7)))

            # ── Phase 2: 情感极性权重调整 ──
            emotion_label = meta.get("emotion", "neutral")
            polarity_factor = 1.0
            if emotion_label in _NEGATIVE_EMOTIONS:
                polarity_factor = 0.5
            elif emotion_label in _POSITIVE_EMOTIONS:
                polarity_factor = 1.0
            else:
                polarity_factor = 1.0

            score = similarity * weight * time_decay * polarity_factor
            parsed.append({
                "id": ids_raw[idx] if idx < len(ids_raw) else "",
                "content": doc,
                "emotion": emotion_label,
                "weight": weight,
                "timestamp": timestamp,
                "similarity": round(score, 4),
            })
        parsed.sort(key=lambda x: x["similarity"], reverse=True)
        return parsed[:n_results]

    def update_weight(self, memory_id: str, delta: float) -> None:
        """Adjust the weight of a memory entry."""
        try:
            result = self.collection.get(ids=[memory_id])
            if not result["ids"]:
                logger.warning("Memory not found for weight update: %s", memory_id[:8])
                return
            meta = result["metadatas"][0]
            current_weight = float(meta.get("weight", 1.0))
            new_weight = max(0.1, current_weight + delta)
            meta["weight"] = new_weight
            self.collection.update(ids=[memory_id], metadatas=[meta])
            logger.info("Memory weight updated: id=%s %.2f → %.2f", memory_id[:8], current_weight, new_weight)
        except Exception as e:
            logger.exception("Failed to update memory weight: %s", e)

    def forget(self, memory_id: str) -> None:
        """Delete a memory entry."""
        try:
            self.collection.delete(ids=[memory_id])
            logger.info("Memory deleted: id=%s", memory_id[:8])
        except Exception as e:
            logger.exception("Failed to delete memory: %s", e)

    def get_recent_conversations(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most recent memories sorted by recency."""
        try:
            results = self.collection.get(
                limit=limit * 3,
                include=["documents", "metadatas"],
            )
        except Exception as e:
            logger.exception("Failed to get recent conversations: %s", e)
            return []
        parsed = []
        for idx, doc in enumerate(results.get("documents", [])):
            meta = results["metadatas"][idx] if idx < len(results["metadatas"]) else {}
            parsed.append({
                "id": results["ids"][idx] if idx < len(results["ids"]) else "",
                "content": doc,
                "emotion": meta.get("emotion", "neutral"),
                "weight": meta.get("weight", 1.0),
                "timestamp": meta.get("timestamp", 0),
            })
        parsed.sort(key=lambda x: x["timestamp"], reverse=True)
        return parsed[:limit]


# ═══════════════════════════════════════════════════════════════════
# 插件主类
# ═══════════════════════════════════════════════════════════════════

class EmotionRAGPlugin(PluginBase):
    """情绪分析与 RAG 记忆插件。

    通过 Hook 机制实现：
    - on_startup: 初始化 Chroma 记忆库 + 用户自适应规则
    - on_user_input: 关键词情感 fallback，缓存用户输入
    - on_llm_context: LLM 情感分析 + 自适应检索决策 + 记忆检索 + 构建上下文
    - on_llm_response: 存储对话到记忆库

    自适应规则学习：
    - 预设规则命中 → 正常检索
    - 规则未命中 → 启动学习模式（5次 LLM 判断）+ 道歉
    - 5 次结束后 → 自动分析特征词 → 更新规则文件
    """

    name = "emotion_rag"
    version = "2.0"  # 新增自适应规则学习

    def __init__(self) -> None:
        super().__init__()
        self.memory_rag: MemoryRAG | None = None
        self.rules_manager: UserRulesManager | None = None
        # Phase 3
        self.fer_analyzer: FERAnalyzer | None = None
        self.episodic_memory: EpisodicMemory | None = None
        self._character_knowledge: str = ""  # 角色剧本知识缓存
        # 轮次缓存
        self._last_user_input: str | None = None
        self._last_emotion: Dict[str, Any] | None = None
        self._last_reply: str | None = None
        # 检索决策记录（学习模式用）
        self._last_retrieval_mode: str = ""
        self._last_need_retrieval: bool = False
        # FER 缓存（跨轮次）
        self._last_face_emotion: Dict[str, Any] | None = None

    # ================================================================
    # Hook 实现
    # ================================================================

    def on_startup(self, app) -> None:
        """程序启动时初始化 Chroma 记忆库 + 用户规则 + Phase 3 模块。"""
        super().on_startup(app)
        try:
            self.memory_rag = MemoryRAG(persist_dir="./plugins_data/memory")
            self.rules_manager = UserRulesManager(data_dir="./plugins_data/emotion_rag")
            # Phase 3
            self.fer_analyzer = FERAnalyzer()
            self.episodic_memory = EpisodicMemory(db_path="./plugins_data/emotion_rag/episodic.db")
            self._load_character_knowledge()
            stats = self.rules_manager.get_stats()
            logger.info(
                "[emotion_rag] 插件就绪 — 情感分析 + Chroma 记忆 + 自适应规则 + Phase 3\n"
                "  触发词: %d 个 | 学习词: %d 个 | 学习模式: %s\n"
                "  FER: %s | Episodic: %s",
                stats["trigger_words"], stats["learned_words"], stats["learning_mode"],
                "可用" if self.fer_analyzer and self.fer_analyzer.detector else "不可用",
                "已连接" if self.episodic_memory else "未连接",
            )
        except Exception as e:
            logger.error("[emotion_rag] 初始化失败: %s", e)

    def _load_character_knowledge(self) -> None:
        """Phase 3: 加载角色剧本知识库。"""
        kb_path = "./knowledge_base/character_script.md"
        if os.path.exists(kb_path):
            try:
                with open(kb_path, "r", encoding="utf-8") as f:
                    self._character_knowledge = f.read()
                logger.info("[知识库] 角色剧本已加载: %d 字符", len(self._character_knowledge))
            except Exception as e:
                logger.warning("[知识库] 加载角色剧本失败: %s", e)
        else:
            logger.info("[知识库] 角色剧本未找到: %s（可选）", kb_path)

    def on_user_input(self, text: str) -> str | None:
        """用户输入到达时：缓存输入，关键词情感 fallback（快速不阻塞）。"""
        self._last_user_input = text
        self._last_emotion = _keyword_emotion_fallback(text)
        logger.info(
            "[emotion_rag] 关键词情感 fallback: %s (%.2f)",
            self._last_emotion.get("emotion", "neutral"),
            self._last_emotion.get("confidence", 0.5),
        )
        return None  # 不修改用户输入

    def on_llm_context(self, user_input: str) -> str:
        """LLM 请求前：情感分析 + 自适应检索决策 + 记忆检索 + 构建上下文。

        返回格式化的额外上下文字符串，会被拼接到 system prompt 中。
        """
        if not self.memory_rag or not self._last_user_input:
            return ""

        # ── 1. LLM 零样本情感分析（可选，覆盖关键词 fallback）──
        try:
            if self.app and hasattr(self.app, "llm_manager"):
                llm_emotion = _analyze_emotion_from_text(self._last_user_input, self.app.llm_manager)
                if llm_emotion.get("confidence", 0) > 0.5:
                    self._last_emotion = llm_emotion
                    logger.info(
                        "[emotion_rag] LLM 情感分析: %s (%.2f)",
                        llm_emotion.get("emotion", "neutral"),
                        llm_emotion.get("confidence", 0.5),
                    )
        except Exception as e:
            logger.warning("[emotion_rag] LLM 情感分析失败: %s", e)

        emotion = self._last_emotion or {}
        parts: list[str] = []

        # ── 2. 情绪信息 ──
        if emotion.get("emotion", "neutral") != "neutral":
            parts.append(
                f"【当前用户情绪】{emotion['emotion']}（{emotion.get('confidence', 0):.2f}）"
            )
            if emotion.get("cause"):
                parts.append(f"【情绪原因】{emotion['cause']}")

        # ── 3. 自适应检索决策 ──
        need_retrieval = False
        mode = "default"
        if self.rules_manager:
            need_retrieval, mode = self.rules_manager.decide_retrieval(self._last_user_input)
            self._last_retrieval_mode = mode
            self._last_need_retrieval = need_retrieval

            # 规则未命中 → 启动学习模式
            if mode == "default":
                self.rules_manager.start_learning_mode(self._last_user_input)
                # 道歉：通过上下文注入让 LLM 自然表达歉意
                parts.append(
                    "【系统提示】刚才可能漏检了相关记忆，本次已启用智能检索模式。"
                    "如果回复不够全面，请告诉我。"
                )
                # 强制本次使用 LLM 判断
                try:
                    if self.app and hasattr(self.app, "llm_manager"):
                        need_retrieval = self._llm_decide_retrieval(self._last_user_input, self.app.llm_manager)
                        mode = "llm"
                        self._last_need_retrieval = need_retrieval
                except Exception as e:
                    logger.warning("[emotion_rag] LLM 检索判断失败: %s", e)
                    need_retrieval = True
                    mode = "default"

            # 学习模式中使用 LLM 判断
            elif mode == "llm":
                try:
                    if self.app and hasattr(self.app, "llm_manager"):
                        need_retrieval = self._llm_decide_retrieval(self._last_user_input, self.app.llm_manager)
                        self._last_need_retrieval = need_retrieval
                        # 记录学习结果
                        self.rules_manager.record_learning_input(self._last_user_input, need_retrieval)
                except Exception as e:
                    logger.warning("[emotion_rag] LLM 检索判断失败: %s", e)
                    need_retrieval = True

        logger.info("[emotion_rag] 检索决策: %s (模式=%s)", need_retrieval, mode)

        # ── 4. 记忆检索（含多跳）──
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

                # 去重合并
                seen_content: set[str] = set()
                for m in memories:
                    if m["content"] not in seen_content:
                        memory_items.append(m)
                        seen_content.add(m["content"])
                for m in recent:
                    if m["content"] not in seen_content:
                        memory_items.append(m)
                        seen_content.add(m["content"])

                # ── 多跳检索 ──
                if len(memory_items) < 2 and memories:
                    hop_query = memories[0]["content"]
                    hop_results = self.memory_rag.search(
                        query=hop_query,
                        n_results=3,
                        emotion_filter=None,
                    )
                    for m in hop_results:
                        if m["content"] not in seen_content:
                            memory_items.append(m)
                            seen_content.add(m["content"])
                    logger.info(
                        "[emotion_rag] 多跳检索: 以 '%s' 为查询，补充 %d 条",
                        hop_query[:30], len(hop_results),
                    )

                memory_items = memory_items[:8]

                logger.info(
                    "[emotion_rag] 检索到 %d 条记忆 (语义 %d + 最近 %d)",
                    len(memory_items), len(memories), len(recent),
                )
            except Exception as e:
                logger.warning("[emotion_rag] 记忆检索失败: %s", e)

            if memory_items:
                lines = [f"- [{m.get('emotion', 'neutral')}] {m['content']}" for m in memory_items[:3]]
                parts.append("【相关记忆】\n" + "\n".join(lines))
        else:
            logger.info("[emotion_rag] 跳过检索 — 短问候或规则判定不需要")

        # ── 4. 回复风格 ──
        style = _emotion_to_style(emotion.get("emotion", ""))
        if style:
            parts.append(f"【回复风格】{style}")

        # ── 5. Phase 3: 角色剧本知识库 ──
        if self._character_knowledge:
            # 简单关键词匹配：从知识库中提取与当前情绪相关的段落
            kb_lines = self._character_knowledge.splitlines()
            relevant_lines = []
            for line in kb_lines:
                line_stripped = line.strip()
                if not line_stripped or line_stripped.startswith("#"):
                    continue
                # 检查是否与当前情绪或话题相关
                if any(kw in line_stripped for kw in [emotion.get("emotion", ""), "情绪", "回应", "风格"]):
                    relevant_lines.append(line_stripped)
            if relevant_lines:
                kb_context = "\n".join(relevant_lines[:5])
                parts.append(f"【角色剧本参考】\n{kb_context}")

        extra_context = "\n\n".join(parts)
        if extra_context:
            logger.info("[emotion_rag] 注入上下文 (%d 字符)", len(extra_context))
        return extra_context

    def _llm_decide_retrieval(self, text: str, llm: Any) -> bool:
        """使用 LLM 判断是否需要检索记忆。

        Args:
            text: 用户输入文本。
            llm: LLM 管理器。

        Returns:
            True 表示需要检索，False 表示不需要。
        """
        prompt = (
            "判断下面的用户输入是否需要检索历史记忆才能给出好的回复。\n"
            "只返回 JSON 格式：{\"need_retrieval\": true/false, \"reason\": \"简要原因\"}\n\n"
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

        return True  # 默认需要检索

    def on_llm_response(self, text: str) -> str | None:
        """LLM 回复后：将本轮对话存入 Chroma 记忆库，然后清空轮次缓存。

        Phase 2 增强：情感极性权重 —— 消极记忆降权，积极记忆提权。
        """
        self._last_reply = text

        if not self.memory_rag or not self._last_user_input:
            return None

        try:
            emotion_label = self._last_emotion.get("emotion", "neutral") if self._last_emotion else "neutral"

            # ── Phase 2: 情感极性权重 ──
            if emotion_label in _NEGATIVE_EMOTIONS:
                user_weight = 0.5
            elif emotion_label in _POSITIVE_EMOTIONS:
                user_weight = 1.5
            else:
                user_weight = 1.0

            self.memory_rag.add_memory(
                content=self._last_user_input,
                emotion=emotion_label,
                weight=user_weight,
            )

            if text:
                self.memory_rag.add_memory(
                    content=text,
                    emotion="neutral",
                    weight=0.7,
                )

            logger.info(
                "[emotion_rag] 记忆已入库: 用户[%s] (情感=%s 权重=%.1f) + 回复[%s]",
                self._last_user_input[:30], emotion_label, user_weight, text[:30],
            )

            # ── Phase 3: Episodic Memory 记录 ──
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

        # 清空轮次缓存
        self._last_user_input = None
        self._last_emotion = None
        self._last_reply = None
        self._last_retrieval_mode = ""
        self._last_need_retrieval = False
        self._last_face_emotion = None
        return None

    def on_tick(self, app) -> None:
        """Phase 3: 每轮末尾触发 FER 面部情绪分析（可选）。"""
        self._tick_count = getattr(self, "_tick_count", 0) + 1
        if self.fer_analyzer and self._tick_count % 10 == 0:
            try:
                result = self.fer_analyzer.analyze_from_camera()
                if result.get("available"):
                    self._last_face_emotion = result
                    logger.info(
                        "[FER] 面部情绪: %s (%.2f)",
                        result.get("emotion", "neutral"),
                        result.get("confidence", 0.5),
                    )
            except Exception as e:
                logger.debug("[FER] 本轮未分析: %s", e)

    def on_before_tts(self, text: str) -> str | None:
        """Phase 3: TTS 前清理文本（去掉系统标记等）。"""
        cleaned = re.sub(r"【.*?】", "", text)
        cleaned = cleaned.strip()
        if cleaned != text:
            logger.info("[emotion_rag] TTS 文本清理: %d -> %d 字符", len(text), len(cleaned))
            return cleaned
        return None

    def on_shutdown(self) -> None:
        """程序退出时清理资源。"""
        if self.memory_rag:
            self.memory_rag = None
        logger.info("[emotion_rag] 插件已关闭。")

    # ================================================================
    # 前端面板（展示规则状态 + 调试信息）
    # ================================================================

    def get_frontend_html(self) -> str:
        """返回前端调试面板，展示规则状态和记忆信息。"""
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
                零改动 GraphEngine，纯插件实现。
            </p>
        </div>
        """


# ═══════════════════════════════════════════════════════════════════
# Phase 3: FER 面部情绪分析（预留接口）
# ═══════════════════════════════════════════════════════════════════

class FERAnalyzer:
    """面部情绪分析器（预留接口，Phase 3 启用）。

    依赖：pip install fer
    需要摄像头权限，在 on_tick 或用户说话时触发拍照分析。

    当前实现为框架：如果 fer 未安装，优雅降级，不阻塞主流程。
    """

    def __init__(self) -> None:
        self.detector = None
        self._init_detector()

    def _init_detector(self) -> None:
        """尝试初始化 FER 检测器。"""
        try:
            from fer.fer import FER
            try:
                import tensorflow as tf  # noqa: F401
                self.detector = FER(mtcnn=True)
                logger.info("[FER] MTCNN 检测器初始化成功")
            except (ImportError, Exception) as e:
                logger.warning("[FER] MTCNN 不可用，回退到 OpenCV: %s", e)
                self.detector = FER(mtcnn=False)
                logger.info("[FER] OpenCV 检测器初始化成功")
        except ImportError:
            logger.warning("[FER] fer 库未安装，面部情绪分析不可用。pip install fer")
        except Exception as e:
            logger.warning("[FER] 初始化失败: %s", e)

    def analyze_from_camera(self) -> Dict[str, Any]:
        """从摄像头捕获一帧并分析情绪。

        Returns:
            {"emotion": str, "confidence": float, "available": bool}
        """
        if self.detector is None:
            return {"emotion": "neutral", "confidence": 0.5, "available": False}

        try:
            import cv2
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                logger.warning("[FER] 摄像头未打开")
                return {"emotion": "neutral", "confidence": 0.5, "available": False}

            ret, frame = cap.read()
            cap.release()
            if not ret:
                logger.warning("[FER] 无法读取摄像头帧")
                return {"emotion": "neutral", "confidence": 0.5, "available": False}

            # 保存临时文件供 FER 分析
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                cv2.imwrite(tmp.name, frame)
                tmp_path = tmp.name

            result = self.detector.detect_emotions(tmp_path)
            os.unlink(tmp_path)

            if not result:
                return {"emotion": "neutral", "confidence": 0.3, "available": True}

            emotions = result[0]["emotions"]
            emotion_name = max(emotions, key=emotions.get)
            confidence = float(emotions[emotion_name])

            # FER 标签映射到我们的标签
            _fer_map = {
                "angry": "angry", "disgust": "disgusted", "fear": "fearful",
                "happy": "happy", "sad": "sad", "surprise": "surprised",
                "neutral": "neutral",
            }
            mapped = _fer_map.get(emotion_name, "neutral")

            logger.info("[FER] 面部情绪: %s (%.2f)", mapped, confidence)
            return {"emotion": mapped, "confidence": confidence, "available": True}

        except Exception as e:
            logger.warning("[FER] 分析失败: %s", e)
            return {"emotion": "neutral", "confidence": 0.5, "available": False}


# ═══════════════════════════════════════════════════════════════════
# Phase 3: Episodic Memory（SQLite 时序事件）
# ═══════════════════════════════════════════════════════════════════

class EpisodicMemory:
    """SQLite 时序事件记忆。

    存储结构化的对话事件序列，支持：
    - 记录事件（时间、类型、内容、情绪）
    - 查询最近事件
    - 按时间段查询
    - 事件统计

    与 Chroma 语义记忆互补：
    - Chroma：语义检索，找"相关"的内容
    - Episodic：时序检索，找"最近"和"连续发生"的内容
    """

    def __init__(self, db_path: str = "./plugins_data/emotion_rag/episodic.db") -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """初始化 SQLite 数据库和事件表。"""
        import sqlite3
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp REAL NOT NULL,
                event_type TEXT NOT NULL,
                content TEXT NOT NULL,
                emotion TEXT DEFAULT 'neutral',
                weight REAL DEFAULT 1.0
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_time ON events(timestamp)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type)
        """)
        conn.commit()
        conn.close()
        logger.info("[Episodic] 数据库初始化: %s", self.db_path)

    def add_event(self, event_type: str, content: str, emotion: str = "neutral", weight: float = 1.0) -> int:
        """记录一个事件。

        Args:
            event_type: 事件类型，如 "user_input", "llm_response", "emotion_detected", "care_triggered"
            content: 事件内容
            emotion: 关联情绪
            weight: 事件权重

        Returns:
            事件 ID
        """
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO events (timestamp, event_type, content, emotion, weight) VALUES (?, ?, ?, ?, ?)",
            (time.time(), event_type, content, emotion, weight),
        )
        event_id = cursor.lastrowid
        conn.commit()
        conn.close()
        logger.info("[Episodic] 事件记录: id=%s type=%s emotion=%s", event_id, event_type, emotion)
        return event_id

    def get_recent_events(self, limit: int = 10) -> List[Dict[str, Any]]:
        """获取最近的事件列表。"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, timestamp, event_type, content, emotion, weight FROM events ORDER BY timestamp DESC LIMIT ?",
            (limit,),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": r[0], "timestamp": r[1], "event_type": r[2],
                "content": r[3], "emotion": r[4], "weight": r[5],
            }
            for r in rows
        ]

    def get_events_in_range(self, start_time: float, end_time: float) -> List[Dict[str, Any]]:
        """获取时间段内的事件。"""
        import sqlite3
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, timestamp, event_type, content, emotion, weight FROM events WHERE timestamp >= ? AND timestamp <= ? ORDER BY timestamp",
            (start_time, end_time),
        )
        rows = cursor.fetchall()
        conn.close()
        return [
            {
                "id": r[0], "timestamp": r[1], "event_type": r[2],
                "content": r[3], "emotion": r[4], "weight": r[5],
            }
            for r in rows
        ]

    def get_event_stats(self, hours: int = 24) -> Dict[str, Any]:
        """获取最近 N 小时的事件统计。"""
        import sqlite3
        cutoff = time.time() - hours * 3600
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM events WHERE timestamp >= ?", (cutoff,))
        total = cursor.fetchone()[0]

        cursor.execute("SELECT emotion, COUNT(*) FROM events WHERE timestamp >= ? GROUP BY emotion", (cutoff,))
        emotion_counts = {r[0]: r[1] for r in cursor.fetchall()}

        cursor.execute("SELECT event_type, COUNT(*) FROM events WHERE timestamp >= ? GROUP BY event_type", (cutoff,))
        type_counts = {r[0]: r[1] for r in cursor.fetchall()}

        conn.close()
        return {
            "total_events": total,
            "emotion_distribution": emotion_counts,
            "type_distribution": type_counts,
            "hours": hours,
        }

    def cleanup_old_events(self, days: int = 30) -> int:
        """清理超过 N 天的旧事件。"""
        import sqlite3
        cutoff = time.time() - days * 86400
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        logger.info("[Episodic] 清理 %d 天前事件: %d 条已删除", days, deleted)
        return deleted
