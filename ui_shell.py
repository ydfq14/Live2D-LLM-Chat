"""
前端容器 —— 用 pywebview 嵌入一个 HTML 窗口，承载所有插件的 UI 面板。

特性:
- Tab 顶部导航，一个插件一个 Tab
- JS API 桥接，前端 JS 可调用 Python 函数
- **必须在主线程运行** (pywebview 限制)，对话循环移到后台线程
- 无 pywebview 时优雅降级，主循环照常运行
"""

from __future__ import annotations

import json as _json
from typing import TYPE_CHECKING

from log_config import get_logger

if TYPE_CHECKING:
    from plugin_registry import PluginRegistry

logger = get_logger(__name__)


class UIShell:
    """pywebview 前端窗口管理器（必须主线程运行）"""

    def __init__(
        self,
        registry: PluginRegistry,
        text_input_queue: list[str],
        recording_abort,
        stop_event,
        busy_event,
    ) -> None:
        self._registry = registry
        self._window = None
        self._ready = False
        self._running = False
        # 由 main.py 显式传入，避免 import main 创建第二个模块副本
        self._text_input_queue = text_input_queue
        self._recording_abort = recording_abort
        self._stop_event = stop_event
        self._busy_event = busy_event

    # ==================================================================
    #  窗口启动
    # ==================================================================

    def start(self) -> bool:
        """检查条件并准备启动 pywebview 窗口。

        只做条件检查，不真正启动窗口。窗口由 run_on_main_thread() 在主线程启动。

        Returns:
            True 条件满足可启动，False 缺少 pywebview 或不满足条件。
        """
        # 检查是否有 UI 插件
        if not self._registry.has_ui_plugins():
            logger.info("[UIShell] 无 UI 插件，跳过前端窗口启动。")
            return False

        # 检查 pywebview
        try:
            import webview  # noqa: F401
        except ImportError:
            logger.warning("[UIShell] pywebview 未安装，跳过前端窗口。pip install pywebview")
            return False

        self._ready = True
        logger.info("[UIShell] 前端窗口准备就绪（等待主线程启动）。")
        return True

    def run_on_main_thread(self) -> None:
        """在主线程中启动 pywebview 窗口（阻塞直到窗口关闭）。"""
        if not self._ready:
            logger.info("[UIShell] 未就绪，跳过窗口启动。")
            return
        self._running = True
        logger.info("[UIShell] 前端窗口已启动。")
        self._run_window()
        self._running = False

    def _run_window(self) -> None:
        """pywebview 窗口主循环（在独立线程中运行）。"""
        import webview

        html = self._build_html()

        # 记录 HTML 生成情况
        logger.info("[UIShell] HTML 已生成，长度: %d 字符", len(html))

        # 检查关键 JavaScript 函数是否包含在 HTML 中
        if 'kbSelectAndUpload' in html:
            logger.info("[UIShell] ✓ kbSelectAndUpload 函数已包含在 HTML 中")
        else:
            logger.error("[UIShell] ✗ kbSelectAndUpload 函数未找到!")

        if 'testClick' in html:
            logger.info("[UIShell] ✓ testClick 函数已包含在 HTML 中")
        else:
            logger.error("[UIShell] ✗ testClick 函数未找到!")

        if 'kbRefreshFiles' in html:
            logger.info("[UIShell] ✓ kbRefreshFiles 函数已包含在 HTML 中")
        else:
            logger.error("[UIShell] ✗ kbRefreshFiles 函数未找到!")

        # 暴露给前端 JS 的 Python API
        class JSAPI:
            def __init__(self, shell: UIShell):
                self._shell = shell

            def send_text_input(self, text: str) -> str:
                """前端聊天框发送文本，推入主循环输入队列，同时中断录音。

                忙碌时拒绝输入，返回 error JSON。
                """
                if self._shell._busy_event.is_set():
                    return _json.dumps({"error": "busy", "message": "AI 正在录音或回答中，请稍候。"})
                self._shell._text_input_queue.append(text)
                self._shell._recording_abort.set()  # 中断正在进行的 VAD 录音
                logger.info(f"[UI] 聊天框输入: {text[:50]}...")
                return _json.dumps({"ok": True})

            def get_system_status(self) -> str:
                """前端轮询系统状态（忙碌/空闲）。"""
                return _json.dumps({
                    "busy": self._shell._busy_event.is_set(),
                })

            def call_plugin(self, plugin_name: str, method: str, *args: str) -> str:
                """前端调用指定插件的公开方法。"""
                plugin = self._shell._registry.get(plugin_name)
                if plugin is None or not plugin.enabled:
                    return f'{{"error": "plugin {plugin_name} not found"}}'
                func = getattr(plugin, method, None)
                if func is None:
                    return f'{{"error": "method {method} not found"}}'
                try:
                    return str(func(*args))
                except Exception as e:
                    return f'{{"error": "{e}"}}'

            def select_file(self, filename: str = "") -> str:
                """打开文件选择对话框，返回选择的文件路径。

                Args:
                    filename: 提示的文件名（可选）

                Returns:
                    文件路径字符串，如果取消则返回空字符串
                """
                logger.info("[UI] 文件选择对话框请求，提示文件名: %s", filename if filename else "无")
                try:
                    import webview
                    # 打开文件选择对话框
                    file_types = (
                        '文本文件 (*.txt;*.md;*.csv)',
                        'PDF 文件 (*.pdf)',
                        'JSON 文件 (*.json)',
                        '所有文件 (*.*)'
                    )
                    logger.debug("[UI] 打开文件选择对话框，支持类型: %s", file_types)
                    result = self._shell._window.create_file_dialog(
                        webview.OPEN_DIALOG,
                        allow_multiple=False,
                        file_types=file_types
                    )
                    if result and len(result) > 0:
                        file_path = result[0]
                        import os
                        file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
                        logger.info("[UI] ✓ 用户选择文件: %s (大小: %d bytes)", file_path, file_size)
                        return file_path
                    else:
                        logger.info("[UI] 用户取消文件选择")
                        return ""
                except Exception as e:
                    logger.error("[UI] ✗ 文件选择对话框失败: %s", str(e), exc_info=True)
                    return ""

        self._window = webview.create_window(
            title="VirtuMate — 助手面板",
            html=html,
            js_api=JSAPI(self),
            width=650,
            height=600,
            resizable=True,
            on_top=True,
        )
        # 启用调试模式，便于查看 JavaScript 错误
        logger.info("[UIShell] 启动 pywebview 窗口 (debug=True, http_server=False)")
        webview.start(debug=True, http_server=False)
        self._running = False

    # ==================================================================
    #  HTML 构建
    # ==================================================================

    def _build_html(self) -> str:
        """生成完整的 HTML 页面，含 Tab 导航和各插件面板。"""
        # 收集所有 UI 插件
        ui_plugins = [
            p for p in self._registry.enabled_plugins
            if p.get_frontend_html().strip()
        ]
        if not ui_plugins:
            return "<html><body><h2>无可用面板</h2></body></html>"

        # 构建 Tab 按钮
        tab_buttons: list[str] = []
        tab_panels: list[str] = []
        for i, plugin in enumerate(ui_plugins):
            active_cls = "active" if i == 0 else ""
            icon = getattr(plugin, 'tab_icon', '')
            tab_buttons.append(
                f'<button class="tab-btn {active_cls}" onclick="switchTab({i})">'
                f'<span class="tab-icon">{icon}</span>{plugin.name}</button>'
            )
            tab_panels.append(
                f'<div class="tab-panel" id="panel-{i}">'
                f'{plugin.get_frontend_html()}'
                f'</div>'
            )

        return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>VirtuMate 助手面板</title>
