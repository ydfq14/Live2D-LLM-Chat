"""
日程管理插件 — 支持IOCP后台定时提醒

功能：
- 添加/查看/完成/删除日程任务
- 后台定时检查到期任务，自动提醒
- LangGraph工具调用支持
- 前端日历界面（预留）
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from plugin_base import PluginBase
from log_config import get_logger

logger = get_logger(__name__)


class Task:
    """任务数据结构"""

    def __init__(self, task_id: str, title: str, datetime_str: str, description: str = ""):
        self.id = task_id
        self.title = title
        self.datetime = datetime.fromisoformat(datetime_str)
        self.description = description
        self.status = "pending"  # pending / completed / missed
        self.created_at = datetime.now()
        self.completed_at = None
        self.reminder_sent = False

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "datetime": self.datetime.isoformat(),
            "description": self.description,
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "reminder_sent": self.reminder_sent,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        task = cls(
            task_id=data["id"],
            title=data["title"],
            datetime_str=data["datetime"],
            description=data.get("description", ""),
        )
        task.status = data.get("status", "pending")
        task.created_at = datetime.fromisoformat(data["created_at"])
        task.completed_at = (
            datetime.fromisoformat(data["completed_at"])
            if data.get("completed_at")
            else None
        )
        task.reminder_sent = data.get("reminder_sent", False)
        return task


class SchedulerPlugin(PluginBase):
    """日程管理插件"""

    name = "scheduler"
    version = "1.0"

    CHECK_INTERVAL = 30  # 每30秒检查一次

    def __init__(self):
        super().__init__()
        self._tasks: dict[str, Task] = {}
        self._data_dir: Path | None = None
        self._pending_reminder: str | None = None

    # ==================================================================
    #  生命周期
    # ==================================================================

    def on_startup(self, app) -> None:
        super().on_startup(app)
        self._data_dir = Path(self.get_data_dir())
        self._load_tasks()
        logger.info("[scheduler] 日程管理插件已启动，加载 %d 个任务", len(self._tasks))

    def on_register_background_tasks(self) -> list[dict]:
        return [
            {
                "task_id": "check_reminders",
                "interval": self.CHECK_INTERVAL,
                "callback": self._check_reminders,
                "description": "检查日程提醒",
                "immediate": True,
            }
        ]

    def on_task_complete(self, task_id: str, result: Any) -> None:
        if result and isinstance(result, str):
            self._pending_reminder = result
            logger.info("[scheduler] 待发送提醒: %s", result)

    def on_llm_context(self, user_input: str) -> str:
        """向LLM注入当前待办任务信息"""
        pending = [t for t in self._tasks.values() if t.status == "pending"]
        if not pending:
            return ""

        now = datetime.now()
        today_tasks = [t for t in pending if t.datetime.date() == now.date()]
        upcoming = [t for t in pending if t.datetime.date() > now.date()]

        parts = []
        if today_tasks:
            today_str = "、".join(
                f"{t.datetime.strftime('%H:%M')} {t.title}" for t in sorted(today_tasks, key=lambda x: x.datetime)
            )
            parts.append(f"今天的待办: {today_str}")
        if upcoming:
            up_str = "、".join(
                f"{t.datetime.strftime('%m-%d %H:%M')} {t.title}" for t in sorted(upcoming, key=lambda x: x.datetime)[:5]
            )
            parts.append(f"近期待办: {up_str}")

        return "【日程提醒】" + "; ".join(parts) if parts else ""

    # ==================================================================
    #  后台任务：检查提醒
    # ==================================================================

    def _check_reminders(self) -> str | None:
        """检查是否有到期任务需要提醒（后台任务回调）"""
        now = datetime.now()

        for task in list(self._tasks.values()):
            if task.status != "pending" or task.reminder_sent:
                continue

            # 在任务时间前后1分钟内
            time_diff = abs((task.datetime - now).total_seconds())
            if time_diff < 60:
                task.reminder_sent = True
                self._save_tasks()
                msg = f"提醒：{task.title}"
                if task.description:
                    msg += f"，{task.description}"
                logger.info("[scheduler] 触发提醒: %s", msg)
                return msg

            # 已过期超过1分钟的任务标记为missed
            if task.datetime < now - timedelta(minutes=1):
                task.status = "missed"
                self._save_tasks()

        return None

    # ==================================================================
    #  LangGraph 工具注册
    # ==================================================================

    def on_register_tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "add_task",
                    "description": "添加新的日程任务。当用户说'提醒我'、'添加日程'、'安排任务'等时调用。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "任务标题"},
                            "datetime": {
                                "type": "string",
                                "description": "任务日期时间，格式: YYYY-MM-DD HH:MM",
                            },
                            "description": {
                                "type": "string",
                                "description": "任务详细描述（可选）",
                            },
                        },
                        "required": ["title", "datetime"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_tasks",
                    "description": "查看某天的日程任务列表。当用户问'今天有什么安排'、'看看日程'等时调用。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "date": {
                                "type": "string",
                                "description": "日期，格式: YYYY-MM-DD（可选，默认今天）",
                            }
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "complete_task",
                    "description": "标记任务为已完成。当用户说'完成了'、'做完了'等时调用。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task_id": {"type": "string", "description": "任务ID"}
                        },
                        "required": ["task_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "delete_task",
                    "description": "删除一个日程任务。当用户说'取消任务'、'删除日程'等时调用。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "task_id": {"type": "string", "description": "任务ID"}
                        },
                        "required": ["task_id"],
                    },
                },
            },
        ]

    def on_execute_tool(self, tool_name: str, tool_args: dict) -> str:
        if tool_name == "add_task":
            return self._add_task(**tool_args)
        elif tool_name == "list_tasks":
            return self._list_tasks(**tool_args)
        elif tool_name == "complete_task":
            return self._complete_task(**tool_args)
        elif tool_name == "delete_task":
            return self._delete_task(**tool_args)
        return ""

    # ==================================================================
    #  工具实现
    # ==================================================================

    def _add_task(self, title: str, datetime: str, description: str = "") -> str:
        try:
            # 验证日期格式
            parsed = datetime_lib_parse(datetime)
        except Exception:
            return f"日期格式错误，请使用 YYYY-MM-DD HH:MM 格式，当前输入: {datetime}"

        task_id = uuid.uuid4().hex[:8]
        task = Task(task_id, title, parsed.isoformat(), description)
        self._tasks[task_id] = task
        self._save_tasks()

        logger.info("[scheduler] 添加任务: %s (%s) ID=%s", title, parsed, task_id)
        return f"已添加任务「{title}」，时间: {parsed.strftime('%Y-%m-%d %H:%M')}，任务ID: {task_id}"

    def _list_tasks(self, date: str = "") -> str:
        if date:
            try:
                target_date = datetime_lib_parse(date).date()
            except Exception:
                target_date = datetime.now().date()
        else:
            target_date = datetime.now().date()

        tasks_on_date = [
            t
            for t in self._tasks.values()
            if t.datetime.date() == target_date and t.status == "pending"
        ]

        if not tasks_on_date:
            return f"{target_date} 没有待办任务"

        result = f"{target_date} 的待办任务:\n"
        for t in sorted(tasks_on_date, key=lambda x: x.datetime):
            result += f"- [{t.id}] {t.datetime.strftime('%H:%M')} {t.title}"
            if t.description:
                result += f"（{t.description}）"
            result += "\n"

        return result.strip()

    def _complete_task(self, task_id: str) -> str:
        task = self._tasks.get(task_id)
        if not task:
            # 尝试模糊匹配
            for t in self._tasks.values():
                if task_id in t.title and t.status == "pending":
                    task = t
                    break

        if not task:
            return f"未找到任务: {task_id}"

        task.status = "completed"
        task.completed_at = datetime.now()
        self._save_tasks()

        logger.info("[scheduler] 完成任务: %s", task.title)
        return f"已完成任务「{task.title}」"

    def _delete_task(self, task_id: str) -> str:
        task = self._tasks.get(task_id)
        if not task:
            return f"未找到任务: {task_id}"

        title = task.title
        del self._tasks[task_id]
        self._save_tasks()

        logger.info("[scheduler] 删除任务: %s", title)
        return f"已删除任务「{title}」"

    # ==================================================================
    #  数据持久化
    # ==================================================================

    def _load_tasks(self):
        tasks_file = self._data_dir / "tasks.json"
        if not tasks_file.exists():
            self._tasks = {}
            return

        try:
            with open(tasks_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._tasks = {
                td["id"]: Task.from_dict(td) for td in data.get("tasks", [])
            }
        except Exception as e:
            logger.error("[scheduler] 加载任务失败: %s", e)
            self._tasks = {}

    def _save_tasks(self):
        tasks_file = self._data_dir / "tasks.json"
        try:
            with open(tasks_file, "w", encoding="utf-8") as f:
                json.dump(
                    {"tasks": [t.to_dict() for t in self._tasks.values()]},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            logger.error("[scheduler] 保存任务失败: %s", e)

    # ==================================================================
    #  前端（预留）
    # ==================================================================

    def get_frontend_html(self) -> str:
        return r"""
