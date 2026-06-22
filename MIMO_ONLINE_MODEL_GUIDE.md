# MIMO 在线模型使用说明

**检查日期**: 2026-06-22
**状态**: ✅ 项目使用MIMO在线模型

---

## 概述

VirtuMate Live2D-LLM-Chat 项目**主要使用MIMO云端在线模型**，而非本地模型。这使得项目可以快速启动，无需下载大量模型文件。

---

## MIMO 在线模型配置

### 配置文件位置

**文件**: `config.py`

### ASR（语音识别）配置

```python
# 语音识别模式
ASR_MODE = "cloud"  # "local" 或 "cloud"

# MIMO ASR 配置
MIMO_API_KEY = os.getenv("MIMO_API_KEY", "")  # API密钥
MIMO_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"  # API地址
MIMO_ASR_MODEL = "mimo-v2.5-asr"  # 模型名称
MIMO_ASR_LANGUAGE = "auto"  # 语言：auto/zh/en
```

**功能特性**:
- ✅ 支持多语言自动检测（中文、英文等）
- ✅ 高精度语音识别
- ✅ 无需下载本地模型
- ✅ 实时云端处理

---

### TTS（文本转语音）配置

```python
# 文本转语音模式
TTS_MODE = "cloud"  # "local" 或 "cloud"

# MIMO TTS 配置
MIMO_TTS_MODEL = "mimo-v2.5-tts"  # 模型名称
MIMO_TTS_VOICE = "冰糖"  # 音色选择
MIMO_TTS_FORMAT = "wav"  # 音频格式
MIMO_TTS_STYLE = "语速适中、自然亲切"  # 风格控制
```

**可用音色**:
- 冰糖（默认）
- 茉莉
- 苏打
- 白桦
- Mia
- Chloe
- Milo
- Dean
- mimo_default

**功能特性**:
- ✅ 支持多种预置音色
- ✅ 自然语言风格控制
- ✅ 高质量语音合成
- ✅ 无需下载本地模型

---

### LLM（大语言模型）配置

```python
# LLM 模式
LLM_MODE = "cloud"  # "local" 或 "cloud"

# 云端 LLM 配置
LLM_CLOUD_API_KEY = os.getenv("LLM_CLOUD_API_KEY", "")
LLM_CLOUD_BASE_URL = "https://api.deepseek.com"  # DeepSeek API
LLM_CLOUD_MODEL_NAME = "deepseek-v4-flash"  # 模型名称
```

**支持的云端LLM**:
- DeepSeek（默认）
- OpenAI
- MiMo
- 其他OpenAI兼容协议的LLM

**功能特性**:
- ✅ 支持多种云端LLM
- ✅ OpenAI兼容协议
- ✅ 高质量对话生成
- ✅ 无需下载本地模型

---

## 使用流程

### 1. 获取API密钥

**MIMO平台**: https://platform.xiaomimimo.com

**步骤**:
1. 注册MIMO账号
2. 登录控制台
3. 获取API Key（格式：`sk-xxxxxxxx`）
4. 配置到 `.env` 文件或环境变量

**.env 文件示例**:
```env
MIMO_API_KEY=sk-xxxxxxxxxxxxxxxx
LLM_CLOUD_API_KEY=sk-xxxxxxxxxxxxxxxx
```

---

### 2. 配置模式

**config.py 中的模式设置**:

```python
# ASR模式
ASR_MODE = "cloud"  # 使用MIMO ASR

# TTS模式
TTS_MODE = "cloud"  # 使用MIMO TTS

# LLM模式
LLM_MODE = "cloud"  # 使用云端LLM
```

---

### 3. 启动程序

```bash
python main.py
```

**启动日志**:
```
[阶段 2/5] 核心模块初始化
  → 初始化 ASR 管理器...
    [OK] ASR 管理器就绪 (模式: cloud)
  → 初始化 TTS 管理器...
    [OK] TTS 管理器就绪 (模式: cloud)
  → 初始化 LLM 管理器...
    [OK] LLM 管理器就绪 (模式: cloud, deepseek-v4-flash)
```

---

## 在线模型 vs 本地模型

### MIMO在线模型（推荐）

**优势**:
- ✅ 无需下载模型文件
- ✅ 启动速度快
- ✅ 不占用本地存储空间
- ✅ 自动更新模型版本
- ✅ 支持高并发处理

**劣势**:
- ❌ 需要网络连接
- ❌ 依赖第三方API服务
- ❌ 可能有API调用费用

**适用场景**:
- 快速原型开发
- 生产环境部署
- 不想占用本地存储
- 需要最新模型版本

---

### 本地模型（可选）

