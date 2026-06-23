"""
memory_rag/episodic_memory.py — SQLite 时序事件记忆（从 emotion_rag_plugin.py 迁移）。

与 Chroma 语义记忆互补：
- Chroma：语义检索，找"相关"的内容
- Episodic：时序检索，找"最近"和"连续发生"的内容

不依赖任何情感分析模块，可独立使用。
"""
from __future__ import annotations

import os
import sqlite3
import time
from typing import Any, Dict, List

from log_config import get_logger

logger = get_logger("memory_rag.episodic")


class EpisodicMemory:
    """SQLite 时序事件记忆。

    存储结构化的对话事件序列，支持：
    - 记录事件（时间、类型、内容、情绪）
    - 查询最近事件
    - 按时间段查询
    - 事件统计
    """

    def __init__(self, db_path: str = "./plugins_data/emotion_rag/episodic.db") -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """初始化 SQLite 数据库和事件表。"""
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

    def add_event(
        self,
        event_type: str,
        content: str,
        emotion: str = "neutral",
        weight: float = 1.0,
    ) -> int:
        """记录一个事件。

        Args:
            event_type: 事件类型，如 "user_input", "llm_response", "emotion_detected", "care_triggered"
            content: 事件内容
            emotion: 关联情绪
            weight: 事件权重

        Returns:
            事件 ID
        """
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
                "id": r[0],
                "timestamp": r[1],
                "event_type": r[2],
                "content": r[3],
                "emotion": r[4],
                "weight": r[5],
            }
            for r in rows
        ]

    def get_events_in_range(self, start_time: float, end_time: float) -> List[Dict[str, Any]]:
        """获取时间段内的事件。"""
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
                "id": r[0],
                "timestamp": r[1],
                "event_type": r[2],
                "content": r[3],
                "emotion": r[4],
                "weight": r[5],
            }
            for r in rows
        ]

    def get_event_stats(self, hours: int = 24) -> Dict[str, Any]:
        """获取最近 N 小时的事件统计。"""
        cutoff = time.time() - hours * 3600
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM events WHERE timestamp >= ?", (cutoff,))
        total = cursor.fetchone()[0]

        cursor.execute(
            "SELECT emotion, COUNT(*) FROM events WHERE timestamp >= ? GROUP BY emotion",
            (cutoff,),
        )
        emotion_counts = {r[0]: r[1] for r in cursor.fetchall()}

        cursor.execute(
            "SELECT event_type, COUNT(*) FROM events WHERE timestamp >= ? GROUP BY event_type",
            (cutoff,),
        )
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
        cutoff = time.time() - days * 86400
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM events WHERE timestamp < ?", (cutoff,))
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
        logger.info("[Episodic] 清理 %d 天前事件: %d 条已删除", days, deleted)
        return deleted