<style>
.scheduler-wrap { padding: 12px; }
.scheduler-title { font-size: 16px; font-weight: bold; color: #e94560; margin-bottom: 12px; }
.scheduler-empty { color: #888; text-align: center; margin-top: 40px; font-size: 13px; }
.scheduler-list { display: flex; flex-direction: column; gap: 8px; }
.scheduler-item {
    background: #16213e; border-radius: 8px; padding: 10px 12px;
    display: flex; justify-content: space-between; align-items: center;
}
.scheduler-item-info { flex: 1; }
.scheduler-item-time { color: #e94560; font-size: 12px; }
.scheduler-item-title { color: #eee; font-size: 13px; margin-top: 2px; }
.scheduler-item-actions button {
    background: none; border: 1px solid rgba(255,255,255,0.15);
    color: #aaa; border-radius: 4px; padding: 2px 8px; font-size: 11px; cursor: pointer;
}
.scheduler-item-actions button:hover { border-color: #e94560; color: #e94560; }
.scheduler-add-row {
    display: flex; gap: 6px; margin-top: 12px;
    border-top: 1px solid rgba(255,255,255,0.08); padding-top: 10px;
}
.scheduler-add-row input {
    flex: 1; padding: 6px 10px; border: 1px solid rgba(255,255,255,0.12);
    border-radius: 6px; background: #16213e; color: #eee; font-size: 12px; outline: none;
}
.scheduler-add-row button {
    padding: 6px 14px; border: none; border-radius: 6px;
    background: #e94560; color: #fff; font-size: 12px; cursor: pointer;
}
</style>
<div class="scheduler-wrap">
    <div class="scheduler-title">📅 日程管理</div>
    <div id="schedulerList" class="scheduler-list"><div class="scheduler-empty">加载中...</div></div>
    <div class="scheduler-add-row">
        <input id="schTitle" type="text" placeholder="任务标题" />
        <input id="schTime" type="datetime-local" />
        <button onclick="schAdd()">添加</button>
    </div>
</div>
<script>
function schRefresh() {
    var now = new Date();
    var dateStr = now.getFullYear() + '-' + String(now.getMonth()+1).padStart(2,'0') + '-' + String(now.getDate()).padStart(2,'0');
    pywebview.api.call_plugin('scheduler', '_list_tasks', dateStr).then(function(raw) {
        var el = document.getElementById('schedulerList');
        if (!raw || raw.indexOf('没有待办') >= 0 || !raw.trim()) {
            el.innerHTML = '<div class="scheduler-empty">今天没有待办任务<br>在下方添加新任务</div>';
            return;
        }
        var lines = raw.split('\n').filter(function(l){ return l.indexOf('- [') === 0; });
        if (!lines.length) { el.innerHTML = '<div class="scheduler-empty">今天没有待办任务</div>'; return; }
        var html = '';
        for (var i = 0; i < lines.length; i++) {
            var m = lines[i].match(/- \[(\w+)\]\s+(\S+)\s+(.*)/);
            if (m) {
                html += '<div class="scheduler-item"><div class="scheduler-item-info">'
                    + '<div class="scheduler-item-time">' + m[2] + '</div>'
                    + '<div class="scheduler-item-title">' + m[3] + '</div></div>'
                    + '<div class="scheduler-item-actions">'
                    + '<button onclick="schDone(\'' + m[1] + '\')">完成</button></div></div>';
            }
        }
        el.innerHTML = html || '<div class="scheduler-empty">今天没有待办任务</div>';
    }).catch(function(){});
}
function schAdd() {
    var title = document.getElementById('schTitle').value.trim();
    var time = document.getElementById('schTime').value;
    if (!title || !time) return;
    var dt = time.replace('T', ' ');
    pywebview.api.call_plugin('scheduler', '_add_task', title, dt, '').then(function() {
        document.getElementById('schTitle').value = '';
        document.getElementById('schTime').value = '';
        schRefresh();
    });
}
function schDone(id) {
    pywebview.api.call_plugin('scheduler', '_complete_task', id).then(function() { schRefresh(); });
}
setInterval(schRefresh, 5000);
schRefresh();
</script>
"""


# ==================================================================
#  辅助函数
# ==================================================================

def datetime_lib_parse(s: str) -> datetime:
    """解析日期时间字符串，支持多种格式"""
    s = s.strip()
    for fmt in (
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%m-%d %H:%M",
    ):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue

    # 如果只有时间，假设是今天
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            t = datetime.strptime(s, fmt)
            now = datetime.now()
            return now.replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        except ValueError:
            continue

    raise ValueError(f"无法解析日期时间: {s}")
