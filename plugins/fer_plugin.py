"""
FER 插件 —— 面部情绪分析（Facial Emotion Recognition）独立模块。

集成方案：fer (Justin Shenk) —— 开箱即用，pip 安装，自带预训练模型。
  PyPI: pip install fer
  GitHub: https://github.com/justinshenk/fer

情绪标签映射（fer 7 类 → 项目 10 类）：
  angry    → angry
  disgust  → disgusted
  fear     → fearful
  happy    → happy
  neutral  → neutral
  sad      → sad
  surprise → surprised

职责：
- 通过摄像头/图片捕捉用户面部表情，分析情绪状态
- 将情绪结果通过共享数据传递给 emotion_rag 插件（辅助情感判断）
- 与 emotion_rag 解耦，可独立运行

当前状态：
- 已集成 fer 库，支持图片分析和摄像头分析
- 降级时返回 available=False，不影响主流程

插件接口：
- on_startup：初始化 FER 分析器
- on_tick：定期触发分析（每 2 轮）
- on_user_input：可选，将面部情绪注入到用户输入上下文
- get_frontend_html：前端面板显示当前情绪状态

共享数据：
- 分析结果写入 plugins_data/fer_emotion.json
- emotion_rag 通过读取此文件获取面部情绪
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from plugin_base import PluginBase
from log_config import get_logger

logger = get_logger("fer_plugin")


# ═══════════════════════════════════════════════════════════════════
# 情绪标签映射：fer 输出 → 项目标准标签
# ═══════════════════════════════════════════════════════════════════

_FER_TO_PROJECT: Dict[str, str] = {
    "angry":    "angry",
    "disgust":  "disgusted",
    "fear":     "fearful",
    "happy":    "happy",
    "neutral":  "neutral",
    "sad":      "sad",
    "surprise": "surprised",
}

# fer 原始情绪标签（用于验证）
_FER_LABELS = set(_FER_TO_PROJECT.keys())

# 项目标准标签中没有直接面部对应的情绪（需通过文字分析）
_NO_FER_MAPPING = {"love", "upset", "anxious"}


def _map_fer_emotion(fer_label: str) -> str:
    """将 fer 原始标签映射到项目标准情绪标签。"""
    return _FER_TO_PROJECT.get(fer_label.lower(), "neutral")


# ═══════════════════════════════════════════════════════════════════
# FERAnalyzer：面部情绪分析器（可独立使用）
# ═══════════════════════════════════════════════════════════════════

class FERAnalyzer:
    """基于 fer 库的面部情绪分析器。

    支持三种输入模式：
    1. 图片路径分析（analyze_from_image）—— 最常用，用于测试和批量处理
    2. 摄像头实时分析（analyze_from_camera）—— 虚拟桌宠运行时
    3. 视频文件分析（analyze_from_video）—— 扩展用途

    Args:
        mtcnn: 是否使用 MTCNN 进行人脸检测（比 Haar Cascade 更精确但更慢）
    """

    def __init__(self, mtcnn: bool = True) -> None:
        self.detector = None
        self._available = False
        self._mtcnn = mtcnn
        self._init_detector()

    def _init_detector(self) -> None:
        """尝试加载 fer 库，失败则降级。"""
        try:
            # 尝试标准导入方式
            import fer
            if hasattr(fer, 'FER'):
                self.detector = fer.FER(mtcnn=self._mtcnn)
            else:
                # fallback：某些版本的 fer 包 FER 类在 fer.fer 子模块中
                from fer.fer import FER as FERClass
                self.detector = FERClass(mtcnn=self._mtcnn)
            self._available = True
            logger.info("[FER] 检测器已加载（fer + %s）", "MTCNN" if self._mtcnn else "Haar Cascade")
        except ImportError:
            logger.info("[FER] fer 库未安装，降级为不可用。pip install fer")
            self._available = False
        except AttributeError as e:
            logger.warning(
                "[FER] fer 模块缺少 FER 属性: %s。"
                "请检查是否安装了正确的 fer 包 (pip install fer)，"
                "而不是其他同名模块。当前 fer 路径: %s",
                e, getattr(fer, '__file__', 'unknown')
            )
            self._available = False
        except Exception as e:
            logger.warning("[FER] 初始化失败: %s", e)
            self._available = False

    # ────────────────────────────────────────────
    # 图片分析（核心接口）
    # ────────────────────────────────────────────

    def analyze_from_image(self, image_path: str) -> Dict[str, Any]:
        """分析图片中的人脸情绪。

        Args:
            image_path: 图片文件路径（支持 jpg, png, bmp 等）

        Returns:
            {
                "available": bool,
                "emotion": str,       # 项目标准标签
                "confidence": float,
                "source": str,        # "image"
                "raw_results": list,  # fer 原始输出（多个人脸）
                "faces_detected": int,
            }
        """
        if not self._available or not self.detector:
            return self._unavailable_result()

        try:
            # 优先用 OpenCV 读取，失败则用 PIL fallback
            # 使用 open() + np.frombuffer 绕过 Windows 中文路径编码问题
            try:
                import cv2
                import numpy as np
                with open(image_path, 'rb') as f:
                    buf = np.frombuffer(f.read(), dtype=np.uint8)
                img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
                if img is None:
                    logger.warning("[FER] 无法读取图片: %s", image_path)
                    return self._unavailable_result()
            except ImportError:
                from PIL import Image
                import numpy as np
                pil_img = Image.open(image_path).convert("RGB")
                rgb_array = np.array(pil_img)
                img = rgb_array[:, :, ::-1]  # RGB -> BGR
        except Exception as e:
            logger.warning("[FER] 图片读取失败: %s", e)
            return self._unavailable_result()

        try:
            raw_results = self.detector.detect_emotions(img)
        except Exception as e:
            logger.warning("[FER] 检测失败: %s", e)
            return self._unavailable_result()

        faces_detected = len(raw_results)

        if faces_detected == 0:
                logger.info("[FER] 未检测到人脸: %s", image_path)
                return {
                    "available": True,
                    "emotion": "neutral",
                    "confidence": 0.0,
                    "source": "image",
                    "raw_results": [],
                    "faces_detected": 0,
                }

        # 取置信度最高的人脸（多脸场景取最显著）
        top_face = self._pick_top_face(raw_results)
        fer_emotion = top_face["emotion"]
        confidence = top_face["score"]
        mapped_emotion = _map_fer_emotion(fer_emotion)

        logger.info(
            "[FER] 图片分析: %s → %s (%.2f) | 人脸数=%d",
            os.path.basename(image_path), mapped_emotion, confidence, faces_detected,
        )
        return {
            "available": True,
            "emotion": mapped_emotion,
            "confidence": round(confidence, 4),
            "source": "image",
            "raw_results": raw_results,
            "faces_detected": faces_detected,
        }

    def _pick_top_face(self, raw_results: List[Dict]) -> Dict[str, Any]:
        """从 fer 原始结果中提取置信度最高的情绪。"""
        best = None
        best_score = -1.0
        for face in raw_results:
            emotions = face.get("emotions", {})
            if not emotions:
                continue
            top_fer = max(emotions.items(), key=lambda x: x[1])
            if top_fer[1] > best_score:
                best_score = top_fer[1]
                best = {"emotion": top_fer[0], "score": top_fer[1], "box": face.get("box")}
        return best or {"emotion": "neutral", "score": 0.0, "box": None}

    # ────────────────────────────────────────────
    # 摄像头分析（实时）
    # ────────────────────────────────────────────

    def analyze_from_camera(self) -> Dict[str, Any]:
        """分析摄像头当前帧中的情绪。

        Returns:
            标准化情绪字典
        """
        if not self._available or not self.detector:
            return self._unavailable_result()

        try:
            import cv2
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                logger.warning("[FER] 摄像头未打开")
                return self._unavailable_result()

            ret, frame = cap.read()
            cap.release()

            if not ret or frame is None:
                logger.warning("[FER] 无法读取摄像头帧")
                return self._unavailable_result()

            raw_results = self.detector.detect_emotions(frame)
            faces_detected = len(raw_results)

            if faces_detected == 0:
                return {
                    "available": True,
                    "emotion": "neutral",
                    "confidence": 0.0,
                    "source": "camera",
                    "raw_results": [],
                    "faces_detected": 0,
                }

            top_face = self._pick_top_face(raw_results)
            fer_emotion = top_face["emotion"]
            confidence = top_face["score"]
            mapped_emotion = _map_fer_emotion(fer_emotion)

            logger.info(
                "[FER] 摄像头: %s (%.2f) | 人脸数=%d",
                mapped_emotion, confidence, faces_detected,
            )
            return {
                "available": True,
                "emotion": mapped_emotion,
                "confidence": round(confidence, 4),
                "source": "camera",
                "raw_results": raw_results,
                "faces_detected": faces_detected,
            }

        except Exception as e:
            logger.warning("[FER] 摄像头分析失败: %s", e)
            return self._unavailable_result()

    # ────────────────────────────────────────────
    # 视频分析（扩展）
    # ────────────────────────────────────────────

    def analyze_from_video(self, video_path: str, sample_every_n_frames: int = 30) -> List[Dict[str, Any]]:
        """分析视频文件，每隔 N 帧采样一次。

        Args:
            video_path: 视频文件路径
            sample_every_n_frames: 每隔多少帧分析一次（默认 30fps 取 1 帧/秒）

        Returns:
            帧分析结果列表
        """
        if not self._available or not self.detector:
            return []

        results = []
        try:
            import cv2
            cap = cv2.VideoCapture(video_path)
            if not cap.isOpened():
                logger.warning("[FER] 无法打开视频: %s", video_path)
                return []

            frame_idx = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_idx % sample_every_n_frames == 0:
                    raw_results = self.detector.detect_emotions(frame)
                    if raw_results:
                        top_face = self._pick_top_face(raw_results)
                        mapped_emotion = _map_fer_emotion(top_face["emotion"])
                        results.append({
                            "frame": frame_idx,
                            "emotion": mapped_emotion,
                            "confidence": round(top_face["score"], 4),
                            "faces_detected": len(raw_results),
                        })
                frame_idx += 1

            cap.release()
            logger.info("[FER] 视频分析完成: %s | 共 %d 帧", video_path, len(results))

        except Exception as e:
            logger.warning("[FER] 视频分析失败: %s", e)

        return results

    # ────────────────────────────────────────────
    # 工具方法
    # ────────────────────────────────────────────

    def _unavailable_result(self) -> Dict[str, Any]:
        """返回降级结果。"""
        return {
            "available": False,
            "emotion": "neutral",
            "confidence": 0.0,
            "source": "unavailable",
            "raw_results": [],
            "faces_detected": 0,
        }

    def get_status(self) -> Dict[str, Any]:
        """获取 FER 模块状态。"""
        return {
            "available": self._available,
            "detector_loaded": self.detector is not None,
            "source": "fer" if self._available else "none",
        }

    def get_supported_labels(self) -> List[str]:
        """返回 fer 库支持的情绪标签列表。"""
        return sorted(_FER_LABELS)

    def get_mapped_labels(self) -> List[str]:
        """返回映射到项目标准的标签列表。"""
        return sorted(set(_FER_TO_PROJECT.values()))


# ═══════════════════════════════════════════════════════════════════
# FERPlugin：PluginBase 封装
# ═══════════════════════════════════════════════════════════════════

class FERPlugin(PluginBase):
    """FER 独立插件：面部情绪分析与跨插件数据共享。"""

    name = "fer_emotion"
    version = "2.0"  # 集成 fer 库后升级

    def __init__(self) -> None:
        super().__init__()
        self.analyzer: FERAnalyzer | None = None
        self._last_face_emotion: Dict[str, Any] | None = None
        self._tick_count: int = 0
        self._data_path: str = "./plugins_data/fer_emotion.json"

    def on_startup(self, app) -> None:
        """初始化 FER 分析器。"""
        super().on_startup(app)
        self.analyzer = FERAnalyzer(mtcnn=True)
        status = self.analyzer.get_status()
        logger.info(
            "[FER] 插件就绪 v%s — 可用=%s 检测器=%s 支持标签=%s",
            self.version, status["available"], status["detector_loaded"],
            self.analyzer.get_mapped_labels() if self.analyzer else [],
        )

    def on_tick(self, app) -> None:
        """定期触发面部情绪分析（每 2 轮）。"""
        self._tick_count += 1
        logger.info("[FER] on_tick 触发，计数=%d", self._tick_count)
        
        if self._tick_count % 2 != 0:
            logger.info("[FER] 计数未到2，跳过")
            return

        if not self.analyzer:
            logger.warning("[FER] analyzer 未初始化，跳过")
            return

        logger.info("[FER] 开始摄像头分析...")
        try:
            result = self.analyzer.analyze_from_camera()
            self._last_face_emotion = result
            self._persist_emotion(result)

            if result.get("available"):
                logger.info(
                    "[FER] ✅ 面部情绪: %s (%.2f)",
                    result.get("emotion", "neutral"),
                    result.get("confidence", 0.5),
                )
            else:
                logger.warning("[FER] ⚠️ 分析器不可用，结果: %s", result)
        except Exception as e:
            logger.error("[FER] ❌ 分析异常: %s", e, exc_info=True)

    def on_user_input(self, text: str) -> str | None:
        """可选 Hook：将面部情绪附加到用户输入的上下文中。

        返回 None 表示不修改用户输入；实际情绪通过共享数据传递。
        """
        return None

    def on_shutdown(self) -> None:
        """清理资源。"""
        if self.analyzer:
            self.analyzer = None
        logger.info("[FER] 插件已关闭。")

    def get_frontend_html(self) -> str:
        """前端面板：显示当前 FER 状态。"""
        status = self.analyzer.get_status() if self.analyzer else {"available": False}
        face = self._last_face_emotion or {"emotion": "—", "confidence": 0.0}
        supported = self.analyzer.get_mapped_labels() if self.analyzer else []

        return f"""
        <div class="fer-panel">
            <h4>FER 面部情绪</h4>
            <p>状态: {"可用" if status["available"] else "不可用"}</p>
            <p>当前情绪: {face.get("emotion", "—")} ({face.get("confidence", 0):.2f})</p>
            <p>来源: {face.get("source", "—")}</p>
            <p>支持标签: {', '.join(supported)}</p>
            <p>版本: {self.version}</p>
        </div>
        """

    # ────────────────────────────────────────────
    # 共享数据接口
    # ────────────────────────────────────────────

    def _persist_emotion(self, result: Dict[str, Any]) -> None:
        """将情绪结果写入共享 JSON 文件。"""
        try:
            os.makedirs(os.path.dirname(self._data_path), exist_ok=True)
            with open(self._data_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug("[FER] 共享数据写入失败: %s", e)

    def get_last_face_emotion(self) -> Dict[str, Any] | None:
        """获取最近一次面部情绪分析结果（供其他插件读取）。"""
        return self._last_face_emotion

    def read_shared_emotion(self) -> Dict[str, Any] | None:
        """从共享文件读取情绪（emotion_rag 插件使用此接口）。"""
        try:
            if os.path.exists(self._data_path):
                with open(self._data_path, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.debug("[FER] 共享数据读取失败: %s", e)
        return None
