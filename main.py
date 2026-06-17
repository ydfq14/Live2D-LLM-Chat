# === 启动引导：必须在所有 import 之前，将模型缓存重定向到项目 .models/ 目录 ===
# 最优先执行环境引导脚本，修改环境变量，把HuggingFace等模型缓存路径改到本地项目内.models文件夹
import infrastructure._bootstrap  # noqa: F401 — noqa:F401 告诉linter导入未使用无需告警

# 导入多线程模块，用于单独开辟线程运行Live2D渲染窗口（避免阻塞语音对话主循环）
import threading
# 导入日期时间模块，用于对话记录写入时间戳
import datetime
# 从自定义日志配置文件导入日志获取函数，统一管理程序日志输出
from log_config import get_logger
# 导入云端/本地TTS接口管理类，负责本地语音合成服务API启动
from TTS_api import TTSAPIManager
# 导入语音识别管理类（ASR：语音转文字 Audio Speech Recognition）
from ASR import ASRManager
# 导入TTS语音合成管理类（文字转语音 Text To Speech）
from TTS import TTSManager
# 导入大语言模型对话管理类，负责接收用户输入并生成AI回复
from LLM import LLMManager
# 导入带渲染、追眼、嘴型同步功能的Live2D桌宠动画管理器
from Live2d_animation import Live2DAnimationManager
# 导入全局配置文件，读取所有模式开关、文件路径、参数常量
from config import Config
# 导入插件注册中心，管理所有插件的加载/卸载/事件广播
from plugin_registry import PluginRegistry
# 导入 pywebview 前端容器，承载各插件 UI 面板（网页桌面窗口）
from ui_shell import UIShell
# 导入 LangGraph 图引擎，替代原线性管道模式，支持工具调用、多分支智能体流程
from graph_engine import GraphEngine

# 获取当前模块(main.py)专属日志实例，日志会自动标注当前文件名称，区分多模块日志
logger = get_logger(__name__)

# 聊天框文本输入队列（全局列表）
# 由ui_shell内嵌JS前端写入文本消息，main.run()主循环循环读取消费
_text_input_queue: list[str] = []
# 全局停止事件对象，pywebview窗口关闭时set()，通知对话循环while退出
_stop_event = threading.Event()
# 录音中断事件：前端输入文字时触发，ASR录音循环检测，立刻终止录音
_recording_abort = threading.Event()
# 忙碌锁事件：录音中/AI生成回复/TTS播放时置为True，前端禁用输入按钮防止并发冲突
_busy_event = threading.Event()


# ==================================================================
#  启动 Banner 打印函数
# ==================================================================
def _print_startup_banner() -> None:
    """打印项目启动横幅，控制台日志输出ASCII艺术字，清晰标识项目名称和版本。"""
    # 空行分隔日志，提升可读性
    logger.info("")
    # 以下多行打印项目LOGO ASCII图案
    logger.info("╔════════════════════════════════════════════════════════════════╗")
    logger.info("║                                                                ║")
    logger.info("║       ██╗   ██╗██╗██████╗ ████████╗██╗   ██╗███╗   ███╗        ║")
    logger.info("║       ██║   ██║██║██╔══██╗╚══██╔══╝██║   ██║████╗ ████║        ║")
    logger.info("║       ██║   ██║██║██████╔╝   ██║   ██║   ██║██╔████╔██║        ║")
    logger.info("║       ╚██╗ ██╔╝██║██╔══██╗   ██║   ██║   ██║██║╚██╔╝██║        ║")
    logger.info("║        ╚████╔╝ ██║██║  ██║   ██║   ╚██████╔╝██║ ╚═╝ ██║        ║")
    logger.info("║         ╚═══╝  ╚═╝╚═╝  ╚═╝   ╚═╝    ╚═════╝ ╚═╝     ╚═╝        ║")
    logger.info("║                                                                ║")
    # 项目介绍标语
    logger.info("║          Virtual Mate — 智能语音对话 Live2D 桌宠               ║")
    logger.info("║          LangGraph Agent · 插件化架构 · 多模态交互             ║")
    logger.info("║                                                                ║")
    logger.info("╚════════════════════════════════════════════════════════════════╝")
    logger.info("")


