
"""
轻量助手特性集（不包含 RAG/规则/Episodic/FER 实现）

说明：
- 仅包含：提醒管理（可回调）、娱乐与学习小功能、活动建议、轻量情绪检测（关键字）。
- 严格避免重复实现 emotion_rag_plugin.py 中的 MemoryRAG / UserRulesManager / EpisodicMemory / FER。
- 若运行时检测到已加载的 emotion_rag 插件，会优先复用该插件的能力（memory_rag / rules_manager / FER）。
- RemindersManager 不会默认联动 TTS/Live2D，提供 on_trigger 回调，回调中可调用 app.tts_manager、app.live2d_manager 等。
"""
from __future__ import annotations

import os
import json
import time
import threading
import datetime
import random
import importlib
from typing import Optional, Callable, Any
from log_config import get_logger

logger = get_logger(__name__)


class RemindersManager:
    """持久化提醒管理器（轻量），不自动与 LLM 绑定。

    用法：
      rm = RemindersManager(storage_dir, on_trigger=callable)
      rm.add(time_iso, text)
      rm.start(interval=30)
      rm.stop()
    on_trigger 回调签名：fn(reminder_dict) -> None
    """

    def __init__(self, storage_dir: str, on_trigger: Optional[Callable[[dict], None]] = None):
        os.makedirs(storage_dir, exist_ok=True)
        self.path = os.path.join(storage_dir, "reminders.json")
        if not os.path.exists(self.path):
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
        self.on_trigger = on_trigger
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def _load(self) -> list:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("加载提醒失败：%s", e)
            return []

    def _save(self, items: list):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(items, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning("保存提醒失败：%s", e)

    def add(self, time_iso: str, text: str) -> dict:
        """添加提醒。time_iso 支持 ISO 或 'YYYY-MM-DD HH:MM' 格式。"""
        try:
            try:
                dt = datetime.datetime.fromisoformat(time_iso)
            except Exception:
                dt = datetime.datetime.strptime(time_iso, "%Y-%m-%d %H:%M")
        except Exception:
            raise ValueError("时间格式错误，请使用 ISO 或 'YYYY-MM-DD HH:MM' 格式")

        items = self._load()
        rid = int(time.time() * 1000) + random.randint(0, 999)
        rem = {"id": rid, "time": dt.isoformat(), "text": text, "created_at": datetime.datetime.now().isoformat(), "done": False}
        items.append(rem)
        self._save(items)
        logger.info("已添加提醒: %s @ %s", text, rem["time"])
        return rem

    def list(self) -> list:
        return self._load()

    def remove(self, rid: int) -> bool:
        items = self._load()
        new = [r for r in items if r.get("id") != rid]
        if len(new) == len(items):
            return False
        self._save(new)
        return True

    def _loop(self, interval: int):
        while not self._stop.is_set():
            try:
                now = datetime.datetime.now()
                items = self._load()
                changed = False
                for r in items:
                    if r.get("done"):
                        continue
                    try:
                        due = datetime.datetime.fromisoformat(r["time"])
                    except Exception:
                        continue
                    if now >= due:
                        logger.info("提醒触发: %s", r)
                        try:
                            if callable(self.on_trigger):
                                self.on_trigger(r)
                        except Exception as e:
                            logger.exception("on_trigger 回调失败: %s", e)
                        r["done"] = True
                        r["triggered_at"] = now.isoformat()
                        changed = True
                if changed:
                    self._save(items)
            except Exception as e:
                logger.debug("提醒线程错误: %s", e)
            time.sleep(interval)

    def start(self, interval: int = 30):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, args=(interval,), daemon=True, name="reminder-loop")
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=1)


