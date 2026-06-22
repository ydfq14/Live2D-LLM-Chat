# === 启动引导：必须在所有 import 之前，将模型缓存重定向到项目 .models/ 目录 ===
import infrastructure._bootstrap  # noqa: F401

import threading
import datetime
import sys
from log_config import get_logger
from TTS_api import TTSAPIManager
from ASR import ASRManager
from TTS import TTSManager
from LLM import LLMManager
from Live2d_animation import Live2DAnimationManager
from config import Config
from plugin_registry import PluginRegistry
from ui_shell import UIShell
from graph_engine import GraphEngine

# IOCP事件循环核心导入
import asyncio
from event_loop import get_scheduler, shutdown_scheduler
from async_wrapper import run_sync

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
# 聆听控制事件：默认关闭（静音），需要用户手动开启
_listening_enabled = threading.Event()  # 默认不 set，即默认静音


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

        # 保存全局事件引用，供插件访问
        self._listening_enabled = _listening_enabled
        self._text_input_queue = _text_input_queue
        self._recording_abort = _recording_abort
        self._busy_event = _busy_event
        self._stop_event = _stop_event

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
        bg_tasks = self.registry.get_background_tasks()
        logger.info("")
        logger.info("┌──────────────────────────────────────────────────────────────┐")
        logger.info("│              初始化完成 — 系统就绪                            │")
        logger.info("├──────────────────────────────────────────────────────────────┤")
        logger.info("│  ASR: %-10s │ TTS: %-10s │ LLM: %-10s          │",
                     Config.ASR_MODE, Config.TTS_MODE, Config.LLM_MODE)
        logger.info("│  插件: %-2d 个   │ 后台任务: %-2d 个                         │",
                     len(loaded), len(bg_tasks))
        logger.info("│  架构: IOCP Agent │ 输入方式: VAD 自动录音                  │")
        logger.info("└──────────────────────────────────────────────────────────────┘")
        logger.info("")

    # ==================================================================
    #  主交互循环 — IOCP Agent 模式
    # ==================================================================

    def run(self):
        """主交互循环 — IOCP Agent 模式

        基于 asyncio ProactorEventLoop（Windows IOCP）实现：
        - 用户输入在线程池中非阻塞等待（VAD录音不阻塞事件循环）
        - 后台任务（日程提醒等）自动执行，不依赖用户对话
        - 插件通过 on_register_background_tasks 注册的定时任务持续运行
        """
        logger.info("")
        logger.info("╔════════════════════════════════════════════════════════════════╗")
        logger.info("║            主对话循环启动  [IOCP Agent 模式]                   ║")
        logger.info("╚════════════════════════════════════════════════════════════════╝")
        logger.info("")

        scheduler = get_scheduler()
        self._round_num = 0

        # 注册用户输入处理协程到事件循环
        scheduler.loop.create_task(self._async_input_loop())

        # 运行事件循环（阻塞，直到 stop() 被调用）
        scheduler.run_forever()

        # 清理资源
        self._cleanup()

    async def _async_input_loop(self):
        """IOCP模式：异步用户输入处理循环"""
        while not _stop_event.is_set():
            self._round_num += 1
            _busy_event.clear()

            user_input = None
            source = None

            # ① 优先检查聊天框输入
            if _text_input_queue:
                user_input = _text_input_queue.pop(0)
                _busy_event.set()
                source = "chatbox"
                logger.info("")
                logger.info("══════════════════════════════════════════════════════════════")
                logger.info("  第 %d 轮对话 [聊天框输入]", self._round_num)
                logger.info("══════════════════════════════════════════════════════════════")
                logger.info("[输入] 聊天框: %s", user_input)

            # ② 无文字输入，检查是否允许聆听
            else:
                # 检查聆听是否开启
                listening_status = _listening_enabled.is_set()
                logger.info("[输入] 检查聆听状态: %s", "开启" if listening_status else "关闭")
                if not listening_status:
                    # 聆听已关闭，短暂等待后继续检查
                    await asyncio.sleep(1)
                    continue

                logger.info("")
                logger.info("══════════════════════════════════════════════════════════════")
                logger.info("  第 %d 轮对话 [语音输入]", self._round_num)
                logger.info("══════════════════════════════════════════════════════════════")
                logger.info("[输入] VAD 录音中（说话即可）...")

                user_wav = Config.ASR_AUDIO_INPUT
                self.asr_manager._abort_event = _recording_abort

                # 在线程池中执行阻塞录音，不阻塞事件循环
                try:
                    recording_done = await run_sync(
                        self.asr_manager.record_audio, user_wav
                    )
                except Exception as e:
                    logger.error("[输入] 录音异常: %s", e)
                    recording_done = False

                logger.info("[输入] VAD 录音结束 → %s", user_wav)

                if not recording_done:
                    logger.info("[输入] 录音未触发（无有效语音），跳过")
                    # 短暂等待再检查（事件循环中使用asyncio.sleep）
                    await asyncio.sleep(0.1)
                    continue

                _busy_event.set()

                # ASR识别（在线程池中非阻塞）
                logger.info("[输入] ASR 识别中...")
                try:
                    user_input = await run_sync(
                        self.asr_manager.recognize_speech, user_wav
                    )
                except Exception as e:
                    logger.error("[输入] ASR识别异常: %s", e)
                    await asyncio.sleep(0.1)
                    continue

                logger.info('[输入] ASR 结果: "%s"', user_input)
                source = "voice"

            # ③ 执行LangGraph智能体图（在线程池中非阻塞）
            logger.info("[Graph] ====== 调用 GraphEngine.invoke() ======")

            try:
                result = await run_sync(
                    self.graph_engine.invoke,
                    {
                        "user_input": user_input,
                        "user_source": source,
                        "messages": list(self.llm_manager.conversation),
                        "round_num": self._round_num,
                        "tool_loop_count": 0,
                    },
                )
            except Exception as e:
                logger.error("[Graph] 异常: %s", e)
                await asyncio.sleep(0.1)
                continue

            # 同步对话上下文
            self.llm_manager.conversation = result.get(
                "messages", self.llm_manager.conversation
            )

            # 保存对话历史
            final_reply = result.get("final_reply", "")
            with open(self.history_file, "a", encoding="utf-8") as f:
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"Time：{timestamp}\n")
                f.write(f"User：{user_input}\nNeko：{final_reply}\n---\n")

            logger.info("[Graph] ====== GraphEngine.invoke() 返回 =====")
            logger.info("[Graph] 最终回复 (%d 字符): %s", len(final_reply), final_reply[:80])

            if result.get("should_exit"):
                logger.info("[退出] 用户请求退出，结束对话循环")
                _stop_event.set()
                get_scheduler().stop()
                break

            logger.info("[循环] 第 %d 轮完成，准备下一轮...", self._round_num)

        logger.info("[IOCP] 用户输入循环退出")

    def _cleanup(self):
        """统一资源清理"""
        _busy_event.clear()
        logger.info("")
        logger.info("╔════════════════════════════════════════════════════════════════╗")
        logger.info("║                  关闭序列 — 清理资源                          ║")
        logger.info("╚════════════════════════════════════════════════════════════════╝")

        logger.info("[关闭] 广播 on_shutdown 到 %d 个插件...", len(self.registry.enabled_plugins))
        self.registry.broadcast_on_shutdown()
        logger.info("[关闭] on_shutdown 广播完成")

        logger.info("[关闭] 停止 UI 前端...")
        self.ui_shell.stop()
        logger.info("[关闭] UI 前端已停止")

        logger.info("[关闭] 关闭 IOCP 调度器...")
        shutdown_scheduler()
        logger.info("[关闭] IOCP 调度器已关闭")

        logger.info("[关闭] 主循环结束，系统已安全退出。")
        logger.info("")


