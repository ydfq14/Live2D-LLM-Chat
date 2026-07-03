"""
自动关怀插件 -- 主动检测用户状态并推送关怀消息。

4 种关怀场景:
1. 空闲检测: 用户 5 分钟无交互
2. 时段问候: 早/中/下午/晚/深夜，每时段每天一次
3. 情绪关怀: 用户负面情绪时主动关心
4. 久聊提醒: 连续对话超过 20 轮

投递方式 (混合模式):
- LLM 生成猫娘语气关怀话术
- 直接 TTS + Live2D 播报 (不进入对话历史)
- 同时注入 chatbox 前端显示
"""

from __future__ import annotations

import json
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from plugin_base import PluginBase
from log_config import get_logger

logger = get_logger(__name__)

# 尝试导入负面情绪常量（emotion_rag 模块未安装时优雅降级）
try:
    from plugins.emotion_analysis.constants import NEGATIVE_EMOTIONS  # type: ignore[import-untyped]
except ImportError:
    NEGATIVE_EMOTIONS: set[str] = {"sad", "angry", "fearful", "anxious", "upset"}


# ==================================================================
# 时段范围与问候模板
# ==================================================================

PERIOD_RANGES: dict[str, tuple[int, int]] = {
    "morning":    (7, 9),
    "noon":       (11, 13),
    "afternoon":  (14, 16),
    "evening":    (17, 19),
    "late_night": (21, 23),
}

GREETING_TEMPLATES: dict[str, str] = {
    "morning":    "早上好！新的一天开始了，今天有什么计划吗？",
    "noon":       "中午啦！记得吃饭哦，别饿着肚子～",
    "afternoon":  "下午好～要不要休息一下？",
    "evening":    "晚上好！今天过得怎么样？",
    "late_night": "这么晚了还没睡吗？要注意休息呀～",
}

# 时段名称映射（用于LLM prompt）
PERIOD_NAMES: dict[str, str] = {
    "morning": "早上", "noon": "中午", "afternoon": "下午",
    "evening": "晚上", "late_night": "深夜",
}


# ==================================================================
# LLM System Prompt（猫娘关怀人设）
# ==================================================================

CARE_SYSTEM_PROMPT = """你是团子，一只奶油色猫娘少女。你现在要主动关心主人。
要求：
1. 用团子的语气说话（温柔、撒娇、可爱，偶尔加"喵"或"～"）
2. 回复控制在1-2句话，不超过40字
3. 不要使用任何格式符号（#、*、-、【】等）
4. 自然、口语化，像猫咪在主动关心主人
5. 自称"团子"，称呼用户为"主人"
6. 直接输出关心的话，不要解释"""


# ==================================================================
# AutoCarePlugin
# ==================================================================

