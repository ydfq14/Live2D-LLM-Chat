"""
测试 bootstrap 环境变量是否正确生效
"""
import os
import sys

print("=" * 60)
print("测试 bootstrap 环境变量加载")
print("=" * 60)

# 模拟 main.py 的导入顺序
print("\n[1] 导入 infrastructure._bootstrap...")
try:
    import infrastructure._bootstrap
    print("✓ bootstrap 导入成功")
except Exception as e:
    print(f"✗ bootstrap 导入失败: {e}")

# 检查环境变量
print("\n[2] 检查环境变量:")
print(f"  HF_ENDPOINT: {os.environ.get('HF_ENDPOINT', '未设置')}")
print(f"  HF_HOME: {os.environ.get('HF_HOME', '未设置')}")

# 测试 HuggingFace 连接
print("\n[3] 测试 HuggingFace 连接:")
try:
    import requests
    hf_endpoint = os.environ.get('HF_ENDPOINT', 'https://huggingface.co')
    response = requests.get(hf_endpoint, timeout=5)
    print(f"✓ {hf_endpoint} 连接成功 (状态码: {response.status_code})")
except Exception as e:
    print(f"✗ 连接失败: {e}")

# 测试 faster_whisper 导入
print("\n[4] 测试 faster_whisper 导入:")
try:
    from faster_whisper import WhisperModel
    print("✓ faster_whisper 导入成功")
except ImportError:
    print("✗ faster_whisper 未安装")
except Exception as e:
    print(f"✗ faster_whisper 导入失败: {e}")

print("\n" + "=" * 60)
print("测试完成")
print("=" * 60)
