# 项目结构说明

**最后更新**: 2026-06-22
**状态**: ✅ 已整理

---

## 目录结构概览

```
Live2D-LLM-Chat/
│
├── 📄 核心配置文件
│   ├── README.md                    # 项目主页
│   ├── LICENSE                       # 许可证
│   ├── requirements.txt             # 依赖列表
│   ├── .env.example                 # 环境变量示例
│   └── .gitignore                   # Git忽略规则
│
├── 📄 核心模块（根目录）
│   ├── main.py                      # 主程序入口
│   ├── config.py                    # 配置文件
│   ├── event_loop.py                # IOCP事件循环调度器
│   ├── async_wrapper.py             # 同步代码异步包装器
│   ├── plugin_base.py               # 插件基类
│   ├── plugin_registry.py           # 插件注册中心
│   ├── graph_engine.py              # LangGraph智能体引擎
│   ├── LLM.py                       # LLM管理器
│   ├── TTS.py                       # TTS管理器
│   ├── ASR.py                       # ASR管理器
│   ├── Live2d_animation.py          # Live2D管理器
│   ├── ui_shell.py                  # UI前端管理器
│   ├── kb_controller.py             # 知识库控制器
│   ├── log_config.py                # 日志配置
│   └── TTS_api.py                   # TTS API管理器
│
├── 📁 docs/                         # 文档目录
│   ├── README.md                   # 项目说明（英文）
│   ├── README_CN.md                # 项目说明（中文）
│   ├── PROJECT_DOCUMENTATION.md    # 完整项目文档
│   ├── IOCP_ARCHITECTURE.md       # IOCP架构文档
│   ├── PROJECT_STATUS_REPORT.md   # 项目状态报告
│   ├── PROJECT_COMPLETED.md       # 项目完成报告
│   ├── PHASE5_SUMMARY.md          # 阶段5总结
│   ├── MIMO_ONLINE_MODEL_GUIDE.md # MIMO在线模型指南
│   ├── AGENTIC_RAG_PATH_FIX.md   # 路径修复说明
│   └── COMPLIANCE_CHECK_REPORT.md # 合规检查报告
│
├── 📁 plugins/                      # 插件目录
│   ├── chatbox_plugin.py           # 聊天框插件
│   ├── emotion_rag_plugin.py       # 情绪分析RAG插件
│   ├── scheduler_plugin.py         # 日程管理插件
│   ├── agentic_rag_plugin.py       # Agentic RAG插件
│   └── demo_template_plugin.py     # 模板示例
│
├── 📁 test/                         # 测试目录
│   ├── test_iocp_basic.py          # IOCP基础测试
│   ├── test_plugin_iocp.py         # 插件系统测试
│   ├── test_main_iocp.py           # main.py验证
│   ├── test_scheduler_plugin.py    # 日程管理测试
│   ├── INTEGRATION_TEST_CHECKLIST.md
│   └── TESTING_GUIDE.md
│
├── 📁 infrastructure/               # 基础设施
│   └── _bootstrap.py               # 启动引导
│
├── 📁 .models/                      # 模型缓存（自动创建）
│   ├── huggingface/
│   ├── modelscope/
│   ├── torch/
│   └── sentence_transformers/
│
├── 📁 plugins_data/                 # 插件数据（自动创建）
│   └── scheduler/
│       └── tasks.json
│
├── 📁 logs/                         # 日志目录
│   └── run.log
│
├── 📁 ASR_env/                      # ASR环境
├── 📁 TTS_env/                      # TTS环境
├── 📁 LLM_env/                      # LLM环境
└── 📁 Live2d_env/                   # Live2D环境
```

---

## 文件分类说明

### 1. 核心配置文件（根目录）

这些文件必须保留在根目录：

| 文件 | 用途 |
|------|------|
| `README.md` | 项目主页，GitHub显示 |
| `LICENSE` | 许可证文件 |
| `requirements.txt` | Python依赖列表 |
| `.env.example` | 环境变量示例 |
| `.gitignore` | Git忽略规则 |

---

### 2. 核心模块文件（根目录）

这些文件是项目的核心代码，保留在根目录便于导入：

| 文件 | 功能 | 依赖 |
|------|------|------|
| `main.py` | 主程序入口 | 所有模块 |
| `config.py` | 配置管理 | 无 |
| `event_loop.py` | IOCP事件循环 | asyncio |
| `async_wrapper.py` | 异步包装器 | asyncio |
| `plugin_base.py` | 插件基类 | 无 |
| `plugin_registry.py` | 插件注册中心 | plugin_base |
| `graph_engine.py` | LangGraph智能体 | LangGraph |
| `LLM.py` | LLM管理器 | OpenAI SDK |
| `TTS.py` | TTS管理器 | 无 |
| `ASR.py` | ASR管理器 | 无 |
| `Live2d_animation.py` | Live2D管理器 | live2d-py |
| `ui_shell.py` | UI前端管理器 | pywebview |
| `kb_controller.py` | 知识库控制器 | Milvus |
| `log_config.py` | 日志配置 | logging |
| `TTS_api.py` | TTS API管理器 | 无 |

---

### 3. 文档目录（docs/）

所有文档文件集中管理：

