"""
插件基类 —— 所有插件必须继承此类。

定义 7 个 Hook 生命周期方法 + 前端 HTML 接口。
每个 Hook 都有默认实现（空操作/返回原值），插件只需覆写自己需要的方法。
"""
# 开启延迟类型注解，支持类内自引用类型，Python3.7+语法
from __future__ import annotations

# 类型注解依赖：TYPE_CHECKING用于仅IDE静态检查、Any任意类型
from typing import TYPE_CHECKING, Any

# TYPE_CHECKING 仅在代码静态检查(IDE/mypy)时为True，运行时恒为False
# 避免运行时循环导入 main.py 的 MainManager
if TYPE_CHECKING:
    # 仅静态分析时导入主管理器，运行时不会执行这行import
    from main import MainManager


class PluginBase:
    """插件基类

    类属性（必须覆写）:
        name:    插件名称，唯一标识
        version: 版本号

    实例属性:
        enabled: 是否启用，默认 True
        app:     主管理器引用（on_startup 时注入）
    """

    # ---- 元信息（子类必须覆写）----
    # 插件唯一名称，默认占位值，子类必须重写
    name: str = "base"
    # 插件版本号，默认占位值，子类必须重写
    version: str = "1.0"

    def __init__(self) -> None:
        """插件实例初始化构造函数"""
        # 插件启用状态，默认开启
        self.enabled: bool = True
        # 主程序管理器实例引用，启动钩子时赋值，初始为空
        self.app: MainManager | None = None

    # ==================================================================
    #  Hook 生命周期（按调用顺序排列）
    # ==================================================================

    def on_startup(self, app: MainManager) -> None:
        """程序启动时调用，只调一次。

        用途：加载数据、注入初始 context、检查待办等。
        """
        # 将传入的主管理器保存到实例属性，插件后续可调用主程序能力
        self.app = app

    def on_user_input(self, text: str) -> str | None:
        """用户输入文本到达时调用（ASR 识别后 / 聊天框输入后）。

        Args:
            text: 用户原始输入文本

        Returns:
            处理后的文本；返回 None 表示不做修改。
        """
        # 默认无处理，返回None，上层逻辑会使用原始文本
        return None

    def on_llm_context(self, user_input: str) -> str:
        """LLM 请求前调用，生成要注入的额外上下文。

        Args:
            user_input: 用户当前输入文本

        Returns:
            要拼到 system prompt 末尾的额外上下文；返回 "" 表示无额外内容。
        """
        # 默认无额外上下文，返回空字符串
        return ""

    def on_llm_response(self, text: str) -> str | None:
        """LLM 返回回复后、TTS 合成前调用。

        Args:
            text: LLM 原始回复

        Returns:
            处理后的文本；返回 None 表示不做修改。
        """
        # 默认不修改大模型原始输出文本
        return None

    def on_before_tts(self, text: str) -> str | None:
        """TTS 合成前调用，可用于文本清理（去掉工具调用标记等）。

        Args:
            text: 待合成的文本

        Returns:
            清理后的文本；返回 None 表示不做修改。
        """
        # 默认不对语音合成文本做清洗处理
        return None

    def on_tick(self, app: MainManager) -> None:
        """主循环每轮对话末尾调用，用于定时任务（检查提醒等）。"""
        # 默认空实现，无定时逻辑
        pass

    def on_shutdown(self) -> None:
        """程序退出时调用，用于清理资源。"""
        # 默认空实现，无需资源释放
        pass

    # ==================================================================
    #  Graph 扩展 Hook（LangGraph 智能体模式）
    # ==================================================================

    def on_register_tools(self) -> list[dict]:
        """向 LangGraph 智能体注册工具定义。

        返回值是 OpenAI function-calling 格式的工具列表：
        [{"type": "function", "function": {"name": "...", "description": "...", "parameters": {...}}}]

        Returns:
            工具定义列表；返回空列表表示无工具。
        """
        return []

    def on_execute_tool(self, tool_name: str, tool_args: dict) -> str:
        """执行 LangGraph 智能体调用的工具。

        Args:
            tool_name: 工具名称
            tool_args: 工具参数

        Returns:
            工具执行结果字符串；返回 "" 表示不处理该工具。
        """
        return ""

    # ==================================================================
    #  前端
    # ==================================================================

    def get_frontend_html(self) -> str:
        """返回该插件的 HTML 界面片段，会被嵌入 ui_shell 的 Tab 面板。

        Returns:
            HTML 字符串；返回 "" 表示该插件无前端面板。
        """
        # 默认无前端可视化面板，返回空HTML字符串
        return ""

    # ==================================================================
    #  内置工具
    # ==================================================================

    def get_data_dir(self) -> str:
        """获取该插件的持久化数据目录，自动创建。"""
        # 局部导入os，仅调用此方法时才加载，减少启动导入开销
        import os
        # 拼接插件专属数据文件夹完整路径
        path = os.path.join(
            # 当前插件脚本所在文件夹绝对路径
            os.path.dirname(os.path.abspath(__file__)),
            # 统一插件数据根目录
            "plugins_data",
            # 以插件唯一name区分子文件夹，多插件数据隔离
            self.name,
        )
        # 创建目录，exist_ok=True：目录已存在不会抛出异常
        os.makedirs(path, exist_ok=True)
        # 返回插件数据目录绝对路径，用于读写配置、缓存文件
        return path