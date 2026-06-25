# 导入时间模块，用于延时、计算识别耗时
import time
# 导入wave模块，用于读写wav格式音频文件
import wave
# 导入base64编码库，云端ASR需要将音频二进制转为base64字符串传输
import base64
# 导入keyboard键盘监听库，实现按住Ctrl录音、Alt停止录音的交互逻辑
import keyboard
# 导入pyaudio音频采集库，实现麦克风实时录音
#import pyaudio

import pyaudiowpatch as pyaudio
# 导入numpy，用于 VAD 能量计算
import numpy as np
# 导入requests网络请求库，用于调用云端ASR接口发送HTTP请求
import requests
# 导入faster-whisper语音识别框架（可选，按需导入）
try:
    from faster_whisper import WhisperModel as FasterWhisperModel
    HAS_FASTER_WHISPER = True
except ImportError:
    HAS_FASTER_WHISPER = False
# 导入全局配置文件，读取ASR模式、模型路径、云端密钥、接口地址等常量
from config import Config
# 导入日志工具，统一格式化日志输出
from log_config import get_logger

# 获取当前模块的日志实例，日志会标注当前脚本名称
logger = get_logger(__name__)



# ASR语音识别管理器：统一封装 faster-whisper 本地识别 + 云端MIMO语音识别，包含录音逻辑
class ASRManager:
    # 类构造函数，初始化ASR运行模式、录音参数、本地模型/云端接口信息
    def __init__(self, mode=None, model_dir=None, device="cuda:0"):
        """
        初始化 ASR 语音识别管理器，支持 faster-whisper 本地和云端（MIMO）两种模式。

        :param mode: "faster-whisper" 或 "cloud"，不传则读取 Config.ASR_MODE
        :param model_dir: 本地模型路径（仅本地模式使用）
        :param device: 本地模式使用的计算设备（默认 cuda:0）
        """
        # 优先使用传入的mode，未传入则读取配置文件中的全局ASR模式
        self.mode = mode or Config.ASR_MODE
        # 校验模式合法性，支持本地local、云端cloud或faster-whisper
        if self.mode not in ("local", "cloud", "faster-whisper"):
            # 非法模式抛出异常，终止程序并提示错误
            raise ValueError(f"ASR_MODE 必须为 'local', 'cloud' 或 'faster-whisper'，当前为: {self.mode}")

        # ===================== 录音通用参数（本地/云端录音共用一套配置） =====================
        # 音频采样率：44100Hz，通用人声录音标准采样率
        self.sample_rate = 44100
        # 声道数：1 单声道，语音识别不需要立体声，减少数据量
        self.channels = 1
        # 单次读取音频块大小，平衡实时性与CPU占用
        self.chunk = 1024
        # 采样位深：16位整型，wav标准音频格式
        self.format = pyaudio.paInt16

        # ===================== Faster-Whisper 模式初始化 =====================
        if self.mode == "faster-whisper":
            if not HAS_FASTER_WHISPER:
                raise ImportError("未安装 faster-whisper，请运行: pip install faster-whisper")

            logger.info(f"ASR 初始化: faster-whisper, model={Config.ASR_WHISPER_MODEL_SIZE}, device={Config.ASR_WHISPER_DEVICE}")

            # 自动选择设备
            device = Config.ASR_WHISPER_DEVICE
            if device == "auto":
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"

            # 初始化 WhisperModel
            self.model = FasterWhisperModel(
                model_size_or_path=Config.ASR_WHISPER_MODEL_SIZE,
                device=device,
                compute_type=Config.ASR_WHISPER_COMPUTE_TYPE,
            )
            self.whisper_language = Config.ASR_WHISPER_LANGUAGE
        # ===================== 云端ASR模式初始化 =====================
        else:
            # 打印日志，记录云端识别初始化与使用的云端模型名称
            logger.info(f"ASR 初始化: cloud, model={Config.MIMO_ASR_MODEL}")
            # 读取配置文件中的接口密钥
            self.api_key = Config.MIMO_API_KEY
            # 读取云端接口基础域名
            self.base_url = Config.MIMO_BASE_URL
            # 读取云端使用的ASR模型标识
            self.asr_model = Config.MIMO_ASR_MODEL
            # 读取识别语言（中文/多语言）
            self.language = Config.MIMO_ASR_LANGUAGE

    # ------------------------------------------------------------------
    # 录音（VAD 自动检测：监听 → 检测语音 → 2 秒静音后自动结束）
    # ------------------------------------------------------------------
    def record_audio(self, output_wav_file):
        """
        VAD 自动录音，替代原来的按键控制。

        状态机:
          LISTENING → SPEAKING → SILENCE_WAIT → (结束 or 回到 SPEAKING)

        - 持续监控麦克风音量
        - 检测到语音（RMS > 阈值）→ 开始录音
        - 语音中断后持续 2 秒静音 → 自动结束录音
        - 支持外部 _abort_event 中断

        :param output_wav_file: 录制完成后保存的wav音频文件路径
        :return: True 录音完成且有有效语音，False 被中断或无有效语音
        """
        abort = getattr(self, "_abort_event", None)
        if abort:
            abort.clear()

        p = pyaudio.PyAudio()
        stream = p.open(
            format=self.format,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk,
        )
        sample_width = p.get_sample_size(self.format)

        # 状态机
        state = "LISTENING"       # LISTENING | SPEAKING | SILENCE_WAIT
        frames: list[bytes] = []  # 录音帧缓存
        silence_start = 0.0       # 当前静音段起始时间
        speech_start = 0.0        # 第一帧语音时间（用于最小语音时长校验）

        # 语音前缓冲区（保留 VAD_SPEECH_PADDING 秒的音频，避免截断开头）
        pre_frames: list[bytes] = []
        max_pre_frames = max(1, int(self.sample_rate * Config.VAD_SPEECH_PADDING / self.chunk))
        # 每帧时长（秒）
        frame_dur = self.chunk / self.sample_rate

        print("[VAD] 正在聆听...")

        while True:
            data = stream.read(self.chunk, exception_on_overflow=False)

            # 计算 RMS 能量
            audio_np = np.frombuffer(data, dtype=np.int16)
            rms = float(np.sqrt(np.mean(audio_np.astype(np.float64) ** 2)))

            # 检查外部中断
            if abort and abort.is_set():
                self._cleanup_stream(p, stream)
                logger.info("录音被中断（聊天框输入到达）。")
                return False

            if state == "LISTENING":
                # 维护语音前缓冲区
                pre_frames.append(data)
                if len(pre_frames) > max_pre_frames:
                    pre_frames.pop(0)

                if rms > Config.VAD_SILENCE_THRESHOLD:
                    state = "SPEAKING"
                    speech_start = time.time()
                    # 保留语音前的 padding 音频
                    frames.extend(pre_frames)
                    frames.append(data)
                    print("[VAD] 检测到语音，正在录音...")

            elif state == "SPEAKING":
                frames.append(data)
                if rms < Config.VAD_SILENCE_THRESHOLD:
                    state = "SILENCE_WAIT"
                    silence_start = time.time()

            elif state == "SILENCE_WAIT":
                frames.append(data)
                if rms > Config.VAD_SILENCE_THRESHOLD:
                    # 语音恢复，回到录音状态
                    state = "SPEAKING"
                elif time.time() - silence_start >= Config.VAD_SILENCE_TIMEOUT:
                    # 静音超时，录音结束
                    break

        self._cleanup_stream(p, stream)

        # 校验最短语音时长（过滤咳嗽等短杂音）
        speech_duration = time.time() - speech_start - Config.VAD_SILENCE_TIMEOUT
        if speech_duration < Config.VAD_MIN_SPEECH_DURATION:
            print(f"[VAD] 语音过短 ({speech_duration:.1f}s < {Config.VAD_MIN_SPEECH_DURATION}s)，已忽略。")
            return False

        # 保存 wav
        with wave.open(output_wav_file, "wb") as wf:
            wf.setnchannels(self.channels)
            wf.setsampwidth(sample_width)
            wf.setframerate(self.sample_rate)
            wf.writeframes(b"".join(frames))

        total_dur = len(frames) * frame_dur
        print(f"[VAD] 录音完成，时长 {total_dur:.1f}s")
        return True

    @staticmethod
    def _cleanup_stream(p, stream):
        """清理 PyAudio 音频流和设备资源。"""
        try:
            stream.stop_stream()
            stream.close()
        except Exception:
            pass
        try:
            p.terminate()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # 语音识别统一入口：根据当前mode自动分发本地/云端识别函数
    # ------------------------------------------------------------------
    def recognize_speech(self, wav_path):
        """
        根据当前模式调用本地或云端识别。

        :param wav_path: 待识别的wav音频文件路径
        :return: 识别完成后的纯文本结果
        """
        # 记录识别开始时间戳，用于计算识别耗时
        start_time = time.time()

        # 打印日志，标记开始识别并显示当前使用的模式
        logger.info("▶ ASR 识别中 (%s)...", self.mode)

        # 判断模式，调用对应识别方法
        if self.mode == "faster-whisper":
            # Faster-Whisper 本地识别，获取文本
            text = self._recognize_faster_whisper(wav_path)
        else:
            # 云端MIMO接口识别，获取文本
            text = self._recognize_cloud(wav_path)

        # 计算识别总耗时：当前时间 - 起始时间
        elapsed = time.time() - start_time
        # 文本预览截断：超过50字则截取前50字加省略号，日志精简输出
        text_preview = text[:50] + "..." if len(text) > 50 else text
        # 打印日志：识别完成、模式、耗时、识别文本预览
        logger.info(f'▶ ASR 完成 ({self.mode})，耗时: {elapsed:.2f}s → "{text_preview}"')
        # 返回完整识别文本给上层调用（MainManager对话循环）
        return text

    # ------------------------------------------------------------------
    # Faster-Whisper 识别私有方法：使用 Whisper 模型离线识别
    # ------------------------------------------------------------------
    def _recognize_faster_whisper(self, wav_path):
        """
        使用 faster-whisper 进行语音识别。

        :param wav_path: 待识别的 wav 音频文件路径
        :return: 识别完成后的纯文本结果
        """
        # 执行转录，language 为 None 时自动检测
        language = self.whisper_language if self.whisper_language != "auto" else None
        segments, info = self.model.transcribe(
            wav_path,
            language=language,
            beam_size=5,
            vad_filter=True,  # 启用 VAD 过滤静音段
        )

        # 拼接所有 segments 的文本
        text = " ".join([segment.text for segment in segments])

        # 清理文本：去除首尾空白
        text = text.strip()

        logger.debug(f"faster-whisper 识别结果: language={info.language}, probability={info.language_probability:.2f}")

        return text

    # ------------------------------------------------------------------
    # 云端识别私有方法：调用MIMO大模型ASR HTTP接口
    # ------------------------------------------------------------------
    def _recognize_cloud(self, wav_path):
        """
        调用 MIMO ASR API 进行语音识别。
        音频通过 Base64 编码后以 data URL 格式发送。
        """
        # 1. 二进制读取本地wav音频文件
        with open(wav_path, "rb") as f:
            audio_bytes = f.read()
        # 将音频二进制数据编码为base64字符串，网络传输只能传文本
        audio_b64 = base64.b64encode(audio_bytes).decode("utf-8")

        # 调试日志：打印请求模型、音频文件字节大小
        logger.debug(f"云端 ASR 请求: model={self.asr_model}, size={len(audio_bytes)}B")

        # 2. 拼接完整云端接口请求地址
        url = f"{self.base_url}/chat/completions"
        # 构造HTTP请求头，携带鉴权密钥与数据格式
        headers = {
            "api-key": self.api_key,        # 接口鉴权密钥
            "Content-Type": "application/json", # 请求体为JSON格式
        }
        # 构造接口请求体，遵循OpenAI兼容对话格式，嵌入音频base64数据
        payload = {
            "model": self.asr_model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": f"data:audio/wav;base64,{audio_b64}" # base64音频DataURL
                            },
                        }
                    ],
                }
            ],
            "asr_options": {"language": self.language}, # 指定识别语言参数
        }

        # 3. 发送POST网络请求，设置60秒超时防止卡死
        resp = requests.post(url, headers=headers, json=payload, timeout=60)
        # 判断HTTP响应状态码，非200代表接口请求失败
        if resp.status_code != 200:
            # 打印错误日志，输出状态码与接口返回报错信息
            logger.error(f"MIMO ASR 请求失败 (HTTP {resp.status_code}): {resp.text}")
            # 抛出运行时异常，终止流程向上层反馈接口故障
            raise RuntimeError(
                f"MIMO ASR 请求失败 (HTTP {resp.status_code}): {resp.text}"
            )

        # 4. 将接口返回的JSON字符串转为字典，解析识别结果
        result = resp.json()
        # 取出AI回复的识别文本，去除首尾空白空格换行后返回
        return result["choices"][0]["message"]["content"].strip()


# ------------------------------------------------------------------
# 自测入口：单独运行本脚本时执行录音+识别测试
# ------------------------------------------------------------------
if __name__ == "__main__":
    # 实例化ASR管理器，自动读取配置文件中的ASR_MODE模式
    asr = ASRManager()
    # 从配置读取录音保存的wav文件路径
    audio_file = Config.ASR_AUDIO_INPUT

    # 执行录音函数，生成音频文件
    asr.record_audio(audio_file)
    # 调用识别函数，得到文本结果
    text = asr.recognize_speech(audio_file)
    # 控制台打印最终识别文字
    print(f"识别结果: {text}")