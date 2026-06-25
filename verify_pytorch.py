#!/usr/bin/env python3
"""
验证 PyTorch CUDA 安装
"""
import sys

print("=" * 60)
print("验证 PyTorch CUDA 安装")
print("=" * 60)

print(f"\nPython 版本: {sys.version}")

try:
    import torch
    print(f"\n✓ PyTorch 已安装")
    print(f"  版本: {torch.__version__}")
    print(f"  CUDA 编译版本: {torch.version.cuda if hasattr(torch.version, 'cuda') else '无'}")

    if torch.cuda.is_available():
        print(f"\n✓ CUDA 可用!")
        print(f"  CUDA 版本: {torch.version.cuda}")
        print(f"  GPU: {torch.cuda.get_device_name(0)}")
        print(f"  GPU 显存: {round(torch.cuda.get_device_properties(0).total_mem / 1024**3, 1)} GB")

        # 测试 GPU 计算
        print(f"\n测试 GPU 计算...")
        x = torch.randn(1000, 1000).cuda()
        y = torch.matmul(x, x)
        print(f"  ✓ GPU 计算测试通过")

    else:
        print(f"\n✗ CUDA 不可用")
        print(f"  当前安装的是 CPU 版本的 PyTorch")
        print(f"\n解决方案:")
        print(f"  1. 卸载当前 PyTorch: pip uninstall torch torchvision torchaudio -y")
        print(f"  2. 安装 CUDA 版本: pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124")

except ImportError:
    print(f"\n✗ PyTorch 未安装")
    print(f"\n安装命令:")
    print(f"  pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124")
except Exception as e:
    print(f"\n✗ 错误: {e}")

print("\n" + "=" * 60)
