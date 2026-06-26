# LM Studio 本地部署指南

## 1. 安装 LM Studio

1. 访问 https://lmstudio.ai/ 下载最新版
2. 安装并启动 LM Studio

## 2. 下载 Qwen2.5-7B 模型

1. 在 LM Studio 搜索栏输入 `Qwen2.5-7B-Instruct`
2. 选择推荐的 GGUF 格式（推荐 Q4_K_M 量化版本）
3. 点击下载（约 4-5GB）

## 3. 启动本地 API 服务

1. 在 LM Studio 左侧边栏选择 "Local Server" 标签
2. 在模型下拉菜单中选择已下载的 `Qwen2.5-7B-Instruct`
3. 点击 "Start Server" 按钮
4. 确认服务运行在 `http://localhost:1234`

## 4. 配置项目

项目已自动配置为使用 LM Studio：
- `LLM_MODE = "local"`
- `LOCAL_LLM_MODEL_NAME = "qwen2.5-7b-instruct"`
- `LOCAL_LLM_API_URL = "http://127.0.0.1:1234/v1/chat/completions"`

## 5. 优化建议

### 5.1 LM Studio 设置
- **Context Length**: 建议 8192 或更高
- **GPU Offload**: 尽量设满（7B 模型可完全加载到 4060 显卡）
- **Temperature**: 0.7（匹配自然对话感）

### 5.2 Function Calling 支持
- LM Studio >= 0.3.x 支持 function calling
- Qwen2.5 系列原生支持工具调用
- 如果工具调用不稳定，可尝试更大的模型（如 Qwen2.5-14B）

## 6. 故障排查

### 问题：工具调用失败
**症状**：插件功能（情绪分析、知识库检索）不工作
**解决**：
1. 确认 LM Studio 版本 >= 0.3.x
2. 在 LM Studio Server Settings 中启用 function calling
3. 检查模型是否支持 tool calling（Qwen2.5 支持）

### 问题：响应速度慢
**症状**：AI 回复需要 10+ 秒
**解决**：
1. 确认 GPU Offload 已设满
2. 减小 Context Length（如 4096）
3. 考虑使用更小的量化版本（如 Q3_K_M）

### 问题：连接失败
**症状**：项目启动报错 "Connection refused"
**解决**：
1. 确认 LM Studio 本地服务已启动
2. 检查端口 1234 是否被占用
3. 确认防火墙未阻止本地连接
