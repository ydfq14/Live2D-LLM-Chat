"""
VectorStore 适配器 —— 统一向量数据库接口。

设计模式：适配器模式（Adapter Pattern）
- 定义抽象基类 VectorStore，屏蔽底层数据库差异
- ChromaAdapter、MilvusAdapter、QdrantAdapter 等各自实现
- 上层业务（MemoryRAG、SafetyRAG）只依赖 VectorStore 接口

切换数据库时：只需改配置 ADAPTER_NAME = "chroma" → "milvus"
无需修改任何业务代码。
"""
from __future__ import annotations

import abc
import os
from typing import Any, Dict, List, Optional

from log_config import get_logger

logger = get_logger("vector_store")


# ═══════════════════════════════════════════════════════════════════
# 抽象接口
# ═══════════════════════════════════════════════════════════════════

class VectorStore(abc.ABC):
    """向量数据库抽象接口。所有底层库必须实现此类。"""

    @abc.abstractmethod
    def get(self, id: str) -> Optional[Dict[str, Any]]:
        """按 ID 获取单条文档。

        Returns:
            {"id": str, "content": str, "metadata": dict} | None
        """
        raise NotImplementedError

    @abc.abstractmethod
    def add(self, ids: List[str], documents: List[str], metadatas: List[Dict[str, Any]]) -> None:
        """添加文档到向量库。

        Args:
            ids: 唯一标识列表
            documents: 文本内容列表
            metadatas: 元数据字典列表（如 emotion, weight, timestamp）
        """
        raise NotImplementedError

    @abc.abstractmethod
    def query(self, query_text: str, n_results: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """语义检索。

        Args:
            query_text: 查询文本
            n_results: 返回结果数量
            filters: 过滤条件（如 {"emotion": "happy"}）

        Returns:
            [{"id": str, "content": str, "metadata": dict, "distance": float}, ...]
        """
        raise NotImplementedError

    @abc.abstractmethod
    def delete(self, ids: List[str]) -> None:
        """按 ID 删除文档。"""
        raise NotImplementedError

    @abc.abstractmethod
    def get_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        """按时间倒序获取最近添加的文档。"""
        raise NotImplementedError

    @abc.abstractmethod
    def update_metadata(self, id: str, metadata: Dict[str, Any]) -> None:
        """更新指定文档的元数据。"""
        raise NotImplementedError

    @abc.abstractmethod
    def close(self) -> None:
        """释放资源。"""
        raise NotImplementedError

    @property
    @abc.abstractmethod
    def is_ready(self) -> bool:
        """数据库是否就绪。"""
        raise NotImplementedError


# ═══════════════════════════════════════════════════════════════════
# Chroma 适配器（当前实现）
# ═══════════════════════════════════════════════════════════════════

class ChromaAdapter(VectorStore):
    """ChromaDB 适配器。"""

    def __init__(self, persist_dir: str, collection_name: str, embedding_model: str = "all-MiniLM-L6-v2") -> None:
        self.persist_dir = persist_dir
        self.collection_name = collection_name
        self.embedding_model = embedding_model
        self.client = None
        self.collection = None
        self._init()

    def _init(self) -> None:
        """初始化 Chroma 客户端和集合。"""
        try:
            import chromadb
            from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

            logger.info("[ChromaAdapter] 开始初始化 (collection: %s)", self.collection_name)
            os.makedirs(self.persist_dir, exist_ok=True)
            logger.debug("[ChromaAdapter] 持久化目录: %s", self.persist_dir)

            self.client = chromadb.PersistentClient(path=self.persist_dir)
            logger.info("[ChromaAdapter] ChromaDB 客户端已创建")

            # ── 优先使用本地模型（魔搭/手动下载），避免网络依赖 ──
            model_path = self._resolve_model_path(self.embedding_model)
            if model_path != self.embedding_model:
                logger.info("[ChromaAdapter] ✓ 使用本地模型: %s", model_path)
            else:
                logger.warning("[ChromaAdapter] ⚠ 使用远程模型: %s (需联网下载，可能较慢)", model_path)
                logger.info("[ChromaAdapter] 提示：如果下载失败，请设置环境变量 HF_ENDPOINT=https://hf-mirror.com")
                logger.info("[ChromaAdapter] 或手动下载模型到 ./models/ 目录")

            logger.info("[ChromaAdapter] 加载 SentenceTransformer 模型: %s", model_path)
            try:
                self.embedding_fn = SentenceTransformerEmbeddingFunction(model_name=model_path)
                logger.info("[ChromaAdapter] ✓ SentenceTransformer 模型加载成功")
            except Exception as model_error:
                logger.error("[ChromaAdapter] ✗ SentenceTransformer 模型加载失败: %s", str(model_error))
                logger.error("[ChromaAdapter] 可能原因：")
                logger.error("[ChromaAdapter]   1. 网络不通，无法下载模型")
                logger.error("[ChromaAdapter]   2. 模型文件损坏")
                logger.error("[ChromaAdapter] 解决方案：")
                logger.error("[ChromaAdapter]   - 设置环境变量: HF_ENDPOINT=https://hf-mirror.com")
                logger.error("[ChromaAdapter]   - 或手动下载模型到: ./models/sentence-transformers_all-MiniLM-L6-v2/")
                raise model_error

            # 使用 get_or_create_collection 避免 "already exists" 错误
            logger.info("[ChromaAdapter] 创建/获取 collection: %s", self.collection_name)
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name, embedding_function=self.embedding_fn
            )
            logger.info("[ChromaAdapter] ✓ Collection '%s' 就绪", self.collection_name)

        except ImportError as e:
            logger.error("[ChromaAdapter] ✗ chromadb 未安装: %s", e)
            logger.error("[ChromaAdapter] 请运行: pip install chromadb")
        except Exception as e:
            logger.error("[ChromaAdapter] ✗ 初始化失败: %s", str(e), exc_info=True)

    @staticmethod
    def _resolve_model_path(model_name: str) -> str:
        """优先解析本地模型路径，避免 HuggingFace 网络下载。

        搜索顺序：
        1. ./models/sentence-transformers_all-MiniLM-L6-v2/ (魔搭下载)
        2. 环境变量 LOCAL_MODEL_PATH
        3. 原 model_name (回退到 HuggingFace 下载)
        """
        import os

        if os.path.isabs(model_name) and os.path.isdir(model_name):
            return model_name

        # 候选本地路径
        candidates = [
            os.path.join(os.path.dirname(__file__), "..", "models", "sentence-transformers_all-MiniLM-L6-v2"),
            os.path.join(os.path.dirname(__file__), "..", "models", model_name),
            os.path.join(os.getcwd(), "models", "sentence-transformers_all-MiniLM-L6-v2"),
            os.path.join(os.getcwd(), "models", model_name),
        ]

        # 环境变量覆盖
        env_path = os.environ.get("LOCAL_MODEL_PATH")
        if env_path:
            candidates.insert(0, env_path)

        for path in candidates:
            path = os.path.abspath(path)
            if os.path.isdir(path):
                # 检查是否有模型文件标识
                markers = ["config.json", "pytorch_model.bin", "model.safetensors"]
                if any(os.path.exists(os.path.join(path, m)) for m in markers):
                    return path

        return model_name

    def get(self, id: str) -> Optional[Dict[str, Any]]:
        if not self.collection:
            return None
        try:
            raw = self.collection.get(ids=[id], include=["documents", "metadatas"])
            if not raw or not raw["ids"]:
                return None
            return {
                "id": raw["ids"][0],
                "content": raw["documents"][0],
                "metadata": raw["metadatas"][0],
            }
        except Exception:
            return None

    def add(self, ids: List[str], documents: List[str], metadatas: List[Dict[str, Any]]) -> None:
        if not self.collection:
            raise RuntimeError("Chroma 未初始化")
        self.collection.add(ids=ids, documents=documents, metadatas=metadatas)

    def query(self, query_text: str, n_results: int = 5, filters: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        if not self.collection:
            return []

        kwargs = {"query_texts": [query_text], "n_results": n_results, "include": ["metadatas", "documents", "distances"]}
        if filters:
            kwargs["where"] = filters

        raw = self.collection.query(**kwargs)
        results = []
        for i, doc_id in enumerate(raw["ids"][0]):
            results.append({
                "id": doc_id,
                "content": raw["documents"][0][i],
                "metadata": raw["metadatas"][0][i],
                "distance": raw["distances"][0][i],
            })
        return results

    def delete(self, ids: List[str]) -> None:
        if self.collection:
            self.collection.delete(ids=ids)

    def get_recent(self, limit: int = 10) -> List[Dict[str, Any]]:
        if not self.collection:
            return []
        # Chroma 没有内置排序，用 get 全部然后按 timestamp 排序
        all_data = self.collection.get(include=["metadatas", "documents"])
        items = []
        for i, doc_id in enumerate(all_data["ids"]):
            meta = all_data["metadatas"][i]
            items.append({
                "id": doc_id,
                "content": all_data["documents"][i],
                "metadata": meta,
                "timestamp": meta.get("timestamp", 0),
            })
        items.sort(key=lambda x: x["timestamp"], reverse=True)
        return items[:limit]

    def update_metadata(self, id: str, metadata: Dict[str, Any]) -> None:
        if self.collection:
            self.collection.update(ids=[id], metadatas=[metadata])

    def close(self) -> None:
        # Chroma PersistentClient 不需要显式关闭
        self.collection = None
        self.client = None

    @property
    def is_ready(self) -> bool:
        return self.collection is not None


# ═══════════════════════════════════════════════════════════════════
# 工厂函数 —— 根据配置创建对应适配器
# ═══════════════════════════════════════════════════════════════════

ADAPTER_REGISTRY = {
    "chroma": ChromaAdapter,
    # "milvus": MilvusAdapter,   # 未来扩展
    # "qdrant": QdrantAdapter,   # 未来扩展
}


def create_vector_store(adapter_name: str, **kwargs) -> VectorStore:
    """工厂函数：根据配置创建向量数据库适配器。

    Args:
        adapter_name: 适配器名称（chroma / milvus / qdrant）
        **kwargs: 传递给适配器的参数（persist_dir, collection_name 等）

    Returns:
        VectorStore 实例

    Raises:
        ValueError: 未知适配器名称
    """
    adapter_cls = ADAPTER_REGISTRY.get(adapter_name)
    if not adapter_cls:
        raise ValueError(f"未知向量数据库适配器: {adapter_name}。可用: {list(ADAPTER_REGISTRY.keys())}")
    return adapter_cls(**kwargs)