**优势**:
- ✅ 无需网络连接
- ✅ 无API调用费用
- ✅ 数据隐私性好

**劣势**:
- ❌ 需要下载大量模型文件
- ❌ 占用本地存储空间
- ❌ 启动速度慢
- ❌ 需要手动更新模型

**适用场景**:
- 离线环境
- 数据隐私要求高
- 有足够本地存储空间

---

## 模型存储路径

### 在线模型（MIMO云端）

**存储位置**: 云端服务器（MIMO平台）
**本地缓存**: 无（实时调用API）

### 本地模型（可选）

**存储位置**: `.models/` 目录

```
.models/
├── huggingface/          # HuggingFace 模型
├── modelscope/           # ModelScope 模型
├── torch/                # PyTorch 模型
├── sentence_transformers/  # sentence-transformers 模型
└── tfhub/                # TensorFlow 模型（预留）
```

**本地模型类型**:
- SenseVoice: 本地ASR模型
- CosyVoice: 本地TTS模型
- BGE-M3: 知识库嵌入模型

---

## API调用流程

### ASR调用流程

```
用户语音输入
    ↓
录音模块（本地）
    ↓
发送到MIMO ASR API
    ↓
MIMO云端处理
    ↓
返回识别文本
    ↓
后续处理（LLM、TTS等）
```

### TTS调用流程

```
LLM生成回复文本
    ↓
发送到MIMO TTS API
    ↓
MIMO云端处理
    ↓
返回语音音频
    ↓
本地播放音频
    ↓
Live2D嘴型同步
```

### LLM调用流程

```
用户输入文本
    ↓
发送到云端LLM API（DeepSeek/OpenAI/MiMo）
    ↓
云端处理生成回复
    ↓
返回回复文本
    ↓
后续处理（TTS、Live2D等）
```

---

## 配置示例

### 完整配置示例

**.env 文件**:
```env
# MIMO API配置
MIMO_API_KEY=sk-xxxxxxxxxxxxxxxx

# LLM API配置
LLM_CLOUD_API_KEY=sk-xxxxxxxxxxxxxxxx
```

**config.py**:
```python
class Config:
    # ASR模式
    ASR_MODE = "cloud"
    
    # TTS模式
    TTS_MODE = "cloud"
    
    # LLM模式
    LLM_MODE = "cloud"
    
    # MIMO API配置
    MIMO_API_KEY = os.getenv("MIMO_API_KEY", "")
    MIMO_BASE_URL = "https://token-plan-cn.xiaomimimo.com/v1"
    MIMO_ASR_MODEL = "mimo-v2.5-asr"
    MIMO_ASR_LANGUAGE = "auto"
    
    # TTS配置
    MIMO_TTS_MODEL = "mimo-v2.5-tts"
    MIMO_TTS_VOICE = "冰糖"
    MIMO_TTS_FORMAT = "wav"
    MIMO_TTS_STYLE = "语速适中、自然亲切"
    
    # LLM配置
    LLM_CLOUD_API_KEY = os.getenv("LLM_CLOUD_API_KEY", "")
    LLM_CLOUD_BASE_URL = "https://api.deepseek.com"
    LLM_CLOUD_MODEL_NAME = "deepseek-v4-flash"
```

---

## 费用说明

### MIMO API费用

**定价**: 按量计费
**计费单位**: Token/字符
**免费额度**: 新用户有免费额度（具体请参考MIMO官网）

**费用优化建议**:
- 合理设置API调用频率
- 使用缓存减少重复调用
- 选择合适的模型版本

---

## 常见问题

### 1. API调用失败

**原因**:
- API密钥无效
- 网络连接问题
- API服务异常

**解决**:
- 检查API密钥是否正确
- 检查网络连接
- 查看错误日志

### 2. 识别准确率低

**原因**:
- 语音质量差
- 背景噪音大
- 语言设置不正确

**解决**:
- 确保录音环境安静
- 检查 `MIMO_ASR_LANGUAGE` 设置
- 尝试使用本地模型

### 3. TTS音质差

**原因**:
- 音色选择不当
- 风格控制不准确
- 网络延迟

**解决**:
- 尝试不同音色
- 调整 `MIMO_TTS_STYLE`
- 检查网络连接

---

## 总结

✅ **项目主要使用MIMO在线模型**
✅ **无需下载本地模型**
✅ **快速启动，实时处理**
✅ **支持ASR、TTS、LLM云端服务**

MIMO在线模型使得项目可以快速部署和使用，无需占用本地存储空间，适合快速原型开发和生产环境部署。

---

**文档版本**: v1.0
**最后更新**: 2026-06-22
**状态**: ✅ 项目使用MIMO在线模型
