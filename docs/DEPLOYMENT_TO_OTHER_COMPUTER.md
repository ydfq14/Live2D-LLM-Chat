# 其他电脑部署指南 — 解决 HuggingFace 连接超时问题

## 问题原因

当项目部署到其他电脑时，访问 HuggingFace 可能会超时：
```
[WinError 10060] 由于连接方在一段时间后没有正确答复或连接的主机没有反应，连接尝试失败。
```

这是因为 HuggingFace 在国内访问不稳定，需要使用镜像站点。

## ✅ 解决方案（已在项目中实现）

### 方案 1: 项目自动配置（推荐）

项目已内置 HuggingFace 国内镜像配置，**无需手动设置**。

在 `main.py` 最顶部加载 `infrastructure._bootstrap`，会自动：
1. 设置 `HF_ENDPOINT=https://hf-mirror.com`（国内镜像）
2. 将模型缓存重定向到项目本地 `.models/` 目录

```python
# main.py 第 1 行
import infrastructure._bootstrap  # noqa: F401
```

### 方案 2: 手动设置环境变量（备选）

如果需要手动配置，在 Windows 命令行中执行：

```cmd
# 临时设置（当前会话有效）
set HF_ENDPOINT=https://hf-mirror.com

# 永久设置（需要重启电脑）
setx HF_ENDPOINT "https://hf-mirror.com"
```

或者在 PowerShell 中：
```powershell
# 临时设置
$env:HF_ENDPOINT = "https://hf-mirror.com"

# 永久设置（用户级别）
[Environment]::SetEnvironmentVariable("HF_ENDPOINT", "https://hf-mirror.com", "User")
```

### 方案 3: 使用 .env 文件

在项目根目录的 `.env` 文件中添加：
```
HF_ENDPOINT=https://hf-mirror.com
```

## 验证配置

运行以下命令验证镜像是否生效：
```python
python -c "import os; print('HF_ENDPOINT:', os.environ.get('HF_ENDPOINT'))"
```

预期输出：
```
HF_ENDPOINT: https://hf-mirror.com
```

## 其他国内镜像站点

如果 `hf-mirror.com` 不可用，可尝试：

| 镜像站点 | 地址 |
|---------|------|
| hf-mirror.com | https://hf-mirror.com |
| HuggingFace 中国 | https://huggingface.co.cn |
| ModelScope | https://modelscope.cn/models |

修改方式：
```python
# 在 infrastructure/_bootstrap.py 第 21 行修改
os.environ.setdefault("HF_ENDPOINT", "https://huggingface.co.cn")
```

## 完整的部署步骤

1. **克隆项目**
   ```bash
   git clone <项目地址>
   ```

2. **创建虚拟环境**
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   ```

3. **安装依赖**
   ```bash
   pip install -r requirements.txt
   ```

4. **运行项目**（镜像自动生效）
   ```bash
   python main.py
   ```

5. **如果仍有超时错误**
   - 手动设置环境变量（见方案 2）
   - 检查防火墙/代理设置
   - 尝试其他镜像站点（见上表）

## 缓存目录说明

项目的模型缓存在本地 `.models/` 目录，结构如下：
```
.models/
├── huggingface/      # HuggingFace 模型缓存
├── modelscope/       # ModelScope 模型缓存
├── torch/            # PyTorch 模型缓存
└── sentence_transformers/  # Sentence Transformers 缓存
```

**优势**：
- ✅ 不占用 C 盘空间
- ✅ 可以整体备份/迁移
- ✅ 避免重复下载

## 常见问题

### Q: 为什么自动配置不生效？

A: 可能原因：
1. 没有在 `main.py` 最顶部导入 `infrastructure._bootstrap`
2. Python 环境变量已被系统覆盖
3. 某些库在 import 时就已经尝试访问 HuggingFace

解决：手动设置环境变量（见方案 2）

### Q: 可以离线运行吗？

A: 可以！
1. 首次运行需要联网下载模型（约 500MB-2GB）
2. 下载完成后模型缓存在 `.models/` 目录
3. 后续运行可以完全离线

### Q: 模型下载在哪里？

A: 默认下载到项目本地 `.models/` 目录，不在 C 盘用户目录。

## 相关文件

- `infrastructure/_bootstrap.py` — 启动配置
- `config.py` — 应用配置
- `.env` — 用户环境变量（可选）
