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
        self.last_reminder_time = None  # 上次提醒时间
        self.reminder_count = 0  # 提醒次数

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
            "last_reminder_time": self.last_reminder_time.isoformat() if self.last_reminder_time else None,
            "reminder_count": self.reminder_count,
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
        task.last_reminder_time = (
            datetime.fromisoformat(data["last_reminder_time"])
            if data.get("last_reminder_time")
            else None
        )
        task.reminder_count = data.get("reminder_count", 0)
        return task

    def should_remind(self) -> bool:
        """判断是否应该提醒（每5分钟提醒一次，直到完成）。"""
        if self.status != "pending":
            return False

        now = datetime.now()

        # 任务时间还没到
        if now < self.datetime:
            return False

        # 第一次提醒（任务时间到了）
        if self.last_reminder_time is None:
            return True

        # 距离上次提醒超过5分钟
        time_since_last = (now - self.last_reminder_time).total_seconds()
        return time_since_last >= 300  # 5分钟 = 300秒


class SchedulerPlugin(PluginBase):
    """日程管理插件"""

    name = "scheduler"
    version = "1.0"
    tab_icon = "📅"

    # 动态间隔策略：根据最近任务时间自动调整检查频率
    INTERVAL_NORMAL = 120      # 普通间隔：120秒
    INTERVAL_APPROACHING = 60  # 临近间隔：60秒（任务在5分钟内）
    INTERVAL_URGENT = 30       # 紧急间隔：30秒（任务在2分钟内）

    def __init__(self):
        super().__init__()
        self._tasks: dict[str, Task] = {}
        self._data_dir: Path | None = None
        self._app = None  # 保存 app 引用，用于访问 TTS 和 Live2D
        self._current_interval = self.INTERVAL_NORMAL  # 当前检查间隔

    # ==================================================================
    #  生命周期
    # ==================================================================

    def on_startup(self, app) -> None:
        super().on_startup(app)
        self._data_dir = Path(self.get_data_dir())
        self._load_tasks()
        self._app = app  # 保存 app 引用，用于访问 TTS 和 Live2D
        logger.info("[scheduler] 日程管理插件已启动，加载 %d 个任务", len(self._tasks))

    def on_register_background_tasks(self) -> list[dict]:
        return [
            {
                "task_id": "check_reminders",
                "interval": self._current_interval,
                "callback": self._check_reminders,
                "description": "检查日程提醒（动态间隔）",
                "immediate": True,
            }
        ]

    def on_task_complete(self, task_id: str, result: Any) -> None:
        if result and isinstance(result, str):
            logger.info("[scheduler] 触发语音提醒: %s", result)
            # 直接播放语音提醒
            self._play_voice_reminder(result)

    def _play_voice_reminder(self, text: str):
        """播放语音提醒（在插件内部完成）。"""
        try:
            # 获取 TTS 和 Live2D 管理器
            tts_manager = self._app.tts_manager if hasattr(self._app, 'tts_manager') else None
            live2d_manager = self._app.live2d_manager if hasattr(self._app, 'live2d_manager') else None

            if not tts_manager:
                logger.warning("[scheduler] TTS 管理器不可用，跳过语音提醒")
                return

            # 合成语音
            logger.info("[scheduler] 合成语音: %s", text[:50])
            audio_path = tts_manager.synthesize(text)

            if audio_path and live2d_manager:
                logger.info("[scheduler] 播放语音: %s", audio_path)
                live2d_manager.play_audio_and_print_mouth(audio_path)
                logger.info("[scheduler] 语音提醒播放完成")
            elif audio_path:
                logger.info("[scheduler] 语音合成完成，但 Live2D 不可用，无法播放")
            else:
                logger.warning("[scheduler] TTS 合成失败")

        except Exception as e:
            logger.error("[scheduler] 语音提醒播放失败: %s", e)

    def _calculate_next_interval(self) -> int:
        """根据最近任务时间动态计算下一次检查间隔。"""
        now = datetime.now()
        min_diff = float('inf')

        # 找到最近的待处理任务
        for task in self._tasks.values():
            if task.status != "pending":
                continue
            diff = (task.datetime - now).total_seconds()
            if diff > 0 and diff < min_diff:
                min_diff = diff

        # 根据最近任务时间动态调整间隔
        if min_diff <= 120:  # 2分钟内
            new_interval = self.INTERVAL_URGENT
            logger.debug("[scheduler] 动态间隔: 任务在 %.0f 秒内，使用 %d 秒间隔", min_diff, new_interval)
        elif min_diff <= 300:  # 5分钟内
            new_interval = self.INTERVAL_APPROACHING
            logger.debug("[scheduler] 动态间隔: 任务在 %.0f 秒内，使用 %d 秒间隔", min_diff, new_interval)
        else:
            new_interval = self.INTERVAL_NORMAL
            logger.debug("[scheduler] 动态间隔: 任务在 %.0f 秒后，使用 %d 秒间隔", min_diff, new_interval)

        return new_interval

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
        result = None

        for task in list(self._tasks.values()):
            if task.should_remind():
                # 更新提醒状态
                task.last_reminder_time = now
                task.reminder_sent = True
                task.reminder_count += 1
                self._save_tasks()

                # 生成提醒消息
                raw_msg = self._generate_reminder_message(task)
                logger.info("[scheduler] 触发提醒 (第%d次): %s", task.reminder_count, raw_msg)

                # 使用 LLM 润色提醒内容
                polished_msg = self._polish_reminder(raw_msg, task)
                result = polished_msg
                break  # 一次只触发一个提醒

            # 已过期超过1小时且未完成的任务标记为missed
            if task.status == "pending" and task.datetime < now - timedelta(hours=1):
                task.status = "missed"
                self._save_tasks()

        # 动态调整下一次检查间隔
        self._update_check_interval()

        return result

    def _generate_reminder_message(self, task: Task) -> str:
        """生成原始提醒消息。"""
        time_str = task.datetime.strftime("%H:%M")
        msg = f"提醒：现在是{time_str}，{task.title}"
        if task.description:
            msg += f"，{task.description}"
        if task.reminder_count > 1:
            msg += f"（这是第{task.reminder_count}次提醒，任务尚未完成）"
        return msg

    def _polish_reminder(self, raw_msg: str, task: Task) -> str:
        """使用 LLM 润色提醒内容，使其更自然亲切。"""
        try:
            # 尝试使用 app 的 LLM 进行润色
            if hasattr(self._app, 'llm_manager') and self._app.llm_manager:
                llm = self._app.llm_manager

                # 构建润色提示
                polish_prompt = f"""请将以下日程提醒内容润色为自然、亲切、口语化的语音提醒，适合用语音播报。
要求：
1. 语气友好、温暖
2. 简洁明了，不超过2句话
3. 如果是重复提醒，语气要更关切但不要啰嗦
4. 直接输出润色后的内容，不要解释

原始提醒内容：{raw_msg}"""

                # 调用 LLM 润色
                polished = llm.model_chat_completion([
                    {"role": "system", "content": "你是一个贴心的语音助手，负责将日程提醒润色为自然亲切的语音内容。"},
                    {"role": "user", "content": polish_prompt}
                ])

                if polished and len(polished) > 5:
                    logger.info("[scheduler] LLM 润色完成: %s", polished[:50])
                    return polished

        except Exception as e:
            logger.warning("[scheduler] LLM 润色失败，使用原始内容: %s", e)

        # 如果润色失败，返回原始消息
        return raw_msg

    def _update_check_interval(self):
        """根据最近任务时间动态更新检查间隔。"""
        try:
            new_interval = self._calculate_next_interval()

            # 只有当间隔变化时才更新
            if new_interval != self._current_interval:
                old_interval = self._current_interval
                self._current_interval = new_interval

                # 使用 IOCP 调度器动态更新间隔
                scheduler = self.get_scheduler()
                if scheduler and hasattr(scheduler, 'tasks') and 'scheduler_check_reminders' in scheduler.tasks:
                    scheduler.tasks['scheduler_check_reminders'].interval = new_interval
                    logger.info("[scheduler] 动态调整检查间隔: %d秒 → %d秒", old_interval, new_interval)
        except Exception as e:
            logger.debug("[scheduler] 更新间隔失败: %s", e)

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
.scheduler-title {
    font-size: 16px;
    font-weight: bold;
    color: var(--neon-cyan, #00f0ff);
    margin-bottom: 12px;
    text-shadow: 0 0 10px var(--glow-cyan, rgba(0, 240, 255, 0.4));
}
.scheduler-empty {
    color: var(--text-muted, #7a7a9e);
    text-align: center;
    margin-top: 40px;
    font-size: 13px;
}
.scheduler-list { display: flex; flex-direction: column; gap: 8px; }
.scheduler-item {
    background: var(--surface-1, #111128);
    border-radius: 8px;
    padding: 10px 12px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.06));
    transition: all var(--transition-normal, 0.3s cubic-bezier(0.4, 0, 0.2, 1));
    position: relative;
    overflow: hidden;
}
.scheduler-item::before {
    content: '';
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: linear-gradient(90deg, transparent, var(--neon-cyan, #00f0ff), transparent);
    opacity: 0;
    transition: opacity var(--transition-normal, 0.3s cubic-bezier(0.4, 0, 0.2, 1));
}
.scheduler-item:hover {
    border-color: var(--border-glow, rgba(0, 240, 255, 0.2));
    box-shadow: var(--shadow-card, 0 4px 20px rgba(0, 0, 0, 0.4), 0 0 1px rgba(0, 240, 255, 0.1));
    transform: translateY(-1px);
}
.scheduler-item:hover::before { opacity: 1; }
.scheduler-item-info { flex: 1; }
.scheduler-item-time {
    color: var(--neon-cyan, #00f0ff);
    font-size: 12px;
}
.scheduler-item-title {
    color: var(--text, #e8e8f0);
    font-size: 13px;
    margin-top: 2px;
}
.scheduler-item-actions button {
    background: none;
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.06));
    color: var(--text-muted, #7a7a9e);
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    cursor: pointer;
    transition: all var(--transition-fast, 0.15s ease);
}
.scheduler-item-actions button:hover {
    border-color: var(--neon-cyan, #00f0ff);
    color: var(--neon-cyan, #00f0ff);
    box-shadow: 0 0 8px rgba(0, 240, 255, 0.3);
}
.scheduler-add-row {
    display: flex;
    gap: 6px;
    margin-top: 12px;
    border-top: 1px solid var(--border-glow, rgba(0, 240, 255, 0.2));
    padding-top: 10px;
}
.scheduler-add-row input {
    flex: 1;
    padding: 6px 10px;
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.06));
    border-radius: 6px;
    background: var(--surface-2, #1a1a3a);
    color: var(--text, #e8e8f0);
    font-size: 12px;
    outline: none;
    transition: all var(--transition-normal, 0.3s cubic-bezier(0.4, 0, 0.2, 1));
}
.scheduler-add-row input:focus {
    border-color: var(--neon-cyan, #00f0ff);
    box-shadow: 0 0 0 2px rgba(0, 240, 255, 0.15);
}
.scheduler-add-row button {
    padding: 6px 14px;
    border: none;
    border-radius: 6px;
    background: var(--gradient-accent, linear-gradient(135deg, #e94560, #b94eff));
    color: #fff;
    font-size: 12px;
    cursor: pointer;
    transition: all var(--transition-fast, 0.15s ease);
    box-shadow: 0 2px 8px rgba(233, 69, 96, 0.3);
}
.scheduler-add-row button:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 12px rgba(233, 69, 96, 0.5);
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
    <div class="scheduler-add-row" style="margin-top: 6px;">
        <input id="schDesc" type="text" placeholder="任务内容（可选）" style="flex: 1;" />
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
                var taskInfo = m[3];
                // 检查是否有任务描述（格式：标题（描述））
                var descMatch = taskInfo.match(/^(.+?)（(.+?)）$/);
                var title = descMatch ? descMatch[1] : taskInfo;
                var desc = descMatch ? descMatch[2] : '';

                html += '<div class="scheduler-item"><div class="scheduler-item-info">'
                    + '<div class="scheduler-item-time">' + m[2] + '</div>'
                    + '<div class="scheduler-item-title">' + title + '</div>';
                if (desc) {
                    html += '<div style="color:#888; font-size:11px; margin-top:2px;">' + desc + '</div>';
                }
                html += '</div><div class="scheduler-item-actions">'
                    + '<button onclick="schDone(\'' + m[1] + '\')">完成</button></div></div>';
            }
        }
        el.innerHTML = html || '<div class="scheduler-empty">今天没有待办任务</div>';
    }).catch(function(){});
}
function schAdd() {
    var title = document.getElementById('schTitle').value.trim();
    var time = document.getElementById('schTime').value;
    var desc = document.getElementById('schDesc').value.trim();
    if (!title || !time) return;
    var dt = time.replace('T', ' ');
    pywebview.api.call_plugin('scheduler', '_add_task', title, dt, desc).then(function() {
        document.getElementById('schTitle').value = '';
        document.getElementById('schTime').value = '';
        document.getElementById('schDesc').value = '';
        schRefresh();
    });
}
function schDone(id) {
    pywebview.api.call_plugin('scheduler', '_complete_task', id).then(function() { schRefresh(); });
}

// 等待 pywebview 就绪后再初始化
if (window.pywebview) {{
    // pywebview 已经注入，直接初始化
    console.log('[scheduler] pywebview 已就绪，初始化');
    setInterval(schRefresh, 5000);
    schRefresh();
}} else {{
    // 等待 pywebviewready 事件
    console.log('[scheduler] 等待 pywebview 就绪...');
    window.addEventListener('pywebviewready', function() {{
        console.log('[scheduler] pywebview 已就绪，初始化');
        setInterval(schRefresh, 5000);
        schRefresh();
    }});
}}
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
