
import os
import sys
import time
import types
import base64
import shutil
import requests
import pygame
import wave
from pathlib import Path
from config import Config
from log_config import get_logger

logger = get_logger(__name__)


def download_piper_model(model_path: str) -> None:
    """
    自动下载 piper-tts 模型文件。

    :param model_path: 模型文件路径（.onnx 文件）
    """
    model_path = Path(model_path)
    config_path = model_path.with_suffix('.onnx.json')

    # 如果模型文件和配置文件都已存在，直接返回
    if model_path.exists() and config_path.exists():
        logger.info(f"piper-tts 模型已存在: {model_path.name}")
        return

    logger.info("piper-tts 模型不存在，开始自动下载...")
    model_dir = model_path.parent
    model_dir.mkdir(parents=True, exist_ok=True)

    # HuggingFace 仓库信息
    repo_id = "rhasspy/piper-voices"

    # 需要下载的文件列表（相对于仓库的路径）
    files_to_download = [
        (f"zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx", model_path),
        (f"zh/zh_CN/huayan/medium/zh_CN-huayan-medium.onnx.json", config_path),
    ]

    try:
        # 使用 requests 直接下载（更可靠，能正确使用镜像）
        hf_endpoint = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com")
        logger.info(f"使用 HuggingFace 镜像: {hf_endpoint}")

        # HuggingFace 仓库基础URL
        base_url = f"https://huggingface.co/{repo_id}/resolve/main"

        for repo_file, local_path in files_to_download:
            if local_path.exists():
                logger.info(f"文件已存在，跳过: {local_path.name}")
                continue

            # 构建完整的下载URL
            original_url = f"{base_url}/{repo_file}"

            # 如果配置了镜像，替换URL中的域名
            if hf_endpoint and "hf-mirror.com" in hf_endpoint:
                download_url = original_url.replace("huggingface.co", "hf-mirror.com")
            else:
                download_url = original_url

            # 先用镜像尝试，失败则回退到官方 Hub
            urls_to_try = [download_url]
            if download_url != original_url:
                urls_to_try.append(original_url)

            last_err = None
            for url in urls_to_try:
                try:
                    logger.info(f"正在下载: {repo_file}")
                    logger.info(f"  来源: {url}")

                    # 下载文件（带进度显示）
                    response = requests.get(url, stream=True, timeout=300)
                    response.raise_for_status()

                    # 获取文件总大小
                    total_size = int(response.headers.get('content-length', 0))
                    if total_size > 0:
                        logger.info(f"  文件大小: {total_size / 1024 / 1024:.1f} MB")

                    downloaded_size = 0
                    last_progress = 0  # 上次显示进度的百分比

                    # 写入文件（带进度更新）
                    with open(local_path, 'wb') as f:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:
                                f.write(chunk)
                                downloaded_size += len(chunk)

                                # 显示下载进度（每5%显示一次）
                                if total_size > 0:
                                    progress = (downloaded_size / total_size) * 100
                                    if progress - last_progress >= 5:
                                        downloaded_mb = downloaded_size / 1024 / 1024
                                        total_mb = total_size / 1024 / 1024
                                        logger.info(f"  进度: {progress:.1f}% ({downloaded_mb:.1f}/{total_mb:.1f} MB)")
                                        last_progress = progress

                    logger.info(f"  下载完成: {local_path.name} ({local_path.stat().st_size / 1024 / 1024:.1f} MB)")
                    break  # 成功，跳出重试循环

                except Exception as err:
                    last_err = err
                    if url != urls_to_try[-1]:
                        logger.warning(f"镜像下载失败: {err}，尝试官方 Hub...")
                    continue
            else:
                # 所有 URL 都失败
                raise last_err

    except Exception as e:
        logger.error(f"下载失败: {e}")
        logger.error(f"提示: 如果自动下载失败，请手动下载文件到 {model_dir}")
        logger.error(f"下载地址: https://huggingface.co/{repo_id}/tree/main/zh_CN/huayan/medium")
        raise FileNotFoundError(f"无法下载 piper-tts 模型: {e}")