class AssistantFeatures:
    """轻量助手功能集合（不包含 RAG/规则/episodic/FER 实现）。

    责任边界：
      - 本模块提供：reminders（轻量）、joke/quiz/studyplan、activity suggestion、轻量情绪检测（关键词）。
      - RAG / UserRules / Episodic / FER 均应由 plugins/emotion_rag_plugin.py 提供；本模块会自动检测并复用该插件实例（如果存在）。
    """

    def __init__(self, app: Optional[Any] = None, data_dir: Optional[str] = None):
        # app: 可选 MainManager（含 registry、llm_manager、tts_manager 等）
        self.app = app
        base_dir = data_dir or os.path.join(os.path.dirname(os.path.abspath(__file__)), ".assistant_tmp")
        os.makedirs(base_dir, exist_ok=True)
        self.data_dir = base_dir

        # RemindersManager 实例（独立，不会自动注入到 LLM，除非传入回调）
        self.reminders = RemindersManager(self.data_dir, on_trigger=self._default_on_reminder)

        # 轻量娱乐/学习素材
        self._jokes = [
            "你知道猫最拿手的乐器是什么吗？是喵键琴，因为每次按键都很喵。",
            "为什么书总是很冷？因为有很多封面（风）哈哈。",
            "如果时间会发热，那就是咖啡时间了。"
        ]
        self._activities = [
            "做个五分钟的深呼吸放松一下",
            "听一首你喜欢的轻音乐",
            "读一段短短的诗或者一则小故事",
            "做五道简单的数学题锻炼大脑",
            "和我聊聊天，说说今天的心情"
        ]

    # ---------------------------
    # 与 emotion_rag_plugin 的协作（非重复实现）
    # ---------------------------
    def _find_emotion_rag_plugin(self):
        """尝试从 app.registry 获取 emotion_rag 插件实例，否则尝试导入模块引用以便调用其工具函数（只读复用）。"""
        try:
            if self.app and hasattr(self.app, "registry"):
                plugin = self.app.registry.get("emotion_rag")
                if plugin:
                    return plugin
        except Exception:
            pass
        # 作为回退，尝试导入插件模块（不会实例化插件）
        try:
            mod = importlib.import_module("emotion_rag_plugin")
            return getattr(mod, None)
        except Exception:
            return None

    def get_memory_rag(self):
        """如果 emotion_rag 插件可用，返回其 memory_rag 对象（或 None）。"""
        p = self._find_emotion_rag_plugin()
        if not p:
            return None
        return getattr(p, "memory_rag", None)

    def get_rules_manager(self):
        p = self._find_emotion_rag_plugin()
        if not p:
            return None
        return getattr(p, "rules_manager", None)

    def get_episodic_memory(self):
        p = self._find_emotion_rag_plugin()
        if not p:
            return None
        return getattr(p, "episodic_memory", None)

    def get_fer_analyzer(self):
        p = self._find_emotion_rag_plugin()
        if not p:
            return None
        return getattr(p, "fer_analyzer", None)

    # ---------------------------
    # 情绪检测（轻量关键词优先，若 emotion_rag 可用优先复用其函数）
    # ---------------------------
    def detect_emotion(self, text: str) -> dict:
        """轻量情绪检测：优先复用 emotion_rag 模块的函数，否则使用本地关键词启发式判断。"""
        if not text:
            return {"emotion": "neutral", "confidence": 0.5, "cause": ""}

        # 尝试复用 emotion_rag 模块级回退函数（如果存在）
        try:
            mod = importlib.import_module("emotion_rag_plugin")
            if hasattr(mod, "_keyword_emotion_fallback"):
                res = mod._keyword_emotion_fallback(text)
                if res:
                    return res
        except Exception:
            # 忽略导入错误，回退到本地实现
            pass

        # 本地关键词启发式
        lower = text.lower()
        pos = ["开心", "高兴", "喜欢", "love", "happy"]
        neg = ["难过", "伤心", "生气", "失落", "sad", "angry"]
        score = 0.0
        for w in pos:
            if w in lower:
                score += 1.0
        for w in neg:
            if w in lower:
                score -= 1.0
        if score > 0:
            return {"emotion": "happy", "confidence": min(1.0, score / 3.0), "cause": ""}
        if score < 0:
            return {"emotion": "sad", "confidence": min(1.0, abs(score) / 3.0), "cause": ""}
        return {"emotion": "neutral", "confidence": 0.5, "cause": ""}

    # ---------------------------
    # Reminders API：包装 RemindersManager
    # ---------------------------
    def add_reminder(self, time_iso: str, text: str) -> dict:
        return self.reminders.add(time_iso, text)

    def list_reminders(self) -> list:
        return self.reminders.list()

    def remove_reminder(self, rid: int) -> bool:
        return self.reminders.remove(rid)

    def start_reminders(self, interval: int = 30):
        self.reminders.start(interval=interval)

    def stop_reminders(self):
        self.reminders.stop()

    def _default_on_reminder(self, rem: dict):
        """默认提醒触发行为：把提醒追加到 LLM conversation（若可用），并记录日志。"""
        text = f"提醒：{rem.get('text')}"
        logger.info("默认提醒回调: %s", text)
        try:
            if self.app and hasattr(self.app, "llm_manager") and getattr(self.app.llm_manager, "conversation", None) is not None:
                self.app.llm_manager.conversation.append({"role": "assistant", "content": text})
        except Exception as e:
            logger.debug("追加提醒到 LLM.conversation 失败: %s", e)

    # ---------------------------
    # 娱乐/助理小功能
    # ---------------------------
    def tell_joke(self) -> str:
        return random.choice(self._jokes)

    def start_quiz(self, n: int = 3) -> dict:
        pool = [
            ("中国的首都是哪里？", "北京"),
            ("太阳系中最大的行星是？", "木星"),
            ("水的化学式是什么？", "H2O"),
            ("二加二等于多少？", "4"),
            ("人类用来呼吸的主要气体是？", "氧气"),
        ]
        selected = random.sample(pool, k=min(n, len(pool)))
        questions = []
        answers = {}
        for i, (q, a) in enumerate(selected):
            qid = int(time.time() * 1000) + i
            questions.append({"id": qid, "q": q})
            answers[qid] = a
        # 可选：把游戏提示写入 conversation 以便前端显示
        try:
            if self.app and hasattr(self.app, "llm_manager"):
                self.app.llm_manager.conversation.append({"role": "assistant", "content": "我们来玩个小测验，我会问你几个简单问题，准备好就告诉我开始。"})
        except Exception:
            pass
        return {"questions": questions, "answers": answers}

    def prepare_study_plan(self, topic: str, minutes: int = 30) -> str:
        minutes = max(5, min(180, int(minutes)))
        return f"对于{topic}，建议分成三个阶段：先用{int(minutes*0.3)}分钟预习关键概念，再用{int(minutes*0.5)}分钟做集中练习或做题，最后用{int(minutes*0.2)}分钟复盘并整理笔记。完成后和我说完成，我会帮你回顾。"

    def suggest_activity(self, mood_hint: str = "", category: str = "mixed") -> str:
        base = list(self._activities)
        if category == "study":
            base = [
                "做二十分钟番茄钟，专注学习一个小任务",
                "复习今天学到的要点，写两句总结",
                "看一个与学习相关的短视频并做笔记"
            ]
        elif category == "relax":
            base = [
                "闭眼做三分钟深呼吸，放松肩颈",
                "听一首轻音乐，慢慢呼吸",
                "站起来伸展五分钟活动筋骨"
            ]
        elif category == "entertain":
            base = [
                "看一段短视频放松一下",
                "听一首节奏感强的歌，动一动身体",
                "和我说个笑话，换换心情"
            ]

        if "累" in mood_hint or "疲" in mood_hint:
            return "休息一下，做个短暂的伸展或小憩"
        if "焦虑" in mood_hint or "紧张" in mood_hint:
            return "尝试三分钟的呼吸放松，我在这里陪你"
        return random.choice(base)