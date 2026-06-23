from __future__ import annotations
from typing import Any
import json
from plugin_base import PluginBase
from assistant_features import AssistantFeatures
from log_config import get_logger

logger = get_logger(__name__)


class AssistantToolsPlugin(PluginBase):
    name = "assistant_tools"
    version = "1.0"

    def on_startup(self, app):
        super().on_startup(app)
        # 复用 LLMManager 已挂载的 features（如果存在），否则创建自己的实例并挂载到 app.llm_manager.features
        if hasattr(app, "llm_manager") and getattr(app.llm_manager, "features", None):
            self.features = app.llm_manager.features
        else:
            # 使用插件独立数据目录存储提醒等
            data_dir = self.get_data_dir()
            self.features = AssistantFeatures(app.llm_manager if hasattr(app, "llm_manager") else None, data_dir=data_dir)
            # 若 app.llm_manager 可用，挂载到其中，便于全局复用
            if hasattr(app, "llm_manager"):
                app.llm_manager.features = self.features

        # 启动提醒后台线程（如果尚未启动）
        self.features.start_reminders()
        logger.info("AssistantToolsPlugin 启动完成，features 已就绪")

    def on_register_tools(self) -> list[dict]:
        """
        返回 OpenAI function-calling 风格的工具列表，GraphEngine 可将其传入模型供模型选择调用。
        每个工具都定义 name、description、parameters（JSON schema）。
        """
        tools = [
            {
                "type": "function",
                "function": {
                    "name": "add_reminder",
                    "description": "添加提醒，参数包含 time (ISO or YYYY-MM-DD HH:MM) 与 text（提醒内容）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "time": {"type": "string", "description": "ISO 或 'YYYY-MM-DD HH:MM'"},
                            "text": {"type": "string", "description": "提醒文本"}
                        },
                        "required": ["time", "text"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "list_reminders",
                    "description": "列出所有提醒，无参数",
                    "parameters": {"type": "object", "properties": {}, "required": []}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "remove_reminder",
                    "description": "删除提醒，参数为提醒 id",
                    "parameters": {
                        "type": "object",
                        "properties": {"id": {"type": "integer"}},
                        "required": ["id"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "tell_joke",
                    "description": "讲一句简短笑话，无参数",
                    "parameters": {"type": "object", "properties": {}, "required": []}
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "start_quiz",
                    "description": "开启一个简短问答测验，可选参数 n 表示题目数量",
                    "parameters": {
                        "type": "object",
                        "properties": {"n": {"type": "integer", "default": 3}},
                        "required": []
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "prepare_study_plan",
                    "description": "根据主题和时长生成简短学习计划",
                    "parameters": {
                        "type": "object",
                        "properties": {"topic": {"type": "string"}, "minutes": {"type": "integer", "default": 30}},
                        "required": ["topic"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "detect_emotion",
                    "description": "对文本做简单情绪检测，返回 label/score/explain",
                    "parameters": {
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "suggest_activity",
                    "description": "基于心情提示和类别建议一条活动，可选 category: study|relax|entertain|mixed",
                    "parameters": {
                        "type": "object",
                        "properties": {"mood_hint": {"type": "string"}, "category": {"type": "string", "enum": ["study", "relax", "entertain", "mixed"]}},
                        "required": []
                    }
                }
            }
        ]
        return tools

    def on_execute_tool(self, tool_name: str, tool_args: dict) -> str:
        """
        GraphEngine 调用工具时执行此方法，返回字符串结果（或JSON序列化字符串）。
        """
        try:
            if tool_name == "add_reminder":
                rem = self.features.add_reminder(tool_args.get("time", ""), tool_args.get("text", ""))
                return json.dumps(rem, ensure_ascii=False)
            if tool_name == "list_reminders":
                rems = self.features.list_reminders()
                return json.dumps(rems, ensure_ascii=False)
            if tool_name == "remove_reminder":
                ok = self.features.remove_reminder(int(tool_args.get("id", 0)))
                return json.dumps({"ok": bool(ok)})
            if tool_name == "tell_joke":
                return self.features.tell_joke()
            if tool_name == "start_quiz":
                res = self.features.start_quiz(int(tool_args.get("n", 3)))
                return json.dumps(res, ensure_ascii=False)
            if tool_name == "prepare_study_plan":
                topic = tool_args.get("topic", "")
                minutes = int(tool_args.get("minutes", 30))
                return self.features.prepare_study_plan(topic, minutes)
            if tool_name == "detect_emotion":
                text = tool_args.get("text", "")
                return json.dumps(self.features.detect_emotion(text), ensure_ascii=False)
            if tool_name == "suggest_activity":
                mood_hint = tool_args.get("mood_hint", "")
                category = tool_args.get("category", "mixed")
                return self.features.suggest_activity(mood_hint=mood_hint, category=category)
            return ""
        except Exception as e:
            logger.exception("执行工具失败: %s %s", tool_name, e)
            return f"error: {e}"