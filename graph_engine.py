"""
LangGraph 智能体引擎 —— 替代原管道模式的对话处理核心。

基于 LangGraph StateGraph，支持：
  - 多步工具调用循环（LLM 决定调用工具 → 执行 → 再思考 → 最终回复）
  - 插件通过 on_register_tools / on_execute_tool 注册工具
  - 所有原有插件 Hook 在对应节点触发，与管道模式完全兼容

流程图:
  get_input → process_user_input → check_exit
    → (退出) → END
    → (继续) → gather_context → agent_think
        → (需工具) → tool_executor → agent_think (循环)
        → (完成) → process_response → prepare_tts → live2d_output → post_tick → END
"""
# 支持在类注解中引用自身类，消除Python版本注解报错
from __future__ import annotations

# 导入标准json，起别名防止和局部变量冲突，用于解析工具调用参数
import json as _json
# 标准日志模块，此处未直接使用，仅预留扩展
import logging
# 类型提示工具：仅IDE静态检查生效，运行时不加载
from typing import TYPE_CHECKING, Any, TypedDict

# LangGraph核心组件：状态图构建器、流程终止标记END
from langgraph.graph import StateGraph, END

# 项目统一日志工厂，获取模块专属日志器
from log_config import get_logger

# TYPE_CHECKING运行时恒为False，仅静态检查导入，避免循环导入
if TYPE_CHECKING:
    # 仅做类型注解，运行不会加载这些模块
    from LLM import LLMManager
    from TTS import TTSManager
    from Live2d_animation import Live2DAnimationManager
    from plugin_registry import PluginRegistry

# 创建当前文件专属日志实例，日志打印会携带graph_engine标识
logger = get_logger(__name__)


# ==================================================================
#  状态定义：单轮对话全局数据载体
# ==================================================================
class AgentState(TypedDict, total=False):
    """LangGraph 智能体状态（一次对话轮次的状态快照）。
    图内所有节点共享、读写该字典；LangGraph自动管理状态流转、版本隔离。
    total=False：所有字段可选，节点只需返回修改的字段，不用全量返回
    """

    # 本轮用户输入信息
    user_input: str        # 用户原始文本（语音识别/网页聊天框）
    user_source: str       # 输入来源枚举："voice"麦克风 / "chatbox"网页输入

    # 对话上下文，遵循OpenAI消息格式
    messages: list[dict[str, Any]]

    # LLM推理原始输出
    llm_content: str       # LLM原生返回文本（未经过插件后处理）
    tool_calls: list[dict[str, Any]] | None  # LLM要求执行的工具调用列表，无则为None

    # 工具执行结果缓存
    tool_results: list[dict[str, Any]]  # 本轮所有工具执行返回结果

    # 最终输出产物
    final_reply: str       # 经过所有插件Hook处理后的最终回复文本
    audio_path: str        # TTS合成生成的音频本地路径

    # 流程控制标记
    should_exit: bool      # 标记是否需要结束整个对话程序
    round_num: int         # 当前是第几轮对话

    # 插件扩展上下文
    extra_context: str     # 所有插件通过on_llm_context钩子注入的补充信息（时间、记忆、系统状态等）

    # 工具循环防死锁计数
    tool_loop_count: int   # 当前工具调用循环次数，限制最大循环次数避免无限递归