<style>
:root {{
    /* 基础调色板 */
    --bg: #0a0a1a;
    --bg-deep: #05050f;
    --surface: #111128;
    --surface-hover: #181840;
    --primary: #0f3460;
    --primary-light: #1a4a80;
    --accent: #e94560;
    --accent-glow: #ff2d55;
    --text: #e8e8f0;
    --text-muted: #7a7a9e;
    --radius: 8px;

    /* 赛博朋克霓虹色彩 */
    --neon-cyan: #00f0ff;
    --neon-pink: #ff2d95;
    --neon-purple: #b94eff;
    --neon-green: #39ff14;
    --neon-orange: #ff6b35;

    /* 发光效果颜色 */
    --glow-cyan: rgba(0, 240, 255, 0.4);
    --glow-pink: rgba(255, 45, 149, 0.4);
    --glow-accent: rgba(233, 69, 96, 0.5);

    /* 表面层次 */
    --surface-0: #0a0a1a;
    --surface-1: #111128;
    --surface-2: #1a1a3a;
    --surface-3: #222250;
    --border-subtle: rgba(255, 255, 255, 0.06);
    --border-glow: rgba(0, 240, 255, 0.2);

    /* 渐变 */
    --gradient-primary: linear-gradient(135deg, #0f3460 0%, #1a1a3a 100%);
    --gradient-accent: linear-gradient(135deg, #e94560 0%, #b94eff 100%);
    --gradient-surface: linear-gradient(180deg, #111128 0%, #0a0a1a 100%);

    /* 阴影 */
    --shadow-card: 0 4px 20px rgba(0, 0, 0, 0.4), 0 0 1px rgba(0, 240, 255, 0.1);
    --shadow-glow: 0 0 15px var(--glow-cyan), 0 0 40px rgba(0, 240, 255, 0.1);

    /* 动画时间 */
    --transition-fast: 0.15s ease;
    --transition-normal: 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    --transition-slow: 0.5s cubic-bezier(0.4, 0, 0.2, 1);
}}
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{
    font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
    background: var(--bg);
    background-image:
        radial-gradient(ellipse at 20% 80%, rgba(15, 52, 96, 0.3) 0%, transparent 50%),
        radial-gradient(ellipse at 80% 20%, rgba(185, 78, 255, 0.08) 0%, transparent 50%);
    color: var(--text);
    display: flex;
    flex-direction: column;
    height: 100vh;
    overflow: hidden;
}}
.tab-bar {{
    display: flex;
    background: rgba(17, 17, 40, 0.85);
    backdrop-filter: blur(12px);
    -webkit-backdrop-filter: blur(12px);
    border-bottom: 1px solid var(--border-glow);
    flex-shrink: 0;
    position: relative;
}}
.tab-bar::after {{
    content: '';
    position: absolute;
    bottom: 0;
    left: 0;
    right: 0;
    height: 1px;
    background: linear-gradient(90deg,
        transparent 0%,
        var(--neon-cyan) 20%,
        var(--neon-pink) 50%,
        var(--neon-cyan) 80%,
        transparent 100%);
    opacity: 0.3;
}}
.tab-btn {{
    flex: 1;
    padding: 14px 8px;
    background: none;
    border: none;
    color: var(--text-muted);
    font-size: 13px;
    font-weight: 500;
    cursor: pointer;
    transition: all var(--transition-normal);
    border-bottom: 2px solid transparent;
    position: relative;
    letter-spacing: 0.02em;
}}
.tab-btn:hover {{
    color: var(--text);
    background: rgba(0, 240, 255, 0.03);
}}
.tab-icon {{
    display: inline-block;
    margin-right: 6px;
    font-size: 14px;
}}
.tab-btn.active {{
    color: var(--neon-cyan);
    border-bottom-color: var(--neon-cyan);
    background: rgba(0, 240, 255, 0.05);
    text-shadow: 0 0 8px var(--glow-cyan);
}}
.tab-btn.active::after {{
    content: '';
    position: absolute;
    bottom: -1px;
    left: 10%;
    right: 10%;
    height: 2px;
    background: var(--neon-cyan);
    box-shadow: 0 0 8px var(--glow-cyan), 0 0 20px var(--glow-cyan);
    border-radius: 1px;
}}
.content {{
    flex: 1;
    overflow-y: auto;
    padding: 16px;
    position: relative;
    overflow-x: hidden;
}}
.tab-panel {{
    height: 100%;
    opacity: 0;
    transform: translateY(8px);
    transition: opacity var(--transition-normal), transform var(--transition-normal);
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    pointer-events: none;
    contain: content;
}}
.tab-panel.active {{
    opacity: 1;
    transform: translateY(0);
    pointer-events: auto;
}}
/* 滚动条美化 */
.content::-webkit-scrollbar {{ width: 4px; }}
.content::-webkit-scrollbar-track {{ background: transparent; }}
.content::-webkit-scrollbar-thumb {{
    background: var(--primary-light);
    border-radius: 2px;
}}
.content::-webkit-scrollbar-thumb:hover {{
    background: var(--neon-cyan);
    box-shadow: 0 0 6px var(--glow-cyan);
}}
</style>
</head>
<body>
<div class="tab-bar">
    {''.join(tab_buttons)}
</div>
<div class="content">
    {''.join(tab_panels)}
</div>
<script>
function switchTab(idx) {{
    document.querySelectorAll('.tab-btn').forEach((btn,i) => {{
        btn.classList.toggle('active', i === idx);
    }});
    document.querySelectorAll('.tab-panel').forEach((panel,i) => {{
        panel.classList.toggle('active', i === idx);
    }});
}}
// 初始化第一个 Tab 为活跃状态
document.addEventListener('DOMContentLoaded', function() {{
    const firstPanel = document.querySelector('.tab-panel');
    if (firstPanel) {{
        firstPanel.classList.add('active');
    }}
}});
</script>
</body>
</html>"""

    # ==================================================================
    #  管理
    # ==================================================================

    @property
    def is_running(self) -> bool:
        return self._running

    def stop(self) -> None:
        """关闭前端窗口。"""
        self._running = False
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:
                pass
        logger.info("[UIShell] 前端窗口已关闭。")
