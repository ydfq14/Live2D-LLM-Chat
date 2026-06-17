
import os
import time
import base64
import shutil
import requests
import pygame
from gradio_client import Client, handle_file
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
            logger.info(f"TTS 初始化: local, api={api_url or Config.TTS_API_URL}")
            self.client = Client(api_url or Config.TTS_API_URL)
            self.history_dir = Config.TTS_HISTORY_DIR
            self.prompt_text_path = Config.TTS_PROMPT_TEXT
            self.prompt_wav_path = Config.TTS_PROMPT_WAV
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
        """
        调用本地 CosyVoice 进行语音合成（3s 极速复刻模式）。
        """
        self.clear_output_directory()

        with open(self.prompt_text_path, "r", encoding="utf-8") as f:
            prompt_text = f.read()

        start_time = time.time()
        self.client.predict(
            tts_text=text,
            mode_checkbox_group="3s极速复刻",
            sft_dropdown="",
            prompt_text=prompt_text,
            prompt_wav_upload=handle_file(self.prompt_wav_path),
            prompt_wav_record=handle_file(self.prompt_wav_path),
            instruct_text="",
            seed=0,
            stream=False,
            speed=1,
            api_name="/generate_audio",
        )
        logger.info(f"▶ TTS 完成 (local)，耗时: {time.time() - start_time:.2f}s")
        return self._get_latest_audio()

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

    def _get_latest_audio(self):
        """获取 output_voice 目录下最新生成的音频文件（仅本地模式使用）"""
        audio_files = [f for f in os.listdir(self.output_dir) if f.endswith(".wav")]
        if not audio_files:
            logger.warning("output_voice 目录下未找到音频文件。")
            return None

        audio_files.sort(
            key=lambda x: os.path.getmtime(os.path.join(self.output_dir, x)),
            reverse=True,
        )
        return os.path.join(self.output_dir, audio_files[0])


# ------------------------------------------------------------------
# 自测入口
# ------------------------------------------------------------------

if __name__ == "__main__":
    tts = TTSManager()
    test_text = "你好，我是你的AI猫娘助手，很高兴为你服务！"
    audio_path = tts.synthesize(test_text)
    print(f"音频已生成: {audio_path}")
