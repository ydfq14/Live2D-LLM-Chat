# 导入时间模块，用于计算帧间隔、音频计时、鼠标闲置判断
import time
# 导入GLFW窗口库，用于创建透明置顶窗口、OpenGL上下文管理
import glfw
# 导入OpenGL核心库，用于图形清屏、视口设置等渲染操作
import OpenGL.GL as gl
# 导入pyautogui，用于获取屏幕鼠标坐标、获取屏幕分辨率
import pyautogui
# 导入pygame混音模块，用于音频加载与播放
import pygame
# 导入ctypes，调用Windows原生User32 API修改窗口扩展样式（穿透、分层）
import ctypes
# 导入pydub音频工具，用于解析wav音频、分段提取音量RMS值
from pydub import AudioSegment
# 导入Live2D V3核心类与全局初始化/销毁/渲染工具函数
from live2d.v3 import LAppModel, init, dispose, glInit, clearBuffer
# 导入项目配置文件（存放全局常量、路径等自定义配置）
from config import Config
from log_config import get_logger

logger = get_logger(__name__)

# ===================== Windows窗口API常量定义 =====================
# 获取/设置窗口扩展样式的参数索引
GWL_EXSTYLE = -20
# 分层窗口标识：支持透明通道渲染，必须搭配WS_EX_TRANSPARENT实现穿透
WS_EX_LAYERED = 0x00080000
# 鼠标穿透标识：窗口区域鼠标事件穿透到下层桌面/窗口
WS_EX_TRANSPARENT = 0x00000020

# ===================== Live2D眨眼状态枚举常量（预留扩展） =====================
# 无眨眼动作
BLINK_STATE_NONE = 0
# 闭眼过程中
BLINK_STATE_CLOSING = 1
# 完全闭眼状态
BLINK_STATE_CLOSED = 2
# 睁眼过程中
BLINK_STATE_OPENING = 3