| 文件 | 内容 |
|------|------|
| `README.md` | 项目说明（英文） |
| `README_CN.md` | 项目说明（中文） |
| `PROJECT_DOCUMENTATION.md` | 完整项目文档 |
| `IOCP_ARCHITECTURE.md` | IOCP架构文档 |
| `PROJECT_STATUS_REPORT.md` | 项目状态报告 |
| `PROJECT_COMPLETED.md` | 项目完成报告 |
| `PHASE5_SUMMARY.md` | 阶段5总结 |
| `MIMO_ONLINE_MODEL_GUIDE.md` | MIMO在线模型指南 |
| `AGENTIC_RAG_PATH_FIX.md` | 路径修复说明 |
| `COMPLIANCE_CHECK_REPORT.md` | 合规检查报告 |

---

### 4. 插件目录（plugins/）

所有插件文件集中管理：

| 文件 | 功能 | Hook实现 |
|------|------|---------|
| `chatbox_plugin.py` | 聊天框界面 | on_user_input, on_llm_response |
| `emotion_rag_plugin.py` | 情绪分析RAG | on_user_input, on_llm_context |
| `scheduler_plugin.py` | 日程管理 | on_register_background_tasks |
| `agentic_rag_plugin.py` | 知识库RAG | on_register_tools, on_execute_tool |
| `demo_template_plugin.py` | 模板示例 | 所有Hook |

---

### 5. 测试目录（test/）

所有测试文件集中管理：

| 文件 | 测试内容 | 测试数量 |
|------|---------|---------|
| `test_iocp_basic.py` | IOCP基础框架 | 7 |
| `test_plugin_iocp.py` | 插件系统 | 5 |
| `test_main_iocp.py` | main.py结构 | 4 |
| `test_scheduler_plugin.py` | 日程管理插件 | 12 |
| `INTEGRATION_TEST_CHECKLIST.md` | 集成测试清单 | - |
| `TESTING_GUIDE.md` | 测试指南 | - |

---

### 6. 基础设施目录（infrastructure/）

启动引导模块：

| 文件 | 功能 |
|------|------|
| `_bootstrap.py` | 启动引导，重定向模型缓存路径 |

---

### 7. 自动生成目录

这些目录在运行时自动创建：

| 目录 | 用途 | 内容 |
|------|------|------|
| `.models/` | 模型缓存 | HuggingFace, ModelScope, PyTorch模型 |
| `plugins_data/` | 插件数据 | 任务数据、配置等 |
| `logs/` | 日志 | 运行日志文件 |
| `ASR_env/` | ASR环境 | 录音文件 |
| `TTS_env/` | TTS环境 | 音频文件、模型 |
| `LLM_env/` | LLM环境 | 对话历史 |
| `Live2d_env/` | Live2D环境 | 模型文件 |

---

## 路径约定

### 模型缓存路径

所有模型缓存统一存储到 `.models/` 目录：

```
.models/
├── huggingface/          # HuggingFace 模型
├── modelscope/           # ModelScope 模型
├── torch/                # PyTorch 模型
└── sentence_transformers/  # sentence-transformers 模型
```

**环境变量**:
- `HF_HOME` → `.models/huggingface`
- `MODELSCOPE_CACHE` → `.models/modelscope`
- `TORCH_HOME` → `.models/torch`
- `SENTENCE_TRANSFORMERS_HOME` → `.models/sentence_transformers`

---

### 插件数据路径

插件数据统一存储到 `plugins_data/` 目录：

```
plugins_data/
├── scheduler/
│   └── tasks.json        # 日程任务数据
├── agentic_rag/
│   ├── kb.db             # Milvus数据库
│   └── bm25_cache.pkl    # BM25缓存
└── chatbox/
    └── ...               # 聊天框数据
```

**路径获取**: 使用 `get_data_dir()` 方法

---

## 导入路径说明

### 核心模块导入

```python
# 从根目录导入
from main import MainManager
from config import Config
from event_loop import get_scheduler
from plugin_base import PluginBase
from plugin_registry import PluginRegistry
```

### 插件导入

```python
# 从插件目录导入
from plugins.scheduler_plugin import SchedulerPlugin
from plugins.chatbox_plugin import ChatboxPlugin
```

### 基础设施导入

```python
# 从基础设施目录导入
from infrastructure._bootstrap import apply
```

---

## 文件大小统计

| 类型 | 文件数量 | 总大小 |
|------|---------|--------|
| 核心模块 | 15 | ~200KB |
| 插件文件 | 5 | ~90KB |
| 测试文件 | 4 | ~50KB |
| 文档文件 | 10 | ~100KB |
| **总计** | **34** | **~440KB** |

---

## 维护建议

### 1. 添加新插件

1. 在 `plugins/` 目录创建新文件
2. 命名格式: `{plugin_name}_plugin.py`
3. 继承 `PluginBase` 类
4. 重启程序自动加载

### 2. 添加新测试

1. 在 `test/` 目录创建新文件
2. 命名格式: `test_{feature}.py`
3. 遵循现有测试结构
4. 更新 `INTEGRATION_TEST_CHECKLIST.md`

### 3. 添加新文档

1. 在 `docs/` 目录创建新文件
2. 使用 `.md` 格式
3. 更新 `docs/README.md` 索引

### 4. 修改配置

1. 编辑 `config.py` 或 `.env` 文件
2. 参考 `.env.example` 格式
3. 重启程序生效

---

## 总结

✅ **项目结构清晰**
✅ **文件分类明确**
✅ **路径约定统一**
✅ **易于维护和扩展**

所有文件已按功能分类整理，项目结构更加美观和易于维护。

---

**文档版本**: v1.0
**最后更新**: 2026-06-22
