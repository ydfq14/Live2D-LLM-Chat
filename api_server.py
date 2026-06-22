"""
VirtuMate API Server — FastAPI 封装现有全部服务，提供 Web 端点。

不修改任何已有文件，仅通过 import 复用现有模块。
支持：文本对话、语音对话（ASR+TTS）、情感分析、记忆检索、安全检测。

运行方式：
    cd "D:\软件综合实训\实训项目"
    python api_server.py

前端示例：访问 http://localhost:8000/static/index.html
"""
from __future__ import annotations

import base64
import json
import os
import shutil
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# 将项目根目录加入 Python 路径，以便 import 现有模块
PROJECT_ROOT = Path(__file__).parent.resolve()
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import Config
from LLM import LLMManager
from TTS import TTSManager
from ASR import ASRManager
from plugins.emotion_rag_plugin import (
    _analyze_emotion_from_text,
    _keyword_emotion_fallback,
    MemoryRAG,
    UserRulesManager,
    EpisodicMemory,
)
from safety_rag.safety_rag import SafetyRAG
from log_config import get_logger

logger = get_logger("api_server")

app = FastAPI(title="VirtuMate API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ═══════════════════════════════════════════════════════════════════
# 初始化所有现有模块（与桌面应用独立，共享数据目录）
# ═══════════════════════════════════════════════════════════════════

class ServiceManager:
    """封装所有现有服务的统一入口。"""

    def __init__(self) -> None:
        logger.info("[API] 初始化服务管理器...")

        # 1. 配置与 LLM
        self.config = Config()
        self.llm = LLMManager()
        logger.info("[API] LLM 就绪: %s", self.llm.model_name)

        # 2. TTS（语音合成）
        self.tts = TTSManager()
        logger.info("[API] TTS 就绪: %s", self.tts.voice_name)

        # 3. ASR（语音识别）
        self.asr = ASRManager()
        logger.info("[API] ASR 就绪: %s", self.asr.model_name)

        # 4. RAG 记忆
        self.memory_rag = MemoryRAG(persist_dir="./plugins_data/memory")
        logger.info("[API] MemoryRAG 就绪")

        # 5. 安全拦截
        self.safety_rag = SafetyRAG()
        logger.info("[API] SafetyRAG 就绪")

        # 6. 规则管理
        self.rules_manager = UserRulesManager(data_dir="./plugins_data/emotion_rag")
        logger.info("[API] UserRulesManager 就绪")

        # 7. Episodic Memory
        self.episodic = EpisodicMemory(db_path="./plugins_data/emotion_rag/episodic.db")
        logger.info("[API] EpisodicMemory 就绪")

        # 8. 音频缓存目录（供前端播放）
        self.audio_output_dir = Path("./api_output/audio")
        self.audio_output_dir.mkdir(parents=True, exist_ok=True)

    # ────────────────────────────────────────────
    # 核心对话流程（复用现有逻辑）
    # ────────────────────────────────────────────

    def chat(self, user_text: str) -> Dict[str, Any]:
        """完整对话：安全检测 → 情感分析 → 检索 → LLM 生成 → TTS 合成 → 记忆存储。"""
        result: Dict[str, Any] = {
            "user_input": user_text,
            "timestamp": time.time(),
        }

        # 1. 安全检测
        safety = self.safety_rag.check_input(user_text)
        result["safety"] = safety
        if safety.get("intercept"):
            result["type"] = "intercepted"
            result["reply"] = safety.get("response", "")
            result["emotion"] = "fearful"
            return result

        # 2. 情感分析（关键词 + LLM 双引擎）
        emotion_fallback = _keyword_emotion_fallback(user_text)
        try:
            emotion_llm = _analyze_emotion_from_text(user_text, self.llm)
        except Exception:
            emotion_llm = emotion_fallback
        # 优先使用 LLM 结果（置信度更高），fallback 兜底
        emotion = emotion_llm if emotion_llm.get("confidence", 0) > 0.5 else emotion_fallback
        result["emotion"] = emotion

        # 3. 检索决策 + 记忆检索
        need_retrieval, mode = self.rules_manager.decide_retrieval(user_text)
        memories = []
        if need_retrieval:
            memories = self.memory_rag.search(user_text, n_results=5)
        result["retrieval_mode"] = mode
        result["memories"] = [
            {"content": m["content"], "emotion": m["emotion"], "score": m["similarity"]}
            for m in memories
        ]

        # 4. 组装上下文 + 调用 LLM 生成回复
        context = self._build_context(user_text, emotion, memories)
        reply = self._llm_generate(context, user_text)
        result["reply"] = reply

        # 5. TTS 合成（生成音频文件）
        audio_path = self._synthesize_speech(reply)
        if audio_path:
            result["audio_url"] = f"/audio/{audio_path.name}"
            result["audio_path"] = str(audio_path)

        # 6. 存储记忆（用户输入 + 角色回复）
        self._store_memory(user_text, reply, emotion)

        # 7. Episodic 事件记录
        self._record_episodic(user_text, reply, emotion)

        return result

    def _build_context(self, user_text: str, emotion: Dict[str, Any], memories: List[Dict[str, Any]]) -> str:
        """组装系统提示 + 记忆上下文。"""
        emotion_label = emotion.get("emotion", "neutral")
        from plugins.emotion_rag_plugin import _emotion_to_style
        style = _emotion_to_style(emotion_label)

        lines = [
            "你是一位虚拟桌宠角色，温柔、耐心、活泼。",
        ]
        if style:
            lines.append(f"当前用户情绪：{emotion_label}。回复风格：{style}")
        if memories:
            snippets = "\n".join([f"- {m['content']}" for m in memories[:3]])
            lines.append(f"相关历史记忆：\n{snippets}")
        return "\n".join(lines)

    def _llm_generate(self, context: str, user_text: str) -> str:
        """调用 LLM 生成回复。"""
        messages = [
            {"role": "system", "content": context},
            {"role": "user", "content": user_text},
        ]
        try:
            raw = self.llm.model_chat_completion(messages)
            # 清理可能的标记
            reply = raw.replace("【", "").replace("】", "").strip()
            return reply
        except Exception as e:
            logger.error("[API] LLM 生成失败: %s", e)
            return "嗯…我现在有点反应不过来，你能再说一遍吗？"

    def _synthesize_speech(self, text: str) -> Optional[Path]:
        """调用 TTS 合成语音，保存到音频目录，返回文件路径。"""
        try:
            # 生成唯一文件名
            filename = f"tts_{uuid.uuid4().hex[:8]}.wav"
            output_path = self.audio_output_dir / filename

            # 调用 TTS（假设返回音频文件路径或 bytes）
            # 根据实际 TTSManager 接口调整
            audio_data = self.tts.text_to_speech(text)
            if isinstance(audio_data, str) and os.path.exists(audio_data):
                shutil.copy(audio_data, output_path)
            elif isinstance(audio_data, bytes):
                output_path.write_bytes(audio_data)
            else:
                # 如果 TTS 接口不同，请根据实际调整
                return None

            return output_path
        except Exception as e:
            logger.warning("[API] TTS 合成失败: %s", e)
            return None

    def _store_memory(self, user_text: str, reply: str, emotion: Dict[str, Any]) -> None:
        """存储对话到 Chroma 记忆库。"""
        try:
            emotion_label = emotion.get("emotion", "neutral")
            from plugins.emotion_rag_plugin import _NEGATIVE_EMOTIONS, _POSITIVE_EMOTIONS
            if emotion_label in _NEGATIVE_EMOTIONS:
                weight = 0.5
            elif emotion_label in _POSITIVE_EMOTIONS:
                weight = 1.5
            else:
                weight = 1.0
            self.memory_rag.add_memory(user_text, emotion_label, weight)
            if reply:
                self.memory_rag.add_memory(reply, "neutral", 0.7)
        except Exception as e:
            logger.warning("[API] 记忆存储失败: %s", e)

    def _record_episodic(self, user_text: str, reply: str, emotion: Dict[str, Any]) -> None:
        """记录到时序事件数据库。"""
        try:
            emotion_label = emotion.get("emotion", "neutral")
            self.episodic.add_event("user_input", user_text[:100], emotion_label, 1.0)
            if reply:
                self.episodic.add_event("llm_response", reply[:100], "neutral", 0.7)
        except Exception as e:
            logger.warning("[API] Episodic 记录失败: %s", e)

    # ────────────────────────────────────────────
    # 辅助方法
    # ────────────────────────────────────────────

    def asr_recognize(self, audio_file: Path) -> str:
        """语音识别：音频文件 → 文本。"""
        try:
            return self.asr.recognize(audio_file)
        except Exception as e:
            logger.warning("[API] ASR 识别失败: %s", e)
            return ""

    def cleanup_audio(self, max_age_hours: int = 24) -> int:
        """清理过期音频文件。"""
        deleted = 0
        cutoff = time.time() - max_age_hours * 3600
        for f in self.audio_output_dir.glob("*.wav"):
            if f.stat().st_mtime < cutoff:
                f.unlink()
                deleted += 1
        return deleted


# ═══════════════════════════════════════════════════════════════════
# 全局服务实例（单例）
# ═══════════════════════════════════════════════════════════════════

services = ServiceManager()

# ═══════════════════════════════════════════════════════════════════
# 请求/响应模型
# ═══════════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    text: str

class ChatResponse(BaseModel):
    user_input: str
    reply: str
    emotion: Dict[str, Any]
    safety: Dict[str, Any]
    retrieval_mode: str
    memories: List[Dict[str, Any]]
    audio_url: str | None = None
    type: str = "normal"

class MemorySearchRequest(BaseModel):
    query: str
    n_results: int = 5
    emotion_filter: str | None = None

class MemoryAddRequest(BaseModel):
    content: str
    emotion: str = "neutral"
    weight: float = 1.0

class EmotionRequest(BaseModel):
    text: str
    use_llm: bool = False

# ═══════════════════════════════════════════════════════════════════
# 静态文件与前端
# ═══════════════════════════════════════════════════════════════════

# 创建前端目录
STATIC_DIR = PROJECT_ROOT / "api_static"
STATIC_DIR.mkdir(exist_ok=True)

# 挂载静态文件（前端 HTML/CSS/JS）
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# 音频文件临时访问
AUDIO_DIR = PROJECT_ROOT / "api_output" / "audio"
AUDIO_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")

# ═══════════════════════════════════════════════════════════════════
# API 端点
# ═══════════════════════════════════════════════════════════════════

@app.get("/", response_class=HTMLResponse)
def index():
    """根路径：返回前端页面链接。"""
    return """
    <html>
    <head><title>VirtuMate API</title></head>
    <body>
        <h1>VirtuMate API Server</h1>
        <p><a href="/static/index.html">进入 Web 对话界面</a></p>
        <p><a href="/docs">API 文档 (Swagger UI)</a></p>
    </body>
    </html>
    """

@app.get("/health")
def health() -> Dict[str, Any]:
    """健康检查。"""
    return {
        "status": "ok",
        "services": {
            "llm": True,
            "tts": True,
            "asr": True,
            "memory_rag": services.memory_rag.store.is_ready if services.memory_rag.store else False,
            "safety_rag": services.safety_rag.store is not None and services.safety_rag.store.is_ready,
            "rules_manager": True,
            "episodic": True,
        },
        "timestamp": time.time(),
    }

@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> Dict[str, Any]:
    """文本对话：完整流程（安全检测 + 情感分析 + 检索 + LLM + TTS + 记忆存储）。"""
    return services.chat(req.text)

@app.post("/chat/voice")
def chat_voice(
    audio: UploadFile = File(...),
) -> JSONResponse:
    """语音对话：上传音频 → ASR → 完整对话流程 → 返回文本 + 音频 URL。"""
    # 保存上传的音频
    suffix = Path(audio.filename).suffix or ".wav"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(audio.file, tmp)
        tmp_path = Path(tmp.name)

    # ASR 识别
    user_text = services.asr_recognize(tmp_path)
    tmp_path.unlink(missing_ok=True)

    if not user_text:
        return JSONResponse({"error": "语音识别失败"}, status_code=400)

    # 走完整对话流程
    result = services.chat(user_text)
    result["asr_text"] = user_text
    return JSONResponse(result)

@app.post("/emotion/analyze")
def analyze_emotion(req: EmotionRequest) -> Dict[str, Any]:
    """情感分析。"""
    if req.use_llm:
        return _analyze_emotion_from_text(req.text, services.llm)
    return _keyword_emotion_fallback(req.text)

@app.post("/memory/search")
def search_memory(req: MemorySearchRequest) -> List[Dict[str, Any]]:
    """语义检索记忆。"""
    return services.memory_rag.search(
        req.query,
        n_results=req.n_results,
        emotion_filter=req.emotion_filter,
    )

@app.post("/memory/add")
def add_memory(req: MemoryAddRequest) -> Dict[str, Any]:
    """添加记忆。"""
    memory_id = services.memory_rag.add_memory(req.content, req.emotion, req.weight)
    return {"memory_id": memory_id, "status": "ok"}

@app.get("/memory/recent")
def recent_memory(limit: int = 10) -> List[Dict[str, Any]]:
    """获取最近记忆。"""
    return services.memory_rag.get_recent_conversations(limit=limit)

@app.post("/safety/check")
def check_safety(req: ChatRequest) -> Dict[str, Any]:
    """安全检测。"""
    return services.safety_rag.check_input(req.text)

@app.get("/episodic/stats")
def episodic_stats(hours: int = 24) -> Dict[str, Any]:
    """Episodic Memory 统计。"""
    return services.episodic.get_event_stats(hours)

@app.get("/episodic/recent")
def episodic_recent(limit: int = 10) -> List[Dict[str, Any]]:
    """最近时序事件。"""
    return services.episodic.get_recent_events(limit)

@app.post("/admin/cleanup")
def cleanup_audio() -> Dict[str, Any]:
    """清理过期音频文件。"""
    deleted = services.cleanup_audio()
    return {"deleted_files": deleted, "status": "ok"}

# ═══════════════════════════════════════════════════════════════════
# 前端 HTML（自动生成，也可替换为独立 React/Vue 项目）
# ═══════════════════════════════════════════════════════════════════

INDEX_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VirtuMate Web</title>
<style>
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: "Segoe UI", "Microsoft YaHei", sans-serif;
    background: #f0f4f8;
    display: flex; flex-direction: column; align-items: center;
    min-height: 100vh; padding: 20px;
}
.container { width: 100%; max-width: 700px; }
header {
    text-align: center; margin-bottom: 24px;
}
header h1 { color: #37474F; font-size: 1.8rem; }
header p { color: #78909C; font-size: 0.9rem; margin-top: 4px; }

/* 角色区域（用 CSS 动画替代 Live2D） */
.avatar-area {
    display: flex; flex-direction: column; align-items: center;
    margin-bottom: 20px;
}
.avatar {
    width: 120px; height: 120px; border-radius: 50%;
    background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
    display: flex; align-items: center; justify-content: center;
    font-size: 3rem; animation: breathe 3s ease-in-out infinite;
    box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
}
@keyframes breathe {
    0%, 100% { transform: scale(1); }
    50% { transform: scale(1.05); }
}
.emotion-tag {
    margin-top: 8px; padding: 4px 12px; border-radius: 12px;
    background: #EEF3F6; color: #37474F; font-size: 0.85rem;
}

/* 聊天区域 */
.chat-box {
    background: #fff; border-radius: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    padding: 16px; min-height: 300px; max-height: 400px;
    overflow-y: auto; margin-bottom: 16px;
}
.message {
    display: flex; flex-direction: column; margin-bottom: 12px;
    max-width: 80%;
}
.message.user { align-self: flex-end; align-items: flex-end; }
.message.bot { align-self: flex-start; align-items: flex-start; }
.bubble {
    padding: 10px 14px; border-radius: 14px; font-size: 0.95rem;
    line-height: 1.5; word-break: break-word;
}
.message.user .bubble { background: #667eea; color: #fff; border-bottom-right-radius: 4px; }
.message.bot .bubble { background: #EEF3F6; color: #37474F; border-bottom-left-radius: 4px; }
.time { font-size: 0.7rem; color: #90a4ae; margin-top: 2px; }

/* 输入区域 */
.input-area {
    display: flex; gap: 8px; align-items: flex-end;
    background: #fff; padding: 12px; border-radius: 12px;
    box-shadow: 0 2px 8px rgba(0,0,0,0.06);
}
.input-area textarea {
    flex: 1; border: 1px solid #e0e6ed; border-radius: 8px;
    padding: 10px; font-size: 0.95rem; resize: none; height: 60px;
    font-family: inherit;
}
.input-area button {
    border: none; border-radius: 8px; padding: 10px 16px;
    cursor: pointer; font-size: 0.9rem; transition: opacity 0.2s;
}
.input-area button:hover { opacity: 0.9; }
.btn-send { background: #667eea; color: #fff; }
.btn-voice { background: #EEF3F6; color: #37474F; }
.btn-record { background: #ff7043; color: #fff; }

/* 状态栏 */
.status-bar {
    display: flex; gap: 12px; margin-top: 12px; flex-wrap: wrap;
    justify-content: center; font-size: 0.8rem; color: #78909C;
}
.status-bar span { display: flex; align-items: center; gap: 4px; }
.dot { width: 8px; height: 8px; border-radius: 50%; background: #ccc; }
.dot.active { background: #66bb6a; }
.dot.warning { background: #ffa726; }

/* 安全提示 */
.safety-alert {
    background: #fff3e0; border-left: 4px solid #ff9800;
    padding: 10px 14px; border-radius: 4px;
    margin-bottom: 12px; font-size: 0.9rem; color: #e65100;
}

/* 音频播放器 */
.audio-player { margin-top: 6px; }
</style>
</head>
<body>
<div class="container">
    <header>
        <h1>VirtuMate Web</h1>
        <p>智能语音对话 · 情感感知 · RAG 记忆</p>
    </header>

    <div class="avatar-area">
        <div class="avatar" id="avatar">🤖</div>
        <div class="emotion-tag" id="emotion-tag">等待对话...</div>
    </div>

    <div class="chat-box" id="chat-box"></div>

    <div class="input-area">
        <textarea id="input-text" placeholder="输入消息，或点击录音..."></textarea>
        <button class="btn-send" onclick="sendText()">发送</button>
        <button class="btn-record" id="btn-record" onclick="toggleRecord()">🎤</button>
    </div>

    <div class="status-bar">
        <span><span class="dot active" id="dot-llm"></span>LLM</span>
        <span><span class="dot active" id="dot-tts"></span>TTS</span>
        <span><span class="dot active" id="dot-asr"></span>ASR</span>
        <span><span class="dot active" id="dot-memory"></span>Memory</span>
        <span><span class="dot active" id="dot-safety"></span>Safety</span>
    </div>
</div>

<script>
const API = window.location.origin;
let recording = false;
let mediaRecorder = null;
let audioChunks = [];

// 检查服务状态
async function checkHealth() {
    try {
        const res = await fetch(`${API}/health`);
        const data = await res.json();
        const s = data.services;
        document.getElementById('dot-llm').className = 'dot ' + (s.llm ? 'active' : 'warning');
        document.getElementById('dot-tts').className = 'dot ' + (s.tts ? 'active' : 'warning');
        document.getElementById('dot-asr').className = 'dot ' + (s.asr ? 'active' : 'warning');
        document.getElementById('dot-memory').className = 'dot ' + (s.memory_rag ? 'active' : 'warning');
        document.getElementById('dot-safety').className = 'dot ' + (s.safety_rag ? 'active' : 'warning');
    } catch (e) {
        console.error('Health check failed:', e);
    }
}
checkHealth();

// 发送文本消息
async function sendText() {
    const input = document.getElementById('input-text');
    const text = input.value.trim();
    if (!text) return;
    input.value = '';

    addMessage('user', text);
    setLoading(true);

    try {
        const res = await fetch(`${API}/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text })
        });
        const data = await res.json();
        handleReply(data);
    } catch (e) {
        addMessage('bot', '连接失败，请检查后端服务是否运行。');
    }
    setLoading(false);
}

// 处理回复
function handleReply(data) {
    // 安全拦截
    if (data.type === 'intercepted') {
        const alert = document.createElement('div');
        alert.className = 'safety-alert';
        alert.textContent = '【安全提示】' + data.reply;
        document.getElementById('chat-box').appendChild(alert);
        return;
    }

    // 情感标签
    const emotion = data.emotion?.emotion || 'neutral';
    const tagMap = { happy: '😊 开心', sad: '😢 难过', angry: '😠 生气', neutral: '😐 平静', fearful: '😨 害怕', anxious: '😰 焦虑', love: '❤️ 喜爱', upset: '😤 沮丧' };
    document.getElementById('emotion-tag').textContent = tagMap[emotion] || emotion;

    // 显示回复
    addMessage('bot', data.reply);

    // 播放音频
    if (data.audio_url) {
        const audio = document.createElement('audio');
        audio.src = data.audio_url;
        audio.controls = true;
        audio.className = 'audio-player';
        const lastMsg = document.querySelector('.message.bot:last-child');
        if (lastMsg) lastMsg.appendChild(audio);
    }

    // 显示记忆检索
    if (data.memories && data.memories.length > 0) {
        const memInfo = document.createElement('div');
        memInfo.className = 'time';
        memInfo.textContent = `🧠 检索到 ${data.memories.length} 条记忆（模式：${data.retrieval_mode}）`;
        const lastMsg = document.querySelector('.message.bot:last-child');
        if (lastMsg) lastMsg.appendChild(memInfo);
    }
}

// 添加消息到聊天框
function addMessage(role, text) {
    const box = document.getElementById('chat-box');
    const msg = document.createElement('div');
    msg.className = `message ${role}`;
    msg.innerHTML = `<div class="bubble">${escapeHtml(text)}</div><div class="time">${new Date().toLocaleTimeString()}</div>`;
    box.appendChild(msg);
    box.scrollTop = box.scrollHeight;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function setLoading(isLoading) {
    const avatar = document.getElementById('avatar');
    avatar.textContent = isLoading ? '⏳' : '🤖';
}

// 录音功能
async function toggleRecord() {
    if (!recording) {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);
            audioChunks = [];
            mediaRecorder.ondataavailable = e => audioChunks.push(e.data);
            mediaRecorder.onstop = async () => {
                const blob = new Blob(audioChunks, { type: 'audio/wav' });
                await sendVoice(blob);
            };
            mediaRecorder.start();
            recording = true;
            document.getElementById('btn-record').textContent = '⏹';
            document.getElementById('btn-record').style.background = '#ef5350';
        } catch (e) {
            alert('无法访问麦克风：' + e.message);
        }
    } else {
        mediaRecorder.stop();
        recording = false;
        document.getElementById('btn-record').textContent = '🎤';
        document.getElementById('btn-record').style.background = '#ff7043';
    }
}

// 发送语音
async function sendVoice(blob) {
    const form = new FormData();
    form.append('audio', blob, 'voice.wav');
    addMessage('user', '🎤 [语音消息]');
    setLoading(true);
    try {
        const res = await fetch(`${API}/chat/voice`, { method: 'POST', body: form });
        const data = await res.json();
        if (data.asr_text) {
            // 替换最后一条 [语音消息] 为识别文本
            const msgs = document.querySelectorAll('.message.user .bubble');
            const last = msgs[msgs.length - 1];
            if (last) last.textContent = data.asr_text;
        }
        handleReply(data);
    } catch (e) {
        addMessage('bot', '语音处理失败。');
    }
    setLoading(false);
}

// 回车发送
document.getElementById('input-text').addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendText(); }
});
</script>
</body>
</html>
"""

# 写入前端 HTML
(STATIC_DIR / "index.html").write_text(INDEX_HTML, encoding="utf-8")

# ═══════════════════════════════════════════════════════════════════
# 启动入口
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("  VirtuMate API Server")
    print("  访问 http://localhost:8000/static/index.html 进入 Web 界面")
    print("  访问 http://localhost:8000/docs 查看 API 文档")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=8000)