# 程序总调度主管理器，顶层核心类
# 统筹语音识别、大模型、语音合成、虚拟形象渲染、UI、插件、智能体全部模块
class MainManager:
    # 主管理器构造函数，程序全局初始化唯一入口
    def __init__(self):
        """
        初始化主管理器，整合 TTS_API、TTS、ASR、LLM、Live2D。

        根据 Config.ASR_MODE / Config.TTS_MODE 自动切换本地/云端模式。
        云端模式下跳过本地 TTS API 的启动，减少资源占用。
        """
        # 第一步打印启动LOGO横幅
        _print_startup_banner()

        # ================================================================
        #  阶段 0: 项目基础信息打印，日志输出环境基础配置
        # ================================================================
        logger.info("[阶段 0/5] 项目基础信息")
        # 打印项目根目录路径，不存在PROJECT_ROOT则显示自动检测
        logger.info("  项目根目录: %s", Config.PROJECT_ROOT if hasattr(Config, "PROJECT_ROOT") else "(自动检测)")
        # 提示模型缓存路径已通过前置bootstrap脚本重定向
        logger.info("  模型缓存: .models/ (已通过 bootstrap 重定向)")
        # 日志存储位置
        logger.info("  日志输出: logs/run.log + 控制台")

        # ================================================================
        #  阶段 1: TTS API（仅本地模式启动）
        # 本地CosyVoice语音合成需要单独后台API服务提供推理接口
        # ================================================================
        logger.info("[阶段 1/5] TTS API 初始化")
        # 判断配置文件TTS模式是否为本地离线
        if Config.TTS_MODE == "local":
            logger.info("  TTS 模式: 本地 (CosyVoice)")
            # 实例化本地TTS后台API管理器，传入窗口显示开关
            self.tts_api_manager = TTSAPIManager(Config.SHOW_WINDOW)
            # 启动TTS推理API服务，返回布尔值标记是否启动成功
            api_ready = self.tts_api_manager.start_tts_api()
            # API启动失败，严重错误，直接终止初始化
            if not api_ready:
                logger.error("  [FAIL] TTS API 启动失败，程序终止！")
                return
            logger.info("  [OK] TTS API 启动成功")
        else:
            # 云端TTS模式，无需启动本地推理服务，跳过该流程
            logger.info("  TTS 模式: 云端，跳过本地 CosyVoice 启动。")

        # ================================================================
        #  阶段 2: 四大核心AI模块初始化 ASR / TTS / LLM / Live2D
        # ================================================================
        logger.info("[阶段 2/5] 核心模块初始化")

        logger.info("  → 初始化 ASR 管理器...")
        # 实例化语音识别管理对象，封装录音、VAD静音检测、音频识别全逻辑
        self.asr_manager = ASRManager()
        logger.info("    [OK] ASR 管理器就绪 (模式: %s)", Config.ASR_MODE)

        logger.info("  → 初始化 TTS 管理器...")
        # 实例化语音合成管理器，封装调用本地/云端TTS接口、音频播放逻辑
        self.tts_manager = TTSManager()
        logger.info("    [OK] TTS 管理器就绪 (模式: %s)", Config.TTS_MODE)

        logger.info("  → 初始化 LLM 管理器...")
        # 实例化大模型管理器，维护对话上下文、调用本地/云端大模型API
        self.llm_manager = LLMManager()
        # 云端模式拼接模型名称打印日志，本地模式为空
        cloud_info = f" ({Config.LLM_CLOUD_MODEL_NAME})" if Config.LLM_MODE == "cloud" else ""
        logger.info("    [OK] LLM 管理器就绪 (模式: %s%s)", Config.LLM_MODE, cloud_info)

        logger.info("  → 初始化 Live2D 管理器...")
        # 截取模型文件夹名称用于日志展示
        model_name = Config.LIVE2D_MODEL_PATH.split("/")[-1] if "/" in Config.LIVE2D_MODEL_PATH else Config.LIVE2D_MODEL_PATH
        # 实例化Live2D渲染管理器，加载人物模型，封装窗口渲染、嘴型同步、眼球追踪
        self.live2d_manager = Live2DAnimationManager(
            model_path=Config.LIVE2D_MODEL_PATH
        )
        logger.info("    [OK] Live2D 管理器就绪 (模型: %s)", model_name)

        # 从全局配置读取对话历史保存文件路径
        self.history_file = Config.LLM_CONVERSATION_HISTORY
        logger.info("  对话历史: %s", self.history_file)

        # ================================================================
        #  阶段 3: 插件系统 + WebUI前端窗口初始化
        # ================================================================
        logger.info("[阶段 3/5] 插件系统初始化")
        # 创建插件注册中心实例，统一管理所有扩展插件
        self.registry = PluginRegistry()
        # 自动扫描插件目录、加载全部合法插件，返回已加载插件名称列表
        loaded = self.registry.scan_and_load()
        # 打印加载插件数量与名称，无插件则显示(无)
        logger.info("  [OK] 已加载 %d 个插件: %s", len(loaded), ", ".join(loaded) if loaded else "(无)")

        logger.info("  → 广播 on_startup...")
        # 向所有插件广播程序启动事件，插件可在on_startup做初始化逻辑
        self.registry.broadcast_on_startup(self)
        logger.info("  [OK] on_startup 广播完成")

        logger.info("  → 启动 UI 前端 (pywebview)...")
        # 创建网页桌面窗口管理器，注入全局事件、消息队列供前端JS交互
        self.ui_shell = UIShell(self.registry, _text_input_queue, _recording_abort, _stop_event, _busy_event)
        # 后台初始化webview资源，不阻塞主线程
        self.ui_shell.start()
        logger.info("  [OK] UI 前端窗口已启动")

        # ================================================================
        #  阶段 4: LangGraph 智能体图引擎初始化
        # 替代老式顺序执行流程，支持工具调用、条件分支、多轮思考智能体
        # ================================================================
        logger.info("[阶段 4/5] LangGraph 智能体引擎初始化")
        # 图引擎注入所有核心模块实例，让智能体可调用LLM、TTS、Live2D、插件事件
        self.graph_engine = GraphEngine(
            self.llm_manager, self.tts_manager, self.live2d_manager, self.registry
        )
        logger.info("  [OK] GraphEngine 已创建并编译")

        # ================================================================
        #  阶段 5: 启动运行时渲染线程
        # ================================================================
        logger.info("[阶段 5/5] 启动运行时")

        logger.info("  → 启动 Live2D 渲染线程...")
        # 新建守护线程运行Live2D渲染循环，daemon=True主线程退出时自动销毁
        live2d_thread = threading.Thread(
            target=self.live2d_manager.play_live2d_once, daemon=True
        )
        # 启动渲染线程
        live2d_thread.start()
        logger.info("    [OK] Live2D 渲染线程已启动 (tid=%s)", live2d_thread.ident)

        logger.info("  → 等待 OpenGL 窗口就绪 (1s)...")
        # 导入time模块做短暂延时，等待OpenGL渲染窗口完成初始化，防止嘴型同步报错
        import time
        time.sleep(1)
        logger.info("    [OK] 渲染窗口就绪")

        # 打印初始化完成汇总面板，快速查看系统整体状态
        logger.info("")
        logger.info("┌──────────────────────────────────────────────────────────────┐")
        logger.info("│              初始化完成 — 系统就绪                            │")
        logger.info("├──────────────────────────────────────────────────────────────┤")
        logger.info("│  ASR: %-10s │ TTS: %-10s │ LLM: %-10s          │",
                     Config.ASR_MODE, Config.TTS_MODE, Config.LLM_MODE)
        logger.info("│  插件: %-2d 个   │ 架构: LangGraph Agent                    │",
                     len(loaded))
        logger.info("│  交互: 语音 / 聊天框   │ 输入方式: VAD 自动录音             │")
        logger.info("└──────────────────────────────────────────────────────────────┘")
        logger.info("")

    # 主交互循环 — LangGraph 智能体模式核心对话逻辑
    def run(self):
        """主交互循环 — LangGraph 智能体模式

        每次循环执行流程：
          1. 获取用户输入（优先读取聊天框队列 无文字则启动VAD录音+ASR转文字）
          2. 调用 GraphEngine.invoke() 运行完整智能体图（插件钩子→LLM思考→工具调用→TTS语音播放→Live2D嘴型动画）
          3. 将智能体更新后的对话上下文同步回LLM管理器
          4. 持久化保存本轮对话记录到本地历史文件
        """
        logger.info("")
        logger.info("╔════════════════════════════════════════════════════════════════╗")
        logger.info("║            主对话循环启动  [LangGraph Agent 模式]              ║")
        logger.info("╚════════════════════════════════════════════════════════════════╝")
        logger.info("")

        # 对话轮次计数器，标记当前是第几轮对话
        round_num = 0

        # 主循环：未触发停止事件则持续循环对话
        while not _stop_event.is_set():
            # 每轮对话轮次+1
            round_num += 1

            # ================================================================
            #  空闲态：清除忙碌锁，前端输入框解除禁用，允许用户输入
            # ================================================================
            _busy_event.clear()

            # ────────── ① 优先检查聊天框文本输入队列 ──────────
            # 声明使用全局消息队列变量
            global _text_input_queue
            # 判断队列是否存在前端输入文本
            if _text_input_queue:
                # 取出队列头部第一条用户消息
                user_input = _text_input_queue.pop(0)
                # 设置忙碌锁，锁定前端输入
                _busy_event.set()
                # 标记输入来源为网页聊天框
                source = "chatbox"
                logger.info("")
                logger.info("══════════════════════════════════════════════════════════════")
                logger.info("  第 %d 轮对话 [聊天框输入]", round_num)
                logger.info("══════════════════════════════════════════════════════════════")
                logger.info("[输入] 聊天框: %s", user_input)
            else:
                # ────────── ② 无文字输入，启动VAD自动录音分支 ──────────
                # 读取配置音频临时保存路径
                user_wav = Config.ASR_AUDIO_INPUT
                logger.info("")
                logger.info("══════════════════════════════════════════════════════════════")
                logger.info("  第 %d 轮对话 [语音输入]", round_num)
                logger.info("══════════════════════════════════════════════════════════════")
                logger.info("[输入] VAD 录音中（说话即可）...")

                # 将全局录音中断事件注入ASR管理器，文字输入可打断录音
                self.asr_manager._abort_event = _recording_abort
                # 阻塞式录音，带VAD静音检测，返回是否捕获有效人声
                recording_done = self.asr_manager.record_audio(user_wav)
                logger.info("[输入] VAD 录音结束 → %s", user_wav)

                # 录音无有效人声，跳过本轮循环，回到空闲等待输入状态
                if not recording_done:
                    logger.info("[输入] 录音未触发（无有效语音），跳过")
                    continue

                # 捕获人声，设置忙碌锁，禁止前端输入
                _busy_event.set()

                # ASR音频转文字识别
                logger.info("[输入] ASR 识别中...")
                user_input = self.asr_manager.recognize_speech(user_wav)
                logger.info('[输入] ASR 结果: "%s"', user_input)
                # 标记输入来源为麦克风语音
                source = "voice"

            # ================================================================
            #  LangGraph 智能体图执行入口
            #  图内部完整链路：全局插件前置Hook → LLM生成回复 → 工具循环调用 → TTS语音合成播放 → Live2D嘴型同步动画
            # ================================================================
            logger.info("[Graph] ====== 调用 GraphEngine.invoke() ======")

            # 传入本轮对话全部上下文参数，执行智能体图流程
            result = self.graph_engine.invoke({
                "user_input": user_input,       # 用户原始输入文本
                "user_source": source,          # 输入来源 chatbox/voice
                "messages": list(self.llm_manager.conversation), # 历史对话上下文
                "round_num": round_num,          # 当前对话轮次
                "tool_loop_count": 0,            # 工具调用循环计数器初始值
            })

            # 将智能体处理后更新的完整对话上下文同步回LLM管理器
            self.llm_manager.conversation = result.get("messages", self.llm_manager.conversation)

            # 从图引擎返回结果取出AI最终回复文本
            final_reply = result.get("final_reply", "")
            # 追加写入本地对话历史文件，utf-8编码防止中文乱码
            with open(self.history_file, "a", encoding="utf-8") as f:
                # 获取当前时间戳
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                # 写入时间、用户消息、AI回复，分割线区分轮次
                f.write(f"Time：{timestamp}\n")
                f.write(f"User：{user_input}\nNeko：{final_reply}\n---\n")

            logger.info("[Graph] ====== GraphEngine.invoke() 返回 =====")
            # 打印AI回复前80字符预览，避免日志过长
            logger.info("[Graph] 最终回复 (%d 字符): %s", len(final_reply), final_reply[:80])

            # 智能体标记需要退出程序，跳出主对话循环
            if result.get("should_exit"):
                logger.info("[退出] 用户请求退出，结束对话循环")
                break

            logger.info("[循环] 第 %d 轮完成，准备下一轮...", round_num)

        # ================================================================
        #  循环退出后统一资源关闭清理流程
        # ================================================================
        # 清除忙碌锁
        _busy_event.clear()
        logger.info("")
        logger.info("╔════════════════════════════════════════════════════════════════╗")
        logger.info("║                  关闭序列 — 清理资源                          ║")
        logger.info("╚════════════════════════════════════════════════════════════════╝")

        # 向所有已启用插件广播程序关闭事件，插件释放自有资源
        logger.info("[关闭] 广播 on_shutdown 到 %d 个插件...", len(self.registry.enabled_plugins))
        self.registry.broadcast_on_shutdown()
        logger.info("[关闭] on_shutdown 广播完成")

        # 停止pywebview网页UI窗口
        logger.info("[关闭] 停止 UI 前端...")
        self.ui_shell.stop()
        logger.info("[关闭] UI 前端已停止")

        logger.info("[关闭] 主循环结束，系统已安全退出。")
        logger.info("")


