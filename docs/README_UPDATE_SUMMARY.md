# README 和 requirements.txt 更新总结

## 更新日期
2026-06-25

## 更新内容

### 1. requirements.txt 更新

**主要改动**：
- ✅ 添加 PyTorch 基础版本（CPU）的注释说明
- ✅ 明确说明 GPU 用户需要手动安装 CUDA 版本
- ✅ 避免在 requirements.txt 中指定 CUDA 版本（防止其他用户安装失败）

**新增的 PyTorch 依赖**：
```txt
# ==================== PyTorch（基础版本，默认为 CPU 版本）====================
# GPU 用户请按照 README.md 中的说明手动安装 CUDA 版本
# 不要在此处指定 CUDA 版本，避免其他用户安装失败
torch             # PyTorch（基础版本，CPU）
torchvision       # PyTorch 视觉模块
torchaudio        # PyTorch 音频模块
```

**新增的说明注释**：
```txt
# ⚠️ PyTorch 默认安装的是 CPU 版本！
#    GPU 用户请按照 README.md 中的说明手动安装 CUDA 版本
```

### 2. README_CN.md 更新

**新增章节**：

#### 3.3 GPU 加速配置（推荐）
包含完整 GPU 安装指南：
- 步骤 1: 检查 GPU 和 CUDA 版本
- 步骤 2: 在 Conda 虚拟环境中卸载 CPU 版本的 PyTorch
- 步骤 3: 安装 CUDA 版本的 PyTorch（支持多个 CUDA 版本）
- 步骤 4: 验证 GPU 安装
- GPU 性能对比表

**更新的章节**：

#### 3.4 配置和运行
- 合并了原来的两个 "3.4" 部分
- 重新组织为 "配置" 和 "运行" 两个子部分

#### ❓ 11. 常见问题（FAQ）
新增 9 个常见问题：
1. 为什么 PyTorch 默认安装的是 CPU 版本？
2. 如何确定我的 CUDA 版本？
3. 安装 CUDA 版本 PyTorch 后仍然显示 CUDA 不可用？
4. 可以同时使用 GPU 和 CPU 模式吗？
5. HuggingFace 模型下载超时？
6. 如何更新依赖？
7. PyTorch CUDA 版本下载很慢？
8. conda 环境中应该使用哪个 Python 版本？
9. faster-whisper 和 piper-tts 是什么？

#### 🤝 12. 贡献与鸣谢
更新了技术引用，替换过时的技术：
- ❌ SenseVoice → ✅ faster-whisper
- ❌ CosyVoice → ✅ piper-tts
- ✅ 新增 PyTorch 和 HuggingFace 引用

**更新的技术栈表格**：
| 组件 | 本地技术 | 云端技术 |
|------|---------|---------|
| ASR（语音识别） | faster-whisper | MiMo ASR |
| LLM（大语言模型） | LM Studio / Ollama | OpenAI / DeepSeek / MiMo |
| TTS（文本转语音） | piper-tts | MiMo TTS |

**更新的徽章**：
- ASR: SenseVoice → faster-whisper
- TTS: CosyVoice → piper-tts

**其他更新**：
- 更新文档更新时间：2026-06-22 → 2026-06-25
- 修复章节编号错误

## 关键设计决策

### 为什么不在 requirements.txt 中指定 CUDA 版本？

**问题**：
- PyTorch CUDA 版本很大（约 2.5GB）
- 不同用户的 CUDA 版本不同（11.8、12.1、12.4 等）
- 如果在 requirements.txt 中指定某个 CUDA 版本，会导致其他用户安装失败

**解决方案**：
- requirements.txt 中只包含基础 CPU 版本
- 在 README 中提供详细的 GPU 安装指南
- 用户根据自己的 CUDA 版本手动安装

**优势**：
- ✅ 所有用户都能成功安装基础依赖
- ✅ GPU 用户可以获得详细的安装指导
- ✅ 避免因 CUDA 版本不匹配导致的安装失败
- ✅ 用户可以根据需要选择是否使用 GPU

## 文件变更清单

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| requirements.txt | 修改 | 添加 PyTorch 基础版本和 GPU 安装说明 |
| docs/README_CN.md | 修改 | 添加 GPU 安装指南、FAQ、更新技术栈 |
| docs/DEPLOYMENT_TO_OTHER_COMPUTER.md | 新增 | 部署到其他电脑的指南 |
| docs/DEPLOYMENT_MODE_GUIDE.md | 新增 | 部署模式选择指南 |

## 验证步骤

### 验证 requirements.txt
```bash
# 应该成功安装所有依赖（CPU 版本）
pip install -r requirements.txt

# 验证 PyTorch 安装
python -c "import torch; print('PyTorch:', torch.__version__)"
```

### 验证 README GPU 部分
1. 检查 "3.3 GPU 加速配置" 章节是否存在
2. 检查是否包含 Conda 虚拟环境说明
3. 检查是否包含多个 CUDA 版本的安装命令
4. 检查是否包含验证步骤
5. 检查常见问题部分是否完整

## 使用场景

### 场景 1: 普通用户（无 GPU）
```bash
# 1. 创建 conda 环境
conda create -n virtumate python=3.10 -y
conda activate virtumate

# 2. 安装依赖（CPU 版本）
pip install -r requirements.txt

# 3. 运行项目（选择云端模式或 CPU 本地模式）
python main.py
```

### 场景 2: GPU 用户（有 NVIDIA GPU）
```bash
# 1. 创建 conda 环境
conda create -n virtumate python=3.10 -y
conda activate virtumate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 安装 CUDA 版本的 PyTorch（按照 README 指南）
pip uninstall torch torchvision torchaudio -y
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# 4. 验证 GPU 安装
python -c "import torch; print('CUDA:', torch.cuda.is_available())"

# 5. 运行项目（选择 GPU 本地模式）
python main.py
```

## 后续改进建议

1. **创建 GPU 安装脚本**：提供 `install_gpu.bat` 自动化脚本
2. **添加 CUDA 版本检测**：自动检测用户的 CUDA 版本并推荐合适的 PyTorch 版本
3. **创建 Docker 镜像**：提供预配置的 GPU Docker 镜像
4. **添加 GPU 性能测试**：提供 GPU 性能基准测试脚本

## 相关文档

- `docs/README_CN.md` - 完整的项目文档（包含 GPU 安装指南）
- `docs/DEPLOYMENT_TO_OTHER_COMPUTER.md` - 部署到其他电脑的指南
- `docs/DEPLOYMENT_MODE_GUIDE.md` - 部署模式选择指南
- `requirements.txt` - 依赖清单
