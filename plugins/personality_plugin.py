# -*- coding: utf-8 -*-
"""
性格定制插件 (PersonalityPlugin)

功能：
- 支持多套性格配置（角色档案），每套包含 LLM 人设 + TTS 音色
- 切换性格时自动替换 system prompt 并切换 TTS 音色
- 前端 HTML 面板展示性格卡片，一键切换

配合 profiles/*.yaml 配置文件使用。
"""
from __future__ import annotations

import json
import os

import yaml
from typing import TYPE_CHECKING

from plugin_base import PluginBase
from log_config import get_logger

if TYPE_CHECKING:
    from main import MainManager

logger = get_logger(__name__)


class PersonalityPlugin(PluginBase):
    """
    性格定制插件 —— 多角色档案 + TTS 音色联动

    Hook 说明：
    - on_startup: 加载所有 YAML 配置文件，应用默认性格
    - on_llm_context: 每轮对话注入当前性格的 system prompt
    - on_before_tts: TTS 前预留接口（可用于语气词替换）
    - get_frontend_html: 返回前端性格选择面板 HTML
    - switch_personality: 供前端 JS 调用的切换接口
    """

    name = "personality"       # 插件唯一标识，前端 call_plugin 使用此名称
    version = "1.0"
    tab_icon = "\U0001f3ad"    # 前端 Tab 图标（🎭）

    def __init__(self):
        super().__init__()
        # 存储所有已加载的性格配置，key=文件名(不含后缀)
        self._profiles: dict = {}
        # 当前激活的性格名称
        self.current: str = ""
        #用于TTS文本梳理
        self._last_clean: str = ""

    # ═══════════════ 启动初始化 ═══════════════

    def on_startup(self, app: MainManager) -> None:
        """
        程序启动时自动调用。

        从 profiles/ 目录加载所有 YAML 配置文件，
        应用默认性格（catgirl），没有则用第一个。
        """
        self.app = app
        self._profiles = self._load_all()

        # 如果 profiles 目录为空或没有配置文件，使用内置默认性格兜底
        if not self._profiles:
            logger.warning("[personality] 未找到性格配置文件，使用内置默认性格")
            self._profiles["catgirl"] = self._default_profile()

        # 默认使用 catgirl，不存在则取第一个
        default_key = "catgirl" if "catgirl" in self._profiles else list(self._profiles.keys())[0]
        self._apply(default_key)

        # 打印就绪日志
        names = [p["name"] for p in self._profiles.values()]
        logger.info(
            "[personality] 插件就绪 — 已加载 %d 套性格: %s",
            len(self._profiles), names,
        )

    # ═══════════════ 配置加载 ═══════════════

    def _get_profiles_dir(self) -> str:
        """获取性格配置文件目录的绝对路径"""
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")

    def _load_all(self) -> dict:
        """
        扫描 profiles/ 目录，加载所有 .yaml / .yml 配置文件。

        返回格式：{"catgirl": {...}, "tutor": {...}, ...}
        其中 key 是文件名（不含后缀）。
        """
        profiles = {}
        profiles_dir = self._get_profiles_dir()

        if not os.path.isdir(profiles_dir):
            logger.warning("[personality] profiles 目录不存在: %s", profiles_dir)
            return profiles

        for filename in sorted(os.listdir(profiles_dir)):
            if not filename.endswith((".yaml", ".yml")):
                continue

            filepath = os.path.join(profiles_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    profile = yaml.safe_load(f)
                key = filename.rsplit(".", 1)[0]  # catgirl.yaml → catgirl
                profiles[key] = profile
                logger.info("[personality] 已加载性格配置: %s (%s)",
                            profile.get("name", key), filename)
            except Exception as e:
                logger.error("[personality] 加载配置文件失败 %s: %s", filename, e)

        return profiles

    def _default_profile(self) -> dict:
        """内置默认性格配置，当 profiles/ 目录为空时使用"""
        return {
            "name": "温柔猫娘",
            "voice": "冰糖",
            "greeting": "你好呀～今天想聊什么呢？",
            "style_tags": ["可爱", "治愈", "软萌"],
            "system_prompt": (
                "【核心人设】\n"
                "你是一位知识渊博、性格温柔的猫娘学习陪伴助手，"
                "是用户桌面端的虚拟伙伴。\n\n"
                "【输出规则】\n"
                "- 禁止输出任何格式符号（#、*、-、【】等）\n"
                "- 语气自然亲和，适度带猫娘的软萌感\n"
                "- 回复精炼，单轮不超过3个句子"
            ),
        }

    # ═══════════════ 性格应用与切换 ═══════════════

    def _apply(self, name: str) -> None:
        """
        应用指定性格，做两件事：
        1. 替换 LLM 对话上下文中的 system prompt
        2. 切换 TTS 音色（云端用 set_voice，本地用 set_voice_sample）
        """
        profile = self._profiles.get(name)
        if not profile:
            logger.error("[personality] 性格不存在: %s", name)
            return

        # 第一步：替换 LLM 的 system prompt
        if self.app and self.app.llm_manager:
            self.app.llm_manager.conversation[0]["content"] = profile["system_prompt"]

        # 第二步：切换 TTS 音色
        if self.app and self.app.tts_manager:
            try:
                if self.app.tts_manager.mode == "cloud":
                    # 云端 MIMO TTS：直接传音色名称
                    self.app.tts_manager.set_voice(profile.get("voice", "mimo_default"))
                else:
                    # 本地 CosyVoice：替换音色样本文件
                    wav = profile.get("prompt_wav", "")
                    txt = profile.get("prompt_text", "")
                    if wav and txt:
                        self.app.tts_manager.set_voice_sample(wav, txt)
            except Exception as e:
                logger.warning("[personality] TTS 音色切换失败: %s", e)

        self.current = name
        logger.info("[personality] 已切换性格: %s (音色: %s)",
                    profile["name"], profile.get("voice", "默认"))

    def switch_personality(self, name: str) -> str:
        """
        前端切换性格的入口方法。

        前端通过 pywebview 桥接调用：
            pywebview.api.call_plugin('personality', 'switch_personality', 'tutor')

        返回 JSON 字符串：
            {"ok": true, "name": "知性老师", "voice": "白桦"}
            或 {"error": "性格 tutor 不存在"}
        """
        if name not in self._profiles:
            return json.dumps({"error": f"性格 {name} 不存在"}, ensure_ascii=False)

        self._apply(name)
        profile = self._profiles[name]
        return json.dumps({
            "ok": True,
            "name": profile["name"],
            "voice": profile.get("voice", ""),
        }, ensure_ascii=False)

    # ═══════════════ Hook 方法 ═══════════════

    def on_llm_context(self, user_input: str) -> str:
        """
        【核心 Hook】每轮对话前调用。

        graph_engine 的 gather_context 节点会广播此事件，
        返回值作为 system 消息拼到 LLM 输入的最前面。
        """
        profile = self._profiles.get(self.current)
        if not profile:
            return ""
        return f"【当前角色设定】\n{profile['system_prompt']}"



    def on_before_tts(self, text: str) -> str | None:
        """
        TTS 合成前调用，清理文本中不适合朗读的内容：
        - 删除中文括号内的动作描述：（尾巴摇了摇）
        - 删除英文括号内的动作描述：(ears twitching)
        - 保留其他文本不变，只影响 TTS 朗读，不影响聊天框显示
        """
        import re
        # 删除中文括号及其内容：（动作描述）
        text = re.sub(r'（[^）]*?）', '', text)
        # 删除英文括号及其内容：(action description)
        text = re.sub(r'\([^)]*?\)', '', text)
        # 清理多余空格
        text = re.sub(r'\s+', ' ', text).strip()
        # 如果清理后为空或没有变化，返回 None 表示不做修改
        return text if text != self._last_clean else None


    # ═══════════════ 前端 HTML 面板 ═══════════════

    def get_frontend_html(self) -> str:
        """
        返回性格选择面板的 HTML。

        嵌入到 pywebview 前端窗口的 Tab 页中，
        显示所有性格的卡片，点击卡片触发切换。
        """
        if not self._profiles:
            return "<p style='color:#aaa;'>未加载性格配置</p>"

        # 逐个生成性格卡片
        cards = ""
        for key, profile in self._profiles.items():
            # 当前激活的性格高亮
            active_class = "active" if key == self.current else ""

            # 风格标签
            tags_html = ""
            for tag in profile.get("style_tags", []):
                tags_html += f"<span class=\"tag\">{tag}</span>"

            # 欢迎语
            greeting = profile.get("greeting", "")

            cards += f"""
            <div class="p-card {active_class}"
                 onclick="switchPersonality('{key}')">
                <div class="p-header">
                    <span class="p-name">{profile['name']}</span>
                    <span class="p-voice">\U0001f3a4 {profile.get('voice', '默认')}</span>
                </div>
                <div class="p-tags">{tags_html}</div>
                <div class="p-greet">{greeting}</div>
            </div>"""

        # 完整 HTML + CSS + JS
        return f"""
        <style>
        .p-card {{
            padding: 14px;
            margin: 10px 0;
            background: #1a1a3a;
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 10px;
            cursor: pointer;
            transition: all 0.25s ease;
        }}
        .p-card:hover {{
            border-color: #00f0ff;
            background: #222250;
        }}
        .p-card.active {{
            border-color: #00f0ff;
            box-shadow: 0 0 15px rgba(0,240,255,0.3);
            background: #1a1a4a;
        }}
        .p-header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }}
        .p-name {{
            font-size: 16px;
            font-weight: 600;
            color: #e8e8f0;
        }}
        .p-voice {{
            font-size: 13px;
            color: #00f0ff;
        }}
        .p-tags {{ margin-bottom: 6px; }}
        .tag {{
            display: inline-block;
            padding: 2px 10px;
            margin: 2px 4px 2px 0;
            background: #0f3460;
            border-radius: 12px;
            font-size: 11px;
            color: #7a7a9e;
        }}
        .p-card.active .tag {{
            background: #1a5080;
            color: #00f0ff;
        }}
        .p-greet {{
            font-size: 12px;
            color: #7a7a9e;
            font-style: italic;
        }}
        </style>

        <h3 style="color:#00f0ff; margin-bottom:16px;">\U0001f3ad 选择性格</h3>

        <div id="p-list">
            {cards}
        </div>

        <script>
        function switchPersonality(name) {{
            document.querySelectorAll('.p-card').forEach(function(c) {{
                c.classList.remove('active');
            }});
            pywebview.api.call_plugin('personality', 'switch_personality', name)
                .then(function(r) {{
                    var result = JSON.parse(r);
                    if (result.ok) {{
                        console.log('性格已切换: ' + result.name);
                    }}
                }});
        }}
        </script>"""