class TTSManager:
    def __init__(self, mode=None):
        """
        初始化 TTS 管理器，支持三种模式：
        - "local": 本地 piper-tts
        - "cloud": 云端 MIMO TTS
        - "moss": 本地 MOSS-TTS-Nano ONNX

        :param mode: "local"、"cloud" 或 "moss"，不传则读取 Config.TTS_MODE
        """
        self.mode = mode or Config.TTS_MODE
        if self.mode not in ("local", "cloud", "moss"):
            raise ValueError(f"TTS_MODE 必须为 'local'、'cloud' 或 'moss'，当前为: {self.mode}")

        # 输出目录（两种模式共用）
        self.output_dir = Config.TTS_OUTPUT_DIR
        os.makedirs(self.output_dir, exist_ok=True)

        if self.mode == "local":
            model_path = Config.PIPER_MODEL_PATH
            logger.info(f"TTS 初始化: local (piper-tts), model={model_path}")

            # 自动下载模型文件（如果不存在）
            try:
                download_piper_model(model_path)
            except Exception as e:
                logger.error(f"自动下载模型失败: {e}")
                raise

            try:
                # 延迟导入 piper（仅在本地模式时加载）
                from piper import PiperVoice
                self.voice = PiperVoice.load(model_path)
            except ImportError as e:
                logger.error(f"未安装 piper-tts，请运行: pip install piper-tts")
                raise ImportError(f"未安装 piper-tts，请运行: pip install piper-tts") from e
            except FileNotFoundError:
                logger.error(f"模型文件不存在: {model_path}")
                logger.error("请下载 piper-tts 模型文件:")
                logger.error("  1. 访问 https://huggingface.co/rhasspy/piper-voices/tree/main/zh_CN/huayan/medium")
                logger.error("  2. 下载 zh_CN-huayan-medium.onnx 和 zh_CN-huayan-medium.onnx.json")
                logger.error("  3. 放到 TTS_env/piper/ 目录下")
                raise FileNotFoundError(f"piper-tts 模型文件不存在: {model_path}，请查看日志了解下载方法")
            except Exception as e:
                logger.error(f"加载 piper 模型失败: {e}")
                raise
            self.speaker_id = Config.PIPER_SPEAKER_ID
            self.length_scale = Config.PIPER_LENGTH_SCALE
            self.noise_scale = Config.PIPER_NOISE_SCALE
            self.noise_w = Config.PIPER_NOISE_W
            self.history_dir = Config.TTS_HISTORY_DIR
            os.makedirs(self.history_dir, exist_ok=True)

        elif self.mode == "moss":
            # --- MOSS-TTS-Nano ONNX 本地初始化 ---
            logger.info("TTS 初始化: moss (MOSS-TTS-Nano ONNX)")
            moss_dir = Config.MOSS_TTS_NANO_DIR
            if not os.path.isdir(moss_dir):
                raise FileNotFoundError(
                    f"MOSS-TTS-Nano 目录不存在: {moss_dir}\n"
                    f"请克隆 MOSS-TTS-Nano 到该路径，或修改 Config.MOSS_TTS_NANO_DIR"
                )
            # MOSS-TTS-Nano 顶层脚本使用裸 import，需将其根目录加入 sys.path
            if moss_dir not in sys.path:
                sys.path.insert(0, moss_dir)
            try:
                from onnx_tts_runtime import OnnxTtsRuntime, ensure_browser_onnx_model_dir
            except ImportError as e:
                logger.error("无法导入 MOSS-TTS-Nano ONNX 模块: %s", e)
                raise ImportError(
                    "MOSS-TTS-Nano 模块导入失败。请确认:\n"
                    f"  1. 目录存在: {moss_dir}\n"
                    "  2. 已安装依赖: pip install onnxruntime sentencepiece numpy torchaudio huggingface_hub"
                ) from e

            model_dir = ensure_browser_onnx_model_dir(Config.MOSS_MODEL_DIR)
            self.moss_runtime = OnnxTtsRuntime(
                model_dir=model_dir,
                thread_count=Config.MOSS_CPU_THREADS,
                max_new_frames=Config.MOSS_MAX_NEW_FRAMES,
                execution_provider=Config.MOSS_EXECUTION_PROVIDER,
                output_dir=self.output_dir,
            )
            self.moss_voice = Config.MOSS_VOICE
            self.moss_prompt_audio_path = Config.MOSS_PROMPT_AUDIO_PATH

            # 预编码参考音频并缓存，避免每次合成都重新加载和编码
            if self.moss_prompt_audio_path:
                logger.info("预编码参考音频: %s", self.moss_prompt_audio_path)
                self.moss_prompt_audio_codes = self.moss_runtime.encode_reference_audio(
                    self.moss_prompt_audio_path
                )
                logger.info("参考音频编码完成，共 %d 帧", len(self.moss_prompt_audio_codes))
                # 注册为临时内置音色，后续合成时通过 voice 名称引用
                self.moss_voice = "_custom_cached"
                self.moss_runtime.manifest.setdefault("builtin_voices", [])
                self.moss_runtime.manifest["builtin_voices"] = [
                    v for v in self.moss_runtime.manifest["builtin_voices"]
                    if v.get("voice") != "_custom_cached"
                ]
                self.moss_runtime.manifest["builtin_voices"].append({
                    "voice": "_custom_cached",
                    "prompt_audio_codes": self.moss_prompt_audio_codes,
                })
            else:
                self.moss_prompt_audio_codes = None

            self.history_dir = Config.TTS_HISTORY_DIR
            os.makedirs(self.history_dir, exist_ok=True)
            logger.info(
                "✔ TTS 本地模式 (MOSS-TTS-Nano ONNX) 初始化成功, "
                "voice=%s, threads=%d, provider=%s",
                self.moss_voice, Config.MOSS_CPU_THREADS, Config.MOSS_EXECUTION_PROVIDER,
            )

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
        elif self.mode == "moss":
            return self._synthesize_moss(text)
        else:
            return self._synthesize_cloud(text)

    # ------------------------------------------------------------------
    # 音色控制（供 personality 插件调用）
    # ------------------------------------------------------------------

    def set_voice(self, voice_name: str):
        """切换云端 TTS 音色。可用音色: 冰糖, 茉莉, 苏打, 白桦, Mia, Chloe, Milo, Dean, mimo_default"""
        self.tts_voice = voice_name
        logger.info(f"TTS 音色已切换: {voice_name}")

    def set_voice_sample(self, wav_path: str, text_path: str):
        """切换本地 TTS 音色样本"""
        self.prompt_wav_path = wav_path
        self.prompt_text_path = text_path
        logger.info(f"TTS 音色样本已切换: {wav_path}")
        
    # ------------------------------------------------------------------
    # 工具方法
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
            # 使用synthesize返回的SynthesisResult获取音频数据
            logger.info(f"调用 piper.synthesize: text='{text[:30]}...'")

            # synthesize返回一个SynthesisResult对象或generator
            result = self.voice.synthesize(text)

            # 检查返回类型
            logger.info(f"synthesize 返回类型: {type(result)}")

            if isinstance(result, types.GeneratorType):
                # generator 类型：逐块收集 PCM 数据
                logger.info("检测到 generator，逐块收集音频数据")
                audio_chunks = []
                sample_rate = Config.PIPER_SAMPLE_RATE
                for chunk in result:
                    audio_chunks.append(chunk.audio_int16_bytes)
                    sample_rate = chunk.sample_rate
                audio_data = b''.join(audio_chunks)
                logger.info(f"generator 收集完成，总大小: {len(audio_data)} bytes")
                with wave.open(output_path, "wb") as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(sample_rate)
                    wav_file.writeframes(audio_data)
                logger.info(f"generator 收集完成，总大小: {len(audio_data)} bytes")
                with wave.open(output_path, "wb") as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(sample_rate)
                    wav_file.writeframes(audio_data)
            elif hasattr(result, 'audio_bytes'):
                # SynthesisResult：直接写入 audio_bytes
                logger.info(f"使用 audio_bytes 写入文件 (大小: {len(result.audio_bytes)} bytes)")
                with open(output_path, 'wb') as f:
                    f.write(result.audio_bytes)
            elif isinstance(result, bytes):
                # bytes 类型：直接写 PCM
                logger.info(f"使用 raw bytes 写入文件 (大小: {len(result)} bytes)")
                with wave.open(output_path, "wb") as wav_file:
                    wav_file.setnchannels(1)
                    wav_file.setsampwidth(2)
                    wav_file.setframerate(Config.PIPER_SAMPLE_RATE)
                    wav_file.writeframes(result)
            else:
                logger.error(f"无法处理的返回类型: {type(result)}")
                return None

            logger.info(f"piper 合成完成，文件: {output_path}")

        except Exception as e:
            logger.error(f"piper 合成失败: {e}")
            import traceback
            traceback.print_exc()
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
    # 本地合成：MOSS-TTS-Nano (ONNX)
    # ------------------------------------------------------------------

    def _synthesize_moss(self, text):
        """
        使用 MOSS-TTS-Nano ONNX 后端进行本地语音合成。

        :param text: 待合成的文本
        :return: 生成的音频文件路径
        """
        self.clear_output_directory()

        start_time = time.time()
        timestamp = int(time.time() * 1000)
        output_path = os.path.join(self.output_dir, f"tts_output_{timestamp}.wav")

        try:
            logger.info(
                "调用 MOSS-TTS-Nano: text='%s...', voice=%s",
                text[:30], self.moss_voice,
            )

            result = self.moss_runtime.synthesize(
                text=text,
                voice=self.moss_voice,
                output_audio_path=output_path,
                do_sample=True,
                streaming=False,
                max_new_frames=Config.MOSS_MAX_NEW_FRAMES,
                voice_clone_max_text_tokens=75,
                enable_wetext=False,
                enable_normalize_tts_text=False,
            )
            output_path = result["audio_path"]
            logger.info("MOSS-TTS-Nano 合成完成，文件: %s", output_path)

        except Exception as e:
            logger.error("MOSS-TTS-Nano 合成失败: %s", e)
            import traceback
            traceback.print_exc()
            return None

        elapsed = time.time() - start_time
        logger.info("TTS 完成 (moss/MOSS-TTS-Nano)，耗时: %.2fs，文件: %s", elapsed, output_path)

        if not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
            logger.error("合成失败：输出文件为空或不存在 %s", output_path)
            return None

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
