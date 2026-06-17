"""
聊天框插件 —— 提供文字输入界面，用户可直接打字与 AI 对话。

前端：聊天气泡 + 输入框 + 发送按钮
后端：记录对话消息供前端轮询展示
"""

from __future__ import annotations

import json
from plugin_base import PluginBase
from log_config import get_logger

logger = get_logger(__name__)


class ChatboxPlugin(PluginBase):
    """聊天框插件"""

    name = "chatbox"
    version = "1.0"

    def __init__(self) -> None:
        super().__init__()
        # 消息列表（供前端轮询展示）
        self._messages: list[dict[str, str]] = []

    # ==================================================================
    #  Hook
    # ==================================================================

    def on_startup(self, app) -> None:
        super().on_startup(app)
        logger.info("[chatbox] 聊天框插件已就绪，可打字对话。")

    def on_user_input(self, text: str) -> str | None:
        """记录用户消息，不修改文本。"""
        self._messages.append({"role": "user", "content": text})
        logger.info(f"[chatbox] 用户: {text[:50]}...")
        return None

    def on_llm_response(self, text: str) -> str | None:
        """记录 AI 回复，不修改文本。"""
        self._messages.append({"role": "assistant", "content": text})
        logger.info(f"[chatbox] AI: {text[:50]}...")
        return None

    # ==================================================================
    #  前端 JS API（由 ui_shell 的 call_plugin 调用）
    # ==================================================================

    def get_messages(self, index: str = "0") -> str:
        """获取从 index 之后的新消息（JSON 数组）。

        Args:
            index: 上次已获取到的消息索引（字符串，因为 JS API 只传字符串）

        Returns:
            JSON 字符串，{"messages": [...], "next_index": N}
        """
        try:
            start = int(index)
        except (ValueError, TypeError):
            start = 0
        new_msgs = self._messages[start:]
        return json.dumps({
            "messages": new_msgs,
            "next_index": len(self._messages),
        }, ensure_ascii=False)

    def clear_messages(self) -> str:
        """清空消息列表。"""
        self._messages.clear()
        return "ok"

    # ==================================================================
    #  前端 HTML
    # ==================================================================

    def get_frontend_html(self) -> str:
        return r"""
<style>
.chatbox-wrap {
    display: flex;
    flex-direction: column;
    height: 100%;
}
.chatbox-messages {
    flex: 1;
    overflow-y: auto;
    padding: 8px 4px;
    display: flex;
    flex-direction: column;
    gap: 8px;
}
.chatbox-msg {
    max-width: 85%;
    padding: 8px 12px;
    border-radius: 12px;
    font-size: 13px;
    line-height: 1.5;
    word-break: break-word;
}
.chatbox-msg.user {
    align-self: flex-end;
    background: #e94560;
    color: #fff;
    border-bottom-right-radius: 4px;
}
.chatbox-msg.assistant {
    align-self: flex-start;
    background: #16213e;
    color: #eee;
    border-bottom-left-radius: 4px;
}
.chatbox-input-row {
    display: flex;
    gap: 8px;
    padding: 8px 4px 0 4px;
    border-top: 1px solid rgba(255,255,255,0.08);
    flex-shrink: 0;
}
.chatbox-input-row input {
    flex: 1;
    padding: 8px 12px;
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 20px;
    background: #16213e;
    color: #eee;
    font-size: 13px;
    outline: none;
    transition: border-color 0.2s;
}
.chatbox-input-row input:focus {
    border-color: #e94560;
}
.chatbox-input-row button {
    padding: 8px 16px;
    border: none;
    border-radius: 20px;
    background: #e94560;
    color: #fff;
    font-size: 13px;
    cursor: pointer;
    transition: background 0.2s;
}
.chatbox-input-row input:disabled, .chatbox-input-row button:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}
.chatbox-status {
    text-align: center;
    font-size: 12px;
    color: #e94560;
    padding: 4px 0;
    min-height: 20px;
    flex-shrink: 0;
}
.chatbox-status.idle {
    color: #4a9;
}
.chatbox-empty {
    color: #555;
    text-align: center;
    margin-top: 60px;
    font-size: 13px;
    line-height: 1.8;
}
</style>

<div class="chatbox-wrap">
    <div class="chatbox-messages" id="chatboxMessages">
        <div class="chatbox-empty">
            VirtuMate<br>
            输入文字或直接说话进行对话
        </div>
    </div>
    <div class="chatbox-status idle" id="chatboxStatus">空闲 — 可以输入</div>
    <div class="chatbox-input-row">
        <input id="chatboxInput" type="text" placeholder="输入消息..." autofocus />
        <button id="chatboxSendBtn">发送</button>
    </div>
</div>

<script>
(function() {
    var container = document.getElementById('chatboxMessages');
    var input = document.getElementById('chatboxInput');
    var btn = document.getElementById('chatboxSendBtn');
    var statusEl = document.getElementById('chatboxStatus');
    var nextIndex = 0;
    var hasMessages = false;

    // --- 发送 ---
    function send() {
        if (input.disabled) return;  // 忙碌时忽略
        var text = input.value.trim();
        if (!text) return;
        try {
            pywebview.api.send_text_input(text).then(function(raw) {
                var resp = JSON.parse(raw);
                if (resp.error) {
                    // 忙碌时提示，不清空输入框
                    statusEl.textContent = resp.message || '系统忙碌中...';
                    statusEl.className = 'chatbox-status';
                } else {
                    input.value = '';
                }
            }).catch(function(e) { console.error(e); });
        } catch(e) { console.error(e); }
    }
    btn.addEventListener('click', send);
    input.addEventListener('keydown', function(e) {
        if (e.key === 'Enter') send();
    });

    // --- 轮询系统忙碌状态 ---
    function pollStatus() {
        try {
            pywebview.api.get_system_status().then(function(raw) {
                var status = JSON.parse(raw);
                if (status.busy) {
                    input.disabled = true;
                    btn.disabled = true;
                    input.placeholder = 'AI 正在处理中...';
                    statusEl.textContent = '忙碌 — AI 正在录音或回答中';
                    statusEl.className = 'chatbox-status';
                } else {
                    input.disabled = false;
                    btn.disabled = false;
                    input.placeholder = '输入消息...';
                    statusEl.textContent = '空闲 — 可以输入';
                    statusEl.className = 'chatbox-status idle';
                }
            }).catch(function(){});
        } catch(e) {}
    }
    setInterval(pollStatus, 300);
    pollStatus();

    // --- 轮询新消息 ---
    function addBubble(msg) {
        var div = document.createElement('div');
        div.className = 'chatbox-msg ' + msg.role;
        div.textContent = msg.content;
        container.appendChild(div);
        container.scrollTop = container.scrollHeight;
    }

    function poll() {
        try {
            pywebview.api.call_plugin('chatbox', 'get_messages', String(nextIndex)).then(function(raw) {
                var data = JSON.parse(raw);
                if (!data.messages || !data.messages.length) return;
                // 首次有消息时清除占位提示
                if (!hasMessages) {
                    hasMessages = true;
                    container.innerHTML = '';
                }
                for (var i = 0; i < data.messages.length; i++) {
                    addBubble(data.messages[i]);
                }
                nextIndex = data.next_index;
            }).catch(function() {});
        } catch(e) {}
    }

    setInterval(poll, 500);
    poll();
})();
</script>
"""