# 程序入口判断：仅当直接运行main.py脚本时执行下方启动代码
# 若本文件被其他py文件import导入，则不会执行启动逻辑，方便模块化调用
if __name__ == "__main__":
    logger.info("================================================================")
    logger.info("  VirtuMate 启动")
    logger.info("  Python: %s | 架构: IOCP Agent | 线程: 主+Live2D+对话",
                sys.version.split()[0])
    logger.info("================================================================")
    logger.info("")

    logger.info(">>> 创建 MainManager（全模块初始化）...")
    main_manager = MainManager()
    logger.info(">>> MainManager 创建完成")

    # 启动IOCP对话循环线程（后台任务自动执行）
    logger.info(">>> 启动IOCP对话循环线程...")
    conv_thread = threading.Thread(
        target=main_manager.run, daemon=True, name="conv-loop"
    )
    conv_thread.start()
    logger.info(">>> IOCP对话循环线程已启动 (tid=%s)", conv_thread.ident)

    # 主线程专门阻塞运行pywebview前端窗口事件循环
    logger.info(">>> 主线程进入 pywebview 事件循环（阻塞）...")
    logger.info(">>> 【提示】关闭 Live2D 窗口或按 Ctrl+C 退出程序")
    logger.info("")
    try:
        main_manager.ui_shell.run_on_main_thread()
    except KeyboardInterrupt:
        logger.info("")
        logger.info(">>> 收到 Ctrl+C，开始退出...")
    finally:
        _stop_event.set()
        shutdown_scheduler()
        logger.info(">>> 程序正常退出。")