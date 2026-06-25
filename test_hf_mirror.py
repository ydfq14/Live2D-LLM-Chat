#!/usr/bin/env python3
"""
测试 HuggingFace 镜像配置是否正确加载
"""
import os
import sys

print("=" * 70)
print("测试 HuggingFace 镜像配置")
print("=" * 70)

# 1. 测试 bootstrap 加载
print("\n[1] 加载 infrastructure._bootstrap...")
try:
    import infrastructure._bootstrap
    print("✓ bootstrap 加载成功")

    # 验证环境变量
    hf_endpoint = os.environ.get('HF_ENDPOINT')
    hf_home = os.environ.get('HF_HOME')

    print(f"\n环境变量:")
    print(f"  HF_ENDPOINT: {hf_endpoint}")
    print(f"  HF_HOME: {hf_home}")

    if hf_endpoint and 'hf-mirror.com' in hf_endpoint:
        print("\n✓ HuggingFace 镜像配置正确!")
    else:
        print("\n✗ HuggingFace 镜像配置未生效!")

except Exception as e:
    print(f"✗ bootstrap 加载失败: {e}")
    sys.exit(1)

# 2. 测试 huggingface_hub 是否使用了镜像
print("\n[2] 测试 huggingface_hub 配置...")
try:
    import huggingface_hub
    print(f"✓ huggingface_hub 版本: {huggingface_hub.__version__}")

    # 检查 huggingface_hub 的常量
    from huggingface_hub import constants
    print(f"  HF_HUB_CACHE: {constants.HF_HUB_CACHE}")

    # 尝试获取模型信息（测试连接）
    print("\n[3] 测试 HuggingFace 连接...")
    try:
        # 尝试访问镜像站点
        import requests
        response = requests.get(hf_endpoint, timeout=5)
        print(f"✓ {hf_endpoint} 连接成功 (状态码: {response.status_code})")
    except Exception as e:
        print(f"✗ 连接失败: {e}")

except ImportError:
    print("✗ huggingface_hub 未安装")
except Exception as e:
    print(f"✗ huggingface_hub 测试失败: {e}")

# 4. 测试 ASR 模块导入
print("\n[4] 测试 ASR 模块...")
try:
    # 模拟 main.py 的导入顺序
    from ASR import ASRManager
    print("✓ ASR 模块导入成功")
except ImportError as e:
    print(f"✗ ASR 模块导入失败: {e}")
except Exception as e:
    print(f"✗ ASR 模块初始化失败: {e}")

print("\n" + "=" * 70)
print("测试完成")
print("=" * 70)

# 提示用户
print("\n提示:")
print("  如果看到 '✓ HuggingFace 镜像配置正确!'，说明镜像已生效")
print("  现在可以运行 main.py，模型下载应该使用镜像加速")
