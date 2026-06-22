# agentic_rag_plugin.py 模型路径修复说明

**修复日期**: 2026-06-22
**问题类型**: 违反项目约定
**影响范围**: kb_controller.py

---

## 问题描述

`agentic_rag_plugin.py` 使用的 `kb_controller.py` 中存在硬编码路径，违反了项目将所有模型缓存统一到 `.models/` 目录的约定。

### 原始问题代码

```python
# kb_controller.py 第65行
DEFAULT_LOCAL_EMBEDDING_DIR = "D:/Models/bge-m3"  ❌ 硬编码

# kb_controller.py 第93行
cache_dir = str(Path(self._local_dir).parent) if self._local_dir else "D:/Models"  ❌ 硬编码
```

### 项目约定

根据 `_bootstrap.py` 的配置，所有模型缓存应该存储在：

```
.models/
├── huggingface/          # HuggingFace 模型
├── modelscope/           # ModelScope 模型
├── torch/                # PyTorch 模型
├── sentence_transformers/  # sentence-transformers 模型
└── tfhub/                # TensorFlow 模型（预留）
```

---

## 修复方案

### 1. 移除硬编码路径

**修改前**:
```python
DEFAULT_LOCAL_EMBEDDING_DIR = "D:/Models/bge-m3"
```

**修改后**:
```python
# 移除 DEFAULT_LOCAL_EMBEDDING_DIR 常量
```

### 2. 添加辅助函数

**新增函数**:

```python
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
```

### 3. 更新 EmbeddingManager

**修改前**:
```python
class EmbeddingManager:
    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        local_dir: Optional[str] = DEFAULT_LOCAL_EMBEDDING_DIR,  ❌ 使用硬编码
    ):
        self._local_dir = local_dir  ❌

    def _download_from_modelscope(self) -> str:
        cache_dir = str(Path(self._local_dir).parent) if self._local_dir else "D:/Models"  ❌
```

**修改后**:
```python
class EmbeddingManager:
    def __init__(
        self,
        model_name: str = DEFAULT_EMBEDDING_MODEL,
        local_dir: Optional[str] = None,  ✅ 默认为 None
    ):
        self._local_dir = local_dir or _get_sentence_transformers_cache_dir()  ✅

    def _download_from_modelscope(self) -> str:
        cache_dir = _get_model_cache_dir()  ✅ 使用辅助函数
```

### 4. 更新 MilvusLiteKBController

**修改前**:
```python
class MilvusLiteKBController:
    def __init__(
        self,
        milvus_uri: str = DEFAULT_MILVUS_URI,
        collection_name: str = DEFAULT_COLLECTION,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        local_embedding_dir: Optional[str] = DEFAULT_LOCAL_EMBEDDING_DIR,  ❌
        bm25_cache_path: Optional[str] = DEFAULT_BM25_CACHE_PATH,
    ):
```

**修改后**:
```python
class MilvusLiteKBController:
    def __init__(
        self,
        milvus_uri: str = DEFAULT_MILVUS_URI,
        collection_name: str = DEFAULT_COLLECTION,
        embedding_model: str = DEFAULT_EMBEDDING_MODEL,
        local_embedding_dir: Optional[str] = None,  ✅ 默认为 None
        bm25_cache_path: Optional[str] = DEFAULT_BM25_CACHE_PATH,
    ):
```

---

## 修复后的路径使用

### 模型缓存路径

| 模型类型 | 环境变量 | 回退路径 |
|---------|---------|---------|
| ModelScope 模型 | `MODELSCOPE_CACHE` | `.models/modelscope/` |
| sentence-transformers | `SENTENCE_TRANSFORMERS_HOME` | `.models/sentence_transformers/` |
| HuggingFace 模型 | `HF_HOME` | `.models/huggingface/` |
| PyTorch 模型 | `TORCH_HOME` | `.models/torch/` |

### 数据文件路径

| 文件类型 | 路径 | 说明 |
|---------|------|------|
| Milvus 数据库 | `plugins_data/agentic_rag/kb.db` | 向量数据库 |
| BM25 缓存 | `plugins_data/agentic_rag/bm25_cache.pkl` | 关键词索引 |

---

## 环境变量优先级

1. **用户设置的环境变量** (最高优先级)
   - 用户可以在终端或 .env 文件中设置
   - 使用 `os.environ.setdefault()` 不会覆盖

2. **bootstrap 设置的环境变量**
   - `_bootstrap.py` 在 main.py 最顶部加载
   - 设置到 `.models/` 目录

3. **辅助函数的回退路径** (最低优先级)
   - 如果环境变量未设置
   - 使用 `os.path.join(project_root, ".models", "xxx")`

---

## 测试验证

修复后，模型缓存应该存储在：

```
.models/
├── modelscope/
│   └── BAAI/
│       └── bge-m3/           # 从 ModelScope 下载的模型
└── sentence_transformers/
    └── BAAI/
        └── bge-m3/           # sentence-transformers 缓存的模型
```

而不是之前的：

```
D:/Models/
└── bge-m3/                   ❌ 硬编码路径
```

---

## 相关文件

- `infrastructure/_bootstrap.py` - 环境变量配置
- `plugins/agentic_rag_plugin.py` - Agentic RAG 插件
- `kb_controller.py` - 知识库控制器

---

## 总结

✅ **已修复**: 移除所有硬编码路径
✅ **已修复**: 使用辅助函数获取缓存目录
✅ **已修复**: 遵循项目约定的 `.models/` 目录结构
✅ **已修复**: 优先使用环境变量（由 bootstrap 设置）

---

**修复状态**: ✅ 完成
**修复日期**: 2026-06-22