# Live2D动画管理主类：负责窗口创建、模型加载、鼠标追眼、音频嘴型同步、渲染循环
class Live2DAnimationManager:
    # 类构造函数，初始化所有基础参数与变量
    def __init__(self, model_path, frame_rate=60):
        """
        初始化 Live2D 动画管理器
        :param model_path: Live2D 模型文件路径（.model3.json 主配置文件）
        :param frame_rate: 渲染帧率，同时音频分段采样帧率与该值对齐
        """
        # 存储模型json文件路径
        self.model_path = model_path
        # 存储渲染/音频采样帧率，默认60帧每秒
        self.frame_rate = frame_rate
        # 嘴型参数值：范围0~1，0闭嘴，1最大张开，绑定Live2D ParamMouthOpenY参数
        self.mouth_value = 0
        # GLFW窗口对象实例，初始为空
        self.window = None
        # Live2D模型实例对象，初始为空
        self.model = None
        # 渲染循环运行总开关，True持续渲染，False退出循环
        self.running = True

        # ===================== 窗口拖动相关参数初始化 =====================
        # 是否正在拖动窗口（右键按住拖动）
        self._dragging = False
        # 拖动开始时的鼠标屏幕全局坐标
        self._drag_start_mouse = (0, 0)
        # 拖动开始时的窗口左上角屏幕坐标
        self._drag_start_win = (0, 0)
        # 当前是否处于可拖动模式（移除鼠标穿透）
        self._drag_mode = False

        # ===================== 鼠标跟随相关参数初始化 =====================
        # 获取程序启动时初始鼠标坐标，记录上一帧鼠标位置
        self.last_mouse_x, self.last_mouse_y = pyautogui.position()
        # 记录鼠标最后一次移动的时间戳，用于判断闲置状态
        self.last_move_time = time.time()
        # 鼠标闲置阈值：3秒无移动自动让视线回归模型中心
        self.IDLE_THRESHOLD = 3.0

        # ===================== 头部/视线映射范围参数 =====================
        # 视线参数X轴最小值（Live2D内部Drag参数区间）
        self.X_MIN, self.X_MAX = 200, 480
        # 视线参数Y轴最小值（Live2D内部Drag参数区间）
        self.Y_MIN, self.Y_MAX = 300, 360
        # 计算X轴映射中心点（鼠标不动时视线回归的X基准）
        self.center_x_mapped = (self.X_MIN + self.X_MAX) / 2
        # 计算Y轴映射中心点（鼠标不动时视线回归的Y基准）
        self.center_y_mapped = (self.Y_MIN + self.Y_MAX) / 2
        # 当前平滑后的视线X坐标（用于Drag驱动头部跟随）
        self.gaze_x = 0.0
        # 当前平滑后的视线Y坐标（用于Drag驱动头部跟随）
        self.gaze_y = 0.0
        # 鼠标移动时视线平滑缓动系数，数值越大跟随越快
        self.GAZE_EASING = 0.02

    # 配置GLFW窗口Windows原生属性：透明分层、鼠标穿透
    def configure_window(self, window, width, height):
        """
        配置 GLFW 窗口，使其透明且可穿透鼠标
        :param window: glfw创建的窗口实例
        :param width: 窗口宽度
        :param height: 窗口高度
        """
        # 通过GLFW获取Windows原生窗口句柄HWND，用于调用Win32 API
        hwnd = glfw.get_win32_window(window)
        # 绑定user32库获取窗口扩展样式函数
        get_window_long = ctypes.windll.user32.GetWindowLongW
        # 绑定user32库设置窗口扩展样式函数
        set_window_long = ctypes.windll.user32.SetWindowLongW
        # 读取窗口当前已有的扩展样式
        ex_style = get_window_long(hwnd, GWL_EXSTYLE)
        # 位运算叠加分层透明、鼠标穿透两个样式标识
        ex_style |= (WS_EX_LAYERED | WS_EX_TRANSPARENT)
        # 将修改后的样式写回窗口
        set_window_long(hwnd, GWL_EXSTYLE, ex_style)

        # 将当前窗口OpenGL上下文设置为活跃，后续GL渲染指令作用于此窗口
        glfw.make_context_current(window)
        # 获取显示器完整屏幕宽、高分辨率
        screen_width, screen_height = pyautogui.size()
        # 设置窗口位置：贴屏幕底部，左上角坐标(0, 屏幕高度-窗口高度)
        glfw.set_window_pos(window, 0, screen_height - height)

    # 启用拖动模式：移除鼠标穿透样式，窗口可接收鼠标事件
    def _enable_drag_mode(self):
        """移除 WS_EX_TRANSPARENT，让窗口接管鼠标事件以实现拖动"""
        if self._drag_mode:
            return
        hwnd = glfw.get_win32_window(self.window)
        get_window_long = ctypes.windll.user32.GetWindowLongW
        set_window_long = ctypes.windll.user32.SetWindowLongW
        ex_style = get_window_long(hwnd, GWL_EXSTYLE)
        # 去除鼠标穿透标志，保留分层透明标志
        ex_style &= ~WS_EX_TRANSPARENT
        set_window_long(hwnd, GWL_EXSTYLE, ex_style)
        self._drag_mode = True
        logger.debug("拖动模式已启用（已移除鼠标穿透）")

    # 恢复穿透模式：重新添加鼠标穿透样式，鼠标事件穿透到桌面
    def _disable_drag_mode(self):
        """还原 WS_EX_TRANSPARENT，恢复鼠标穿透桌面"""
        if not self._drag_mode:
            return
        hwnd = glfw.get_win32_window(self.window)
        get_window_long = ctypes.windll.user32.GetWindowLongW
        set_window_long = ctypes.windll.user32.SetWindowLongW
        ex_style = get_window_long(hwnd, GWL_EXSTYLE)
        # 重新叠加鼠标穿透标志
        ex_style |= WS_EX_TRANSPARENT
        set_window_long(hwnd, GWL_EXSTYLE, ex_style)
        self._drag_mode = False
        logger.debug("穿透模式已恢复（已启用鼠标穿透）")

    # GLFW 鼠标按键回调：右键按下启动拖动，右键松开停止拖动
    def _on_mouse_button(self, window, button, action, mods):
        """
        GLFW 鼠标按键事件回调
        - 右键按下 (MOUSE_BUTTON_RIGHT + PRESS)：记录拖动起点，进入拖动状态
        - 右键松开 (MOUSE_BUTTON_RIGHT + RELEASE)：退出拖动，恢复穿透
        """
        if button == glfw.MOUSE_BUTTON_RIGHT:
            if action == glfw.PRESS:
                # 记录按下时鼠标的屏幕全局坐标
                mx, my = pyautogui.position()
                # 记录按下时窗口的屏幕坐标
                wx, wy = glfw.get_window_pos(window)
                self._drag_start_mouse = (mx, my)
                self._drag_start_win = (wx, wy)
                self._dragging = True
                logger.debug(f"开始拖动 — 鼠标起点=({mx},{my})，窗口起点=({wx},{wy})")
            elif action == glfw.RELEASE:
                self._dragging = False
                # 拖动结束后恢复鼠标穿透，避免遮挡桌面操作
                self._disable_drag_mode()
                logger.debug("停止拖动，恢复穿透模式")

    # GLFW 鼠标移动回调：拖动中实时更新窗口位置
    def _on_cursor_pos(self, window, xpos, ypos):
        """
        GLFW 鼠标移动事件回调
        拖动模式下：计算鼠标位移量，等比移动窗口位置
        """
        if self._dragging:
            # 获取当前鼠标屏幕全局坐标
            mx, my = pyautogui.position()
            # 计算相对于拖动起点的位移量
            dx = mx - self._drag_start_mouse[0]
            dy = my - self._drag_start_mouse[1]
            # 计算新窗口位置 = 拖动起点窗口位置 + 位移量
            new_x = self._drag_start_win[0] + dx
            new_y = self._drag_start_win[1] + dy
            # 移动 GLFW 窗口到新坐标
            glfw.set_window_pos(window, new_x, new_y)

    # GLFW 键盘回调：按住 Ctrl 键切换拖动模式
    def _on_key(self, window, key, scancode, action, mods):
        """
        GLFW 键盘事件回调
        - 按下 Ctrl：启用拖动模式（移除穿透，此后右键可拖动窗口）
        - 松开 Ctrl 且未在拖动：恢复穿透模式
        """
        if key == glfw.KEY_LEFT_CONTROL or key == glfw.KEY_RIGHT_CONTROL:
            if action == glfw.PRESS:
                self._enable_drag_mode()
                logger.debug("Ctrl 按下，拖动模式就绪（右键拖拽窗口）")
            elif action == glfw.RELEASE:
                # 只有未在拖动状态时才立即恢复穿透，避免拖动中断
                if not self._dragging:
                    self._disable_drag_mode()

    # 根据路径加载Live2D模型并适配窗口尺寸
    def load_live2d_model(self, width, height):
        """
        加载 Live2D 模型
        :param width: 窗口宽度
        :param height: 窗口高度
        :return: 初始化完成的Live2D模型对象
        """
        # 实例化Live2D V3模型加载类
        model = LAppModel()
        # 传入model3.json路径加载模型资源（纹理、骨骼、参数、动画）
        model.LoadModelJson(self.model_path)
        # 根据窗口宽高重置模型渲染画布尺寸
        model.Resize(width, height)
        # 返回加载完成的模型实例供渲染循环使用
        return model

    # 创建窗口、启动持续渲染循环，常驻显示Live2D角色
    def play_live2d_once(self):
        """
        创建 Live2D 窗口，并让角色进行渲染（保持运行）
        """
        # 全局初始化Live2D底层运行环境
        init()
        # 初始化GLFW窗口库，失败则直接退出
        if not glfw.init():
            logger.error("GLFW 初始化失败！")
            return

        # GLFW窗口属性设置：帧缓冲支持透明通道Alpha
        glfw.window_hint(glfw.TRANSPARENT_FRAMEBUFFER, glfw.TRUE)
        # GLFW窗口属性设置：无边框，无标题栏、最小化按钮
        glfw.window_hint(glfw.DECORATED, glfw.FALSE)
        # GLFW窗口属性设置：置顶悬浮，始终在所有窗口上层
        glfw.window_hint(glfw.FLOATING, glfw.TRUE)

        # 定义渲染窗口固定宽高
        window_width, window_height = 800, 600
        # 创建GLFW窗口对象，无监视器、无共享上下文
        self.window = glfw.create_window(window_width, window_height, "Live2D Window", None, None)
        # 窗口创建失败判断，释放资源并退出
        if not self.window:
            logger.error("GLFW 窗口创建失败！")
            glfw.terminate()
            return

        # 调用自定义方法配置窗口透明、鼠标穿透、底部贴边
        self.configure_window(self.window, window_width, window_height)

        # ===== 注册拖动相关 GLFW 事件回调 =====
        # 注册鼠标按键回调（右键按下/松开控制拖动）
        glfw.set_mouse_button_callback(self.window, self._on_mouse_button)
        # 注册鼠标移动回调（拖动中实时更新窗口位置）
        glfw.set_cursor_pos_callback(self.window, self._on_cursor_pos)
        # 注册键盘回调（按 Ctrl 进入/退出拖动模式）
        glfw.set_key_callback(self.window, self._on_key)
        logger.info("💡 提示：按住 Ctrl 键启用拖动模式，然后右键拖拽可移动窗口")
        # ===== 回调注册完成 =====
        # Live2D专用OpenGL函数初始化，绑定底层渲染接口
        glInit()

        # 加载模型到实例变量self.model，全局可访问
        self.model = self.load_live2d_model(window_width, window_height)
        logger.info(f"Live2D 模型已加载: {self.model_path}")

        # 记录上一帧时间戳，用于计算帧间隔dt
        last_time = time.time()
        # 开启OpenGL Alpha混合，确保Live2D纹理透明区域正确渲染
        gl.glEnable(gl.GL_BLEND)
        gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
        # 设置OpenGL清屏底色：RGBA全透明（黑底0，Alpha0）
        gl.glClearColor(0.0, 0.0, 0.0, 0.0)

        # 主渲染循环：运行开关开启且窗口未关闭时持续执行
        while self.running and not glfw.window_should_close(self.window):
            # 清空颜色缓冲区，擦除上一帧画面
            gl.glClear(gl.GL_COLOR_BUFFER_BIT)
            # 获取当前系统时间戳
            now = time.time()
            # 计算当前帧与上一帧的时间差（帧间隔dt）
            dt = now - last_time
            # 更新上一帧时间戳为当前时间，供下一帧计算间隔
            last_time = now

            # 获取当前窗口帧缓冲实际宽高（适配窗口缩放）
            width, height = glfw.get_framebuffer_size(self.window)
            # 设置OpenGL视口：渲染区域铺满整个窗口
            gl.glViewport(0, 0, width, height)
            # Live2D专用缓冲清空，清除透明背景残留
            clearBuffer(0, 0, 0, 0)

            # 更新Live2D模型内部状态（骨骼、动画参数、物理摆动）
            self.model.Update()
            # 设置模型嘴型参数，绑定self.mouth_value，插值权重1立即生效
            self.model.SetParameterValue("ParamMouthOpenY", self.mouth_value, 1)

            # 调用视线追踪逻辑，更新头部跟随鼠标参数
            self.update_gaze_tracking(width, height)

            # 执行模型绘制渲染，输出到帧缓冲
            self.model.Draw()
            # 交换前后帧缓冲，将渲染画面显示到窗口
            glfw.swap_buffers(self.window)
            # 轮询窗口事件（鼠标移动、窗口关闭、按键等）
            glfw.poll_events()

        # 循环退出后停止所有音频播放
        pygame.mixer.music.stop()
        # 销毁pygame混音器，释放音频设备资源
        pygame.mixer.quit()
        # 全局销毁Live2D底层资源
        dispose()
        # 关闭GLFW窗口库，释放窗口、OpenGL上下文
        glfw.terminate()
        logger.info("Live2D 渲染循环已退出，资源已释放。")

    # 更新视线跟随逻辑：鼠标移动跟随，闲置回归中心
    def update_gaze_tracking(self, width, height):
        """
        计算鼠标跟随逻辑，让 Live2D 角色的眼睛和头部跟随鼠标
        :param width: 当前窗口宽度
        :param height: 当前窗口高度
        """
        # 获取鼠标在整个屏幕上的全局坐标
        screen_x, screen_y = pyautogui.position()
        # 获取窗口在屏幕左上角的全局坐标
        win_x, win_y = glfw.get_window_pos(self.window)
        # 计算鼠标在窗口内部的局部X坐标（屏幕鼠标X - 窗口左偏移）
        local_mouse_x = screen_x - win_x
        # 计算鼠标在窗口内部的局部Y坐标（屏幕鼠标Y - 窗口上偏移）
        local_mouse_y = screen_y - win_y

        # 判断鼠标坐标是否发生变化（鼠标移动）
        if (screen_x != self.last_mouse_x) or (screen_y != self.last_mouse_y):
            # 更新鼠标最后移动时间戳，重置闲置计时
            self.last_move_time = time.time()
            # 保存当前鼠标坐标为上一帧坐标，用于下一帧对比
            self.last_mouse_x, self.last_mouse_y = screen_x, screen_y

        # 判断鼠标未闲置：距离上次移动小于3秒
        if (time.time() - self.last_move_time) < self.IDLE_THRESHOLD:
            # 将窗口局部鼠标X坐标归一化，映射到Live2D Drag参数X区间[X_MIN,X_MAX]
            mapped_x = self.X_MIN + (local_mouse_x / width) * (self.X_MAX - self.X_MIN)
            # 将窗口局部鼠标Y坐标归一化，映射到Live2D Drag参数Y区间[Y_MIN,Y_MAX]
            mapped_y = self.Y_MIN + (local_mouse_y / height) * (self.Y_MAX - self.Y_MIN)
            # 视线目标坐标 = 鼠标映射后的坐标
            target_x = mapped_x
            target_y = mapped_y
            # 活跃状态使用正常缓动系数，视线敏捷跟随鼠标
            easing = self.GAZE_EASING
        # 鼠标闲置超过阈值，视线回归模型中心点
        else:
            # 视线目标X设为中心基准
            target_x = self.center_x_mapped
            # 视线目标Y设为中心基准
            target_y = self.center_y_mapped
            # 闲置时降低缓动系数，视线缓慢归位
            easing = 0.0004

        # 平滑插值X：当前视线向目标视线靠近，乘以缓动系数
        self.gaze_x += easing * (target_x - self.gaze_x)
        # 平滑插值Y：当前视线向目标视线靠近，乘以缓动系数
        self.gaze_y += easing * (target_y - self.gaze_y)
        # 将平滑后的视线坐标传入Live2D Drag接口，驱动头部、眼球跟随
        self.model.Drag(self.gaze_x, self.gaze_y)

    # 解析音频文件，按帧率分段提取音量，归一化输出用于嘴型驱动
    def extract_volume_array(self, audio_file):
        """
        提取音频的音量信息，并归一化用于嘴型同步
        :param audio_file: wav音频文件路径
        :return volumes: 归一化音量数组(0~1)；audio_duration: 音频总时长秒
        """
        # 使用pydub加载wav格式音频文件，生成音频段对象
        seg = AudioSegment.from_file(audio_file, format="wav")
        # 单帧音频时长(毫秒)：1000ms / 渲染帧率
        frame_duration_ms = 1000 / self.frame_rate
        # 计算音频总帧数 = 音频总秒数 × 帧率
        num_frames = int(seg.duration_seconds * self.frame_rate)

        # 空列表存储每一帧音频的RMS音量值
        volumes = []
        # 循环遍历每一帧音频片段
        for i in range(num_frames):
            # 当前帧起始毫秒时间戳
            start_ms = i * frame_duration_ms
            # 截取当前帧对应的音频片段
            frame_seg = seg[start_ms: start_ms + frame_duration_ms]
            # 获取该音频片段RMS均方根音量（代表响度大小）
            rms = frame_seg.rms
            # 将音量存入数组
            volumes.append(rms)

        # 取音量数组最大值，用于归一化；空数组则默认最大值1避免除0
        max_rms = max(volumes) if volumes else 1
        # 全部音量除以最大值，归一化到0~1区间
        volumes = [v / max_rms for v in volumes]
        # 返回归一化音量数组、音频总时长
        return volumes, seg.duration_seconds

    # 播放音频，同步更新嘴型参数self.mouth_value，实现说话动嘴
    def play_audio_and_print_mouth(self, audio_file):
        """
        播放音频并同步嘴型动作
        :param audio_file: wav音频文件路径
        """
        logger.info("▶ Live2D 嘴型同步播放中...")

        # 解析音频得到归一化音量数组、音频总时长
        volume_array, audio_duration = self.extract_volume_array(audio_file)
        # 获取音频总帧数
        total_frames = len(volume_array)

        logger.debug(f"嘴型同步播放: {audio_file}, 时长={audio_duration:.1f}s, 帧数={total_frames}")

        # 初始化pygame音频混音器
        pygame.mixer.init()
        # 加载音频文件到混音器
        pygame.mixer.music.load(audio_file)
        # 开始播放音频
        pygame.mixer.music.play()

        # 记录音频播放起始时间戳
        start_time = time.time()
        # 循环持续更新嘴型，直到播放时长超过音频总长度
        while True:
            # 计算当前已播放时长（当前时间 - 播放起始时间）
            current_time = time.time() - start_time
            # 播放时长超过音频总时长，退出循环停止更新嘴型
            if current_time >= audio_duration:
                break

            # 根据播放时长计算当前对应音频帧索引
            frame_index = int(current_time * self.frame_rate)
            # 索引越界保护：超过总帧数则取最后一帧音量
            if frame_index >= total_frames:
                frame_index = total_frames - 1

            # 将当前帧归一化音量赋值给嘴型参数，渲染循环实时读取
            self.mouth_value = volume_array[frame_index]

        # 音频播放完成后停止混音器播放
        pygame.mixer.music.stop()

        logger.info("▶ Live2D 播放完成")