"""
Milvus Lite 本地知识库控制器
============================
基于 Milvus Lite + BGE-M3 + BM25 实现的本地知识库后端，
完整对接 agentic_rag.py 的 6 个接口方法。
支持本地已下载的 BGE-M3 模型加载，并支持 BM25 pickle 持久化缓存。

依赖安装:
  pip install pymilvus[model] sentence-transformers rank-bm25 jieba pypdf

快速开始:
  from kb_controller import create_controller, ingest_directory

  # 1. 创建控制器
  kb = create_controller()

  # 2. 摄入文档（可选，只在首次需要）
  ingest_directory(kb, "./docs", glob="*.txt")

  # 3. 搜索
  results = kb.search(kb_id=0, query="什么是 RAG")
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import jieba
from rank_bm25 import BM25Okapi

from pymilvus import (
    Collection,
    CollectionSchema,
    DataType,
    FieldSchema,
    connections,
)

log = logging.getLogger("kb_controller")

# ===================== Windows 兼容性修复 =====================
# Milvus Lite 在 Windows 上 os.rename 不会自动覆盖已存在的文件，
# 需要替换为 os.replace 来修复 flush 失败的问题。
import sys as _sys
if _sys.platform == "win32":
    import os as _os
    _original_rename = _os.rename
    def _windows_rename(src, dst):
        """Windows 兼容的 rename：目标存在时自动覆盖。"""
        try:
            _original_rename(src, dst)
        except FileExistsError:
            _os.replace(src, dst)
    _os.rename = _windows_rename

# ===================== 默认配置 =====================
DEFAULT_MILVUS_URI = "./plugins_data/agentic_rag/kb.db"
DEFAULT_COLLECTION = "kb_chunks"
DEFAULT_EMBEDDING_MODEL = "BAAI/bge-m3"
DEFAULT_BM25_CACHE_PATH = "./plugins_data/agentic_rag/bm25_cache.pkl"
EMBEDDING_DIM = 1024
DEFAULT_CHUNK_SIZE = 500
DEFAULT_CHUNK_OVERLAP = 50
MAX_VARCHAR_LEN = 65535

def _get_model_cache_dir() -> str:
    """获取模型缓存目录，遵循项目约定使用 .models/ 目录。"""
    # 优先使用环境变量（由 bootstrap 设置）
    modelscope_cache = os.environ.get("MODELSCOPE_CACHE")
    if modelscope_cache:
        return modelscope_cache
    # 回退到项目约定的 .models/modelscope 目录
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), ".models", "modelscope")


def _get_sentence_transformers_cache_dir() -> str:
    """获取 sentence-transformers 缓存目录，遵循项目约定。"""
    # 优先使用环境变量（由 bootstrap 设置）
    st_cache = os.environ.get("SENTENCE_TRANSFORMERS_HOME")
    if st_cache:
        return st_cache
    # 回退到项目约定的 .models/sentence_transformers 目录
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), ".models", "sentence_transformers")


# =====================================================================
# EmbeddingManager - BGE-M3 模型加载与向量化
# =====================================================================
class EmbeddingManager:
    """管理 BGE-M3 embedding 模型，提供文本向量化能力。"""

    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        local_dir: Optional[str] = None,
    ):
        self._model_name = model_name
        self._local_dir = local_dir or _get_sentence_transformers_cache_dir()
        self._model = None

    @property
    def model_name(self) -> str:
        """获取模型名称。"""
        return self._model_name

    def _download_from_modelscope(self) -> str:
        """从魔塔社区下载模型到本地目录（遵循项目约定）。"""
        try:
            from modelscope import snapshot_download

            cache_dir = _get_model_cache_dir()
            log.info("本地模型目录不存在，从魔塔社区下载 %s 到 %s ...", self._model_name, cache_dir)
            model_dir = snapshot_download(self._model_name, cache_dir=cache_dir)
            log.info("模型下载完成: %s", model_dir)
            # 更新本地目录，避免下次重复下载
            self._local_dir = model_dir
            return model_dir
        except ImportError:
            log.warning("未安装 modelscope，尝试从 HuggingFace 下载...")
            return self._model_name

    def _load(self):
        if self._model is not None:
            return
        from sentence_transformers import SentenceTransformer
        from pathlib import Path

        local_dir = self._local_dir
        log.info("尝试加载 embedding 模型，本地目录: %s", local_dir)

        # 检查本地目录是否存在
        if local_dir and Path(local_dir).is_dir():
            # 查找 snapshot 目录中的正确模型路径
            snapshot_path = self._find_snapshot_path(local_dir)
            if snapshot_path:
                load_source = snapshot_path
                log.info("✓ 找到模型快照: %s", load_source)
            else:
                # 直接使用本地目录
                load_source = local_dir
                log.info("使用本地目录: %s", load_source)
        else:
            load_source = self._download_from_modelscope()
            log.info("从远程下载模型: %s", load_source)

        try:
            log.info("正在加载 SentenceTransformer 模型: %s", load_source)
            self._model = SentenceTransformer(load_source, trust_remote_code=True)
            log.info(
                "✓ embedding 模型加载完成，维度: %d",
                self._model.get_sentence_embedding_dimension(),
            )
        except Exception as e:
            log.error("✗ 模型加载失败: %s", str(e))
            log.info("尝试使用模型名称直接加载...")
            # 如果本地加载失败，尝试使用模型名称
            try:
                self._model = SentenceTransformer(self._model_name, trust_remote_code=True)
                log.info("✓ 使用模型名称加载成功")
            except Exception as e2:
                log.error("✗ 使用模型名称也失败: %s", str(e2))
                raise

    def _find_snapshot_path(self, base_dir: str) -> Optional[str]:
        """在 HuggingFace Hub 缓存目录中查找最新的 snapshot 路径。"""
        import glob
        from pathlib import Path

        base_path = Path(base_dir)

        # 查找 models--* 目录
        model_dirs = list(base_path.glob("models--*"))
        if not model_dirs:
            return None

        # 查找最新的 snapshot
        for model_dir in model_dirs:
            snapshots_dir = model_dir / "snapshots"
            if snapshots_dir.exists():
                snapshots = list(snapshots_dir.iterdir())
                if snapshots:
                    # 返回最新的 snapshot
                    latest = max(snapshots, key=lambda p: p.stat().st_mtime)
                    log.debug("找到 snapshot: %s", latest)
                    return str(latest)

        return None

    def encode(self, texts: List[str], batch_size: int = 32) -> List[List[float]]:
        """将文本列表编码为向量列表。"""
        self._load()
        embeddings = self._model.encode(
            texts, batch_size=batch_size, normalize_embeddings=True
        )
        return embeddings.tolist()

    def encode_single(self, text: str) -> List[float]:
        """编码单条文本。"""
        return self.encode([text])[0]

    def get_embedding_dimension(self) -> int:
        """获取 embedding 模型的输出维度。"""
        self._load()
        return self._model.get_sentence_embedding_dimension()


# =====================================================================
# BM25Index - 内存 BM25 索引（jieba 分词）
# =====================================================================
class BM25Index:
    """基于 jieba 分词 + rank_bm25 的内存关键词索引。"""

    def __init__(self):
        # flat index: [(file_id, chunk_index, content, tokenized)]
        self._entries: List[tuple] = []
        self._bm25: Optional[BM25Okapi] = None
        self._dirty = True

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return list(jieba.cut_for_search(text))

    def add(self, file_id: int, chunk_index: int, content: str):
        tokens = self._tokenize(content)
        self._entries.append((file_id, chunk_index, content, tokens))
        self._dirty = True

    def add_batch(self, entries: List[tuple]):
        """批量添加: [(file_id, chunk_index, content), ...]"""
        for fid, ci, content in entries:
            tokens = self._tokenize(content)
            self._entries.append((fid, ci, content, tokens))
        self._dirty = True

    def remove_by_file(self, file_id: int):
        self._entries = [e for e in self._entries if e[0] != file_id]
        self._dirty = True

    def _rebuild(self):
        if not self._entries:
            self._bm25 = None
            self._dirty = False
            return
        corpus = [e[3] for e in self._entries]
        self._bm25 = BM25Okapi(corpus)
        self._dirty = False

    def search(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """BM25 搜索，返回 [{fileId, chunkIndex, content, bm25_score}, ...]"""
        if self._dirty:
            self._rebuild()
        if self._bm25 is None or not self._entries:
            return []

        query_tokens = self._tokenize(query)
        scores = self._bm25.get_scores(query_tokens)

        # 取 top_k
        ranked_indices = sorted(
            range(len(scores)), key=lambda i: scores[i], reverse=True
        )[:top_k]

        results = []
        for idx in ranked_indices:
            score = scores[idx]
            if score <= 0:
                continue
            fid, ci, content, _ = self._entries[idx]
            results.append(
                {
                    "fileId": fid,
                    "chunkIndex": ci,
                    "content": content,
                    "bm25_score": round(float(score), 4),
                }
            )
        return results

    def is_empty(self) -> bool:
        return len(self._entries) == 0

    def save_pickle(self, path: str):
        """将索引条目持久化到 pickle 文件。"""
        import pickle

        cache_dir = Path(path).parent
        if cache_dir and not cache_dir.exists():
            cache_dir.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self._entries, f)
        log.debug("BM25 索引已保存: %s (%d 条)", path, len(self._entries))

    @classmethod
    def load_pickle(cls, path: str) -> "BM25Index":
        """从 pickle 文件加载索引条目。"""
        import pickle

        idx = cls()
        with open(path, "rb") as f:
            idx._entries = pickle.load(f)
        idx._dirty = True  # 需要重建 BM25Okapi 对象
        log.debug("BM25 索引已加载: %s (%d 条)", path, len(idx._entries))
        return idx


# =====================================================================
# MilvusLiteKBController - 主控制器
# =====================================================================
class MilvusLiteKBController:
    """
    基于 Milvus Lite 的知识库控制器。
    实现 agentic_rag.py 所需的 6 个接口方法。
    """

    def __init__(
        self,
        milvus_uri: str = DEFAULT_MILVUS_URI,
        collection_name: str = DEFAULT_COLLECTION,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        local_embedding_dir: Optional[str] = None,
        bm25_cache_path: Optional[str] = DEFAULT_BM25_CACHE_PATH,
    ):
        self._milvus_uri = milvus_uri
        self._collection_name = collection_name
        self._embedding = EmbeddingManager(
            embedding_model, local_dir=local_embedding_dir
        )
        self._bm25 = BM25Index()
        self._bm25_cache_path = bm25_cache_path
        self._max_file_id: int = 0  # file_id 缓存，避免每次查询
        self._file_meta_cache: Dict[int, dict] = {}  # 文件元数据缓存

        # 确保 Milvus 数据目录存在
        os.makedirs(os.path.dirname(os.path.abspath(milvus_uri)), exist_ok=True)

        # 连接 Milvus Lite（嵌入式，不需要外部服务）
        connections.connect(alias="default", uri=milvus_uri)
        log.info("Milvus Lite 连接成功: %s", milvus_uri)

        self._collection: Optional[Collection] = None
        self._ensure_collection()
        self._load_bm25_from_cache_or_rebuild()
        self._refresh_max_file_id()

    # -------------------- 内部方法 --------------------

    def _ensure_collection(self):
        """确保 collection 存在，不存在则创建。"""
        from pymilvus import utility

        if utility.has_collection(self._collection_name):
            self._collection = Collection(self._collection_name)
            self._collection.load()
            log.info("已加载现有 collection: %s", self._collection_name)
            return

        # 获取 embedding 模型的实际维度
        embedding_dim = self._embedding.get_embedding_dimension()
        log.info("使用 embedding 维度: %d (模型: %s)", embedding_dim, self._embedding.model_name)

        # 创建 schema
        fields = [
            FieldSchema(
                name="id", dtype=DataType.INT64, is_primary=True, auto_id=True
            ),
            FieldSchema(name="file_id", dtype=DataType.INT64),
            FieldSchema(name="chunk_index", dtype=DataType.INT64),
            FieldSchema(
                name="content", dtype=DataType.VARCHAR, max_length=MAX_VARCHAR_LEN
            ),
            FieldSchema(name="file_name", dtype=DataType.VARCHAR, max_length=512),
            FieldSchema(name="summary", dtype=DataType.VARCHAR, max_length=2048),
            FieldSchema(
                name="embedding", dtype=DataType.FLOAT_VECTOR, dim=embedding_dim
            ),
        ]
        schema = CollectionSchema(
            fields, description="Agentic RAG knowledge base chunks"
        )
        self._collection = Collection(self._collection_name, schema)

        # 创建向量索引（HNSW，cosine 距离）
        index_params = {
            "metric_type": "COSINE",
            "index_type": "HNSW",
            "params": {"M": 16, "efConstruction": 200},
        }
        self._collection.create_index("embedding", index_params)
        self._collection.load()
        log.info("已创建 collection 并建立索引: %s", self._collection_name)

    def _load_bm25_from_cache_or_rebuild(self):
        cache_path = self._bm25_cache_path
        if cache_path and Path(cache_path).is_file():
            try:
                self._bm25 = BM25Index.load_pickle(cache_path)
                log.info("已从 BM25 缓存加载索引: %s", cache_path)
                return
            except Exception as e:
                log.warning("加载 BM25 缓存失败，将回退重建: %s", e)

        self._rebuild_bm25()

    def _rebuild_bm25(self):
        """从 Milvus 加载所有 chunk，重建 BM25 索引并写入缓存。"""
        self._bm25 = BM25Index()
        count = self._collection.num_entities
        if count == 0:
            log.info("collection 为空，跳过 BM25 索引重建")
            self._save_bm25_cache_if_needed()
            return

        log.info("从 Milvus 加载 %d 条记录重建 BM25 索引...", count)
        batch_size = 1000
        offset = 0
        total = 0
        while offset < count:
            results = self._collection.query(
                expr="id >= 0",
                output_fields=["file_id", "chunk_index", "content"],
                limit=batch_size,
                offset=offset,
            )
            if not results:
                break
            entries = [
                (r["file_id"], r["chunk_index"], r["content"]) for r in results
            ]
            self._bm25.add_batch(entries)
            total += len(results)
            offset += batch_size
        log.info("BM25 索引重建完成: %d 条记录", total)
        self._save_bm25_cache_if_needed()

    def _save_bm25_cache_if_needed(self):
        cache_path = self._bm25_cache_path
        if not cache_path:
            return
        try:
            cache_dir = Path(cache_path).parent
            if cache_dir and not cache_dir.exists():
                cache_dir.mkdir(parents=True, exist_ok=True)
            self._bm25.save_pickle(cache_path)
            log.info("已保存 BM25 缓存: %s", cache_path)
        except Exception as e:
            log.warning("保存 BM25 缓存失败: %s", e)

    def _refresh_max_file_id(self):
        """从 Milvus 刷新 max_file_id 缓存。"""
        all_file_ids = self._collection.query(
            expr="file_id >= 0",
            output_fields=["file_id"],
            limit=16384,
        )
        if not all_file_ids:
            self._max_file_id = 0
        else:
            self._max_file_id = max(r["file_id"] for r in all_file_ids)

    def _get_next_file_id(self) -> int:
        """获取下一个可用的 file_id（使用缓存）。"""
        return self._max_file_id + 1

    # -------------------- 接口方法 --------------------

    def search(self, kb_id: int, query: str, top_k: int = 10) -> str:
        """语义搜索。返回 JSON 字符串。"""
        try:
            query_vec = self._embedding.encode_single(query)
            results = self._collection.search(
                data=[query_vec],
                anns_field="embedding",
                param={"metric_type": "COSINE", "params": {"ef": 128}},
                limit=top_k,
                output_fields=["file_id", "chunk_index", "content"],
            )
            if not results or not results[0]:
                return None

            hits = []
            for hit in results[0]:
                entity = hit.entity
                hits.append(
                    {
                        "fileId": entity.get("file_id"),
                        "chunkIndex": entity.get("chunk_index"),
                        "content": entity.get("content"),
                        "score": round(hit.score, 4),
                    }
                )
            return json.dumps(hits, ensure_ascii=False)
        except Exception as e:
            log.error("语义搜索异常: %s", e)
            raise

    def keyword_search(self, kb_id: int, query: str, top_k: int = 10) -> str:
        """BM25 关键词搜索。返回 JSON 字符串。"""
        try:
            results = self._bm25.search(query, top_k=top_k)
            if not results:
                return None
            return json.dumps(results, ensure_ascii=False)
        except Exception as e:
            log.error("关键词搜索异常: %s", e)
            raise

    def getFileSummary(self, kb_id: int, file_id: int) -> str:
        """获取文档摘要。"""
        try:
            results = self._collection.query(
                expr=f"file_id == {file_id}",
                output_fields=["summary"],
                limit=1,
            )
            if not results:
                return None
            summary = results[0].get("summary", "")
            return summary if summary else None
        except Exception as e:
            log.error("获取摘要异常: %s", e)
            raise

    def getFilesMeta(self, kb_id: int, file_ids: List[int]) -> str:
        """获取文件元数据。返回 JSON 字符串。"""
        try:
            if not file_ids:
                return None

            ids_str = ", ".join(str(fid) for fid in file_ids)
            results = self._collection.query(
                expr=f"file_id in [{ids_str}]",
                output_fields=["file_id", "file_name", "summary"],
                limit=16384,
            )
            if not results:
                return None

            # 按 file_id 聚合
            meta_map: Dict[int, dict] = {}
            for r in results:
                fid = r["file_id"]
                if fid not in meta_map:
                    meta_map[fid] = {
                        "id": fid,
                        "filename": r.get("file_name", "unknown"),
                        "size": "N/A",
                        "type": Path(r.get("file_name", ""))
                        .suffix.lstrip(".")
                        or "unknown",
                        "chunk_count": 0,
                        "summary": r.get("summary", ""),
                    }
                meta_map[fid]["chunk_count"] += 1

            return json.dumps(
                list(meta_map.values()), ensure_ascii=False, indent=2
            )
        except Exception as e:
            log.error("获取元数据异常: %s", e)
            raise

    def readFileChunks(self, kb_id: int, chunks: List[Dict[str, int]]) -> str:
        """精读指定片段。返回 JSON 字符串。"""
        try:
            if not chunks:
                return None

            # 构建 OR 表达式批量查询，避免 N+1 问题
            or_parts = []
            for item in chunks:
                fid = item["fileId"]
                ci = item["chunkIndex"]
                or_parts.append(f"(file_id == {fid} and chunk_index == {ci})")
            expr = " or ".join(or_parts)

            query_results = self._collection.query(
                expr=expr,
                output_fields=["file_id", "chunk_index", "content"],
                limit=len(chunks),
            )

            if not query_results:
                return None

            # 保持请求顺序
            result_map = {}
            for r in query_results:
                key = (r["file_id"], r["chunk_index"])
                result_map[key] = {
                    "fileId": r["file_id"],
                    "chunkIndex": r["chunk_index"],
                    "content": r["content"],
                }

            results = []
            for item in chunks:
                key = (item["fileId"], item["chunkIndex"])
                if key in result_map:
                    results.append(result_map[key])

            if not results:
                return None
            return json.dumps(results, ensure_ascii=False, indent=2)
        except Exception as e:
            log.error("读取片段异常: %s", e)
            raise

    def _rebuild_file_meta_cache(self):
        """从 Milvus 重建文件元数据缓存。"""
        all_results = self._collection.query(
            expr="id >= 0",
            output_fields=["file_id", "file_name"],
            limit=16384,
        )
        self._file_meta_cache = {}
        if not all_results:
            return

        for r in all_results:
            fid = r["file_id"]
            if fid not in self._file_meta_cache:
                self._file_meta_cache[fid] = {
                    "id": fid,
                    "filename": r.get("file_name", "unknown"),
                    "chunk_count": 0,
                    "status": "done",
                }
            self._file_meta_cache[fid]["chunk_count"] += 1

    def listFilesPaginated(
        self, kb_id: int, page: int = 1, pageSize: int = 20
    ) -> list:
        """分页列出文件。返回 list[dict]。"""
        try:
            # 如果缓存为空，从 Milvus 重建
            if not self._file_meta_cache and self._collection.num_entities > 0:
                self._rebuild_file_meta_cache()

            # 分页
            files = sorted(self._file_meta_cache.values(), key=lambda x: x["id"])
            start = (page - 1) * pageSize
            end = start + pageSize
            return files[start:end]
        except Exception as e:
            log.error("列出文件异常: %s", e)
            raise

    # -------------------- 写入方法（供 IngestionPipeline 使用）--------------------

    def insert_chunks(
        self,
        file_id: int,
        file_name: str,
        chunks: List[str],
        embeddings: List[List[float]],
        summary: str = "",
    ):
        """向 Milvus 写入一个文件的所有 chunk。"""
        data = [
            {
                "file_id": file_id,
                "chunk_index": ci,
                "content": content,
                "file_name": file_name,
                "summary": summary,
                "embedding": emb,
            }
            for ci, (content, emb) in enumerate(zip(chunks, embeddings))
        ]

        self._collection.insert(data)
        try:
            self._collection.flush()
        except Exception as e:
            log.warning("Flush 跳过（Milvus Lite Windows 兼容问题）: %s", e)

        # 更新 BM25 索引
        self._bm25.add_batch(
            [(file_id, ci, content) for ci, content in enumerate(chunks)]
        )
        self._save_bm25_cache_if_needed()

        # 更新 file_id 缓存
        if file_id > self._max_file_id:
            self._max_file_id = file_id

        # 更新文件元数据缓存
        self._file_meta_cache[file_id] = {
            "id": file_id,
            "filename": file_name,
            "chunk_count": len(chunks),
            "status": "done",
        }

        log.info(
            "已写入文件 %s (file_id=%d): %d 个 chunk",
            file_name,
            file_id,
            len(chunks),
        )

    def delete_file(self, file_id: int):
        """删除指定文件的所有 chunk。"""
        self._collection.delete(expr=f"file_id == {file_id}")
        try:
            self._collection.flush()
        except Exception as e:
            log.warning("Flush 跳过（Milvus Lite Windows 兼容问题）: %s", e)
        self._bm25.remove_by_file(file_id)
        self._save_bm25_cache_if_needed()

        # 更新缓存
        self._file_meta_cache.pop(file_id, None)
        # 刷新 max_file_id（如果删除的是最大的）
        if file_id >= self._max_file_id:
            self._refresh_max_file_id()

        log.info("已删除 file_id=%d 的所有 chunk", file_id)

    def close(self):
        """关闭连接。"""
        connections.disconnect("default")
        log.info("Milvus 连接已断开")


# =====================================================================
# IngestionPipeline - 文档摄入
# =====================================================================
class IngestionPipeline:
    """文档摄入管线：加载文件 -> 切 chunk -> embed -> 存入 Milvus。"""

    def __init__(
        self,
        controller: MilvusLiteKBController,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
        chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
    ):
        self._ctrl = controller
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    # -------------------- 文件加载 --------------------

    @staticmethod
    def _extract_text(file_path: str) -> str:
        """从文件中提取文本。支持 PDF、Markdown、TXT。"""
        path = Path(file_path)
        suffix = path.suffix.lower()

        if suffix == ".pdf":
            return IngestionPipeline._extract_pdf(file_path)
        elif suffix in (".md", ".markdown"):
            return path.read_text(encoding="utf-8")
        elif suffix in (".txt", ".text", ".csv", ".log"):
            return path.read_text(encoding="utf-8")
        elif suffix in (".json",):
            return path.read_text(encoding="utf-8")
        else:
            # 尝试当纯文本读取
            try:
                return path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                log.warning("无法读取文件 %s（不支持的编码）", file_path)
                return ""

    @staticmethod
    def _extract_pdf(file_path: str) -> str:
        """从 PDF 提取文本。"""
        from pypdf import PdfReader

        reader = PdfReader(file_path)
        pages = []
        for page in reader.pages:
            text = page.extract_text()
            if text:
                pages.append(text.strip())
        return "\n\n".join(pages)

    # -------------------- 文本切片 --------------------

    def _chunk_text(self, text: str) -> List[str]:
        """
        将文本切分为 chunks。
        策略：先按段落（双换行）拆分，再对超长段落按字符数切分。
        """
        log.info("  开始切片，文本长度: %d 字符", len(text))

        # 按段落拆分
        paragraphs = re.split(r"\n\s*\n", text)
        log.info("  按段落拆分: %d 个段落", len(paragraphs))

        chunks = []
        current = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            # 如果当前 buffer + 新段落 不超限，合并
            if current and len(current) + len(para) + 1 <= self._chunk_size:
                current += "\n" + para
            elif current:
                # 当前 buffer 已满，保存
                chunks.append(current)
                # overlap：取当前 buffer 末尾
                if self._chunk_overlap > 0:
                    current = current[-self._chunk_overlap :] + "\n" + para
                else:
                    current = para
            else:
                current = para

            # 如果单个段落就超限，按字符数硬切
            while len(current) > self._chunk_size:
                cut_point = self._chunk_size
                # 尝试在句号/换行处切
                for sep in ["。", "！", "？", ".", "!", "?", "\n"]:
                    idx = current.rfind(sep, 0, cut_point)
                    if idx > cut_point // 2:
                        cut_point = idx + 1
                        break
                chunks.append(current[:cut_point].strip())
                current = (
                    current[cut_point - self._chunk_overlap :].strip()
                    if self._chunk_overlap > 0
                    else current[cut_point:].strip()
                )

        if current and len(current.strip()) > 0:
            chunks.append(current.strip())

        log.info("  切片完成: %d 个 chunks", len(chunks))
        return chunks

    # -------------------- 摄入单个文件 --------------------

    def ingest_file(self, file_path: str, summary: str = "") -> int:
        """
        摄入单个文件。
        返回分配的 file_id。
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")

        file_name = path.name
        log.info("开始摄入文件: %s", file_name)

        # 1. 提取文本
        text = self._extract_text(file_path)
        if not text.strip():
            log.warning("文件 %s 无文本内容，跳过", file_name)
            return -1

        # 2. 切片
        chunks = self._chunk_text(text)
        if not chunks:
            log.warning("文件 %s 切片后为空，跳过", file_name)
            return -1
        log.info("  切分为 %d 个 chunk", len(chunks))

        # 3. Embedding
        embeddings = self._ctrl._embedding.encode(chunks)
        log.info("  embedding 完成: %d 个向量", len(embeddings))

        # 4. 获取 file_id 并写入
        file_id = self._ctrl._get_next_file_id()
        self._ctrl.insert_chunks(
            file_id, file_name, chunks, embeddings, summary=summary
        )

        return file_id

    # -------------------- 批量摄入目录 --------------------

    def ingest_directory(
        self,
        dir_path: str,
        glob: str = "*.*",
        recursive: bool = False,
    ) -> List[int]:
        """
        摄入目录下的所有文件。

        参数：
          dir_path: 目录路径
          glob: 文件匹配模式，默认 "*.*"
          recursive: 是否递归子目录

        返回：成功摄入的 file_id 列表。
        """
        path = Path(dir_path)
        if not path.is_dir():
            raise NotADirectoryError(f"目录不存在: {dir_path}")

        if recursive:
            files = list(path.rglob(glob))
        else:
            files = list(path.glob(glob))

        if not files:
            log.warning(
                "目录 %s 中未匹配到文件 (glob=%s)", dir_path, glob
            )
            return []

        log.info("匹配到 %d 个文件，开始摄入...", len(files))
        file_ids = []
        for f in files:
            try:
                fid = self.ingest_file(str(f))
                if fid > 0:
                    file_ids.append(fid)
            except Exception as e:
                log.error("摄入文件 %s 失败: %s", f, e)

        log.info("摄入完成: %d/%d 个文件成功", len(file_ids), len(files))
        return file_ids


# =====================================================================
# 便捷函数
# =====================================================================
def create_controller(
    milvus_uri: str = DEFAULT_MILVUS_URI,
    collection_name: str = DEFAULT_COLLECTION,
    embedding_model: str = DEFAULT_EMBEDDING_MODEL,
) -> MilvusLiteKBController:
    """创建并返回知识库控制器实例。"""
    return MilvusLiteKBController(
        milvus_uri=milvus_uri,
        collection_name=collection_name,
        embedding_model=embedding_model,
    )


def ingest_directory(
    controller: MilvusLiteKBController,
    dir_path: str,
    glob: str = "*.*",
    recursive: bool = False,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> List[int]:
    """便捷函数：摄入目录下的文件到知识库。"""
    pipeline = IngestionPipeline(
        controller, chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    return pipeline.ingest_directory(dir_path, glob=glob, recursive=recursive)


def ingest_file(
    controller: MilvusLiteKBController,
    file_path: str,
    summary: str = "",
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    chunk_overlap: int = DEFAULT_CHUNK_OVERLAP,
) -> int:
    """便捷函数：摄入单个文件到知识库。"""
    pipeline = IngestionPipeline(
        controller, chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )
    return pipeline.ingest_file(file_path, summary=summary)
