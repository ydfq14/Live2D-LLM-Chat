# VirtuMate Live2D-LLM-Chat

[![IOCP](https://img.shields.io/badge/IOCP-Architecture-blue.svg)](docs/IOCP_ARCHITECTURE.md)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agent-purple.svg)](https://langchain-ai.github.io/langgraph/)
[![Python](https://img.shields.io/badge/Python-3.10+-yellow.svg)](https://www.python.org/downloads/)

> **智能语音对话 Live2D 桌宠** | IOCP异步架构 | 插件化系统 | LangGraph智能体

---

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env 文件，填入API密钥

# 3. 运行程序
python main.py
```

---

## 项目结构

```
Live2D-LLM-Chat/
├── main.py                    # 主程序入口
├── config.py                  # 配置文件
├── event_loop.py              # IOCP事件循环调度器
├── async_wrapper.py           # 同步代码异步包装器
├── plugin_base.py             # 插件基类
├── plugin_registry.py         # 插件注册中心
├── graph_engine.py            # LangGraph智能体引擎
├── LLM.py                    # LLM管理器
├── TTS.py                    # TTS管理器
├── ASR.py                    # ASR管理器
├── Live2d_animation.py        # Live2D管理器
├── ui_shell.py               # UI前端管理器
├── kb_controller.py           # 知识库控制器
├── log_config.py             # 日志配置
├── requirements.txt           # 依赖列表
├── .env.example              # 环境变量示例
│
├── docs/                     # 📚 文档目录
│   ├── README.md             # 项目说明（英文）
│   ├── README_CN.md          # 项目说明（中文）
│   ├── PROJECT_DOCUMENTATION.md  # 完整项目文档
│   ├── IOCP_ARCHITECTURE.md # IOCP架构文档
│   └── ...                   # 其他文档
│
├── plugins/                  # 🔌 插件目录
│   ├── chatbox_plugin.py     # 聊天框插件
│   ├── emotion_rag_plugin.py # 情绪分析RAG插件
│   ├── scheduler_plugin.py   # 日程管理插件
│   ├── agentic_rag_plugin.py # Agentic RAG插件
│   └── demo_template_plugin.py # 模板示例
│
├── test/                     # 🧪 测试目录
│   ├── test_iocp_basic.py    # IOCP基础测试
│   ├── test_plugin_iocp.py   # 插件系统测试
│   ├── test_main_iocp.py     # main.py验证
│   └── test_scheduler_plugin.py # 日程管理测试
│
├── infrastructure/           # 🏗️ 基础设施
│   └── _bootstrap.py         # 启动引导
│
├── .models/                  # 📦 模型缓存目录
├── plugins_data/             # 💾 插件数据目录
├── logs/                     # 📝 日志目录
├── ASR_env/                  # ASR环境
├── TTS_env/                  # TTS环境
├── LLM_env/                  # LLM环境
└── Live2d_env/               # Live2D环境
```

---

## 核心模块

| 模块 | 文件 | 功能 |
|------|------|------|
| 主程序 | `main.py` | MainManager类，统筹调度所有模块 |
| 配置 | `config.py` | 统一配置管理 |
| IOCP | `event_loop.py` | 高性能异步事件循环调度器 |
| 异步包装器 | `async_wrapper.py` | 同步代码异步包装 |
| 插件系统 | `plugin_base.py` + `plugin_registry.py` | 模块化插件架构 |
| 智能体 | `graph_engine.py` | LangGraph图引擎 |

---

## 插件系统

| 插件 | 功能 |
|------|------|
| chatbox_plugin.py | 聊天框界面 |
| emotion_rag_plugin.py | 情绪分析与RAG记忆 |
| scheduler_plugin.py | 日程管理 |
| agentic_rag_plugin.py | 知识库RAG |
| demo_template_plugin.py | 插件开发模板 |

---

## 技术栈

- **IOCP异步架构**: Windows ProactorEventLoop
- **LangGraph**: 智能体图引擎
- **pywebview**: 桌面前端
- **Chroma**: 向量数据库
- **BGE-M3**: 嵌入模型
- **MIMO**: 云端ASR/TTS/LLM

---

## 文档

详细文档请查看 [docs/](docs/) 目录：

- [项目说明（中文）](docs/README_CN.md)
- [完整项目文档](docs/PROJECT_DOCUMENTATION.md)
- [IOCP架构文档](docs/IOCP_ARCHITECTURE.md)
- [项目状态报告](docs/PROJECT_STATUS_REPORT.md)

---

## 许可证

[Apache-2.0 License](LICENSE)
