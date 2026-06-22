# IOCP 测试套件

本文件夹包含IOCP基础框架的所有测试文件。

## 📁 文件说明

| 文件 | 用途 | 运行时间 |
|------|------|---------|
| `quick_iocp_test.py` | 快速测试（推荐先运行） | ~2秒 |
| `run_iocp_tests.py` | 完整测试套件 | ~10-15秒 |
| `test_iocp_basic.py` | 测试模块（被run_iocp_tests.py调用） | - |
| `TESTING_GUIDE.md` | 详细测试指南 | - |

## 🚀 快速开始

### 方式1：从项目根目录运行（推荐）

```bash
# 快速测试
python test/quick_iocp_test.py

# 完整测试
python test/run_iocp_tests.py
```

### 方式2：从test目录运行

```bash
# 进入test目录
cd test

# 快速测试
python quick_iocp_test.py

# 完整测试
python run_iocp_tests.py
```

## 📊 测试内容

### 快速测试 (quick_iocp_test.py)
- ✅ 调度器创建
- ✅ 任务添加
- ✅ 任务执行
- ✅ 配置检查
- ✅ 异步包装器

### 完整测试 (run_iocp_tests.py)
1. IOCPScheduler 基本功能
2. 任务调度
3. 任务执行
4. 异步任务执行
5. 多任务并发
6. 任务管理
7. AsyncWrapper
8. 全局调度器
9. 线程安全性
10. 资源清理
11. 配置检查
12. 性能测试

## 📖 详细指南

查看 [TESTING_GUIDE.md](TESTING_GUIDE.md) 获取：
- 完整的测试说明
- 预期输出示例
- 常见问题解答
- 调试技巧

## 🎯 测试流程

1. **先运行快速测试**
   ```bash
   python test/quick_iocp_test.py
   ```

2. **如果通过，运行完整测试**
   ```bash
   python test/run_iocp_tests.py
   ```

3. **查看测试结果**
   - ✅ 所有测试通过 → 可以继续阶段2
   - ❌ 有测试失败 → 查看错误信息并修复

## 💡 提示

- 所有测试输出使用日志模块，会显示在控制台
- 测试会自动清理资源，不会影响项目状态
- 如果遇到问题，查看TESTING_GUIDE.md的常见问题部分

## 🔧 环境要求

- Python 3.8+
- Windows 10/11（推荐，支持IOCP）
- 项目依赖已安装（pip install -r requirements.txt）

## 📝 反馈

测试完成后，请告诉我：
1. 测试结果（通过/失败数量）
2. 遇到的问题
3. 性能表现

---

**祝测试顺利！** 🎉
