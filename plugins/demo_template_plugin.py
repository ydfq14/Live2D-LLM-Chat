"""
示例插件 —— 向组员展示插件开发模板。

功能：在每轮对话时打印一条日志，演示 7 个 Hook 的使用方式。

用法：复制此文件，改类名和 name，填自己的逻辑即可。
"""

from plugin_base import PluginBase
from log_config import get_logger

logger = get_logger(__name__)


class DemoTemplatePlugin(PluginBase):
    """插件开发模板 —— 组员照此格式写自己的插件"""

    # ---- 元信息（必须覆写）----
    name = "demo_template"
    version = "1.0"

    # ==================================================================
    #  Hook 实现（按需覆写，不需要的删掉即可）
    # ==================================================================

    def on_startup(self, app) -> None:
        """程序启动时调用，只调一次。"""
        super().on_startup(app)
        logger.info(f"[{self.name}] 插件已启动！")

        # 示例：从插件数据目录加载持久化数据
        data_dir = self.get_data_dir()
        logger.info(f"[{self.name}] 数据目录: {data_dir}")

    def on_user_input(self, text: str) -> str | None:
        """用户输入到达时调用。返回修改后的文本，或 None 表示不修改。"""
        logger.debug(f"[{self.name}] 收到用户输入: {text[:50]}...")
        return None  # 不修改

    def on_llm_context(self, user_input: str) -> str:
        """LLM 请求前调用，返回要注入 system prompt 的额外上下文。"""
        # 示例：告诉 LLM 当前日期
        import datetime
        today = datetime.date.today().strftime("%Y年%m月%d日")
        return f"（系统提示：今天是{today}，请在回复中体现这一点）"

    def on_llm_response(self, text: str) -> str | None:
        """LLM 回复后调用。返回修改后的文本，或 None 表示不修改。"""
        logger.debug(f"[{self.name}] LLM 回复: {text[:50]}...")
        return None

    def on_before_tts(self, text: str) -> str | None:
        """TTS 合成前调用，可用于清理文本（去标记等）。"""
        return None

    def on_tick(self, app) -> None:
        """每轮对话末尾调用（大约每秒一次），用于定时任务。"""
        pass

    def on_shutdown(self) -> None:
        """程序退出时调用，清理资源。"""
        logger.info(f"[{self.name}] 插件已关闭。")

    def get_frontend_html(self) -> str:
        """返回该插件的 HTML 面板。返回 "" 表示无前端。"""
        return """
        <div style="padding:12px">
            <h3 style="color:#e94560; margin-bottom:12px">[示例插件面板]</h3>
            <p style="color:#aaa; font-size:13px">
                这是插件开发模板的前端面板。<br>
                组员替换为自己的 HTML 即可。
            </p>
            <p style="color:#aaa; font-size:13px; margin-top:8px">
                可用 JS API：<br>
                <code>pywebview.api.send_text_input("文本")</code> — 发送聊天消息<br>
                <code>pywebview.api.call_plugin("插件名", "方法", ...)</code> — 调用插件方法
            </p>
        </div>
        """