class AutoCarePlugin(PluginBase):
    """自动关怀插件 -- 混合模式主动推送关怀消息"""

    name = "auto_care"
    version = "1.0"
    tab_icon = "\U0001f495"  # 💕

    # --- 时间阈值 (秒) ---
    IDLE_THRESHOLD = 300          # 5 分钟: 首次空闲触发
    COOLDOWN_DEFAULT = 1800       # 30 分钟: 全局冷却
    COOLDOWN_EMOTION = 600        # 10 分钟: 负面情绪时缩短冷却
    LONG_CHAT_THRESHOLD = 20      # 20 轮: 久聊触发
    CHECK_INTERVAL = 60           # 60 秒: 后台任务间隔
    STARTUP_GRACE = 120           # 2 分钟: 启动后不发关怀
    EMOTION_STALE_SECONDS = 600   # 10 分钟: 情绪过期（超过此时间不触发情绪关怀）

    def __init__(self) -> None:
        super().__init__()

        # --- 状态追踪 ---
        self._last_interaction_time: float = 0.0
        self._conversation_round_count: int = 0
        self._last_care_time: float = 0.0
        self._last_care_type: str = ""
        self._cached_emotion: dict[str, Any] | None = None
        self._greeting_records: dict[str, str] = {}
        self._startup_time: float = 0.0
        self._care_enabled: bool = True

        # --- 基础设施 ---
        self._app: Any = None
        self._data_dir: Path | None = None
        self._lock = threading.Lock()

    # ==================================================================
    #  生命周期 Hooks
    # ==================================================================

    def on_startup(self, app) -> None:
        super().on_startup(app)
        self._app = app
        self._data_dir = Path(self.get_data_dir())
        self._startup_time = time.time()
        self._load_state()
        # 首次运行，把交互时间设为现在（避免立即触发空闲检测）
        if self._last_interaction_time == 0.0:
            self._last_interaction_time = time.time()
        logger.info("[auto_care] Plugin started, care_enabled=%s", self._care_enabled)

    def on_user_input(self, text: str) -> str | None:
        """用户输入时更新最后交互时间。不重置轮次计数（由关怀场景自行重置）。"""
        with self._lock:
            self._last_interaction_time = time.time()
        return None

    def on_llm_response(self, text: str) -> str | None:
        """在 emotion_rag 清空 _last_emotion 之前缓存情绪数据。
        
        插件按字母序加载: auto_care → emotion_rag
        所以 auto_care 的 on_llm_response 在 emotion_rag 之前执行，
        此时 emotion_rag._last_emotion 未被清空。
        """
        with self._lock:
            emotion_rag = self._app.registry.get("emotion_rag")
            if emotion_rag and hasattr(emotion_rag, "_last_emotion") and emotion_rag._last_emotion:
                self._cached_emotion = dict(emotion_rag._last_emotion)
                logger.debug(
                    "[auto_care] Cached emotion: %s (conf=%.2f)",
                    self._cached_emotion.get("emotion"),
                    self._cached_emotion.get("confidence", 0),
                )
        return None

    def on_tick(self, app) -> None:
        """每轮对话结束：轮次 +1、尝试缓存情绪、持久化状态。"""
        with self._lock:
            self._conversation_round_count += 1
            # belt-and-suspenders: 尝试读取情绪（通常已被 emotion_rag 清空）
            emotion_rag = getattr(self._app, 'registry', None)
            if emotion_rag:
                erp = emotion_rag.get("emotion_rag") if hasattr(emotion_rag, "get") else None
                if erp and hasattr(erp, "_last_emotion") and erp._last_emotion:
                    self._cached_emotion = dict(erp._last_emotion)
            self._save_state()

    def on_register_background_tasks(self) -> list[dict]:
        return [
            {
                "task_id": "check_care",
                "interval": self.CHECK_INTERVAL,
                "callback": self._check_care,
                "description": "Auto-care: check idle/greeting/emotion/long-chat",
                "immediate": False,
            }
        ]

    def on_task_complete(self, task_id: str, result: Any) -> None:
        """后台任务完成后，生成关怀消息并投递。"""
        if not result or not isinstance(result, dict):
            return

        care_type = result.get("type", "")
        raw_msg = result.get("raw_message", "")
        context = result.get("context", {})

        if not raw_msg:
            return

        # 二次确认：投递前检查 busy（防止竞态）
        if hasattr(self._app, "_busy_event") and self._app._busy_event.is_set():
            logger.info("[auto_care] System busy, skipping care delivery")
            return

        # 生成润色后的关怀话术
        polished = self._generate_care_message(care_type, raw_msg, context)

        # 更新状态
        with self._lock:
            self._last_care_time = time.time()
            self._last_care_type = care_type
            if care_type == "period_greeting":
                period = context.get("period", "")
                if period:
                    today = datetime.now().strftime("%Y-%m-%d")
                    self._greeting_records[period] = today
            if care_type in ("long_chat", "idle_care"):
                self._conversation_round_count = 0
            self._save_state()

        # 记录到 episodic memory
        self._record_care_event(care_type, polished)

        # 投递: TTS + Live2D + Chatbox
        self._deliver_care(polished)

    def on_shutdown(self) -> None:
        """退出前保存状态。"""
        with self._lock:
            self._save_state()
        logger.info("[auto_care] Plugin shutdown, state saved")

    # ==================================================================
    #  后台任务: 主检测回调
    # ==================================================================

    def _check_care(self) -> dict | None:
        """主后台检测回调。按优先级依次检查 4 种关怀场景。

        Returns:
            关怀结果 dict 或 None（本轮不触发）。
        """
        if not self._care_enabled:
            return None

        now = time.time()

        # 启动保护期
        if now - self._startup_time < self.STARTUP_GRACE:
            return None

        # 系统忙碌检查
        if hasattr(self._app, "_busy_event") and self._app._busy_event.is_set():
            return None

        with self._lock:
            # 全局冷却检查
            cooldown = self._get_current_cooldown()
            if now - self._last_care_time < cooldown:
                return None

            # 按优先级依次检查
            # emotion_care > period_greeting > idle_care > long_chat
            for check_fn in [
                self._check_emotion_care,
                self._check_period_greeting,
                self._check_idle_care,
                self._check_long_chat,
            ]:
                result = check_fn()
                if result:
                    return result

        return None

    # ==================================================================
    #  4 种关怀场景检测
    # ==================================================================

    def _check_emotion_care(self) -> dict | None:
        """检测负面情绪 → 主动关心（最高优先级）。"""
        # 读取缓存情绪（在 on_llm_response 中设置）
        emotion = self._cached_emotion
        if not emotion:
            return None

        emotion_label = emotion.get("emotion", "neutral")
        if emotion_label not in NEGATIVE_EMOTIONS:
            return None

        # 只在用户最近活跃时触发（避免对过期情绪过度反应）
        if time.time() - self._last_interaction_time > self.EMOTION_STALE_SECONDS:
            logger.debug("[auto_care] Emotion stale, skip emotion_care")
            return None

        logger.info("[auto_care] Trigger emotion_care: %s (cause=%s)",
                    emotion_label, emotion.get("cause", "N/A"))

        raw_msg = "感觉你心情不太好，想聊聊吗？我随时都在。"
        return {
            "type": "emotion_care",
            "raw_message": raw_msg,
            "context": {
                "emotion": emotion_label,
                "cause": emotion.get("cause", ""),
                "confidence": emotion.get("confidence", 0.5),
            },
        }

    def _check_period_greeting(self) -> dict | None:
        """检测时段问候：每个时段每天只问候一次。"""
        hour = datetime.now().hour
        period = self._get_current_period(hour)
        if not period:
            return None

        today = datetime.now().strftime("%Y-%m-%d")
        if self._greeting_records.get(period) == today:
            return None  # 该时段今天已问候

        logger.info("[auto_care] Trigger period_greeting: %s (hour=%d)", period, hour)

        return {
            "type": "period_greeting",
            "raw_message": GREETING_TEMPLATES.get(period, "你好呀～"),
            "context": {"period": period, "hour": hour, "date": today},
        }

    def _check_idle_care(self) -> dict | None:
        """检测空闲：用户超过阈值时间无交互。"""
        idle_seconds = time.time() - self._last_interaction_time
        if idle_seconds < self.IDLE_THRESHOLD:
            return None

        logger.info("[auto_care] Trigger idle_care: %d sec idle", int(idle_seconds))

        return {
            "type": "idle_care",
            "raw_message": "你还在吗？我一直在等你呢，需要休息一下吗？",
            "context": {"idle_seconds": int(idle_seconds)},
        }

    def _check_long_chat(self) -> dict | None:
        """检测久聊：连续对话超过阈值轮次。"""
        if self._conversation_round_count < self.LONG_CHAT_THRESHOLD:
            return None

        logger.info("[auto_care] Trigger long_chat: %d rounds",
                    self._conversation_round_count)

        return {
            "type": "long_chat",
            "raw_message": "我们已经聊了好一会儿了，注意休息眼睛哦！",
            "context": {"round_count": self._conversation_round_count},
        }

    # ==================================================================
    #  辅助: 时段判断
    # ==================================================================

    def _get_current_period(self, hour: int) -> str | None:
        """根据小时判断当前时段。late_night 跨 21:00~次日 06:59。"""
        for period, (start, end) in PERIOD_RANGES.items():
            if period == "late_night":
                if hour >= 21 or hour <= 6:
                    return period
            elif start <= hour <= end:
                return period
        return None

    # ==================================================================
    #  动态冷却策略
    # ==================================================================

    def _get_current_cooldown(self) -> int:
        """动态冷却时间：负面情绪时缩短到 10 分钟，否则 30 分钟。"""
        if self._cached_emotion:
            emotion = self._cached_emotion.get("emotion", "neutral")
            if emotion in NEGATIVE_EMOTIONS:
                return self.COOLDOWN_EMOTION
        return self.COOLDOWN_DEFAULT

    # ==================================================================
    #  LLM 消息生成（混合模式）
    # ==================================================================

    def _generate_care_message(
        self, care_type: str, raw_msg: str, context: dict
    ) -> str:
        """使用 LLM 将原始关怀话术润色为猫娘语气。

        Args:
            care_type: 关怀类型 (emotion_care/period_greeting/idle_care/long_chat)
            raw_msg:   原始关怀话术（fallback 用）
            context:   场景上下文（时段、情绪等）

        Returns:
            润色后的关怀消息。
        """
        llm = getattr(self._app, 'llm_manager', None)
        if not llm or not hasattr(llm, "model_chat_completion"):
            logger.debug("[auto_care] LLM unavailable, using raw message")
            return raw_msg

        now = datetime.now()
        time_str = now.strftime("%H:%M")
        period_name = PERIOD_NAMES.get(context.get("period", ""), "")

        # 构建情绪上下文
        emotion_info = ""
        if self._cached_emotion and self._cached_emotion.get("emotion", "neutral") != "neutral":
            emotion_info = f"用户最近的情绪状态：{self._cached_emotion['emotion']}"
            if self._cached_emotion.get("cause"):
                emotion_info += f"（原因：{self._cached_emotion['cause']}）"

        user_prompt = f"""当前时间：{time_str}（{period_name or '未知时段'}）
关怀类型：{care_type}
{emotion_info}
参考内容：{raw_msg}

请用团子的语气，自然地表达这条关心。不要直接照搬参考内容，要用自己的方式说出来。
只输出团子说的话，不要加任何动作描述或括号说明。"""

        try:
            result = llm.model_chat_completion([
                {"role": "system", "content": CARE_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ])
            if result and isinstance(result, str) and len(result.strip()) > 3:
                # 清理可能的括号动作描述
                cleaned = re.sub(r'（[^）]*?）', '', result)
                cleaned = re.sub(r'\([^)]*?\)', '', cleaned)
                cleaned = cleaned.strip()
                if cleaned:
                    logger.info("[auto_care] LLM polished: %s", cleaned[:50])
                    return cleaned
        except Exception as e:
            logger.warning("[auto_care] LLM generation failed: %s", e)

        return raw_msg  # Fallback

    # ==================================================================
    #  消息投递（混合模式）
    # ==================================================================

    def _deliver_care(self, message: str) -> None:
        """混合模式投递关怀消息。

        1. 注入 chatbox._messages（前端气泡显示）
        2. TTS 合成语音
        3. Live2D 口型同步播放

        不进入对话历史（不污染 LLM context）。
        """
        try:
            # 1. 注入 chatbox 前端消息列表
            registry = getattr(self._app, 'registry', None)
            if registry:
                chatbox = registry.get("chatbox")
                if chatbox and hasattr(chatbox, "_messages"):
                    chatbox._messages.append({"role": "assistant", "content": message})
                    logger.info("[auto_care] Injected into chatbox")

            # 2. TTS + Live2D 播放
            tts_manager = getattr(self._app, 'tts_manager', None)
            live2d_manager = getattr(self._app, 'live2d_manager', None)

            if not tts_manager:
                logger.warning("[auto_care] TTS manager unavailable")
                return

            audio_path = tts_manager.synthesize(message)

            if audio_path and live2d_manager:
                live2d_manager.play_audio_and_print_mouth(audio_path)
                logger.info("[auto_care] TTS + Live2D playback complete")
            elif audio_path:
                logger.info("[auto_care] TTS done, Live2D unavailable")
            else:
                logger.warning("[auto_care] TTS synthesis failed")

        except Exception as e:
            logger.error("[auto_care] Care delivery failed: %s", e)

    # ==================================================================
    #  Episodic Memory 集成
    # ==================================================================

    def _record_care_event(self, care_type: str, message: str) -> None:
        """记录关怀事件到 emotion_rag 的 episodic memory。"""
        try:
            registry = getattr(self._app, 'registry', None)
            if not registry:
                return
            emotion_rag = registry.get("emotion_rag")
            if emotion_rag and getattr(emotion_rag, "episodic_memory", None):
                emotion_rag.episodic_memory.add_event(
                    event_type="care_triggered",
                    content=f"[{care_type}] {message[:80]}",
                    emotion="neutral",
                    weight=1.0,
                )
                logger.debug("[auto_care] Recorded to episodic memory")
        except Exception as e:
            logger.debug("[auto_care] Episodic record skipped: %s", e)

    # ==================================================================
    #  数据持久化
    # ==================================================================

    def _load_state(self) -> None:
        """从 care_state.json 加载持久化状态。"""
        if self._data_dir is None:
            return
        state_file = self._data_dir / "care_state.json"
        if not state_file.exists():
            return
        content = state_file.read_text(encoding="utf-8")
        if not content.strip():
            return  # 空文件，视为首次运行
        try:
            data = json.loads(content)
            self._last_interaction_time = data.get("last_interaction_time", 0.0)
            self._conversation_round_count = data.get("conversation_round_count", 0)
            self._last_care_time = data.get("last_care_time", 0.0)
            self._last_care_type = data.get("last_care_type", "")
            self._greeting_records = data.get("greeting_records", {})
            self._cached_emotion = data.get("cached_emotion")
            self._care_enabled = data.get("care_enabled", True)
            logger.info("[auto_care] State loaded: rounds=%d, last_care_type=%s",
                        self._conversation_round_count, self._last_care_type or "none")
        except Exception as e:
            logger.error("[auto_care] Load state failed: %s", e)

    def _save_state(self) -> None:
        """持久化当前状态到 care_state.json。"""
        if self._data_dir is None:
            return
        state_file = self._data_dir / "care_state.json"
        try:
            data: dict[str, Any] = {
                "last_interaction_time": self._last_interaction_time,
                "conversation_round_count": self._conversation_round_count,
                "last_care_time": self._last_care_time,
                "last_care_type": self._last_care_type,
                "greeting_records": self._greeting_records,
                "cached_emotion": self._cached_emotion,
                "care_enabled": self._care_enabled,
            }
            state_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("[auto_care] Save state failed: %s", e)

    # ==================================================================
    #  前端面板
    # ==================================================================

    def get_frontend_html(self) -> str:
        return r"""
<style>
.autocare-wrap { padding: 16px; }
.autocare-title {
    font-size: 16px; font-weight: bold; color: var(--neon-cyan, #00f0ff);
    margin-bottom: 16px; text-shadow: 0 0 10px rgba(0, 240, 255, 0.4);
}
.autocare-toggle-row {
    display: flex; align-items: center; justify-content: space-between;
    padding: 12px; background: var(--surface-1, #111128);
    border-radius: 8px; margin-bottom: 12px;
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.06));
}
.autocare-toggle-label { font-size: 14px; color: var(--text, #e8e8f0); }
.autocare-switch {
    width: 44px; height: 24px; border-radius: 12px;
    background: var(--surface-3, #222250); cursor: pointer;
    position: relative; transition: all 0.3s;
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.06));
}
.autocare-switch.on { background: var(--accent, #e94560); }
.autocare-switch::after {
    content: ''; position: absolute; top: 2px; left: 2px;
    width: 18px; height: 18px; border-radius: 50%;
    background: #fff; transition: all 0.3s;
}
.autocare-switch.on::after { left: 22px; }
.autocare-param {
    padding: 10px 12px; margin-bottom: 8px;
    background: var(--surface-1, #111128);
    border-radius: 6px;
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.06));
}
.autocare-param-label { font-size: 12px; color: var(--text-muted, #7a7a9e); margin-bottom: 4px; }
.autocare-param-value { font-size: 13px; color: var(--neon-cyan, #00f0ff); }
.autocare-status {
    margin-top: 12px; padding: 10px;
    background: rgba(0, 240, 255, 0.05);
    border-radius: 6px; border: 1px solid rgba(0, 240, 255, 0.15);
    font-size: 12px; color: var(--text-muted, #7a7a9e);
}
.autocare-status-line { margin: 2px 0; }
.autocare-status-line span { color: var(--neon-cyan, #00f0ff); }
</style>

<div class="autocare-wrap">
    <div class="autocare-title">💝 自动关怀</div>

    <div class="autocare-toggle-row">
        <span class="autocare-toggle-label">关怀功能</span>
        <div class="autocare-switch on" id="careSwitch" onclick="toggleCare()"></div>
    </div>

    <div class="autocare-param">
        <div class="autocare-param-label">空闲检测阈值</div>
        <div class="autocare-param-value" id="idleThreshold">5 分钟</div>
    </div>
    <div class="autocare-param">
        <div class="autocare-param-label">全局冷却时间</div>
        <div class="autocare-param-value" id="cooldownTime">30 分钟（负面情绪时 10 分钟）</div>
    </div>
    <div class="autocare-param">
        <div class="autocare-param-label">久聊提醒阈值</div>
        <div class="autocare-param-value" id="longChatThreshold">20 轮</div>
    </div>

    <div class="autocare-status" id="careStatus">
        <div class="autocare-status-line">状态加载中...</div>
    </div>
</div>

<script>
function toggleCare() {
    var sw = document.getElementById('careSwitch');
    var enabled = sw.classList.contains('on');
    if (window.pywebview && window.pywebview.api) {
        pywebview.api.call_plugin('auto_care', 'toggle_care', String(!enabled))
            .then(function(raw) {
                try {
                    var data = JSON.parse(raw);
                    if (data.enabled) {
                        sw.classList.add('on');
                    } else {
                        sw.classList.remove('on');
                    }
                } catch(e) {}
            })
            .catch(function(){});
    }
}
function refreshStatus() {
    if (!window.pywebview || !window.pywebview.api) return;
    pywebview.api.call_plugin('auto_care', 'get_status').then(function(raw) {
        try {
            var data = JSON.parse(raw);
            var sw = document.getElementById('careSwitch');
            if (data.enabled) { sw.classList.add('on'); }
            else { sw.classList.remove('on'); }

            var statusEl = document.getElementById('careStatus');
            var idleMin = Math.floor(data.idle_seconds / 60);
            var cooldownMin = Math.floor(data.cooldown_remaining / 60);
            statusEl.innerHTML =
                '<div class="autocare-status-line">功能状态: <span>' + (data.enabled ? '已开启' : '已关闭') + '</span></div>' +
                '<div class="autocare-status-line">上次交互: <span>' + idleMin + ' 分钟前</span></div>' +
                '<div class="autocare-status-line">对话轮数: <span>' + data.round_count + '</span></div>' +
                '<div class="autocare-status-line">冷却剩余: <span>' + (cooldownMin > 0 ? cooldownMin + ' 分钟' : '可触发') + '</span></div>' +
                '<div class="autocare-status-line">用户情绪: <span>' + (data.emotion || 'neutral') + '</span></div>' +
                '<div class="autocare-status-line">上次关怀: <span>' + (data.last_care_type || '无') + '</span></div>';
        } catch(e) {}
    }).catch(function(){});
}
// pywebview 初始化
if (window.pywebview && window.pywebview.api) {
    setInterval(refreshStatus, 3000);
    refreshStatus();
} else {
    window.addEventListener('pywebviewready', function() {
        setInterval(refreshStatus, 3000);
        refreshStatus();
    });
}
</script>
"""

    # ==================================================================
    #  前端 JS API
    # ==================================================================

    def toggle_care(self, enabled: str) -> str:
        """切换关怀功能开关（前端调用）。

        Args:
            enabled: "true" 或 "false" 字符串

        Returns:
            JSON: {"enabled": true/false}
        """
        self._care_enabled = enabled.lower() == "true"
        with self._lock:
            self._save_state()
        logger.info("[auto_care] Care %s", "enabled" if self._care_enabled else "disabled")
        return json.dumps({"enabled": self._care_enabled}, ensure_ascii=False)

    def get_status(self) -> str:
        """获取当前状态（前端轮询）。

        Returns:
            JSON 字符串，含 enabled/idle_seconds/round_count/cooldown_remaining/emotion/last_care_type。
        """
        now = time.time()
        with self._lock:
            cooldown = self._get_current_cooldown()
            cooldown_remaining = max(0, cooldown - (now - self._last_care_time))
            emotion_label = (
                self._cached_emotion.get("emotion")
                if self._cached_emotion
                else None
            )
            return json.dumps({
                "enabled": self._care_enabled,
                "idle_seconds": int(now - self._last_interaction_time),
                "round_count": self._conversation_round_count,
                "cooldown_remaining": int(cooldown_remaining),
                "emotion": emotion_label,
                "last_care_type": self._last_care_type,
            }, ensure_ascii=False)
