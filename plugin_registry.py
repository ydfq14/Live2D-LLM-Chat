"""
插件注册中心 —— 自动发现、加载、管理所有插件。

核心职责：
1. 扫描 plugins/ 目录，用 importlib 动态加载所有插件类
2. 提供启用/禁用/卸载管理
3. broadcast() 向所有已启用插件广播事件（单个插件出错不中断链）
"""
# 支持延后类型注解，允许类内引用自身、循环导入类型标注
from __future__ import annotations

# 动态导入模块工具，用于加载插件py文件
import importlib
# 反射工具，遍历模块内所有类、对象
import inspect
# 文件路径、目录操作标准库
import os
# Python模块搜索路径管理
import sys
# 异常堆栈打印，用于插件加载错误调试
import traceback
# 类型注解相关：静态检查标记、任意类型、可调用对象
from typing import TYPE_CHECKING, Any, Callable

# 导入插件基类，所有插件都继承PluginBase
from plugin_base import PluginBase
# 日志工具，获取全局日志实例
from log_config import get_logger

# TYPE_CHECKING 仅IDE/mypy静态检查时为True，运行时为False，规避循环导入
if TYPE_CHECKING:
    # 仅静态分析导入主管理器，运行时不会执行该行代码
    from main import MainManager

# 初始化日志记录器，统一打印插件中心日志
logger = get_logger(__name__)


