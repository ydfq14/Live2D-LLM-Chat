
import os
import time
import base64
import shutil
import requests
import pygame
import wave
from piper import PiperVoice
from config import Config
from log_config import get_logger

logger = get_logger(__name__)


class TTSManager:
    def __init__(self, mode=None, api_url=None):
        """
        初始化 TTS 管理器，支持本地（CosyVoice）和云端（MIMO）两种模式。

        :param mode: "local" 或 "cloud"，不传则读取 Config.TTS_MODE
        :param api_url: 本地 CosyVoice API 地址（仅本地模式使用）
        """
        self.mode = mode or Config.TTS_MODE
        if self.mode not in ("local", "cloud"):
            raise ValueError(f"TTS_MODE 必须为 'local' 或 'cloud'，当前为: {self.mode}")

        # 输出目录（两种模式共用）
        self.output_dir = Config.TTS_OUTPUT_DIR
        os.makedirs(self.output_dir, exist_ok=True)

        if self.mode == "local":
            model_path = Config.PIPER_MODEL_PATH
            logger.info(f"TTS 初始化: local (piper-tts), model={model_path}")
            try:
                self.voice = PiperVoice.load(model_path)
            except FileNotFoundError:
                logger.error(f"模型文件不存在: {model_path}")
                raise
            except Exception as e:
                logger.error(f"加载 piper 模型失败: {e}")
                raise
            self.speaker_id = Config.PIPER_SPEAKER_ID
            self.length_scale = Config.PIPER_LENGTH_SCALE
            self.noise_scale = Config.PIPER_NOISE_SCALE
            self.noise_w = Config.PIPER_NOISE_W
            self.history_dir = Config.TTS_HISTORY_DIR
            os.makedirs(self.history_dir, exist_ok=True)
        else:
            logger.info(f"TTS 初始化: cloud, model={Config.MIMO_TTS_MODEL}, voice={Config.MIMO_TTS_VOICE}")
            self.api_key = Config.MIMO_API_KEY
            self.base_url = Config.MIMO_BASE_URL
            self.tts_model = Config.MIMO_TTS_MODEL
            self.tts_voice = Config.MIMO_TTS_VOICE
            self.tts_format = Config.MIMO_TTS_FORMAT
            self.tts_style = Config.MIMO_TTS_STYLE

    # ------------------------------------------------------------------
    # 核心合成接口（根据模式调度）
    # ------------------------------------------------------------------

    def synthesize(self, text):
        """
        将文本合成为语音，返回音频文件路径。

        :param text: 待合成的文本
        :return: 生成的音频文件路径
        """
        logger.info("▶ TTS 合成中 (%s)...", self.mode)

        if self.mode == "local":
            return self._synthesize_local(text)
        else:
            return self._synthesize_cloud(text)

    # ------------------------------------------------------------------
    # 本地合成：CosyVoice（通过 gradio_client）
    # ------------------------------------------------------------------

    def clear_output_directory(self):
        """生成前清理旧音频，归档到 history 目录"""
        pygame.mixer.init()
        pygame.mixer.music.stop()
        pygame.mixer.quit()

        audio_files = [f for f in os.listdir(self.output_dir) if f.endswith(".wav")]
        if not audio_files:
            return

        for file in audio_files:
            old_path = os.path.join(self.output_dir, file)
            new_path = os.path.join(self.history_dir, file)
            try:
                shutil.move(old_path, new_path)
            except Exception as e:
                logger.warning(f"无法移动 {file} 到历史目录: {e}")

    def _synthesize_local(self, text):
        """使用 piper-tts 进行本地语音合成。"""
        self.clear_output_directory()

        start_time = time.time()
        timestamp = int(time.time() * 1000)
        output_filename = f"tts_output_{timestamp}.wav"
        output_path = os.path.join(self.output_dir, output_filename)

        try:
            with wave.open(output_path, "wb") as wav_file:
                self.voice.synthesize(
                    text,
                    wav_file,
                    speaker_id=self.speaker_id,
                    length_scale=self.length_scale,
                    noise_scale=self.noise_scale,
                    noise_w=self.noise_w,
                )
        except Exception as e:
            logger.error(f"piper 合成失败: {e}")
            return None

        elapsed = time.time() - start_time
        logger.info(f"▶ TTS 完成 (local/piper)，耗时: {elapsed:.2f}s，文件: {output_path}")

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            logger.error(f"合成失败：输出文件为空或不存在 {output_path}")
            return None

        return output_path

    # ------------------------------------------------------------------
    # 云端合成：MiMo-V2.5-TTS
    # ------------------------------------------------------------------

    def _synthesize_cloud(self, text):
        """
        调用 MIMO TTS API 进行语音合成。

        MIMO TTS 使用 OpenAI Chat Completions 格式：
        - user 消息用于风格描述
        - assistant 消息承载待合成文本
        - 响应中的 audio.data 字段为 Base64 编码的 WAV

        :param text: 待合成文本
        :return: 生成的音频文件路径
        """
        start_time = time.time()

        logger.debug(f"云端 TTS 请求: model={self.tts_model}, voice={self.tts_voice}, len={len(text)}")

        # 1. 构造请求
        url = f"{self.base_url}/chat/completions"
        headers = {
            "api-key": self.api_key,
            "Content-Type": "application/json",
        }

        messages = []
        # 风格描述放在 user 消息中
        if self.tts_style:
            messages.append({"role": "user", "content": self.tts_style})
        # 待合成文本放在 assistant 消息中
        messages.append({"role": "assistant", "content": text})

        payload = {
            "model": self.tts_model,
            "messages": messages,
            "audio": {
                "format": self.tts_format,
                "voice": self.tts_voice,
            },
        }

        # 2. 发送请求
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
        if resp.status_code != 200:
            logger.error(f"MIMO TTS 请求失败 (HTTP {resp.status_code}): {resp.text}")
            raise RuntimeError(
                f"MIMO TTS 请求失败 (HTTP {resp.status_code}): {resp.text}"
            )

        # 3. 解码 Base64 音频并保存
        result = resp.json()
        audio_b64 = result["choices"][0]["message"]["audio"]["data"]
        audio_bytes = base64.b64decode(audio_b64)

        # 4. 保存到输出目录
        timestamp = int(time.time())
        output_path = os.path.join(self.output_dir, f"tts_output_{timestamp}.wav")
        with open(output_path, "wb") as f:
            f.write(audio_bytes)

        logger.info(f"▶ TTS 完成 (cloud)，耗时: {time.time() - start_time:.2f}s，文件: {output_path}")
        return output_path

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------


# ------------------------------------------------------------------
# 自测入口
# ------------------------------------------------------------------

if __name__ == "__main__":
    tts = TTSManager()
    test_text = "你好，我是你的AI猫娘助手，很高兴为你服务！"
    audio_path = tts.synthesize(test_text)
    print(f"音频已生成: {audio_path}")
