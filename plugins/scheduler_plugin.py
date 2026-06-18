from __future__ import annotations
import json
import os
import uuid
import datetime
from typing import Any
from plugin_base import PluginBase

class SchedulerPlugin(PluginBase):
    name = "scheduler"
    version = "0.1"

    def __init__(self) -> None:
        super().__init__()
        self._events: list[dict[str, Any]] = []
        self._data_file: str | None = None

    def on_startup(self, app):
        super().on_startup(app)
        self._data_file = os.path.join(self.get_data_dir(), "events.json")
        try:
            if os.path.exists(self._data_file):
                with open(self._data_file, "r", encoding="utf-8") as f:
                    self._events = json.load(f)
            else:
                self._events = []
        except Exception:
            self._events = []

    def _save(self):
        if not self._data_file:
            return
        try:
            with open(self._data_file, "w", encoding="utf-8") as f:
                json.dump(self._events, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # 注册工具：create_event / list_events / delete_event (供 LLM 调用)
    def on_register_tools(self) -> list[dict]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "create_event",
                    "description": "创建日程事件。参数: title, time_iso(ISO8601), note(可选)。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "time_iso": {"type": "string", "description": "例如 2026-06-17T15:00:00"},
                            "note": {"type": "string"},
                        },
                        "required": ["title", "time_iso"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_events",
                    "description": "列出未来的日程事件。",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "delete_event",
                    "description": "删除事件，按 id 删除。",
                    "parameters": {
                        "type": "object",
                        "properties": {"id": {"type": "string"}},
                        "required": ["id"],
                    },
                },
            },
        ]

    # 执行工具（供 GraphEngine 调用）
    def on_execute_tool(self, tool_name: str, tool_args: dict) -> str:
        now = datetime.datetime.now().isoformat()
        if tool_name == "create_event":
            title = str(tool_args.get("title", "")).strip()
            time_iso = str(tool_args.get("time_iso", "")).strip()
            note = str(tool_args.get("note", "")).strip()
            try:
                dt = datetime.datetime.fromisoformat(time_iso)
            except Exception:
                return f"[失败] 无效时间格式: {time_iso}"
            evt = {
                "id": uuid.uuid4().hex,
                "title": title,
                "time_iso": dt.isoformat(),
                "note": note,
                "created_at": now,
                "notified": False,
            }
            self._events.append(evt)
            self._save()
            return f"已创建事件: {title} @ {dt.isoformat()} (id={evt['id']})"

        if tool_name == "list_events":
            fut = []
            try:
                now_dt = datetime.datetime.now()
                for e in sorted(self._events, key=lambda x: x.get("time_iso", "")):
                    dt = datetime.datetime.fromisoformat(e["time_iso"])
                    if dt >= now_dt:
                        fut.append(e)
            except Exception:
                fut = self._events
            if not fut:
                return "当前没有未来事件。"
            lines = []
            for e in fut:
                lines.append(f"- {e['id']}: {e['title']} @ {e['time_iso']} 备注: {e.get('note','')}")
            return "\n".join(lines)

        if tool_name == "delete_event":
            eid = str(tool_args.get("id", "")).strip()
            before = len(self._events)
            self._events = [e for e in self._events if e.get("id") != eid]
            if len(self._events) < before:
                self._save()
                return f"已删除事件 {eid}"
            return f"未找到事件 {eid}"

        return ""

    # ========== UI 专用方法（供 UIShell.call_plugin 调用） ==========
    def create_event_from_ui(self, title: str, time_iso: str, note: str = "") -> str:
        """由前端直接调用，参数均为字符串。"""
        now = datetime.datetime.now().isoformat()
        title = (title or "").strip()
        time_iso = (time_iso or "").strip()
        note = (note or "").strip()
        try:
            dt = datetime.datetime.fromisoformat(time_iso)
        except Exception:
            return f"[失败] 无效时间格式: {time_iso}"
        evt = {
            "id": uuid.uuid4().hex,
            "title": title,
            "time_iso": dt.isoformat(),
            "note": note,
            "created_at": now,
            "notified": False,
        }
        self._events.append(evt)
        self._save()
        return f"已创建事件: {title} @ {dt.isoformat()} (id={evt['id']})"

    def list_events_ui(self) -> str:
        """供前端调用，返回可展示的事件列表字符串。"""
        fut = []
        try:
            now_dt = datetime.datetime.now()
            for e in sorted(self._events, key=lambda x: x.get("time_iso", "")):
                dt = datetime.datetime.fromisoformat(e["time_iso"])
                if dt >= now_dt:
                    fut.append(e)
        except Exception:
            fut = self._events
        if not fut:
            return "当前没有未来事件。"
        lines = []
        for e in fut:
            lines.append(f"- {e['id']}: {e['title']} @ {e['time_iso']} 备注: {e.get('note','')}")
        return "\n".join(lines)

    def delete_event_from_ui(self, eid: str) -> str:
        eid = (eid or "").strip()
        before = len(self._events)
        self._events = [e for e in self._events if e.get("id") != eid]
        if len(self._events) < before:
            self._save()
            return f"已删除事件 {eid}"
        return f"未找到事件 {eid}"

    # 定时检查（主循环每轮末尾被调用）
    def on_tick(self, app):
        now = datetime.datetime.now()
        changed = False
        for e in self._events:
            if e.get("notified"):
                continue
            try:
                evt_time = datetime.datetime.fromisoformat(e["time_iso"])
            except Exception:
                continue
            # 到期（或过期）则提醒
            if evt_time <= now:
                e["notified"] = True
                changed = True
                text = f"提醒：{e.get('title')}，现在是 {now.strftime('%Y-%m-%d %H:%M')}。{e.get('note','')}"
                # 尝试使用主程序的 TTS + Live2D 播放提醒（容错）
                try:
                    audio = self.app.tts_manager.synthesize(text)
                    self.app.live2d_manager.play_audio_and_print_mouth(audio)
                except Exception:
                    # 如果播放失败，只把提醒写入 LLM 会话，便于下一轮被用户看到
                    try:
                        self.app.llm_manager.conversation.append({"role": "system", "content": text})
                    except Exception:
                        pass
        if changed:
            self._save()

    def get_frontend_html(self) -> str:
        # 前端面板：表单创建事件 / 列表 / 删除
        return """
<div style="padding:12px;font-family:sans-serif;">
  <h3>日程管理</h3>
  <div style="margin-bottom:8px;">
    <label>标题<br><input id="evt_title" style="width:100%"/></label>
  </div>
  <div style="margin-bottom:8px;">
    <label>时间 (ISO 例如 2026-06-17T15:00:00)<br><input id="evt_time" style="width:100%"/></label>
  </div>
  <div style="margin-bottom:8px;">
    <label>备注<br><input id="evt_note" style="width:100%"/></label>
  </div>
  <div style="margin-bottom:12px;">
    <button onclick="createEvent()">创建事件</button>
    <button onclick="listEvents()">列出事件</button>
  </div>
  <div style="margin-bottom:8px;">
    <label>删除事件 ID<br><input id="del_id" style="width:80%"/><button onclick="deleteEvent()">删除</button></label>
  </div>
  <pre id="output" style="background:#0f1724;color:#eee;padding:8px;border-radius:6px;min-height:80px;white-space:pre-wrap;"></pre>

<script>
function setOutput(txt){ document.getElementById('output').innerText = txt; }

function createEvent(){
  const title = document.getElementById('evt_title').value;
  const time_iso = document.getElementById('evt_time').value;
  const note = document.getElementById('evt_note').value;
  // 调用 UIShell 提供的 JS API -> Python 插件方法 create_event_from_ui
  window.pywebview.api.call_plugin('scheduler','create_event_from_ui', title, time_iso, note)
    .then(result => setOutput(result))
    .catch(err => setOutput('错误: '+err));
}

function listEvents(){
  window.pywebview.api.call_plugin('scheduler','list_events_ui')
    .then(result => setOutput(result))
    .catch(err => setOutput('错误: '+err));
}

function deleteEvent(){
  const id = document.getElementById('del_id').value;
  window.pywebview.api.call_plugin('scheduler','delete_event_from_ui', id)
    .then(result => setOutput(result))
    .catch(err => setOutput('错误: '+err));
}
</script>
"""