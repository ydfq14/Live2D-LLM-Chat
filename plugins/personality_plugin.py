# -*- coding: utf-8 -*-
"""
性格定制插件 (PersonalityPlugin)

功能：
- 支持多套性格配置（角色档案），每套包含 LLM 人设 + TTS 音色
- 切换性格时自动替换 system prompt 并切换 TTS 音色
- TTS 合成前自动清理括号内的动作描述，避免被朗读
- 前端 HTML 面板展示性格卡片，点击一键切换
- 切换后自动重置对话历史，防止旧性格的说话风格带偏 LLM

配合 profiles/*.yaml 配置文件使用。
"""
from __future__ import annotations

import json
import os

import yaml
from typing import TYPE_CHECKING

from plugin_base import PluginBase
from log_config import get_logger

# TYPE_CHECKING 在运行时为 False，仅在 IDE 静态检查时导入主管理器
# 避免循环导入 main.py 的 MainManager
if TYPE_CHECKING:
    from main import MainManager

# 获取当前模块的日志记录器，日志自动标注 [personality]
logger = get_logger(__name__)


class PersonalityPlugin(PluginBase):
    """
    性格定制插件 —— 多角色档案 + TTS 音色联动

    通过 Hook 机制嵌入系统，不修改任何现有代码：

    on_startup:
      加载 profiles/*.yaml 中所有性格配置，
      应用默认性格（catgirl 或第一个配置）。

    on_llm_context:
      每轮对话前被 gather_context 节点触发，
      将当前性格的 system_prompt 注入到 LLM 上下文。

    on_before_tts:
      TTS 合成前被 prepare_tts 节点触发，
      删除回复中括号内的动作描述（如（尾巴摇了摇）），
      避免 TTS 将这些描述读出来。

    get_frontend_html:
      返回性格选择面板的 HTML+CSS+JS，
      嵌入到 pywebview 前端的 Tab 页中。

    switch_personality:
      供前端 JS 通过 pywebview.api.call_plugin 调用的切换接口，
      返回 JSON {"ok": true, "name": "知性老师", "voice": "白桦"}。
    """

    name = "personality"       # 插件唯一标识，call_plugin('personality', ...) 使用此名称
    version = "1.0"
    tab_icon = "\U0001f3ad"    # 前端 Tab 图标：🎭

    def __init__(self):
        super().__init__()
        # 性格配置缓存字典：key=文件名(不含后缀)，value=YAML解析后的 dict
        self._profiles: dict = {}
        # 当前激活的性格名称，对应 self._profiles 中的一个 key
        self.current: str = ""
        # TTS 清洗用缓存：记录上一次清洗后的文本，用于判断是否需要重复清洗
        self._last_clean: str = ""

    # ═══════════════════════════════════════════════
    #  启动初始化：加载配置、应用默认性格
    # ═══════════════════════════════════════════════

    def on_startup(self, app: MainManager) -> None:
        """程序启动时由 PluginRegistry 广播调用。

        1. 保存 MainManager 引用到 self.app（供 _apply 访问 LLM / TTS 管理器）
        2. 加载 profiles/ 目录下的所有 YAML 配置文件
        3. 应用默认性格（优先 catgirl，不存在则取第一个）
        """
        self.app = app
        self._profiles = self._load_all()

        # 如果 profiles/ 目录为空或没有 YAML 文件，使用内置默认性格兜底
        if not self._profiles:
            logger.warning("[personality] 未找到性格配置文件，使用内置默认性格")
            self._profiles["catgirl"] = self._default_profile()

        # 确定默认性格：优先使用 catgirl，不存在则取加载的第一个配置
        default_key = "catgirl" if "catgirl" in self._profiles else list(self._profiles.keys())[0]
        self._apply(default_key)

        # 打印就绪日志，列出所有已加载的性格名称
        names = [p["name"] for p in self._profiles.values()]
        logger.info(
            "[personality] 插件就绪 — 已加载 %d 套性格: %s",
            len(self._profiles), names,
        )

    # ═══════════════════════════════════════════════
    #  配置加载：读取 profiles/*.yaml
    # ═══════════════════════════════════════════════

    def _get_profiles_dir(self) -> str:
        """获取性格配置文件目录的绝对路径（本文件同级的 profiles/ 目录）。"""
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")

    def _load_all(self) -> dict:
        """扫描 profiles/ 目录，加载所有 .yaml / .yml 配置文件。

        每个文件经过 yaml.safe_load 解析后，以文件名（不含后缀）为 key 存入字典。
        加载失败的文件会被跳过并记录错误日志，不影响其他配置文件的加载。

        Returns:
            {"catgirl": {...}, "tutor": {...}, "companion": {...}}
        """
        profiles = {}
        profiles_dir = self._get_profiles_dir()

        # 目录不存在时直接返回空字典，后续由 on_startup 使用默认性格
        if not os.path.isdir(profiles_dir):
            logger.warning("[personality] profiles 目录不存在: %s", profiles_dir)
            return profiles

        # 遍历目录下的所有 YAML 文件，按文件名排序保证加载顺序稳定
        for filename in sorted(os.listdir(profiles_dir)):
            if not filename.endswith((".yaml", ".yml")):
                continue

            filepath = os.path.join(profiles_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    profile = yaml.safe_load(f)
                # 用文件名（不含扩展名）作为配置的 key
                # 例如 catgirl.yaml → key="catgirl"
                key = filename.rsplit(".", 1)[0]
                profiles[key] = profile
                logger.info("[personality] 已加载性格配置: %s (%s)",
                            profile.get("name", key), filename)
            except Exception as e:
                # 单个文件加载失败不中断整体流程，记录错误后继续加载下一个
                logger.error("[personality] 加载配置文件失败 %s: %s", filename, e)

        return profiles

    def _default_profile(self) -> dict:
        """内置默认性格配置（当 profiles/ 目录为空时的兜底方案）。"""
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

    # ═══════════════════════════════════════════════
    #  性格应用与切换
    # ═══════════════════════════════════════════════

    def _apply(self, name: str) -> None:
        """应用指定性格，执行三个操作：

        1. 替换 LLM 的 system prompt（核心——改变 AI 的角色和说话风格）
        2. 清空旧的对话历史（防止旧性格的回复带偏 LLM）
        3. 切换 TTS 音色（云端用 set_voice，本地用 set_voice_sample）

        Args:
            name: 性格 key，对应 self._profiles 中的一个键
        """
        profile = self._profiles.get(name)
        if not profile:
            logger.error("[personality] 性格不存在: %s", name)
            return

        # ══════════════════════════════════
        #  第一步：替换 LLM 的 system prompt
        # ══════════════════════════════════
        if self.app and self.app.llm_manager:
            # 获取性格对应的 system_prompt，不存在则终止切换
            sys_prompt = profile.get("system_prompt")
            if not sys_prompt:
                logger.error("[personality] 配置文件 %s 缺少 system_prompt", name)
                return

            # 替换对话上下文的第 0 条消息（system 角色，即核心人设）
            self.app.llm_manager.conversation[0]["content"] = sys_prompt

            # 清空第 0 条之后的所有历史消息和对话摘要
            # 因为旧的多轮回复是旧性格的说话方式，会干扰 LLM 对新性格的理解
            old_msgs = self.app.llm_manager.conversation[1:]
            self.app.llm_manager.conversation = self.app.llm_manager.conversation[:1]
            self.app.llm_manager.conversation_summary = ""
            self.app.llm_manager.user_message_count = 0
            logger.debug("[personality] 已清除旧的对话历史 (%d 条消息)", len(old_msgs))

            # 添加一条角色切换提示消息，让 LLM 知道自己已经切换了性格
            self.app.llm_manager.conversation.append({
                "role": "assistant",
                "content": f"好的，已切换到{profile.get('name', name)}。"
            })

        # ════════════════════════════════════
        #  第二步：切换 TTS 音色
        # ════════════════════════════════════
        if self.app and self.app.tts_manager:
            try:
                if self.app.tts_manager.mode == "cloud":
                    # 云端 MIMO TTS：通过音色名称直接切换
                    self.app.tts_manager.set_voice(profile.get("voice", "mimo_default"))
                else:
                    # 本地 CosyVoice：替换 3 秒极速复刻的样本文件
                    wav = profile.get("prompt_wav", "")
                    txt = profile.get("prompt_text", "")
                    if wav and txt:
                        self.app.tts_manager.set_voice_sample(wav, txt)
            except Exception as e:
                # TTS 切换失败不影响 LLM 切换，只记录警告
                logger.warning("[personality] TTS 音色切换失败: %s", e)

        # 更新当前激活的性格名称
        self.current = name
        logger.info("[personality] 已切换性格: %s (音色: %s)",
                    profile.get("name", name), profile.get("voice", "默认"))

    # ═══════════════════════════════════════════════
    #  Hook 方法
    # ═══════════════════════════════════════════════

    def on_llm_context(self, user_input: str) -> str:
        """【核心 Hook】每轮对话前调用。

        由 graph_engine 的 gather_context 节点广播触发，
        返回值会作为一条 system 消息拼到 LLM 输入的最前面，
        确保 LLM 始终知道当前应该以什么性格说话。

        Returns:
            包含当前性格 system_prompt 的字符串，拼入 extra_context。
            如果当前性格无效则返回空字符串。
        """
        profile = self._profiles.get(self.current)
        if not profile:
            return ""
        sys_prompt = profile.get("system_prompt", "")
        if not sys_prompt:
            return ""
        return f"【当前角色设定】\n{sys_prompt}"

    def on_before_tts(self, text: str) -> str | None:
        """TTS 合成前调用，清理文本中不适合朗读的内容。

        由 graph_engine 的 prepare_tts 节点广播触发。

        清理规则：
        - 删除中文括号内的动作描述：（尾巴摇了摇）（歪着头想了想）
        - 删除英文括号内的动作描述：(ears twitching)
        - 将连续的空白字符压缩为单个空格
        - 清理后的文本只用于 TTS 朗读，不影响聊天框的原始显示

        Args:
            text: LLM 生成的原始回复文本，可能包含动作描述

        Returns:
            清理后的纯文本（用于 TTS 朗读），
            如果清理后为空则返回 None（TTS 将跳过本次合成）。
        """
        import re
        # 删除中文括号及其内容：（动作描述）
        text = re.sub(r'（[^）]*?）', '', text)
        # 删除英文括号及其内容：(action description)
        text = re.sub(r'\([^)]*?\)', '', text)
        # 将多个空格/换行压缩为单个空格
        text = re.sub(r'\s+', ' ', text).strip()
        # 缓存本次清洗结果，供后续判断是否需要重复清洗
        self._last_clean = text
        # 清洗后为空字符串时返回 None，通知上层跳过 TTS 合成
        return text if text else None

    # ═══════════════════════════════════════════════
    #  前端调用接口
    # ═══════════════════════════════════════════════

    def switch_personality(self, name: str) -> str:
        """供前端 JS 调用的性格切换入口。

        前端通过 pywebview 桥接调用：
            pywebview.api.call_plugin('personality', 'switch_personality', 'tutor')

        内部调用 _apply 执行实际的切换逻辑。

        Returns:
            JSON 字符串：
            {"ok": true, "name": "知性老师", "voice": "白桦"}  成功
            {"error": "性格 tutor 不存在"}                    失败
        """
        # 校验：性格名称必须在已加载的配置中
        if name not in self._profiles:
            return json.dumps({"error": f"性格 {name} 不存在"}, ensure_ascii=False)

        # 执行切换（替换 prompt + 清空历史 + 切音色）
        self._apply(name)
        p = self._profiles[name]

        # 返回成功信息，前端 JS 根据此响应更新 UI
        return json.dumps({
            "ok": True,
            "name": p.get("name", name),
            "voice": p.get("voice", ""),
        }, ensure_ascii=False)

    def get_current_personality(self) -> str:
        """返回当前性格信息（供前端轮询或初始化时调用）。"""
        p = self._profiles.get(self.current, {})
        return json.dumps({
            "name": p.get("name", "默认"),
            "voice": p.get("voice", ""),
        }, ensure_ascii=False)

    # ═══════════════════════════════════════════════
    #  前端 HTML 面板
    # ═══════════════════════════════════════════════

    def get_frontend_html(self) -> str:
        """生成性格选择面板的完整 HTML（含 CSS 和 JS）。

        嵌入到 pywebview 前端的 Tab 页中，包含：
        - 状态头：显示当前性格名称和使用的音色
        - 卡片列表：每个性格一张卡片，点击触发切换
        - JS 逻辑：切换后自动更新状态头和卡片高亮

        Returns:
            HTML 字符串，被 ui_shell 嵌入到前端窗口。
        """
        if not self._profiles:
            return "<p style='color:#aaa;'>未加载性格配置</p>"

        # 获取当前性格信息用于状态头显示
        cur = self._profiles.get(self.current, {})
        cur_name = cur.get("name", "未知")
        cur_voice = cur.get("voice", "默认")

        # ── 逐个生成性格卡片 ──
        cards = ""
        for key, profile in self._profiles.items():
            # 当前激活的性格高亮显示
            active_class = "active" if key == self.current else ""

            # 生成风格标签（如「可爱」「治愈」）
            tags_html = ""
            for tag in profile.get("style_tags", []):
                tags_html += f"<span class=\"tag\">{tag}</span>"

            greeting = profile.get("greeting", "")

            # 每张卡片包含：名字、音色、标签、欢迎语
            # data-key 属性供 JS 在切换后定位当前卡片
            cards += f"""
            <div class="p-card {active_class}" data-key="{key}"
                 onclick="switchPersonality('{key}')">
                <div class="p-header">
                    <span class="p-name">{profile['name']}</span>
                    <span class="p-voice">\U0001f3a4 {profile.get('voice', '默认')}</span>
                </div>
                <div class="p-tags">{tags_html}</div>
                <div class="p-greet">{greeting}</div>
            </div>"""

        # 返回完整的 HTML + CSS + JS
        return f"""
        <style>
        /* ── 状态栏：显示当前性格名称和音色 ── */
        .sbar{{
            display:flex;align-items:center;justify-content:space-between;
            padding:12px 16px;margin-bottom:16px;
            background:linear-gradient(135deg,#0f3460,#1a1a4a);
            border:1px solid rgba(0,240,255,0.2);border-radius:10px;
        }}
        .sl{{font-size:12px;color:#7a7a9e;}}
        .sn{{font-size:20px;font-weight:700;color:#00f0ff;text-shadow:0 0 10px rgba(0,240,255,0.3);}}
        .sv{{font-size:13px;color:#7a7a9e;text-align:right;}}
        .sv span{{color:#e8e8f0;}}

        /* ── 性格卡片 ── */
        .p-card{{
            padding:14px;margin:10px 0;background:#1a1a3a;
            border:1px solid rgba(255,255,255,0.08);border-radius:10px;
            cursor:pointer;transition:all 0.25s ease;
        }}
        .p-card:hover{{border-color:#00f0ff;background:#222250;}}
        .p-card.active{{
            border-color:#00f0ff;box-shadow:0 0 15px rgba(0,240,255,0.3);background:#1a1a4a;
        }}
        /* 激活卡片的右上角标记 */
        .p-card.active::after{{
            content:"\\2714 \\u5f53\\u524d";position:absolute;top:8px;right:12px;
            font-size:11px;color:#00f0ff;
        }}
        .p-header{{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;}}
        .p-name{{font-size:16px;font-weight:600;color:#e8e8f0;}}
        .p-voice{{font-size:13px;color:#00f0ff;}}
        .p-tags{{margin-bottom:6px;}}
        .tag{{
            display:inline-block;padding:2px 10px;margin:2px 4px 2px 0;
            background:#0f3460;border-radius:12px;font-size:11px;color:#7a7a9e;
        }}
        .p-card.active .tag{{background:#1a5080;color:#00f0ff;}}
        .p-greet{{font-size:12px;color:#7a7a9e;font-style:italic;}}
        </style>

        <!-- ═══ 当前性格状态头 ═══ -->
        <div class="sbar">
            <div>
                <div class="sl">当前性格</div>
                <div class="sn" id="sName">{cur_name}</div>
            </div>
            <div class="sv">
                音色<br>
                <span id="sVoice">{cur_voice}</span>
            </div>
        </div>

        <h3 style="color:#00f0ff;margin-bottom:16px;">\U0001f3ad 选择性格</h3>

        <!-- ═══ 性格卡片列表 ═══ -->
        <div id="p-list">
            {cards}
        </div>

        <!-- ═══ 切换逻辑 ═══ -->
        <script>
        function switchPersonality(name) {{
            pywebview.api.call_plugin('personality', 'switch_personality', name)
                .then(function(r) {{
                    var result = JSON.parse(r);
                    if (result.ok) {{
                        /* 更新状态栏 */
                        if (result.name) document.getElementById('sName').innerText = result.name;
                        if (result.voice) document.getElementById('sVoice').innerText = result.voice;
                        /* 更新卡片高亮 */
                        var cs = document.querySelectorAll('.p-card');
                        for (var i = 0; i < cs.length; i++) {{
                            cs[i].classList.remove('active');
                            if (cs[i].getAttribute('data-key') === name) {{
                                cs[i].classList.add('active');
                            }}
                        }}
                    }}
                }});
        }}
        </script>"""