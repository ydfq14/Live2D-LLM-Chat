"""
聊天框插件 —— 提供文字输入界面，用户可直接打字与 AI 对话。

前端：聊天气泡 + 输入框 + 发送按钮 + 文件附件
后端：记录对话消息供前端轮询展示，支持文件上下文注入
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from plugin_base import PluginBase
from log_config import get_logger

logger = get_logger(__name__)

# 文件附件配置
MAX_FILE_CONTEXT_CHARS = 50000  # 最大50K字符（约15K tokens）
SUPPORTED_FILE_TYPES = {'.txt', '.md', '.pdf', '.json', '.csv', '.log'}


def _extract_file_text(file_path: str) -> str:
    """从文件中提取文本（轻量级，不依赖重量级库）。

    支持: PDF (pypdf), TXT/MD/CSV/JSON/LOG (直接读取)
    """
    path = Path(file_path)
    suffix = path.suffix.lower()

    if suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())
        return "\n\n".join(pages)
    else:
        return path.read_text(encoding="utf-8")


class ChatboxPlugin(PluginBase):
    """聊天框插件"""

    name = "chatbox"
    version = "1.0"
    tab_icon = "💬"

    def __init__(self) -> None:
        super().__init__()
        self._messages: list[dict[str, str]] = []
        self._listening_enabled = None
        self._attached_file: dict | None = None  # 文件附件

    # ==================================================================
    #  Hook
    # ==================================================================

    def on_startup(self, app) -> None:
        super().on_startup(app)
        # 从 app 获取全局聆听控制事件（确保是同一个对象）
        if hasattr(app, '_listening_enabled'):
            self._listening_enabled = app._listening_enabled
            logger.info("[chatbox] 聊天框插件已就绪，可打字对话。聆听控制已连接。")
        else:
            logger.warning("[chatbox] app 对象没有 _listening_enabled 属性")

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
        """清空消息列表和附件。"""
        self._messages.clear()
        self._attached_file = None
        return "ok"

    # ==================================================================
    #  文件附件 API
    # ==================================================================

    def attach_file(self, file_path: str) -> str:
        """附加文件作为对话上下文。

        Args:
            file_path: 文件绝对路径

        Returns:
            JSON: {"success": true, "filename": ..., "char_count": ...} 或 {"success": false, "error": ...}
        """
        if not file_path:
            return json.dumps({"success": False, "error": "未选择文件"})

        if not os.path.exists(file_path):
            return json.dumps({"success": False, "error": f"文件不存在: {file_path}"})

        # 验证文件类型
        ext = os.path.splitext(file_path)[1].lower()
        if ext not in SUPPORTED_FILE_TYPES:
            return json.dumps({
                "success": False,
                "error": f"不支持的文件类型: {ext}，支持: {' '.join(sorted(SUPPORTED_FILE_TYPES))}"
            })

        try:
            text = _extract_file_text(file_path)
        except Exception as e:
            logger.error("[chatbox] 文件读取失败: %s", e)
            return json.dumps({"success": False, "error": f"文件读取失败: {e}"})

        if not text or not text.strip():
            return json.dumps({"success": False, "error": "文件内容为空"})

        # 截断超长内容
        truncated = False
        if len(text) > MAX_FILE_CONTEXT_CHARS:
            text = text[:MAX_FILE_CONTEXT_CHARS]
            truncated = True

        filename = os.path.basename(file_path)
        self._attached_file = {
            "filename": filename,
            "content": text,
            "char_count": len(text),
        }

        logger.info("[chatbox] 文件已附加: %s (%d 字符%s)", filename, len(text), "，已截断" if truncated else "")

        result = {"success": True, "filename": filename, "char_count": len(text)}
        if truncated:
            result["warning"] = f"文件内容过长，已截断至 {MAX_FILE_CONTEXT_CHARS} 字符"
        return json.dumps(result, ensure_ascii=False)

    def clear_attachment(self) -> str:
        """移除附件。"""
        self._attached_file = None
        logger.info("[chatbox] 附件已移除")
        return "ok"

    def get_attachment_status(self) -> str:
        """获取附件状态（供前端轮询）。"""
        if self._attached_file is None:
            return json.dumps({"attached": False})
        return json.dumps({
            "attached": True,
            "filename": self._attached_file["filename"],
            "char_count": self._attached_file["char_count"],
        }, ensure_ascii=False)

    # ==================================================================
    #  LLM 上下文注入
    # ==================================================================

    def on_llm_context(self, user_input: str) -> str:
        """将附件内容注入 LLM 上下文。"""
        if self._attached_file is None:
            logger.debug("[chatbox] on_llm_context: 无附件")
            return ""

        context = (
            f'【用户附件】用户上传了文件 "{self._attached_file["filename"]}"，内容如下：\n'
            f'---文件内容开始---\n'
            f'{self._attached_file["content"]}\n'
            f'---文件内容结束---\n'
            f'请基于此文件内容回答用户的问题，必要时也可以调用其他工具。'
        )
        logger.info("[chatbox] on_llm_context: 注入附件内容 (%d 字符)", len(context))
        return context

    # ==================================================================
    #  聆听控制 API
    # ==================================================================

    def toggle_listening(self) -> str:
        """切换聆听状态（开/关）。"""
        if self._listening_enabled is None:
            logger.error("[chatbox] _listening_enabled 未初始化！")
            return json.dumps({"enabled": False, "error": "聆听控制未初始化"})

        if self._listening_enabled.is_set():
            self._listening_enabled.clear()  # 关闭聆听
            logger.info("[chatbox] 聆听已关闭（静音模式）")
            return json.dumps({"enabled": False})
        else:
            self._listening_enabled.set()  # 开启聆听
            logger.info("[chatbox] 聆听已开启，状态: %s", self._listening_enabled.is_set())
            return json.dumps({"enabled": True})

    def get_listening_status(self) -> str:
        """获取当前聆听状态。"""
        if self._listening_enabled is None:
            return json.dumps({"enabled": False, "error": "聆听控制未初始化"})

        return json.dumps({"enabled": self._listening_enabled.is_set()})

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
    animation: bubbleIn 0.3s cubic-bezier(0.34, 1.56, 0.64, 1) forwards;
}
@keyframes bubbleIn {
    from {
        opacity: 0;
        transform: translateY(12px) scale(0.95);
    }
    to {
        opacity: 1;
        transform: translateY(0) scale(1);
    }
}
@keyframes bubbleInUser {
    from {
        opacity: 0;
        transform: translateX(20px) scale(0.95);
    }
    to {
        opacity: 1;
        transform: translateX(0) scale(1);
    }
}
.chatbox-msg.user {
    align-self: flex-end;
    background: linear-gradient(135deg, #e94560 0%, #c73e54 100%);
    color: #fff;
    border-bottom-right-radius: 4px;
    box-shadow: 0 2px 12px rgba(233, 69, 96, 0.3);
    animation-name: bubbleInUser;
}
.chatbox-msg.assistant {
    align-self: flex-start;
    background: linear-gradient(135deg, #1a1a3a 0%, #16213e 100%);
    color: #eee;
    border-bottom-left-radius: 4px;
    border-left: 2px solid var(--neon-cyan, #00f0ff);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.3);
}
.chatbox-input-row {
    display: flex;
    gap: 8px;
    padding: 8px 4px 0 4px;
    border-top: 1px solid var(--border-glow, rgba(0, 240, 255, 0.2));
    flex-shrink: 0;
}
.chatbox-input-row input {
    flex: 1;
    padding: 10px 16px;
    border: 1px solid var(--border-subtle, rgba(255, 255, 255, 0.06));
    border-radius: 20px;
    background: var(--surface-2, #1a1a3a);
    color: var(--text, #e8e8f0);
    font-size: 13px;
    outline: none;
    transition: all var(--transition-normal, 0.3s cubic-bezier(0.4, 0, 0.2, 1));
}
.chatbox-input-row input:focus {
    border-color: var(--neon-cyan, #00f0ff);
    box-shadow: 0 0 0 2px rgba(0, 240, 255, 0.15), 0 0 15px rgba(0, 240, 255, 0.1);
    background: var(--surface-3, #222250);
}
.chatbox-input-row button {
    padding: 10px 20px;
    border: none;
    border-radius: 20px;
    background: var(--gradient-accent, linear-gradient(135deg, #e94560, #b94eff));
    color: #fff;
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: all var(--transition-fast, 0.15s ease);
    box-shadow: 0 2px 10px rgba(233, 69, 96, 0.3);
}
.chatbox-input-row button:hover {
    transform: translateY(-1px);
    box-shadow: 0 4px 16px rgba(233, 69, 96, 0.5);
}
.chatbox-input-row button:active {
    transform: translateY(0);
}
.listen-btn {
    padding: 10px 12px !important;
    min-width: 90px;
    font-size: 12px !important;
    background: var(--surface-3, #222250) !important;
    white-space: nowrap;
    box-shadow: none !important;
}
.listen-btn.enabled {
    background: var(--accent, #e94560) !important;
    box-shadow: 0 0 15px rgba(233, 69, 96, 0.4) !important;
    animation: recordPulse 1.5s infinite;
}
@keyframes recordPulse {
    0%, 100% { box-shadow: 0 0 0 0 rgba(233, 69, 96, 0.6); }
    50% { box-shadow: 0 0 0 8px rgba(233, 69, 96, 0); }
}
.attach-btn {
    padding: 10px 10px !important;
    font-size: 14px !important;
    background: var(--surface-2, #1a1a3a) !important;
    min-width: 36px;
    box-shadow: none !important;
}
.attach-btn:hover {
    background: var(--surface-3, #222250) !important;
    box-shadow: 0 2px 8px rgba(0, 240, 255, 0.2) !important;
}
.chatbox-attachment-bar {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 12px;
    background: rgba(233, 69, 96, 0.1);
    border-top: 1px solid rgba(233, 69, 96, 0.2);
    font-size: 12px;
    color: var(--accent, #e94560);
    flex-shrink: 0;
}
.chatbox-attachment-bar .attach-filename {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}
.chatbox-attachment-bar .attach-info {
    color: var(--text-muted, #7a7a9e);
    font-size: 11px;
}
.chatbox-attachment-bar .remove-btn {
    background: none;
    border: 1px solid rgba(233, 69, 96, 0.3);
    color: var(--accent, #e94560);
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    cursor: pointer;
    transition: all var(--transition-fast, 0.15s ease);
}
.chatbox-attachment-bar .remove-btn:hover {
    background: var(--accent, #e94560);
    color: #fff;
    box-shadow: 0 0 10px rgba(233, 69, 96, 0.4);
}
.chatbox-error {
    color: var(--accent, #e94560);
    font-size: 12px;
    padding: 4px 12px;
    flex-shrink: 0;
}
.chatbox-input-row input:disabled, .chatbox-input-row button:disabled {
    opacity: 0.4;
    cursor: not-allowed;
}
.chatbox-status {
    text-align: center;
    font-size: 12px;
    color: var(--neon-cyan, #00f0ff);
    padding: 4px 0;
    min-height: 20px;
    flex-shrink: 0;
    animation: statusGlow 2s infinite;
}
@keyframes statusGlow {
    0%, 100% { opacity: 0.6; }
    50% { opacity: 1; }
}
.chatbox-status.idle {
    color: var(--neon-green, #39ff14);
    animation: none;
}
.chatbox-empty {
    color: var(--text-muted, #7a7a9e);
    text-align: center;
    margin-top: 60px;
    font-size: 13px;
    line-height: 1.8;
    opacity: 0;
    animation: fadeIn 0.8s 0.3s forwards;
}
@keyframes fadeIn {
    to { opacity: 1; }
}
</style>

<div class="chatbox-wrap">
    <div class="chatbox-messages" id="chatboxMessages">
        <div class="chatbox-empty">
            VirtuMate<br>
            输入文字或直接说话进行对话
        </div>
    </div>
    <div class="chatbox-attachment-bar" id="attachBar" style="display:none">
        <span>📎</span>
        <span class="attach-filename" id="attachName"></span>
        <span class="attach-info" id="attachInfo"></span>
        <button class="remove-btn" onclick="clearAttachment()">✕ 移除</button>
    </div>
    <div class="chatbox-error" id="attachError" style="display:none"></div>
    <div class="chatbox-status idle" id="chatboxStatus">空闲 — 可以输入</div>
    <div class="chatbox-input-row">
        <button id="attachBtn" class="attach-btn" onclick="attachFile()">📎</button>
        <button id="listenBtn" class="listen-btn" onclick="toggleListening()">⚪ 静音中</button>
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
    var listenBtn = document.getElementById('listenBtn');
    var nextIndex = 0;
    var hasMessages = false;
    var isListening = false;

    // --- 文件附件 ---
    window.attachFile = function() {
        try {
            pywebview.api.select_file('').then(function(filePath) {
                if (!filePath) return;  // 用户取消
                return pywebview.api.call_plugin('chatbox', 'attach_file', filePath);
            }).then(function(raw) {
                if (!raw) return;
                var data = JSON.parse(raw);
                if (data.success) {
                    updateAttachmentBar(data.filename, data.char_count, data.warning);
                } else {
                    showAttachError(data.error);
                }
            }).catch(function(e) { console.error(e); });
        } catch(e) { console.error(e); }
    }

    window.clearAttachment = function() {
        try {
            pywebview.api.call_plugin('chatbox', 'clear_attachment').then(function() {
                hideAttachmentBar();
            }).catch(function(e) { console.error(e); });
        } catch(e) { console.error(e); }
    }

    function updateAttachmentBar(filename, charCount, warning) {
        var bar = document.getElementById('attachBar');
        var nameEl = document.getElementById('attachName');
        var infoEl = document.getElementById('attachInfo');
        nameEl.textContent = filename;
        infoEl.textContent = '(' + charCount + ' 字符)';
        bar.style.display = 'flex';
        hideAttachError();
        if (warning) showAttachError(warning);
    }

    function hideAttachmentBar() {
        document.getElementById('attachBar').style.display = 'none';
    }

    function showAttachError(msg) {
        var el = document.getElementById('attachError');
        el.textContent = '❌ ' + msg;
        el.style.display = 'block';
        setTimeout(function() { hideAttachError(); }, 5000);
    }

    function hideAttachError() {
        document.getElementById('attachError').style.display = 'none';
    }

    // 轮询附件状态
    function pollAttachment() {
        try {
            pywebview.api.call_plugin('chatbox', 'get_attachment_status').then(function(raw) {
                var data = JSON.parse(raw);
                if (data.attached) {
                    updateAttachmentBar(data.filename, data.char_count);
                } else {
                    hideAttachmentBar();
                }
            }).catch(function(){});
        } catch(e) {}
    }
    setInterval(pollAttachment, 2000);
    pollAttachment();

    // --- 聆听控制 ---
    window.toggleListening = function() {
        try {
            pywebview.api.call_plugin('chatbox', 'toggle_listening').then(function(raw) {
                var data = JSON.parse(raw);
                isListening = data.enabled;
                updateListenButton();
            }).catch(function(e) { console.error(e); });
        } catch(e) { console.error(e); }
    }

    function updateListenButton() {
        if (isListening) {
            listenBtn.textContent = '🔴 聆听中';
            listenBtn.className = 'listen-btn enabled';
        } else {
            listenBtn.textContent = '⚪ 静音中';
            listenBtn.className = 'listen-btn';
        }
    }

    // 轮询聆听状态
    function pollListeningStatus() {
        try {
            pywebview.api.call_plugin('chatbox', 'get_listening_status').then(function(raw) {
                var data = JSON.parse(raw);
                isListening = data.enabled;
                updateListenButton();
            }).catch(function(){});
        } catch(e) {}
    }
    setInterval(pollListeningStatus, 1000);
    pollListeningStatus();

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
