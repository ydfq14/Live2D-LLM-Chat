#!/usr/bin/env python3
"""验证 README 的完整性"""
import re

print("=" * 60)
print("验证 README_CN.md 完整性")
print("=" * 60)

with open("docs/README_CN.md", "r", encoding="utf-8") as f:
    content = f.read()

checks = {
    "GPU 加速配置": "### 3.3 GPU 加速配置",
    "Conda 环境说明": "conda activate virtumate",
    "CUDA 11.8 安装": "cu118",
    "CUDA 12.4 安装": "cu124",
    "GPU 验证步骤": "torch.cuda.is_available()",
    "GPU 性能对比": "GPU 性能对比",
    "常见问题 FAQ": "## ❓ 11. 常见问题",
    "faster-whisper 引用": "faster-whisper",
    "piper-tts 引用": "piper-tts",
    "PyTorch 引用": "PyTorch",
}

passed = 0
failed = 0

for name, pattern in checks.items():
    if pattern in content:
        print(f"[PASS] {name}")
        passed += 1
    else:
        print(f"[FAIL] {name}")
        failed += 1

print("\n" + "=" * 60)
print(f"检查完成: {passed} 通过, {failed} 失败")
print("=" * 60)

if failed == 0:
    print("\n[PASS] README 完整性验证通过！")
else:
    print(f"\n[WARN] 有 {failed} 项检查未通过，请检查 README")