# ==================================================================
#  图引擎顶层主类：对话流程调度核心
# ==================================================================
class GraphEngine:
    """LangGraph 对话处理引擎。
    替换老式线性管道，支持分支、条件路由、工具循环，兼容全部插件生命周期钩子

    标准调用示例:
        engine = GraphEngine(llm_manager, tts_manager, live2d_manager, registry)
        result = engine.invoke({
            "user_input": "...",
            "user_source": "voice",
            "messages": [...],
            "round_num": 1,
        })
        # 返回结果关键字段说明
        # result["final_reply"] → AI最终回复文本
        # result["messages"]   → 更新完毕的完整对话历史
        # result["should_exit"] → 是否触发程序退出
    """

    # 类常量：单轮对话最多允许5次工具循环，防止LLM无限调用工具卡死
    MAX_TOOL_LOOPS = 5

    def __init__(
        self,
        llm_manager: LLMManager,               # 大模型管理器实例
        tts_manager: TTSManager,               # 语音合成管理器实例
        live2d_manager: Live2DAnimationManager,# Live2D虚拟形象动画管理器
        registry: PluginRegistry,              # 插件注册中心，管理钩子、工具
    ) -> None:
        # 依赖注入：保存外部模块引用，各节点内直接调用
        self.llm = llm_manager
        self.tts = tts_manager
        self.live2d = live2d_manager
        self.registry = registry

        # 开始构建LangGraph流程图
        logger.info("================================================================")
        logger.info("  [GraphEngine] 开始构建 LangGraph 智能体图...")
        logger.info("================================================================")
        # 调用内部方法构建、编译状态图，保存编译后的可执行图
        self._graph = self._build_graph()
        # 打印ASCII流程图到日志，方便调试查看整体流程拓扑
        self._print_graph_structure()
        logger.info("  [GraphEngine] 图构建完成，编译成功。")
        logger.info("================================================================")

    # ==================================================================
    #  图结构定义：注册节点、连接边、配置条件分支
    # ==================================================================
    def _build_graph(self) -> StateGraph:
        """构建 LangGraph 状态图，注册全部业务节点、静态边、条件路由分支。
        返回编译完成的可执行图对象
        """
        # 实例化状态图构建器，绑定全局状态类型AgentState
        builder = StateGraph(AgentState)

        # --- 1. 注册所有业务节点（每个节点对应一段独立处理逻辑） ---
        # 打印调试日志：当前正在注册名为 process_user_input 的业务节点
        logger.debug("   注册节点: process_user_input")
        # 向状态图构建器注册节点，节点标识字符串为 "process_user_input"，绑定处理函数 self._node_process_user_input
        builder.add_node("process_user_input", self._node_process_user_input)

        # 打印调试日志：当前正在注册名为 check_exit 的业务节点
        logger.debug("   注册节点: check_exit")
        # 注册check_exit节点，绑定退出检测逻辑函数 _node_check_exit
        builder.add_node("check_exit", self._node_check_exit)

        # 打印调试日志：当前正在注册名为 gather_context 的业务节点
        logger.debug("   注册节点: gather_context")
        # 注册上下文收集节点，绑定插件上下文采集函数 _node_gather_context
        builder.add_node("gather_context", self._node_gather_context)

        # 打印调试日志：当前正在注册名为 agent_think 的业务节点
        logger.debug("   注册节点: agent_think")
        # 注册LLM推理核心节点，绑定模型思考与工具判断函数 _node_agent_think
        builder.add_node("agent_think", self._node_agent_think)

        # 打印调试日志：当前正在注册名为 tool_executor 的业务节点
        logger.debug("   注册节点: tool_executor")
        # 注册工具执行节点，绑定插件工具调用执行函数 _node_tool_executor
        builder.add_node("tool_executor", self._node_tool_executor)

        # 打印调试日志：当前正在注册名为 process_response 的业务节点
        logger.debug("   注册节点: process_response")
        # 注册回复后处理节点，绑定AI回复润色、过滤钩子函数 _node_process_response
        builder.add_node("process_response", self._node_process_response)

        # 打印调试日志：当前正在注册名为 prepare_tts 的业务节点
        logger.debug("   注册节点: prepare_tts")
        # 注册TTS语音合成节点，绑定文本清洗+语音生成函数 _node_prepare_tts
        builder.add_node("prepare_tts", self._node_prepare_tts)

        # 打印调试日志：当前正在注册名为 live2d_output 的业务节点
        logger.debug("   注册节点: live2d_output")
        # 注册虚拟人播放节点，绑定音频播放+嘴型同步函数 _node_live2d_output
        builder.add_node("live2d_output", self._node_live2d_output)

        # 打印调试日志：当前正在注册名为 post_tick 的业务节点
        logger.debug("   注册节点: post_tick")
        # 注册单轮对话收尾节点，绑定每轮结束全局钩子函数 _node_post_tick
        builder.add_node("post_tick", self._node_post_tick)





        # --- 2. 配置流程走向（边：节点之间的跳转规则） ---
        # 设置整个图的入口节点：对话流程从process_user_input开始
        logger.debug("   设置入口: → process_user_input")
        builder.set_entry_point("process_user_input")

        # 静态边：输入处理完成后，无条件进入退出检测节点
        logger.debug("   静态边: process_user_input → check_exit")
        builder.add_edge("process_user_input", "check_exit")

        # 条件分支1：检测退出后二选一
        logger.debug("   条件边: check_exit → {exit | gather_context}")
        builder.add_conditional_edges(
            "check_exit",               # 分支来源节点
            self._route_after_check,    # 路由判断函数，返回分支标识
            {"exit": END, "continue": "gather_context"}, # 分支标识映射目标节点
        )

        # 静态边：上下文收集完成，进入LLM推理节点
        logger.debug("   静态边: gather_context → agent_think")
        builder.add_edge("gather_context", "agent_think")

        # 条件分支2：LLM思考完成后分两路（工具循环 / 生成最终回复）
        logger.debug("   条件边: agent_think → {tool_executor | process_response}")
        builder.add_conditional_edges(
            "agent_think",
            self._route_after_think,
            {"tool": "tool_executor", "done": "process_response"},
        )

        # 静态循环边：工具执行完毕，回到LLM重新思考（形成工具调用循环）
        logger.debug("   静态边: tool_executor → agent_think (循环)")
        builder.add_edge("tool_executor", "agent_think")

        # 线性后置流程：回复处理 → TTS合成 → Live2D播放 → 收尾钩子 → 流程结束
        logger.debug("   静态边: process_response → prepare_tts")
        builder.add_edge("process_response", "prepare_tts")

        logger.debug("   静态边: prepare_tts → live2d_output")
        builder.add_edge("prepare_tts", "live2d_output")

        logger.debug("   静态边: live2d_output → post_tick")
        builder.add_edge("live2d_output", "post_tick")

        logger.debug("   静态边: post_tick → END")
        builder.add_edge("post_tick", END)

        # 编译流程图，生成可调用执行对象并返回
        return builder.compile()

    def _print_graph_structure(self) -> None:
        """打印ASCII格式流程图到日志，直观展示对话全流程拓扑结构"""
        logger.info("  ┌──────────────────────────────────────────────────────────┐")
        logger.info("  │               LangGraph Agent 拓扑图                      │")
        logger.info("  ├──────────────────────────────────────────────────────────┤")
        logger.info("  │                                                          │")
        logger.info("  │  [入口]                                                  │")
        logger.info("  │    │                                                     │")
        logger.info("  │    ▼                                                     │")
        logger.info("  │  ┌─────────────────┐                                     │")
        logger.info("  │  │ process_        │── 广播 on_user_input                │")
        logger.info("  │  │ user_input      │                                     │")
        logger.info("  │  └────────┬────────┘                                     │")
        logger.info("  │           │                                              │")
        logger.info("  │           ▼                                              │")
        logger.info("  │  ┌─────────────────┐                                     │")
        logger.info("  │  │ check_exit      │── 退出词检测                        │")
        logger.info("  │  └────┬───────┬────┘                                     │")
        logger.info("  │       │ exit  │ continue                                 │")
        logger.info("  │       ▼       ▼                                          │")
        logger.info("  │     END   ┌─────────────────┐                            │")
        logger.info("  │           │ gather_context  │── 广播 on_llm_context      │")
        logger.info("  │           └────────┬────────┘                            │")
        logger.info("  │                    │                                     │")
        logger.info("  │                    ▼                                     │")
        logger.info("  │  ┌─────────────────┐        ┌─────────────────┐          │")
        logger.info("  │  │ agent_think     │──tool─→│ tool_executor   │          │")
        logger.info("  │  │  LLM 推理       │←───────│  执行插件工具   │          │")
        logger.info("  │  └────────┬────────┘ 循环   └─────────────────┘          │")
        logger.info("  │           │ done             最多 {} 次                   │".format(self.MAX_TOOL_LOOPS))
        logger.info("  │           ▼                                              │")
        logger.info("  │  ┌─────────────────┐                                     │")
        logger.info("  │  │ process_response│── 广播 on_llm_response              │")
        logger.info("  │  └────────┬────────┘                                     │")
        logger.info("  │           │                                              │")
        logger.info("  │           ▼                                              │")
        logger.info("  │  ┌─────────────────┐                                     │")
        logger.info("  │  │ prepare_tts     │── 广播 on_before_tts + 合成         │")
        logger.info("  │  └────────┬────────┘                                     │")
        logger.info("  │           │                                              │")
        logger.info("  │           ▼                                              │")
        logger.info("  │  ┌─────────────────┐                                     │")
        logger.info("  │  │ live2d_output   │── 嘴型同步播放                     │")
        logger.info("  │  └────────┬────────┘                                     │")
        logger.info("  │           │                                              │")
        logger.info("  │           ▼                                              │")
        logger.info("  │  ┌─────────────────┐                                     │")
        logger.info("  │  │ post_tick       │── 广播 on_tick                     │")
        logger.info("  │  └────────┬────────┘                                     │")
        logger.info("  │           │                                              │")
        logger.info("  │           ▼                                              │")
        logger.info("  │          END                                             │")
        logger.info("  │                                                          │")
        logger.info("  └──────────────────────────────────────────────────────────┘")

    def _route_after_check(self, state: AgentState) -> str:
        """check_exit节点的路由判断函数
        读取状态中的should_exit标记，返回分支标识：exit / continue
        """
        # 判断是否需要退出程序
        decision = "exit" if state.get("should_exit") else "continue"
        # 打印路由跳转日志
        target = "END" if decision == "exit" else "gather_context"
        logger.info("  │ [路由] check_exit ──%s──▶ %s", decision, target)
        return decision

    def _route_after_think(self, state: AgentState) -> str:
        """agent_think节点的路由判断函数
        1. 存在工具调用 且 循环次数未达上限 → 返回tool，去执行工具
        2. 无工具调用/达到最大循环 → 返回done，生成最终回复
        """
        tool_calls = state.get("tool_calls")
        loop_count = state.get("tool_loop_count", 0)
        # 满足工具调用条件，进入工具执行循环
        if tool_calls and loop_count < self.MAX_TOOL_LOOPS:
            logger.info("  │ [路由] agent_think ──tool──▶ tool_executor  (循环 %d/%d)", loop_count, self.MAX_TOOL_LOOPS)
            return "tool"
        # 无需调用工具，直接处理回复
        logger.info("  │ [路由] agent_think ──done──▶ process_response")
        return "done"

    # ==================================================================
    #  全部业务节点实现：流程图中每一步的具体逻辑
    # ==================================================================
    def _node_process_user_input(self, state: AgentState) -> dict[str, Any]:
        """节点1：用户输入预处理
        广播on_user_input插件钩子，允许插件拦截、修改用户原始输入文本
        返回更新后的user_input，LangGraph自动合并进全局状态
        """
        # 从状态字典取出用户原始输入文本
        user_input = state["user_input"]
        # 读取输入来源，无数据则默认voice语音输入
        source = state.get("user_source", "voice")
        # 获取当前对话轮次编号，不存在则默认0
        round_num = state.get("round_num", 0)

        # 打印分割日志，标记节点开始
        logger.info("┌──────────────────────────────────────────────────────────────")
        # 日志打印当前执行节点名称
        logger.info("│ [节点] process_user_input")
        # 打印输入来源，截取前80个字符展示原始用户文本
        logger.info("│   输入来源: %s | 文本: %s", source, user_input[:80])

        # 创建空列表，存放各个插件处理后带标识的文本片段
        parts = []
        # 遍历全部已启用的插件，逐个执行on_user_input钩子
        for plugin in self.registry.enabled_plugins:
            # 捕获单个插件运行异常，防止一个插件报错导致整个流程中断
            try:
                # 执行当前插件的on_user_input方法，传入原始用户输入，拿到插件处理结果
                result = plugin.on_user_input(user_input)
                # 双重判断：返回值是字符串 且 去除首尾空格后不为空字符串
                if isinstance(result, str) and result.strip():
                    # 格式化片段：标注插件名称、版本号，拼接插件生成的内容，存入列表
                    parts.append(f"[插件 {plugin.name} v{plugin.version}] {result}")
            except Exception:
                # 插件执行出现任意错误，直接跳过该插件，不做任何处理
                pass
        # 判断列表内是否存在有效插件输出内容
        if parts:
            # 原始用户文本 + 两段换行分隔 + 所有插件片段换行拼接，重新赋值给user_input
            user_input = user_input + "\n\n" + "\n".join(parts)

        # 打印处理完成后的文本，仅截取前80字符日志展示
        logger.info("│   完成后文本: %s", user_input[:80])
        # 日志打印当前节点执行完毕，跳转至check_exit节点
        logger.info("└──→ check_exit")
        # 返回修改后的user_input字典，LangGraph会自动合并更新全局AgentState状态
        return {"user_input": user_input}

    def _node_check_exit(self, state: AgentState) -> dict[str, Any]:
        """节点2：退出意图检测
        匹配固定中文/英文退出关键词，命中则标记should_exit=True
        """
        # 从全局状态中读取经过插件拼接处理后的完整用户输入文本
        user_input = state["user_input"]

        # 打印日志分隔线，标识当前节点开始执行
        logger.info("┌──────────────────────────────────────────────────────────────")
        # 日志输出当前运行的节点名称
        logger.info("│ [节点] check_exit")
        # 打印待检测的用户文本，为避免日志过长只截取前60个字符
        logger.info("│   检测输入: %s", user_input[:60])

        # 将文本转小写，判断是否命中预设的退出关键词集合
        if user_input.lower() in ("exit。", "quit。", "q。", "结束。", "再见。"):
            # 日志打印命中退出关键词提示
            logger.info("│   ★ 匹配退出词 → 即将终止对话")
            # 日志标记流程走向：直接结束整轮对话
            logger.info("└──→ END")
            # 返回状态更新字典，标记需要退出，LangGraph接收后跳转到END终止节点
            return {"should_exit": True}

        # 代码走到此处代表未检测到退出关键词，打印日志
        logger.info("│   未匹配退出词 → 继续")
        # 日志标记流程走向：进入收集插件上下文节点gather_context
        logger.info("└──→ gather_context")
        # 返回状态更新字典，标记无需退出，继续正常对话流程
        return {"should_exit": False}

    def _node_gather_context(self, state: AgentState) -> dict[str, Any]:
        """节点3：收集插件补充上下文
        广播on_llm_context钩子，插件可返回补充信息注入LLM上下文
        例如：当前时间、用户记忆、系统状态、硬件信息等
        """
        # 从全局状态取出处理完成后的用户输入文本，作为钩子入参
        user_input = state["user_input"]

        # 打印日志分割线，标识当前节点开始执行
        logger.info("┌──────────────────────────────────────────────────────────────")
        # 日志输出当前执行节点名称
        logger.info("│ [节点] gather_context")
        # 打印日志：告知正在广播钩子，同时输出当前启用插件总数
        logger.info("│   广播 on_llm_context 到 %d 个启用插件...", len(self.registry.enabled_plugins))

        # 调用插件注册中心的广播方法，批量执行所有插件的on_llm_context钩子，传入用户输入，收集全部返回值
        extra_contexts = self.registry.broadcast("on_llm_context", user_input)
        # filter(None, extra_contexts) 过滤掉列表内的空值、None；再用换行符拼接所有有效上下文文本
        extra_context = "\n".join(filter(None, extra_contexts))

        # 判断是否收集到有效补充上下文
        if extra_context:
            # 打印日志，展示收集到的上下文总字符长度
            logger.info("│   收集到额外上下文 (%d 字符)", len(extra_context))
        else:
            # 无任何插件返回有效上下文，打印对应日志
            logger.info("│   无额外上下文")
        # 日志标记当前节点执行完毕，下一步跳转至agent_think LLM推理节点
        logger.info("└──→ agent_think")
        # 返回状态更新字典，将拼接好的全部插件上下文存入全局状态AgentState
        return {"extra_context": extra_context}

    def _node_agent_think(self, state: AgentState) -> dict[str, Any]:
        """节点4：LLM核心推理节点（支持工具调用循环）
        1. 首次进入：拼接用户输入+插件补充上下文到对话历史
        2. 调用带工具能力的LLM接口
        3. LLM返回工具调用 → 进入tool_executor；返回纯文本 → 生成最终回复
        """
        # 拷贝对话历史列表，避免直接修改原始state内的引用，防止污染全局状态
        messages: list[dict[str, Any]] = list(state.get("messages", []))
        # 从状态获取拼接好的完整用户输入文本，无数据则为空字符串
        user_input = state.get("user_input", "")
        # 从状态获取插件收集的额外上下文文本，无数据则为空字符串
        extra_context = state.get("extra_context", "")
        # 读取当前工具循环次数，不存在则默认0次
        loop_count = state.get("tool_loop_count", 0)

        # 打印日志分隔线，标记本节点开始执行
        logger.info("┌──────────────────────────────────────────────────────────────")
        # 判断是否是工具执行完成后的重复推理
        if loop_count > 0:
            # 循环次数大于0，代表工具执行完毕，重新进入LLM推理
            logger.info("│ [节点] agent_think  (第 %d 次进入 — 工具执行后重新推理)", loop_count + 1)
        else:
            # 循环次数为0，本轮第一次执行LLM推理
            logger.info("│ [节点] agent_think  (首次推理)")
        # 打印日志：当前对话消息条数、当前工具循环次数/最大允许循环次数
        logger.info("│   消息历史: %d 条 | 工具循环次数: %d/%d", len(messages), loop_count, self.MAX_TOOL_LOOPS)

        # 判断条件：消息列表为空 或者 最后一条消息角色不是user，代表本轮用户输入还未加入历史
        if not messages or messages[-1].get("role") != "user":
            # 判断是否存在插件提供的额外上下文
            if extra_context:
                # 打印日志，记录注入上下文的字符长度
                logger.info("│   注入额外上下文到 system 消息 (%d 字符)", len(extra_context))
                # 以system角色消息，把插件上下文追加到对话历史
                messages.append({"role": "system", "content": extra_context})
            # 将本轮完整用户输入作为user消息存入对话历史
            messages.append({"role": "user", "content": user_input})

        # 调用插件注册中心，收集所有插件注册的工具定义列表
        tools = self.registry.collect_tools()
        # 提取所有工具名称，拼接成日志打印内容；无工具则显示问号占位
        logger.info("│   可用工具: %d 个 %s", len(tools), [t.get("function", {}).get("name", "?") for t in tools] if tools else "")

        # 日志提示即将发起LLM网络调用
        logger.info("│   → 调用 LLM...")
        # 调用LLM管理器支持工具调用的对话接口，传入完整对话历史与工具列表
        result = self.llm.chat_with_tools(messages, tools)

        # 解析LLM返回的文本内容，无content则赋值空字符串兜底
        content = result.get("content", "") or ""
        # 取出LLM生成的工具调用指令列表，无则为None
        tool_calls = result.get("tool_calls")
        # 获取LLM结束原因（工具调用/停止/长度超限等），此处暂未使用
        finish_reason = result.get("finish_reason", "")

        # 分支A：LLM返回了工具调用指令，需要执行工具
        if tool_calls:
            # 构建assistant角色消息，content为空也保留结构
            assistant_msg: dict[str, Any] = {"role": "assistant", "content": content or None}
            # 将工具调用数组挂载到assistant消息中，符合OpenAI消息格式
            assistant_msg["tool_calls"] = tool_calls
            # 把携带工具指令的assistant消息追加到对话历史
            messages.append(assistant_msg)

            # 遍历提取所有要调用的工具名称
            tool_names = [tc["function"]["name"] for tc in tool_calls]
            # 日志打印LLM请求的工具清单
            logger.info("│   ★ LLM 请求工具调用: %s", tool_names)
            # 日志标记流程跳转至工具执行节点
            logger.info("└──→ tool_executor")
            # 返回更新后的状态字段：新对话历史、工具调用列表、循环计数+1
            return {
                "messages": messages,
                "tool_calls": tool_calls,
                "tool_loop_count": loop_count + 1,
            }

        # 分支B：LLM没有请求工具，直接生成最终回答文本
        # 将纯文本assistant回复存入对话历史
        messages.append({"role": "assistant", "content": content})
        # 截断超长回复用于日志预览，超过80字符末尾加省略号
        reply_preview = content[:80] + "..." if len(content) > 80 else content
        # 日志打印最终回复总字符数与预览内容
        logger.info("│   ★ LLM 最终回复 (%d 字符): %s", len(content), reply_preview)
        # 日志标记跳转至回复后处理节点
        logger.info("└──→ process_response")
        # 返回更新后的状态：完整对话历史、原始LLM文本、清空工具调用标记
        return {
            "messages": messages,
            "llm_content": content,
            "tool_calls": None,
        }
    def _node_tool_executor(self, state: AgentState) -> dict[str, Any]:
        """节点5：工具执行器
        遍历LLM下发的所有工具调用，通过插件中心执行工具
        将工具返回结果以tool角色消息存入对话历史，供LLM二次推理
        """
        # 从当前流程状态取出模型下发的工具调用列表，无数据则为空列表兜底
        tool_calls = state.get("tool_calls", []) or []
        # 拷贝当前状态里的完整对话消息上下文，避免直接修改原state数据
        messages: list[dict[str, Any]] = list(state.get("messages", []))

        # 打印分隔日志，标识进入工具执行节点
        logger.info("┌──────────────────────────────────────────────────────────────")
        # 日志输出本次需要执行的工具总数量
        logger.info("│ [节点] tool_executor  (执行 %d 个工具调用)", len(tool_calls))

        # 循环遍历每一条工具调用指令，i从1开始计数方便日志展示序号
        for i, tc in enumerate(tool_calls, 1):
            # 取出单条工具调用里的function对象，包含工具名和参数字符串
            fn = tc.get("function", {})
            # 获取待执行的工具函数名称
            tool_name = fn.get("name", "")
            # 尝试解析arguments JSON字符串为参数字典
            try:
                tool_args = _json.loads(fn.get("arguments", "{}"))
            # JSON解析失败时，使用空字典作为参数兜底，防止程序崩溃
            except _json.JSONDecodeError:
                tool_args = {}

            # 打印当前执行的工具序号、总数量、工具名与格式化入参
            logger.info("│   工具 %d/%d: %s(%s)", i, len(tool_calls), tool_name, _json.dumps(tool_args, ensure_ascii=False))
            # 调用全局插件注册表，根据工具名与参数执行对应工具逻辑，拿到返回文本结果
            tool_result = self.registry.execute_tool(tool_name, tool_args)

            # 按照OpenAI标准tool消息格式，把工具执行结果追加到对话上下文
            messages.append({
                "role": "tool",
                # 绑定本次工具调用唯一ID，供大模型匹配之前的工具调用指令
                "tool_call_id": tc.get("id", ""),
                # 工具执行输出的文本内容
                "content": tool_result,
            })

            # 处理日志预览：超过120字符则截断并加省略号，避免日志过长刷屏
            result_preview = tool_result[:120] + "..." if len(tool_result) > 120 else tool_result
            # 打印当前工具的执行结果预览
            logger.info("│   结果 %d/%d: %s", i, len(tool_calls), result_preview)

        # 日志标记所有工具执行完毕，跳转回LLM思考节点重新整合结果
        logger.info("└──→ agent_think  (重新推理)")
        # 返回更新后的流程状态：更新对话消息、清空工具调用标识，流转至思考节点
        return {"messages": messages, "tool_calls": None}
    

    def _node_process_response(self, state: AgentState) -> dict[str, Any]:
        """节点6：LLM回复后处理
        广播on_llm_response钩子，插件可润色、过滤、改写AI原始回复
        输出final_reply字段，作为后续TTS、历史记录的标准文本
        """
        # 从流程状态中取出大模型原始输出文本，无内容则空字符串兜底
        reply = state.get("llm_content", "")

        # 打印日志分隔线，标识进入回复处理节点
        logger.info("┌──────────────────────────────────────────────────────────────")
        # 日志打印当前进入回复后处理节点
        logger.info("│ [节点] process_response")
        # 打印原始回复长度与前80个字符预览，方便调试查看LLM原始输出
        logger.info("│   原始回复 (%d 字符): %s", len(reply), reply[:80])

        # 遍历所有已启用插件，链式依次处理回复：前一个插件输出作为下一个插件输入
        for plugin in self.registry.enabled_plugins:
            try:
                # 执行插件的LLM回复后置钩子，传入当前处理中的文本
                result = plugin.on_llm_response(reply)
                # 判断插件返回合法字符串，代表插件对回复做了修改
                if isinstance(result, str):
                    # 打印调试日志：记录插件名称、修改前后文本长度变化
                    logger.debug("│   [链] %s 修改回复 (%d→%d 字符)", plugin.name, len(reply), len(result))
                    # 将插件处理后的新文本覆盖原文本，传给下一个插件
                    reply = result
            # 捕获单个插件执行异常，出错直接跳过，不中断整条回复处理链路
            except Exception:
                pass

        # 打印经过所有插件链式处理后的最终文本预览
        logger.info("│   处理后回复 (%d 字符): %s", len(reply), reply[:80])
        # 日志标记处理完成，流转到语音合成准备节点
        logger.info("└──→ prepare_tts")
        # 返回更新状态，输出统一标准字段final_reply，供TTS、存储聊天历史使用
        return {"final_reply": reply}
    
    def _node_prepare_tts(self, state: AgentState) -> dict[str, Any]:
        """节点7：TTS语音合成预处理+合成
        链式执行 on_before_tts 钩子；若无插件处理，应用默认清洗。
        调用TTS管理器生成语音文件，返回音频路径。
        """
        # 从流程状态读取经过后置插件处理完成的最终回复文本，无数据则为空字符串
        reply = state.get("final_reply", "")

        # 打印日志分隔线，62个横线拼接左边界
        logger.info("┌" + "─" * 62)
        # 日志标记当前进入TTS预处理节点
        logger.info("│ [节点] prepare_tts")

        # 标记变量：记录是否有任意插件对文本做过修改
        modified = False
        # 遍历所有已启用插件，链式处理文本，前一个插件输出作为下一个插件输入
        for plugin in self.registry.enabled_plugins:
            try:
                # 执行插件提供的TTS文本预处理钩子函数，传入当前待清洗文本
                result = plugin.on_before_tts(reply)
                # 判断插件返回值是合法字符串，代表文本被插件修改
                if isinstance(result, str):
                    # 调试日志：打印插件名称、文本清洗前后字符长度
                    logger.debug("│   [链] %s 清洗文本 (%d→%d 字符)", plugin.name, len(reply), len(result))
                    # 更新文本为插件清洗后的内容，传递给后续插件循环
                    reply = result
                    # 标记文本已被插件修改
                    modified = True
            # 捕获单个插件运行异常，出错直接跳过，不中断整体文本清洗流程
            except Exception:
                pass

        # 兜底逻辑：没有任何插件修改文本时，执行内置默认清洗规则
        if not modified:
            logger.info("│   无插件清洗，应用默认保底清洗...")
            # 调用静态方法执行统一文本清洗逻辑
            reply = self._default_tts_clean(reply)
        # 存在插件处理过文本，打印清洗后的文本长度与前80字符预览
        else:
            logger.info("│   插件链式清洗后 (%d 字符): %s", len(reply), reply[:80])

        # 日志提示即将调用语音合成接口
        logger.info("│   → TTS 合成中...")
        # 调用TTS管理器，传入清洗完毕的纯朗读文本，生成音频并返回音频文件路径
        audio_path = self.tts.synthesize(reply)
        # 日志打印生成完成的音频文件路径
        logger.info("│   ★ TTS 输出: %s", audio_path)
        # 日志标记TTS流程结束，流转至Live2D数字人输出节点
        logger.info("└──→ live2d_output")
        # 返回更新后的流程状态：清洗完成的朗读文本、生成好的音频路径
        return {"final_reply": reply, "audio_path": audio_path}

    @staticmethod
    def _default_tts_clean(text: str) -> str:
        """默认 TTS 文本清洗 —— 当没有插件处理时兜底。
        去除 Markdown 标记、代码块、URL、多余空白。
        """
        # 局部导入正则模块并起别名 _re，仅该静态方法内使用
        import re as _re

        # 1. 正则匹配并移除多行代码块 ```内容```，替换为单个空格
        text = _re.sub(r"```[\s\S]*?```", " ", text)
        # 2. 移除行内单行代码标记 `内容`，只保留中间文字
        text = _re.sub(r"`([^`]*)`", r"\1", text)
        # 3. 移除粗体标记 **文字**，保留文字本身
        text = _re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        # 4. 移除斜体标记 *文字*，保留文字本身
        text = _re.sub(r"\*([^*]+)\*", r"\1", text)
        # 5. 移除下划线粗体 __文字__
        text = _re.sub(r"__([^_]+)__", r"\1", text)
        # 6. 移除下划线斜体 _文字_
        text = _re.sub(r"_([^_]+)_", r"\1", text)
        # 7. 移除行首Markdown一级至六级标题 # 、## 等，多行模式生效
        text = _re.sub(r"^#{1,6}\s+", "", text, flags=_re.MULTILINE)
        # 8. 移除Markdown链接格式 [显示文本](链接地址)，只保留显示文本
        text = _re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
        # 9. 匹配并删除http/https完整网址，替换空格
        text = _re.sub(r"https?://\S+", " ", text)
        # 10. 删除行首列表标记 - * + 及后方空格，多行模式匹配每一行
        text = _re.sub(r"^[\s]*[-*+]\s+", "", text, flags=_re.MULTILINE)
        # 11. 删除行首引用标记 > 及后方空格
        text = _re.sub(r"^>\s+", "", text, flags=_re.MULTILINE)
        # 12. 将所有连续换行、空格、制表符压缩为单个空格，并去除首尾空白
        text = _re.sub(r"\s+", " ", text).strip()

        # 打印默认清洗完成后的文本长度与前80字符预览日志
        logger.info("│   默认清洗后 (%d 字符): %s", len(text), text[:80])
        # 返回清洗完成、无markdown干扰的纯朗读文本
        return text

    def _node_live2d_output(self, state: AgentState) -> dict[str, Any]:
        """节点8：Live2D虚拟形象播放
        传入合成音频，驱动虚拟人物播放语音+同步嘴型动画
        该方法阻塞至音频播放完成
        """
        audio_path = state.get("audio_path", "")

        logger.info("┌──────────────────────────────────────────────────────────────")
        logger.info("│ [节点] live2d_output")
        logger.info("│   → 嘴型同步播放: %s", audio_path)
        # 播放音频+嘴型同步渲染
        self.live2d.play_audio_and_print_mouth(audio_path)
        logger.info("│   播放完成")
        logger.info("└──→ post_tick")
        # 无状态字段更新，返回空字典
        return {}

    def _node_post_tick(self, state: AgentState) -> dict[str, Any]:
        """节点9：单轮对话收尾钩子
        广播on_tick全局钩子，插件可做每轮结束后的收尾逻辑
        如：更新记忆、统计对话次数、定时任务触发等
        """
        round_num = state.get("round_num", 0)

        logger.info("┌──────────────────────────────────────────────────────────────")
        logger.info("│ [节点] post_tick")
        logger.info("│   广播 on_tick 到 %d 个启用插件...", len(self.registry.enabled_plugins))
        self.registry.broadcast("on_tick", None)
        logger.info("│   第 %d 轮处理完成", round_num)
        logger.info("└──→ END")
        # 无状态更新
        return {}

    # ==================================================================
    # 对外公开入口方法：给main.py调用的唯一接口
    # ==================================================================
    def invoke(self, initial_state: dict[str, Any]) -> dict[str, Any]:
        """运行一次完整智能体图，处理一轮完整对话
        Args:
            initial_state: 外部传入的初始状态字典（来自main.py对话循环）
        Returns:
            执行完毕后的完整AgentState，包含回复、更新后的对话历史、退出标记
        """
        # 初始化全量默认状态，防止字段缺失报错
        state: AgentState = {
            "user_input": "",
            "user_source": "voice",
            "messages": [],
            "llm_content": "",
            "tool_calls": None,
            "tool_results": [],
            "final_reply": "",
            "audio_path": "",
            "should_exit": False,
            "round_num": 0,
            "extra_context": "",
            "tool_loop_count": 0,
        }
        # 用外部传入参数覆盖默认值
        state.update(initial_state)  # type: ignore[typeddict-item]

        round_num = state["round_num"]
        input_preview = state["user_input"][:60]
        logger.debug("[GraphEngine] invoke() 开始 — 第 %d 轮: %s", round_num, input_preview)

        # 执行编译好的流程图，阻塞直到整轮对话全部处理完成
        result = self._graph.invoke(state)

        logger.debug("[GraphEngine] invoke() 完成 — 第 %d 轮, 最终回复: %s",
                     round_num, result.get("final_reply", "")[:60])
        # 返回最终完整状态给main.py
        return result


# ==================================================================
# 模块独立运行自测入口
# ==================================================================
if __name__ == "__main__":
    # GraphEngine依赖大量外部管理器，无法单独运行，提示通过main.py启动
    print("GraphEngine 自测需要完整的 MainManager 上下文，请通过 main.py 运行。")