#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
环境检测脚本 - Windows兼容版本
"""

import os
import sys
import platform
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent))

from system.system_checker import SystemChecker, run_system_check, run_quick_check

def main():
    print("NagaAgent 环境检测工具")
    print("=" * 50)

    if len(sys.argv) > 1:
        if sys.argv[1] == "--quick":
            success = run_quick_check()
        elif sys.argv[1] == "--force":
            success = run_system_check(force_check=True)
        else:
            print("用法:")
            print("  python check_env.py         # 完整检测")
            print("  python check_env.py --quick # 快速检测")
            print("  python check_env.py --force # 强制检测")
            return
    else:
        success = run_system_check()

    print("\n按回车键退出...")
    input()

    return 0 if success else 1

if __name__ == "__main__":
    sys.exit(main())