class PluginRegistry:
    """插件注册中心（单例模式，整个程序只有一个实例）"""

    def __init__(self) -> None:
        # 插件存储字典：key=插件唯一name，value=插件实例对象
        self._plugins: dict[str, PluginBase] = {}
        # 拼接插件目录完整路径：当前脚本同级的plugins文件夹
        self._plugin_dir: str = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "plugins"
        )

    # ==================================================================
    #  发现与加载：自动扫描并实例化所有插件
    # ==================================================================

    def scan_and_load(self) -> list[str]:
        """扫描 plugins/ 目录，自动加载所有合法插件。

        Returns:
            成功加载的插件名称列表。
        """
        # 记录加载成功的插件名，用于返回
        loaded: list[str] = []

        logger.info("[插件] 扫描目录: %s", self._plugin_dir)

        # 判断插件目录是否真实存在，不存在直接返回空列表
        if not os.path.isdir(self._plugin_dir):
            logger.warning("[插件] 目录不存在，跳过: %s", self._plugin_dir)
            return loaded

        # 将插件目录加入Python模块搜索路径，否则无法import插件文件
        if self._plugin_dir not in sys.path:
            sys.path.insert(0, self._plugin_dir)

        # 按文件名排序遍历plugins目录下所有文件
        candidates = [f for f in sorted(os.listdir(self._plugin_dir)) if f.endswith("_plugin.py")]
        logger.info("[插件] 发现 %d 个候选文件: %s", len(candidates), candidates if candidates else "(无)")

        for filename in candidates:
            # 去除.py后缀，得到模块名，用于动态import
            mod_name = filename[:-3]
            try:
                # 动态导入插件模块
                module = importlib.import_module(mod_name)
                # 遍历模块内所有成员，筛选类对象
                for _name, obj in inspect.getmembers(module, inspect.isclass):
                    # 筛选条件：
                    # 1. 是PluginBase的子类
                    # 2. 不是基类本身，排除PluginBase
                    # 3. 类定义在当前插件模块中，避免导入其他模块的子类
                    if (
                        issubclass(obj, PluginBase)
                        and obj is not PluginBase
                        and obj.__module__ == module.__name__
                    ):
                        # 实例化插件类
                        instance = obj()
                        # 将插件实例注册到容器
                        self.register(instance)
                        # 记录已加载插件名称
                        loaded.append(instance.name)

                        # 列出该插件覆写了哪些 Hook
                        hooks = []
                        for hook in ("on_user_input", "on_llm_context", "on_llm_response",
                                     "on_before_tts", "on_tick", "on_register_tools",
                                     "on_execute_tool", "get_frontend_html"):
                            base_method = getattr(PluginBase, hook)
                            override = getattr(type(instance), hook)
                            if override is not base_method:
                                hooks.append(hook)
                        logger.info("  [OK] %s v%s  (Hook: %s)", instance.name, instance.version,
                                    ", ".join(hooks) if hooks else "无覆写")

            except Exception as e:
                # 捕获单个插件加载全部异常，防止一个插件损坏导致全部加载失败
                logger.error("[插件] [FAIL] 加载失败: %s — %s", mod_name, e)
                # 打印完整异常堆栈，方便定位插件代码错误
                logger.debug(traceback.format_exc())

        logger.info("[插件] 扫描完成: 成功加载 %d/%d 个", len(loaded), len(candidates))
        # 返回所有加载成功的插件名称
        return loaded

    # ==================================================================
    #  插件生命周期管理：注册、卸载、启用、禁用
    # ==================================================================

    def register(self, plugin: PluginBase) -> None:
        """手动注册一个插件实例（scan 已自动调用，通常不需要手动调）。"""
        # 判断同名插件已存在，打印覆盖警告
        if plugin.name in self._plugins:
            logger.warning(f"[PluginRegistry] 插件 {plugin.name} 已存在，覆盖旧实例")
        # 存入插件字典，完成注册
        self._plugins[plugin.name] = plugin

    def unregister(self, name: str) -> bool:
        """卸载插件（调用 on_shutdown 后移除）。"""
        # 根据插件名称查找实例
        plugin = self._plugins.get(name)
        # 未找到插件直接返回False
        if not plugin:
            logger.warning(f"[PluginRegistry] 插件不存在: {name}")
            return False
        try:
            # 执行插件退出清理钩子
            plugin.on_shutdown()
        except Exception as e:
            # 清理出错仅打印日志，不阻止插件移除
            logger.error(f"[PluginRegistry] 插件 {name} on_shutdown 出错: {e}")
        # 从容器删除插件实例
        del self._plugins[name]
        logger.info(f"[PluginRegistry] 已卸载插件: {name}")
        # 卸载成功返回True
        return True

    def enable(self, name: str) -> bool:
        """启用插件。"""
        plugin = self._plugins.get(name)
        # 插件不存在返回False
        if not plugin:
            return False
        # 修改启用标记为True
        plugin.enabled = True
        logger.info(f"[PluginRegistry] 已启用: {name}")
        return True

    def disable(self, name: str) -> bool:
        """禁用插件（不卸载，保留实例）。"""
        plugin = self._plugins.get(name)
        # 插件不存在返回False
        if not plugin:
            return False
        # 修改启用标记为False，事件广播时会跳过该插件
        plugin.enabled = False
        logger.info(f"[PluginRegistry] 已禁用: {name}")
        return True

    # ==================================================================
    #  查询接口：获取插件列表、单个插件、UI判断
    # ==================================================================

    @property
    def plugins(self) -> dict[str, PluginBase]:
        """只读属性，返回全部已加载插件字典"""
        return self._plugins

    @property
    def enabled_plugins(self) -> list[PluginBase]:
        """只读属性，返回所有当前启用状态的插件实例列表"""
        return [p for p in self._plugins.values() if p.enabled]

    @property
    def plugin_names(self) -> list[str]:
        """只读属性，返回所有已加载插件名称列表"""
        return list(self._plugins.keys())

    def get(self, name: str) -> PluginBase | None:
        """根据插件名获取插件实例，不存在返回None"""
        return self._plugins.get(name)

    def has_ui_plugins(self) -> bool:
        """是否有任何已启用插件提供了前端 HTML。"""
        # 遍历启用插件，任意插件返回非空HTML片段则返回True
        return any(
            p.get_frontend_html().strip()
            for p in self.enabled_plugins
        )

    # ==================================================================
    #  事件广播：批量执行所有启用插件的生命周期Hook
    # ==================================================================

    def broadcast(self, hook_name: str, *args: Any) -> list[Any]:
        """向所有已启用插件广播 Hook 事件。

        每个插件独立 try/except，单插件报错不中断链。

        Args:
            hook_name: Hook 方法名，如 "on_user_input"
            *args:    传递给 Hook 方法的参数

        Returns:
            所有插件返回值的列表（None 值已过滤）。
        """
        # 收集所有插件Hook的有效返回结果
        results: list[Any] = []
        # 遍历所有启用状态插件
        for plugin in self.enabled_plugins:
            # 反射获取插件对应的hook方法，不存在返回None
            method: Callable | None = getattr(plugin, hook_name, None)
            # 插件未实现该钩子，直接跳过
            if method is None:
                continue
            try:
                # 执行插件钩子方法，传入参数
                result = method(*args)
                # 过滤None返回值，只保存有效结果
                if result is not None:
                    results.append(result)
            except Exception as e:
                # 单个插件执行异常仅打印日志，不打断整个广播流程
                logger.error(
                    f"[PluginRegistry] 插件 {plugin.name}.{hook_name}() 出错: {e}"
                )
                # 打印异常堆栈用于调试
                logger.debug(traceback.format_exc())
        # 返回所有插件钩子的返回结果集合
        return results

    def broadcast_on_startup(self, app: MainManager) -> None:
        """on_startup 广播（特殊处理：注入 app 主管理器引用）。"""
        # 封装启动钩子广播，统一传入主管理器实例
        self.broadcast("on_startup", app)

    def broadcast_on_shutdown(self) -> None:
        """on_shutdown 广播。"""
        # 封装退出清理钩子广播
        self.broadcast("on_shutdown")

    # ==================================================================
    #  LangGraph 工具注册与执行
    # ==================================================================

    def collect_tools(self) -> list[dict]:
        """收集所有已启用插件注册的 OpenAI 格式工具定义。

        Returns:
            合并后的工具定义列表。
        """
        # 初始化空列表，用于存放全部插件的标准OpenAI工具字典
        tools: list[dict] = []
        # 遍历当前所有已启用的插件实例
        for plugin in self.enabled_plugins:
            try:
                # 调用插件的工具注册钩子，获取该插件提供的全部工具定义数组
                plugin_tools = plugin.on_register_tools()
                # 判断插件是否返回了有效工具列表（非空）
                if plugin_tools:
                    # 提取当前插件所有工具的名称，用于日志打印
                    tool_names = [t.get("function", {}).get("name", "?") for t in plugin_tools]
                    # 打印调试日志：输出当前插件名与它注册的所有工具名
                    logger.debug("[插件] %s 注册工具: %s", plugin.name, tool_names)
                    # 将当前插件的工具列表追加到总工具集合中
                    tools.extend(plugin_tools)
            except Exception as e:
                # 捕获单个插件注册工具时的异常，避免整个收集流程崩溃
                logger.error("[插件] %s.on_register_tools() 出错: %s", plugin.name, e)
        # 如果收集到了至少一个工具，打印总工具数量调试日志
        if tools:
            logger.debug("[插件] 共收集 %d 个工具", len(tools))
        # 返回整合完成的、符合OpenAI协议标准的全部工具定义列表
        return tools

    def execute_tool(self, tool_name: str, tool_args: dict) -> str:
        """遍历所有已启用插件，执行指定工具。

        Args:
            tool_name: 工具名称
            tool_args: 工具参数

        Returns:
            工具执行结果字符串；如果没有任何插件处理该工具，返回错误提示。
        """
        for plugin in self.enabled_plugins:
            try:
                result = plugin.on_execute_tool(tool_name, tool_args)
                if result:
                    logger.debug("[插件] %s 执行工具 %s → 结果 %d 字符", plugin.name, tool_name, len(result))
                    return result
            except Exception as e:
                logger.error("[插件] %s.on_execute_tool(%s) 出错: %s", plugin.name, tool_name, e)
        logger.warning("[插件] 工具 '%s' 无插件可执行", tool_name)
        return f"[工具未注册] 没有插件可以执行 '{tool_name}'。"