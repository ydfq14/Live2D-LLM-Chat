"""
IOCP基础测试运行脚本

使用方法：
    python run_iocp_tests.py
"""

import sys
import os

# 切换到项目根目录
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(project_root)
sys.path.insert(0, project_root)

# 导入并运行测试
from test_iocp_basic import run_all_tests

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  IOCP 基础框架测试")
    print("=" * 60)

    success = run_all_tests()

    print("\n" + "=" * 60)
    if success:
        print("  ✅ 测试完成！所有测试通过")
    else:
        print("  ❌ 测试完成！存在失败的测试")
    print("=" * 60 + "\n")

    sys.exit(0 if success else 1)