# 程序入口判断：仅当直接运行main.py脚本时执行下方启动代码
# 若本文件被其他py文件import导入，则不会执行启动逻辑，方便模块化调用
if __name__ == "__main__":
    logger.info("================================================================")
    logger.info("  VirtuMate 启动")
    logger.info("  Python: 3.13 | 架构: LangGraph Agent | 线程: 主+Live2D+对话")
    logger.info("================================================================")
    logger.info("")

    logger.info(">>> 创建 MainManager（全模块初始化）...")
    # 实例化顶层主管理器，自动执行__init__，完成全模块初始化、启动Live2D渲染线程
    main_manager = MainManager()
    logger.info(">>> MainManager 创建完成")

    logger.info(">>> 启动对话循环线程...")
    # 创建守护线程运行对话主循环run()，命名方便日志区分线程
    conv_thread = threading.Thread(
        target=main_manager.run, daemon=True, name="conv-loop"
    )
    # 启动对话循环子线程
    conv_thread.start()
    logger.info(">>> 对话循环线程已启动 (tid=%s)", conv_thread.ident)

    # 主线程专门阻塞运行pywebview前端窗口事件循环
    # pywebview要求窗口必须在主线程创建运行，否则渲染异常
    logger.info(">>> 主线程进入 pywebview 事件循环（阻塞）...")
    logger.info(">>> 【提示】关闭 Live2D 窗口或按 Ctrl+C 退出程序")
    logger.info("")
    try:
        # 主线程阻塞，持续运行网页窗口
        main_manager.ui_shell.run_on_main_thread()
    except KeyboardInterrupt:
        # 用户按下Ctrl+C捕获中断信号
        logger.info("")
        logger.info(">>> 收到 Ctrl+C，开始退出...")
    finally:
        # 无论正常关闭窗口还是Ctrl+C中断，都会执行finally代码块
        # 设置全局停止事件，通知对话循环子线程退出while循环
        _stop_event.set()
        logger.info(">>> 程序正常退出。")